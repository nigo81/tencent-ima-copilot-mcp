# 腾讯 IMA Copilot MCP 服务器

基于 FastMCP v2 的腾讯 IMA Copilot MCP (Model Context Protocol) 服务器，**使用环境变量配置**，将腾讯 IMA Copilot 的 Web 版本功能封装为 MCP 服务，提供通用知识库问答功能。

## ✨ 主要特性

- 🔐 **浏览器自动登录** - 无需手动提取 Cookie，调用 `login` 工具即可自动登录
- 🌐 **自动浏览器检测** - 智能识别 Chrome/Edge/QQ 浏览器/360/Firefox 等常用浏览器
- 🍪 **Cookie 自动捕获** - 登录后自动保存认证凭据，持久化存储
- 🔄 **Token 自动刷新** - 智能管理认证 token，自动刷新保持会话有效
- 📡 **SSE 流式响应** - 支持实时流式输出，长回复也能稳定获取
- 📚 **多知识库支持** - 支持配置多个知识库，灵活切换
- 💪 **Tenacity-powered Retries** - 集成 tenacity 库，优化重试机制，支持指数退避
- 🚦 **并发限流** - 默认串行问答（并发=1），降低请求突发导致的系统错误
- 📝 **Loguru-enhanced Logging** - 采用 Loguru 提升日志体验，提供更清晰、结构化的日志输出
- ⏱️ **超时保护** - 内置请求超时机制（300 秒），防止长时间阻塞
- 🐳 **Docker 支持** - 提供官方 Docker 镜像，开箱即用

## 📋 快速安装（发给 AI 助手）

不想手动装？把下面这段话直接发给你的 AI 编程助手（Claude Code / OpenCode / Cursor 等），它会自动完成克隆、装依赖、配置客户端，**Windows / Mac 通用**：

```
帮我安装腾讯 IMA 知识库 MCP 服务器并配置到你的 MCP 客户端：

仓库：https://github.com/nigo81/tencent-ima-copilot-mcp

要求：
1. git clone 用国内镜像（如 https://ghproxy.com/https://github.com/nigo81/tencent-ima-copilot-mcp），pip 安装用阿里云镜像 -i https://mirrors.aliyun.com/pypi/simple
2. 创建 Python 虚拟环境装依赖，自动检测当前系统（Windows/Mac）选择正确的命令格式
3. 用 python ima_server_simple.py 启动（默认 stdio 传输）
4. 配置你自己的 MCP 客户端指向该服务器：command=python、args=["ima_server_simple.py"]、cwd=克隆目录、env 必须包含 PYTHONUNBUFFERED=1（Windows 上必需，否则工具调用会卡死超时）
5. 装好后提示我，我需要调用 login 工具登录腾讯 IMA
```

