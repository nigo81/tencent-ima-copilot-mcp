#!/usr/bin/env python3
"""
IMA Copilot MCP 服务器 - 基于环境变量的简化版本
专注于 MCP 协议实现，配置通过环境变量管理
"""

# === Windows 兼容性修复（必须在 asyncio / fastmcp / anyio 导入之前）===
# Windows 默认事件循环策略不支持 asyncio subprocess，会导致 MCP stdio 握手卡死。
# ProactorEventLoop 是 Windows 上正确处理 stdin/stdout 子进程 IO 的必要条件。
import os
import sys
import asyncio

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    # 关闭 Python 子进程 stdout/stderr 的全缓冲，避免 MCP 客户端等不到首包。
    # 客户端配置也建议加 PYTHONUNBUFFERED=1，这里作为代码层兜底。
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(line_buffering=True)
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(line_buffering=True)
    except Exception:
        pass

import json
from pathlib import Path
from datetime import datetime

from fastmcp import FastMCP
from mcp.types import TextContent
from loguru import logger

# 导入我们的模块
sys.path.insert(0, str(Path(__file__).parent / "src"))

from config import config_manager, get_config, get_app_config
from ima_client import IMAAPIClient


def _patch_mcp_stdio_crlf() -> None:
    """修复 mcp python-sdk 在 Windows 上的 CRLF 污染问题。

    mcp<=1.27.x 的 stdio_server 用 ``TextIOWrapper(sys.stdout.buffer, encoding="utf-8")``
    包裹 stdout，但没有指定 ``newline=""``，导致 Windows 上写入 ``\\n`` 会被翻译成
    ``\\r\\n``，破坏 JSON-RPC NDJSON 格式，MCP 客户端解析挂起、工具调用超时（-32001）。

    上游追踪: https://github.com/modelcontextprotocol/python-sdk/issues/2433 (PR#2470)

    实现策略：
      - 仅对 mcp < 1.28 应用（1.28+ 上游已内置修复，版本探测后跳过）
      - 替换后的实现**严格复制上游语义**，唯一差异是给 TextIOWrapper 加 ``newline=""``
      - 幂等保护：``_ima_crlf_patched`` 标志防止重复 patch
      - 失败时降级到上游原行为，仅打 warning 日志
    """
    # 版本探测：上游 PR#2470 预计在 1.28.0 合入，已修复版本跳过 patch
    try:
        from importlib.metadata import version as _pkg_version
        _mcp_ver_str = _pkg_version("mcp")
        _mcp_ver = tuple(int(x) for x in _mcp_ver_str.split(".")[:2])
        if _mcp_ver >= (1, 28):
            return  # 上游已修复，无需 patch
    except Exception:
        # 版本探测失败时继续尝试 patch（newline="" 幂等安全）
        pass

    try:
        from mcp.server import stdio as _mcp_stdio
        from contextlib import asynccontextmanager
        from io import TextIOWrapper
        import anyio
        import anyio.lowlevel
        import mcp.types as _mcp_types
        from mcp.shared.message import SessionMessage

        if getattr(_mcp_stdio, "_ima_crlf_patched", False):
            return

        @asynccontextmanager
        async def _stdio_server_fixed(stdin=None, stdout=None):
            # 复制上游 stdio_server 实现，唯一差异：TextIOWrapper 显式传入 newline=""
            if not stdin:
                stdin = anyio.wrap_file(
                    TextIOWrapper(
                        sys.stdin.buffer, encoding="utf-8", errors="replace", newline=""
                    )
                )
            if not stdout:
                stdout = anyio.wrap_file(
                    TextIOWrapper(sys.stdout.buffer, encoding="utf-8", newline="")
                )

            read_stream_writer, read_stream = anyio.create_memory_object_stream(0)
            write_stream, write_stream_reader = anyio.create_memory_object_stream(0)

            async def stdin_reader():
                try:
                    async with read_stream_writer:
                        async for line in stdin:
                            try:
                                message = _mcp_types.JSONRPCMessage.model_validate_json(line)
                            except Exception as exc:
                                await read_stream_writer.send(exc)
                                continue
                            await read_stream_writer.send(SessionMessage(message))
                except anyio.ClosedResourceError:  # pragma: no cover
                    await anyio.lowlevel.checkpoint()  # type: ignore[attr-defined]

            async def stdout_writer():
                try:
                    async with write_stream_reader:
                        async for session_message in write_stream_reader:
                            json_str = session_message.message.model_dump_json(
                                by_alias=True, exclude_none=True
                            )
                            await stdout.write(json_str + "\n")
                            await stdout.flush()
                except anyio.ClosedResourceError:  # pragma: no cover
                    await anyio.lowlevel.checkpoint()  # type: ignore[attr-defined]

            async with anyio.create_task_group() as tg:
                tg.start_soon(stdin_reader)
                tg.start_soon(stdout_writer)
                yield read_stream, write_stream

        _mcp_stdio.stdio_server = _stdio_server_fixed
        _mcp_stdio._ima_crlf_patched = True  # type: ignore[attr-defined]
    except Exception as exc:
        # 补丁失败不应阻断启动，降级到上游原行为
        try:
            logger.warning(f"mcp stdio CRLF 补丁应用失败，降级到上游实现: {exc}")
        except Exception:
            pass


# 注意：patch 调用挪到 _setup_logging() 之后，避免失败时 stderr 污染 stdio 通道


def _detect_transport() -> str:
    """检测当前传输模式（stdio / http / sse），用于决定日志策略。

    优先级：
      1. 环境变量 IMA_MCP_TRANSPORT（由入口脚本显式设置）
      2. 命令行参数 --transport xxx
      3. 默认 stdio（最严格，最安全）
    """
    env_val = os.environ.get("IMA_MCP_TRANSPORT", "").strip().lower()
    if env_val in ("stdio", "http", "sse", "streamable-http"):
        if env_val == "streamable-http":
            return "http"
        return env_val

    argv = sys.argv[1:]
    for i, arg in enumerate(argv):
        if arg == "--transport" and i + 1 < len(argv):
            return argv[i + 1].strip().lower()
        if arg.startswith("--transport="):
            return arg.split("=", 1)[1].strip().lower()

    return "stdio"


def _setup_logging() -> Path:
    """配置 loguru，stdio 模式下默认不向 stderr 输出，避免污染 MCP 通道。

    stdio 模式下 stderr 仍可被客户端捕获，但大量日志输出会拖延握手、
    甚至被部分客户端当作错误信号。stdio 模式仅写文件，
    如需开启 stderr 可设置 IMA_MCP_LOG_TO_STDERR=1。
    """
    log_dir = Path("logs/debug")
    log_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = log_dir / f"ima_server_{timestamp}.log"

    transport = _detect_transport()
    allow_stderr = (
        transport != "stdio"
        or os.environ.get("IMA_MCP_LOG_TO_STDERR", "").strip().lower() in ("1", "true", "yes")
    )

    logger.remove()

    stderr_format = (
        "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | "
        "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
        "<level>{message}</level> | <magenta>{extra}</magenta>"
    )
    file_format = (
        "{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | "
        "{name}:{function}:{line} - {message} | {extra}"
    )

    if allow_stderr:
        logger.add(sys.stderr, level="INFO", format=stderr_format)

    logger.add(
        log_file,
        level="DEBUG",
        rotation="10 MB",
        retention="1 week",
        encoding="utf-8",
        format=file_format,
    )

    logger.info(
        f"日志已启用 (transport={transport}, stderr={allow_stderr})，日志文件: {log_file}"
    )
    return log_file


# 模块加载时尽早配置日志，保证后续 import 链中的日志都能落盘
# 必须在 _patch_mcp_stdio_crlf() 之前：patch 失败时的 warning 才能按 transport 策略
# 正确输出（stdio 模式仅落盘，不污染 stderr）
_log_file = _setup_logging()

# 应用 mcp stdio CRLF 补丁（日志已就绪，降级 warning 不会污染 stdio 通道）
_patch_mcp_stdio_crlf()

# 创建 FastMCP 实例
mcp = FastMCP("IMA Copilot")

# 全局变量
ima_client: IMAAPIClient = None
_token_refreshed: bool = False  # 标记 token 是否已刷新
_client_init_lock = asyncio.Lock()
_cached_kb_list: list[dict] = []  # 缓存登录时获取的知识库列表


def _validate_startup_config() -> tuple[bool, str]:
    """启动配置校验：缺少必需环境变量时阻止服务运行"""
    is_valid, error_message = config_manager.validate_config()
    if is_valid:
        return True, ""

    return False, error_message or "环境变量配置不完整"