> 💡 这段指令让 AI 助手自己适配当前操作系统和它自己的客户端配置格式，无需手动改命令。
> Windows 用户请额外阅读 [Windows 兼容性](#-windows-兼容性) 章节，了解已修复的兼容性问题和故障排查。

## 🚀 快速开始

### 1. 安装

```bash
# 克隆仓库
git clone https://github.com/highkay/tencent-ima-copilot-mcp.git
cd tencent-ima-copilot-mcp

# 安装依赖（推荐使用阿里云镜像加速）
pip install -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple/ --trusted-host mirrors.aliyun.com
```

> **注意**: `playwright` 已包含在 requirements.txt 中，无需单独安装。
> login 工具会自动检测你系统上已安装的浏览器（Chrome/Edge/QQ浏览器/360/Firefox），
> **无需下载 Chromium**。只有在以上浏览器都未安装时，才需要运行 `playwright install chromium`。

### 2. 配置 MCP 客户端

服务器同时支持 **stdio** 和 **HTTP (Streamable HTTP)** 两种传输模式。
- **stdio**: 主流 AI Agent 工具的默认方式（Claude Desktop / Claude Code / OpenCode / Cursor 等）
- **HTTP**: 推荐用于 Docker 部署、远程访问，以及 **Windows 上 stdio 出现兼容性问题时的备选方案**

> Windows 用户：请务必阅读下方的 [Windows 兼容性](#-windows-兼容性) 章节，代码已内置事件循环策略和 CRLF 修复，但部分客户端仍需 `PYTHONUNBUFFERED=1`。

#### 方式 A：stdio 传输（默认推荐）

```bash
# 直接运行（默认 stdio）
python ima_server_simple.py

# 或显式指定
python ima_server_simple.py --transport stdio
```

各客户端配置示例（`/path/to/tencent-ima-copilot-mcp` 替换为你的实际路径）：

**Claude Desktop**（`claude_desktop_config.json`）:
```json
{
  "mcpServers": {
    "ima-copilot": {
      "command": "python",
      "args": ["ima_server_simple.py"],
      "cwd": "/path/to/tencent-ima-copilot-mcp",
      "env": {
        "PYTHONUNBUFFERED": "1"
      }
    }
  }
}
```

**Claude Code** / **Cursor** / **OpenCode** 等支持 stdio 的客户端:
```json
{
  "mcpServers": {
    "ima-copilot": {
      "command": "python",
      "args": ["ima_server_simple.py"],
      "cwd": "/path/to/tencent-ima-copilot-mcp",
      "env": {
        "PYTHONUNBUFFERED": "1"
      }
    }
  }
}
```

> 启动命令也可以用旧的内联形式：
> `python -c "import sys; sys.path.insert(0,'src'); from ima_server_simple import mcp; mcp.run(transport='stdio')"`
> 推荐改用 `python ima_server_simple.py`，会自动应用 Windows 兼容性补丁。

#### 方式 B：HTTP 传输（远程 / Windows 备选）

```bash
# 启动 HTTP 服务器
python ima_server_simple.py --transport http --host 127.0.0.1 --port 8081

# 或使用 fastmcp 命令
fastmcp run ima_server_simple.py:mcp --transport http --host 127.0.0.1 --port 8081
```

然后用 MCP Inspector 连接：`http://127.0.0.1:8081/mcp`

```bash
npx @modelcontextprotocol/inspector
```

### 3. 登录

启动 MCP 客户端后，直接告诉你的 AI 助手：

> "登录 IMA" 或 "login to IMA"

`login` 工具会自动：
1. 检测你系统上已安装的浏览器（Chrome/Edge/QQ 浏览器/360/Firefox 等）
2. 打开 IMA 登录页面（https://ima.qq.com）
3. 等待你在浏览器中完成登录
4. 自动捕获并保存认证 Cookie
5. **自动获取并展示你的知识库列表**

登录成功后会列出所有可用的知识库（个人/共享/订阅），你可以直接告诉 AI 切换，例如：
> "切换到上交所IPO知识库" 或 "使用第3个"

系统会自动将选择的知识库写入配置，无需手动编辑 `.env` 文件。

### 4. 提问

登录并选择知识库后，直接向 AI 提问即可。

## 🪟 Windows 兼容性

Windows 上 MCP stdio 传输存在多个已知兼容性问题，本项目已**在代码层全部修复**，无需用户手动处理。

### 已修复的问题

| 问题 | 表现 | 修复方式 |
|------|------|---------|
| **事件循环策略** | stdio 握手卡死，工具调用超时（错误码 `-32001`） | 顶部强制设置 `WindowsProactorEventLoopPolicy` |
| **CRLF 污染**（mcp python-sdk ≤1.27） | `\n` 被翻成 `\r\n`，破坏 JSON-RPC NDJSON 格式 | Monkey-patch `stdio_server`，为 `TextIOWrapper` 加 `newline=""` |
| **stdout 全缓冲** | 客户端等不到首包 | stdio 模式下 `sys.stdout.reconfigure(line_buffering=True)` |
| **stderr 日志污染** | 日志拖延握手或被误判为错误 | stdio 模式下默认仅写文件，可用 `IMA_MCP_LOG_TO_STDERR=1` 开启 |

### Windows 客户端配置

Windows 上启动命令必须用 **绝对路径**，并强烈建议加 `PYTHONUNBUFFERED=1`：

```json
{
  "mcpServers": {
    "ima-copilot": {
      "command": "python",
      "args": ["ima_server_simple.py"],
      "cwd": "C:\\path\\to\\tencent-ima-copilot-mcp",
      "env": {
        "PYTHONUNBUFFERED": "1"
      }
    }
  }
}
```

> **Claude Code on Windows**：若 `python` 启动失败，可尝试用 `cmd /c` 包装：
> ```json
> { "command": "cmd", "args": ["/c", "python", "ima_server_simple.py"] }
> ```

### 方案 B：切换到 HTTP 传输（彻底绕开 stdio）

若 stdio 在你的 Windows 环境仍有问题，可改用 HTTP 传输。Claude Code / Cursor / OpenCode 均支持 HTTP。

> ⚠️ **诚实评估**：fastmcp 在 Windows ProactorEventLoop 上的 HTTP/SSE 传输也有[间歇性挂起的报告](https://github.com/jlowin/fastmcp/issues/4192)（fastmcp#4192）。HTTP 是「最后兜底」而非「银弹」：若 stdio 在你的环境完全无法工作可尝试，但不要预期它比 stdio 更稳定。优先还是要按下方故障排查清单把 stdio 配置好。

```bash
# 1. 启动 HTTP 服务器（前台或后台）
python ima_server_simple.py --transport http --host 127.0.0.1 --port 8081
```

```json
// 2. 客户端配置指向 HTTP 端点
{
  "mcpServers": {
    "ima-copilot": {
      "url": "http://127.0.0.1:8081/mcp"
    }
  }
}
```

> Claude Desktop 仅支持 stdio，无法用 HTTP；如有问题请优先用 Claude Code / Cursor / OpenCode。

### 故障排查清单

若 Windows 上工具调用仍超时，按顺序检查：

1. `PYTHONUNBUFFERED=1` 是否生效（最常见原因）
2. `cwd` 是否为项目根目录（必须包含 `ima_server_simple.py` 和 `src/`）
3. `python` 命令是否指向已安装依赖的解释器（用绝对路径如 `C:\\path\\to\\python.exe` 更稳）
4. 查看 `logs/debug/` 下最新日志文件，确认服务器是否收到请求
5. 若需要查看服务器实时 stderr 日志（默认 stdio 模式仅落盘），在客户端 env 加 `IMA_MCP_LOG_TO_STDERR=1`
6. 若仍失败，切换到 HTTP 传输（见上文，注意其稳定性限制）

## 🛠️ 可用的 MCP 工具

### 1. `login` - 浏览器自动登录

打开浏览器登录腾讯 IMA，自动获取并保存认证凭据。

**适用场景：**
- 首次使用，尚未配置认证信息
- Cookie/Token 已过期，`ask` 工具返回认证错误
- 需要切换账号

**调用方式：**
```
"登录 IMA" 或 "login to IMA"
```

### 2. `ask` - 提问（单知识库模式）

向腾讯 IMA 知识库询问任何问题。

**参数：**
- `question` (必需): 要询问的问题

**示例：**
```
"什么是机器学习？"
"如何制作番茄炒蛋？"
```

**特性：**
- 自动管理会话，无需手动创建
- 智能 token 刷新，确保认证有效
- 内置并发限流（默认 `IMA_ASK_CONCURRENCY_LIMIT=1`）
- 检测到 `Code=3` 且无文本时自动指数退避重试（最多 2 次）
- 300 秒超时保护，防止长时间等待
- 返回内容为 `TextContent` 列表，包含**回答文本**和格式化后的**参考资料**

> 注意：当配置了多个知识库 ID 时，`ask` 会直接报错并提示改用 `ask_with_kb`。

### 3. `ask_with_kb` - 指定知识库提问（多知识库模式）

向指定知识库询问问题。

**参数：**
- `question` (必需): 要询问的问题
- `knowledge_base_id` (必需): 目标知识库 ID（必须在配置列表中）

**示例：**
```
问题: "总结这个知识库的核心内容"
knowledge_base_id: "7305806844290061"
```

### 4. `set_knowledge_base` - 切换默认知识库

登录后使用，通过编号、名称关键词或完整 ID 选择知识库。

**参数：**
- `selection` (必需): 知识库编号（如 "1"）、名称关键词（如 "信永中和"）或完整知识库 ID

**示例：**
```
"设置知识库为信永中和" 或 "使用第3个"
```

> 注意：需要先调用 `login` 获取知识库列表后才能使用此工具。

## 📚 可用的 MCP 资源

### 1. `ima://config`

获取当前配置信息（不包含敏感数据）

### 2. `ima://help`

获取使用帮助信息

## ⚙️ 环境变量配置

### 必需的环境变量

| 变量名 | 说明 | 获取方式 |
|--------|------|---------|
| `IMA_X_IMA_COOKIE` | X-Ima-Cookie 请求头 | 由 `login` 工具自动填充 |
| `IMA_X_IMA_BKN` | X-Ima-Bkn 请求头 | 由 `login` 工具自动填充 |
| `IMA_KNOWLEDGE_BASE_ID` | 知识库 ID（单知识库模式） | 手动配置（见下方说明） |

### 可选的环境变量

| 变量名 | 说明 | 默认值 |
|--------|------|--------|
| `IMA_KNOWLEDGE_BASE_IDS` | 多知识库 ID 列表（逗号分隔） | 无 |
| `IMA_MCP_HOST` | MCP 服务器地址 | `127.0.0.1` |
| `IMA_MCP_PORT` | MCP 服务器端口 | `8081` |
| `IMA_MCP_LOG_LEVEL` | 日志级别 (DEBUG/INFO/WARNING/ERROR) | `INFO` |
| `IMA_REQUEST_TIMEOUT` | IMA API 请求超时时间（秒） | `30` |
| `IMA_RETRY_COUNT` | 网络/超时类异常重试次数 | `3` |
| `IMA_ASK_CONCURRENCY_LIMIT` | 问答并发上限（建议 1-2） | `1` |
| `IMA_ROBOT_TYPE` | 机器人类型 | `5` |
| `IMA_SCENE_TYPE` | 场景类型 | `1` |
| `IMA_MODEL_TYPE` | 模型类型 | `4` |

### 如何获取知识库 ID

**推荐方式**：直接调用 `login` 工具，登录后会自动列出所有知识库及其 ID，无需手动获取。

**手动方式**：
1. 在 IMA 网页选择目标知识库
2. 按 F12 打开开发者工具，切换到 Network 标签
3. 找到 `init_session` 请求
4. 查看 Payload 中的 `knowledge_base_id` 字段

### 知识库配置模式

- **单知识库模式**：配置 `IMA_KNOWLEDGE_BASE_ID`，使用 `ask` 或 `ask_with_kb` 均可
- **多知识库模式**：配置 `IMA_KNOWLEDGE_BASE_IDS`（逗号分隔），必须使用 `ask_with_kb`
- 同时配置两者时：优先使用 `IMA_KNOWLEDGE_BASE_ID`（单知识库模式）

## 🐳 Docker 使用

### 使用 Docker Compose（推荐）

创建 `.env` 文件：

```bash
IMA_KNOWLEDGE_BASE_ID="your_knowledge_base_id"
```

启动服务：

```bash
docker-compose up -d

# 查看日志
docker-compose logs -f
```

### 使用 Docker Run

```bash
# 拉取镜像
docker pull highkay/tencent-ima-copilot-mcp:latest

# 运行容器
docker run -d \
  --name ima-copilot-mcp \
  -p 8081:8081 \
  -e IMA_KNOWLEDGE_BASE_ID="your_knowledge_base_id" \
  -v $(pwd)/logs:/app/logs \
  --restart unless-stopped \
  highkay/tencent-ima-copilot-mcp:latest
```

> 注意：Docker 模式下使用 MCP Inspector 连接后，也需要调用 `login` 工具进行首次登录。

## 🛠️ 开发

### 本地开发

```bash
# 安装依赖
pip install -r requirements.txt

# 启动服务器（HTTP 模式）
fastmcp run ima_server_simple.py:mcp --transport http --host 127.0.0.1 --port 8081

# 或使用 MCP Inspector 连接
npx @modelcontextprotocol/inspector
# 输入地址: http://127.0.0.1:8081/mcp
```

### 代码风格

```bash
# 使用 Ruff 检查和修复代码
pip install ruff
ruff check --fix .
```

## 🔍 故障排除

### 常见问题

**Q: Windows 上工具调用超时（错误码 `-32001`）/ MCP 服务启动后无响应怎么办？**

A: 参见 [Windows 兼容性](#-windows-兼容性) 章节。代码已内置事件循环策略和 CRLF 修复，但仍需：
1. 在客户端配置中设置 `PYTHONUNBUFFERED=1`
2. 用绝对路径指定 `cwd`
3. 若仍失败，切换到 HTTP 传输（`--transport http`）

**Q: 调用 `ask` 时返回认证错误怎么办？**

A:
1. 直接调用 `login` 工具重新登录
2. `login` 会自动打开浏览器，等待你登录后自动捕获新的认证信息

**Q: `login` 工具提示 "未检测到可用的浏览器" 怎么办？**

A:
1. 确保系统已安装 Chrome/Edge/QQ 浏览器/360/Firefox 等浏览器之一
2. 如果已安装但仍报错，请手动配置浏览器路径到环境变量或代码中

**Q: 如何连接特定的知识库？**

A:
在 `.env` 文件中设置 `IMA_KNOWLEDGE_BASE_ID` 即可。获取方法：
1. 在 IMA 网页选择知识库
2. 找到 `init_session` 请求
3. 查看 Payload 中的 `knowledge_base_id`

**Q: 多知识库怎么配置和调用？**

A:
1. 在 `.env` 中设置 `IMA_KNOWLEDGE_BASE_IDS=id1,id2,id3`
2. 调用工具时使用 `ask_with_kb(question, knowledge_base_id)`
3. 若调用 `ask`，会提示错误并给出可用 `knowledge_base_id` 列表

**Q: 偶发出现 `Code=3` 且无文本怎么办？**

A:
1. 先保持默认并发（`IMA_ASK_CONCURRENCY_LIMIT=1`）
2. 避免同一知识库短时间突发并发请求
3. 服务已内置 `Code=3` 退避重试；若仍频繁出现，可适当增加请求间隔

## 📄 许可证

MIT License