_startup_ok, _startup_error = _validate_startup_config()
if not _startup_ok:
    logger.warning(f"⚠️ 启动配置不完整: {_startup_error}")
    logger.warning("请使用 login 工具完成登录认证")


def _get_knowledge_base_ids() -> list[str]:
    """获取当前配置中的知识库 ID 列表"""
    config = get_config()
    if not config:
        return []

    kb_ids = [kb_id for kb_id in (config.knowledge_base_ids or []) if kb_id]
    if kb_ids:
        return kb_ids

    return [config.knowledge_base_id] if config.knowledge_base_id else []


def _is_multi_knowledge_base_mode() -> bool:
    return len(_get_knowledge_base_ids()) > 1


def _validate_knowledge_base_id(knowledge_base_id: str) -> tuple[bool, str]:
    kb_id = (knowledge_base_id or "").strip()
    if not kb_id:
        return False, "[ERROR] knowledge_base_id 不能为空"

    allowed_ids = _get_knowledge_base_ids()
    if kb_id not in allowed_ids:
        return False, (
            "[ERROR] knowledge_base_id 不在允许列表中，"
            f"可用值: {', '.join(allowed_ids)}"
        )

    return True, ""


async def _ask_with_target_kb(question: str, knowledge_base_id: str) -> list[TextContent]:
    """执行一次指定知识库的问答"""
    global ima_client

    if not question or not question.strip():
        return [TextContent(type="text", text="[ERROR] 问题不能为空")]

    is_valid_kb_id, kb_error = _validate_knowledge_base_id(knowledge_base_id)
    if not is_valid_kb_id:
        return [TextContent(type="text", text=kb_error)]

    request_kb_id = knowledge_base_id.strip()

    try:
        logger.debug("发送问题", length=len(question), knowledge_base_id=request_kb_id)

        # 增加超时时间以支持长回复
        # 注意：某些 MCP 客户端（如 Claude Desktop）可能有自己的 60秒超时限制
        mcp_safe_timeout = 300

        # 将超时控制传递给 ask_question_complete，以便在超时时返回部分结果
        messages = await ima_client.ask_question_complete(
            question,
            timeout=mcp_safe_timeout,
            knowledge_base_id=request_kb_id,
        )

        # 即使没有消息，也会返回包含错误信息的消息列表
        if not messages:
            logger.warning("⚠️ 未收到响应", knowledge_base_id=request_kb_id)
            return [TextContent(type="text", text="[ERROR] 没有收到任何响应，或者请求超时未产生任何输出")]

        # 打印完整的qa结果
        logger.info("-" * 80)
        logger.info(f"完整 QA 结果 (知识库: {request_kb_id}, 原始消息列表):")
        for i, msg in enumerate(messages):
            logger.info(f"  消息 {i + 1} (类型: {msg.type.value}): {msg.content[:200]}...")
        logger.info("-" * 80)

        response = ima_client._extract_text_content(messages)

        # 如果没有提取到文本内容，检查是否有系统错误消息
        if not response:
            error_msgs = [msg.content for msg in messages if msg.type == 'system']
            if error_msgs:
                response = f"[ERROR] {'; '.join(error_msgs)}"
                logger.warning("⚠️ 未提取到文本，返回系统错误", error=response, knowledge_base_id=request_kb_id)
            else:
                response = "没有收到有效回复"

        logger.debug("✅ 获取响应", length=len(response), knowledge_base_id=request_kb_id)

        content_list = [TextContent(type="text", text=response)]

        # 提取并添加参考资料信息
        try:
            knowledge_info = ima_client._extract_knowledge_info(messages)
            if knowledge_info:
                ref_text = "### 📚 参考资料\n\n"
                for i, item in enumerate(knowledge_info, 1):
                    title = item.get('title', '未知标题')
                    intro = item.get('introduction', '')
                    # 截断过长的简介
                    if intro and len(intro) > 150:
                        intro = intro[:150] + "..."

                    ref_text += f"{i}. **{title}**\n"
                    if intro:
                        ref_text += f"   > {intro}\n"
                    ref_text += "\n"

                content_list.append(TextContent(type="text", text=ref_text))
                logger.debug("✅ 添加参考资料", count=len(knowledge_info), knowledge_base_id=request_kb_id)
        except Exception as e:
            logger.warning(f"提取参考资料失败: {e}", knowledge_base_id=request_kb_id)

        # 打印返回 ask 的内容
        logger.info("-" * 80)
        logger.info(f"ask 工具返回内容 (知识库: {request_kb_id}, Block 数量: {len(content_list)}):")
        for i, block in enumerate(content_list):
            logger.info(f"Block {i+1} ({len(block.text)} chars):\n{block.text[:200]}...")
        logger.info("-" * 80)

        return content_list

    except Exception as e:
        logger.exception("询问 IMA 时发生错误", knowledge_base_id=request_kb_id)

        # 返回更友好的错误信息
        error_str = str(e).lower()
        if "超时" in str(e) or "timeout" in error_str:
            return [TextContent(type="text", text="[ERROR] 请求超时，请稍后重试")]
        elif "认证" in str(e) or "auth" in error_str:
            return [TextContent(type="text", text="[ERROR] 认证失败，请检查 IMA 配置信息")]
        elif "网络" in str(e) or "network" in error_str or "connection" in error_str:
            return [TextContent(type="text", text="[ERROR] 网络连接失败，请检查网络设置")]
        else:
            return [TextContent(type="text", text=f"[ERROR] 询问失败: {str(e)}")]


# @mcp.on_shutdown()
# async def on_shutdown():
#     """服务器关闭时的清理工作"""
#     global ima_client
#     if ima_client:
#         logger.info("👋 正在关闭 IMA 客户端会话...")
#         await ima_client.close()
#         logger.info("✅ 客户端会话已关闭")


async def ensure_client_ready():
    """确保客户端已初始化并且 token 有效"""
    global ima_client, _token_refreshed

    if not ima_client:
        async with _client_init_lock:
            if not ima_client:
                logger.info("🚀 首次请求，初始化 IMA 客户端...")

                config = get_config()
                if not config:
                    logger.error("❌ 配置未加载")
                    return False

                try:
                    # 启用原始SSE日志
                    config.enable_raw_logging = True
                    config.raw_log_dir = "logs/debug/raw"
                    config.raw_log_on_success = False

                    ima_client = IMAAPIClient(config)
                    logger.debug("✅ IMA 客户端初始化成功")
                except Exception as e:
                    logger.exception("❌ IMA 客户端初始化失败")
                    return False
    
    # 如果还没刷新过 token，提前刷新一次（添加超时保护）
    if not _token_refreshed:
        logger.info("🔄 验证 token...")
        try:
            import asyncio
            # 为token刷新也添加超时保护（15秒）
            token_valid = await asyncio.wait_for(
                ima_client.ensure_valid_token(),
                timeout=15.0
            )
            
            if token_valid:
                _token_refreshed = True
                logger.info("✅ Token 验证成功")
                return True
            else:
                logger.warning("⚠️ Token 验证失败，尝试继续...")
                # 即使刷新失败也标记为 True，让后续请求在 ask_question 内部触发自动重试逻辑
                _token_refreshed = True 
                return True
        except asyncio.TimeoutError:
            logger.error("❌ Token 验证超时")
            return False
        except Exception as e:
            logger.exception("❌ Token 验证异常")
            return False
    
    return True


@mcp.tool()
async def login() -> list[TextContent]:
    """打开浏览器登录腾讯 IMA，自动获取认证凭据

    适用场景：
    - 首次使用，尚未配置认证信息
    - Cookie/Token 已过期，ask 工具返回认证错误
    - 需要切换账号

    调用后会打开浏览器窗口，请在浏览器中完成登录，
    登录成功后认证信息会自动保存，无需手动配置。
    """
    global ima_client, _token_refreshed

    try:
        from browser_login import login_and_capture
    except ImportError:
        return [TextContent(
            type="text",
            text="[ERROR] browser_login 模块导入失败，请检查 src/ 目录是否完整",
        )]

    try:
        logger.info("🔐 启动浏览器登录流程...")
        result = await login_and_capture()
    except ImportError as e:
        return [TextContent(type="text", text=f"[ERROR] {e}")]
    except TimeoutError as e:
        return [TextContent(type="text", text=f"[ERROR] {e}")]
    except Exception as e:
        logger.exception("浏览器登录异常")
        return [TextContent(type="text", text=f"[ERROR] 登录失败: {e}")]

    # 更新配置
    ok = config_manager.update_auth(
        x_ima_cookie=result["x_ima_cookie"],
        x_ima_bkn=result["x_ima_bkn"],
        cookies=result.get("cookies", ""),
    )

    if not ok:
        return [TextContent(type="text", text="[ERROR] 认证信息保存失败，请查看日志")]

    # 重置客户端，下次 ask 时会用新配置重建
    if ima_client:
        try:
            await ima_client.close()
        except Exception:
            pass
        ima_client = None
    _token_refreshed = False

    config = get_config()
    kb_info = ""
    if config:
        kb_info = f"\n知识库: {config.knowledge_base_id}"

    logger.info("✅ 登录成功，认证信息已更新")

    # 构建返回消息
    msg_parts = ["✅ 登录成功！认证信息已自动保存。"]

    # 解析知识库列表
    kb_list_raw = result.get("knowledge_bases", "")
    kb_list = []
    if kb_list_raw:
        try:
            kb_list = json.loads(kb_list_raw)
        except (json.JSONDecodeError, TypeError):
            logger.warning("⚠️ 知识库列表解析失败")

    if kb_list:
        # 缓存知识库列表供 set_knowledge_base 工具使用
        global _cached_kb_list
        _cached_kb_list = kb_list

        msg_parts.append("\n\n📚 发现以下知识库：")
        for i, kb in enumerate(kb_list, 1):
            msg_parts.append(f"  {i}. {kb['name']} (ID: {kb['id']}) [{kb.get('category', '')}]")

        config = get_config()
        current_kb_id = config.knowledge_base_id if config else ""
        if current_kb_id:
            # 找到当前配置的知识库名称
            current_name = ""
            for kb in kb_list:
                if kb["id"] == current_kb_id:
                    current_name = kb["name"]
                    break
            msg_parts.append(f"\n当前默认知识库: {current_name or current_kb_id}")

        msg_parts.append(
            "\n如需切换知识库，请告诉我要使用哪个（编号或名称），"
            "例如：\"设置知识库为信永中和\" 或 \"使用第3个\""
        )

        # 自动检测：如果当前没有配置知识库，且有且仅有一个，自动设置
        if not current_kb_id and len(kb_list) == 1:
            auto_id = kb_list[0]["id"]
            auto_name = kb_list[0]["name"]
            config_manager.update_knowledge_base(knowledge_base_id=auto_id)
            msg_parts.append(f"\n已自动设置知识库为: {auto_name} ({auto_id})")
    else:
        config = get_config()
        kb_info = ""
        if config:
            kb_info = f"\n知识库: {config.knowledge_base_id}"
        if kb_info:
            msg_parts.append(kb_info)
        msg_parts.append("\n未获取到知识库列表，请手动在 .env 中配置 IMA_KNOWLEDGE_BASE_ID")

    return [TextContent(type="text", text="".join(msg_parts))]


@mcp.tool()
async def set_knowledge_base(selection: str) -> list[TextContent]:
    """设置默认知识库。登录后使用，通过编号、名称关键词或完整 ID 选择知识库。

    Args:
        selection: 知识库编号（如 "1"）、名称关键词（如 "信永中和"）或完整知识库 ID

    Returns:
        设置结果
    """
    global ima_client

    if not _cached_kb_list:
        return [TextContent(type="text", text="[ERROR] 未找到知识库列表，请先调用 login 登录")]

    selection = selection.strip()
    target_kb = None

    # 1. 尝试按编号匹配
    if selection.isdigit():
        idx = int(selection) - 1
        if 0 <= idx < len(_cached_kb_list):
            target_kb = _cached_kb_list[idx]

    # 2. 尝试按完整 ID 匹配
    if not target_kb:
        for kb in _cached_kb_list:
            if kb["id"] == selection:
                target_kb = kb
                break

    # 3. 尝试按名称关键词匹配
    if not target_kb:
        matches = [kb for kb in _cached_kb_list if selection in kb["name"]]
        if len(matches) == 1:
            target_kb = matches[0]
        elif len(matches) > 1:
            names = "\n".join(f"  {i+1}. {kb['name']} (ID: {kb['id']})" for i, kb in enumerate(matches))
            return [TextContent(
                type="text",
                text=f"找到多个匹配的知识库，请更精确地指定：\n{names}",
            )]

    if not target_kb:
        available = "\n".join(f"  {i+1}. {kb['name']} (ID: {kb['id']})" for i, kb in enumerate(_cached_kb_list))
        return [TextContent(
            type="text",
            text=f"未找到匹配的知识库 \"{selection}\"。\n可用的知识库：\n{available}",
        )]

    # 更新配置
    ok = config_manager.update_knowledge_base(knowledge_base_id=target_kb["id"])

    # 重置客户端，下次 ask 时会用新配置重建
    if ima_client:
        try:
            await ima_client.close()
        except Exception:
            pass
        ima_client = None

    if ok:
        return [TextContent(
            type="text",
            text=f"✅ 默认知识库已设置为: {target_kb['name']} (ID: {target_kb['id']})\n现在可以使用 ask 工具提问了。",
        )]
    else:
        return [TextContent(type="text", text="[ERROR] 知识库配置保存失败，请查看日志")]


@mcp.tool()
async def ask(question: str) -> list[TextContent]:
    """向腾讯 IMA 知识库询问任何问题

    Args:
        question: 要询问的问题

    Returns:
        IMA 知识库的回答
    """
    global ima_client
    
    # 生成请求ID用于日志追踪
    import uuid
    request_id = str(uuid.uuid4())[:8]
    
    # 绑定上下文
    with logger.contextualize(request_id=request_id):
        # 确保客户端已初始化并且 token 有效
        if not await ensure_client_ready():
            return [TextContent(type="text", text="[ERROR] IMA 客户端初始化或 token 刷新失败，请检查配置")]

        if _is_multi_knowledge_base_mode():
            kb_ids = _get_knowledge_base_ids()
            return [
                TextContent(
                    type="text",
                    text=(
                        "[ERROR] 当前为多知识库模式，请使用 ask_with_kb 并传入 knowledge_base_id。"
                        f"可用值: {', '.join(kb_ids)}"
                    ),
                )
            ]

        logger.debug("🔍 ask 工具调用", question_preview=question[:50])

        default_kb_id = _get_knowledge_base_ids()[0]
        return await _ask_with_target_kb(question=question, knowledge_base_id=default_kb_id)


@mcp.tool()
async def ask_with_kb(question: str, knowledge_base_id: str) -> list[TextContent]:
    """向指定知识库询问问题（多知识库模式使用）

    Args:
        question: 要询问的问题
        knowledge_base_id: 目标知识库 ID（必须在配置的知识库列表中）

    Returns:
        IMA 知识库的回答
    """
    import uuid

    request_id = str(uuid.uuid4())[:8]
    with logger.contextualize(request_id=request_id):
        if not await ensure_client_ready():
            return [TextContent(type="text", text="[ERROR] IMA 客户端初始化或 token 刷新失败，请检查配置")]

        logger.debug(
            "🔍 ask_with_kb 工具调用",
            question_preview=question[:50],
            knowledge_base_id=knowledge_base_id,
        )
        return await _ask_with_target_kb(question=question, knowledge_base_id=knowledge_base_id)


@mcp.resource("ima://config")
def get_config_resource() -> str:
    """获取当前配置信息（不包含敏感数据）"""
    try:
        config = get_config()
        if not config:
            return "配置未加载"

        # 返回非敏感的配置信息
        config_info = "IMA 配置信息:\n"
        config_info += f"客户端ID: {config.client_id}\n"
        config_info += f"默认知识库ID: {config.knowledge_base_id}\n"
        config_info += f"可用知识库ID: {', '.join(config.knowledge_base_ids)}\n"
        config_info += f"知识库模式: {'多知识库' if len(config.knowledge_base_ids) > 1 else '单知识库'}\n"
        config_info += f"请求超时: {config.timeout}秒\n"
        config_info += f"重试次数: {config.retry_count}\n"
        config_info += f"代理设置: {config.proxy or '未设置'}\n"
        config_info += f"创建时间: {config.created_at}\n"
        if config.updated_at:
            config_info += f"更新时间: {config.updated_at}\n"

        return config_info

    except Exception as e:
        logger.error(f"获取配置资源时发生错误: {e}")
        return f"[ERROR] 获取配置失败: {str(e)}"


@mcp.resource("ima://help")
def get_help_resource() -> str:
    """获取使用帮助信息"""
    help_text = """
# IMA Copilot MCP 服务器帮助

## 概述
这是基于环境变量配置的 IMA Copilot MCP 服务器，提供腾讯 IMA 知识库的 MCP 协议接口。

## 配置方式
通过环境变量或 .env 文件配置 IMA 认证信息：

1. 复制 .env.example 为 .env
2. 填入从浏览器获取的认证信息：
   - IMA_COOKIES: 完整的 cookies 字符串
   - IMA_X_IMA_COOKIE: X-Ima-Cookie 请求头
   - IMA_X_IMA_BKN: X-Ima-Bkn 请求头

## 工具
- `ask`: 向 IMA 知识库询问问题
- `ask_with_kb`: 向指定知识库询问问题（多知识库模式推荐）

## 资源
- `ima://config`: 查看配置信息
- `ima://help`: 查看帮助信息

## 启动方式
```bash
# 使用 fastmcp 命令启动
fastmcp run ima_server_simple.py:mcp --transport http --host 127.0.0.1 --port 8081

# 或使用 Python 直接运行
python ima_server_simple.py
```

## 连接方式
使用 MCP Inspector 连接到: http://127.0.0.1:8081/mcp
"""
    return help_text


def _print_banner(transport: str) -> None:
    """打印启动横幅。stdio 模式下禁止写 stdout（会污染 MCP 通道），改用 logger。"""
    app_config = get_app_config()

    lines = [
        "IMA Copilot MCP 服务器",
        "=" * 50,
        f"传输模式: {transport}",
    ]

    if transport in ("http", "sse"):
        lines.extend([
            f"服务地址: http://{app_config.host}:{app_config.port}",
            f"MCP 端点: http://{app_config.host}:{app_config.port}/mcp",
        ])

    lines.extend([
        f"日志级别: {app_config.log_level}",
        f"日志文件: {_log_file}",
        "=" * 50,
    ])

    # 验证配置（仅打印信息，不阻断启动 —— stdio 模式下允许 login 工具补全配置）
    is_valid, error_message = _validate_startup_config()
    if not is_valid:
        lines.append(f"[WARN] 配置不完整: {error_message}")
        lines.append("[HINT] 请在 MCP 客户端中调用 login 工具完成登录认证")
    else:
        config = get_config()
        if config:
            lines.append("[OK] 配置加载成功")
            lines.append(f"[INFO] 默认知识库: {config.knowledge_base_id}")
            lines.append(f"[INFO] 可用知识库: {', '.join(config.knowledge_base_ids)}")

    output = "\n".join(lines)

    if transport == "stdio":
        # stdio 模式严禁写 stdout，全部走 logger（落盘 + 可选 stderr）
        for line in lines:
            logger.info(line)
    else:
        print(output)


def main():
    """主入口：解析命令行参数并启动 MCP 服务器。

    支持的传输模式：
      - stdio (默认): 适用于 Claude Desktop / Claude Code / OpenCode / Cursor 等
      - http:          适用于远程部署或 Windows 兼容性备选方案
      - sse:           已弃用，仅向后兼容
    """
    import argparse

    parser = argparse.ArgumentParser(
        description="IMA Copilot MCP 服务器",
        allow_abbrev=False,
    )
    parser.add_argument(
        "--transport",
        choices=["stdio", "http", "sse"],
        default=os.environ.get("IMA_MCP_TRANSPORT", "stdio").lower(),
        help="MCP 传输模式（默认 stdio，Windows 有兼容性问题时建议用 http）",
    )
    parser.add_argument("--host", default=os.environ.get("IMA_MCP_HOST", "127.0.0.1"))
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("IMA_MCP_PORT", "8081")),
    )
    args = parser.parse_args()

    # 同步到环境变量，供日志判断和下游模块使用
    os.environ["IMA_MCP_TRANSPORT"] = args.transport
    # 重新配置日志（基于确定的 transport）
    global _log_file
    _log_file = _setup_logging()

    _print_banner(args.transport)

    if args.transport == "stdio":
        logger.info("启动 stdio 传输模式")
        mcp.run(transport="stdio")
    elif args.transport == "http":
        logger.info(f"启动 http 传输模式: http://{args.host}:{args.port}/mcp")
        mcp.run(transport="streamable-http", host=args.host, port=args.port)
    elif args.transport == "sse":
        logger.info(f"启动 sse 传输模式: http://{args.host}:{args.port}/sse")
        mcp.run(transport="sse", host=args.host, port=args.port)


if __name__ == "__main__":
    main()


__all__ = ["mcp"]
