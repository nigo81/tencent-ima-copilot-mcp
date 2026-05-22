"""
Playwright-based IMA login helper
自动检测用户已安装的浏览器，打开 IMA 让用户登录，抓取认证头
"""

import asyncio
import os
import platform
from pathlib import Path
from typing import Dict, Optional, Tuple

from loguru import logger


# ── 浏览器检测 ──────────────────────────────────────────

def _detect_browser() -> Tuple[dict, str]:
    """
    自动检测用户系统上已安装的浏览器。

    优先级（国内常见）：Chrome > Edge > QQ浏览器 > 360浏览器 > Firefox

    Returns:
        (launch_kwargs, display_name) — 传给 playwright.chromium.launch() 的参数

    Raises:
        RuntimeError: 未找到任何支持的浏览器
    """
    system = platform.system()
    candidates = _get_candidates(system)

    for entry in candidates:
        check_path = entry.get("check") or entry.get("executable", "")
        if Path(check_path).exists():
            kwargs: dict = {
                "headless": False,
                "args": ["--disable-blink-features=AutomationControlled"],
            }
            if "channel" in entry:
                kwargs["channel"] = entry["channel"]
            if "executable" in entry:
                kwargs["executable_path"] = entry["executable"]
            return kwargs, entry["name"]

    # 收集已知的浏览器名用于错误提示
    names = [e["name"] for e in candidates]
    raise RuntimeError(
        "未检测到可用的浏览器。\n\n"
        "请安装以下任一浏览器后重试：\n"
        + "\n".join(f"  - {n}" for n in names)
        + "\n\n或者运行以下命令安装 Chromium：\n"
        "  playwright install chromium"
    )


def _get_candidates(system: str) -> list[dict]:
    """按系统返回浏览器候选列表"""

    if system == "Darwin":
        return [
            {
                "channel": "chrome",
                "check": "/Applications/Google Chrome.app",
                "name": "Google Chrome",
            },
            {
                "channel": "msedge",
                "check": "/Applications/Microsoft Edge.app",
                "name": "Microsoft Edge",
            },
            {
                "executable": "/Applications/QQBrowser.app/Contents/MacOS/QQBrowser",
                "name": "QQ 浏览器",
            },
            {
                "executable": (
                    "/Applications/360SafeBrowser.app"
                    "/Contents/MacOS/360SafeBrowser"
                ),
                "name": "360 安全浏览器",
            },
            {
                "channel": "firefox",
                "check": "/Applications/Firefox.app",
                "name": "Firefox",
            },
        ]

    if system == "Windows":
        pf = os.environ.get("ProgramFiles", r"C:\Program Files")
        pf86 = os.environ.get(
            "ProgramFiles(x86)", r"C:\Program Files (x86)"
        )
        local = os.environ.get(
            "LOCALAPPDATA",
            os.path.expanduser(r"~\AppData\Local"),
        )
        return [
            {
                "channel": "chrome",
                "check": f"{pf}\\Google\\Chrome\\Application\\chrome.exe",
                "name": "Google Chrome",
            },
            {
                "channel": "msedge",
                "check": f"{pf}\\Microsoft\\Edge\\Application\\msedge.exe",
                "name": "Microsoft Edge",
            },
            {
                "executable": f"{pf86}\\Tencent\\QQBrowser\\QQBrowser.exe",
                "name": "QQ 浏览器",
            },
            {
                "executable": f"{pf}\\Tencent\\QQBrowser\\QQBrowser.exe",
                "name": "QQ 浏览器",
            },
            {
                "executable": (
                    f"{pf86}\\360\\360Safe\\Browser\\360SafeBrowser.exe"
                ),
                "name": "360 安全浏览器",
            },
            {
                "channel": "firefox",
                "check": f"{pf}\\Mozilla Firefox\\firefox.exe",
                "name": "Firefox",
            },
        ]

    # Linux
    return [
        {
            "channel": "chrome",
            "check": "/usr/bin/google-chrome",
            "name": "Google Chrome",
        },
        {
            "channel": "msedge",
            "check": "/usr/bin/microsoft-edge",
            "name": "Microsoft Edge",
        },
        {
            "channel": "chromium",
            "check": "/usr/bin/chromium-browser",
            "name": "Chromium",
        },
        {
            "channel": "firefox",
            "check": "/usr/bin/firefox",
            "name": "Firefox",
        },
    ]


# ── 登录主流程 ──────────────────────────────────────────

async def login_and_capture(timeout: int = 300) -> Dict[str, str]:
    """
    打开用户已安装的浏览器访问 IMA，等待登录后自动捕获认证信息。

    通过拦截 /cgi-bin/ 请求的 headers 获取 x-ima-cookie 和 x-ima-bkn，
    同时收集浏览器 cookies。

    Args:
        timeout: 等待登录的最大秒数（默认 5 分钟）

    Returns:
        包含 x_ima_cookie, x_ima_bkn, cookies 的字典

    Raises:
        ImportError: playwright 未安装
        TimeoutError: 登录超时
        RuntimeError: 浏览器启动失败 / 未找到浏览器
    """
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        raise ImportError(
            "playwright 未安装。请运行:\n"
            "  pip install playwright"
        )

    # 检测浏览器
    launch_kwargs, browser_name = _detect_browser()
    logger.info(f"🌐 使用浏览器: {browser_name}")

    captured: Dict[str, str] = {}
    login_done = asyncio.Event()

    async def on_request(request):
        if "/cgi-bin/" not in request.url:
            return

        headers = request.headers
        cookie_val = headers.get("x-ima-cookie", "")
        bkn_val = headers.get("x-ima-bkn", "")

        # 确保 cookie 中包含有效登录态（IMA-UID 存在说明已登录）
        if cookie_val and "IMA-UID=" in cookie_val and not captured.get("x_ima_cookie"):
            captured["x_ima_cookie"] = cookie_val
            logger.info(f"✅ 捕获 x-ima-cookie (长度={len(cookie_val)})")

        if bkn_val and not captured.get("x_ima_bkn"):
            captured["x_ima_bkn"] = bkn_val
            logger.info("✅ 捕获 x-ima-bkn")

        # 两个都拿到了就标记完成
        if captured.get("x_ima_cookie") and captured.get("x_ima_bkn"):
            login_done.set()

    async with async_playwright() as p:
        try:
            # Firefox 用 p.firefox，其余 Chromium 系用 p.chromium
            browser_type = p.firefox if "firefox" in launch_kwargs.get("channel", "") else p.chromium
            browser = await browser_type.launch(**launch_kwargs)
        except Exception as e:
            raise RuntimeError(
                f"浏览器启动失败 ({browser_name}): {e}\n"
                "请确认浏览器已正确安装。"
            )

        context = await browser.new_context(
            viewport={"width": 1280, "height": 800},
        )
        page = await context.new_page()
        page.on("request", on_request)

        logger.info("🌐 正在打开 IMA 登录页面...")
        await page.goto("https://ima.qq.com", wait_until="domcontentloaded")

        logger.info(f"⏳ 等待登录（超时 {timeout} 秒）...")

        try:
            await asyncio.wait_for(login_done.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            await browser.close()
            raise TimeoutError(
                f"登录未在 {timeout} 秒内完成，请重试。"
            )

        # 收集浏览器 cookies
        browser_cookies = await context.cookies()
        cookie_str = "; ".join(
            f"{c['name']}={c['value']}" for c in browser_cookies
        )
        if cookie_str:
            captured["cookies"] = cookie_str

        # 登录成功后，导航到知识库页面获取知识库列表
        logger.info("📚 正在获取知识库列表...")

        kb_list = []
        kb_done = asyncio.Event()

        async def on_response(response):
            if "get_home_page_data" not in response.url:
                return
            try:
                resp_json = await response.json()
                if resp_json.get("code") != 0:
                    return

                # 新版 API: results 是 section 数组，每个 section 含 knowledge_base_list
                results = resp_json.get("results", [])
                if results:
                    for section in results:
                        category = section.get("knowledge_base_list_name", "")
                        for kb in section.get("knowledge_base_list", []):
                            kb_id = kb.get("id", "")
                            basic = kb.get("basic_info", {})
                            kb_name = basic.get("name", "") or kb.get("name", "")
                            if kb_id and kb_name:
                                kb_list.append({
                                    "id": kb_id,
                                    "name": kb_name,
                                    "category": category,
                                })
                    kb_done.set()
                    return

                # 旧版兼容: data.section_list
                sections = resp_json.get("data", {}).get("section_list", [])
                if sections:
                    for section in sections:
                        category = section.get("name", "")
                        for kb in section.get("kb_list", []):
                            kb_id = kb.get("id", "")
                            kb_name = kb.get("name", "")
                            if kb_id and kb_name:
                                kb_list.append({
                                    "id": kb_id,
                                    "name": kb_name,
                                    "category": category,
                                })
                    kb_done.set()
            except Exception:
                pass

        page.on("response", on_response)
        await page.goto("https://ima.qq.com/wikis", wait_until="domcontentloaded")

        try:
            await asyncio.wait_for(kb_done.wait(), timeout=15)
        except asyncio.TimeoutError:
            logger.warning("⚠️ 获取知识库列表超时，跳过")

        if kb_list:
            import json
            captured["knowledge_bases"] = json.dumps(kb_list, ensure_ascii=False)
            logger.info(f"📚 获取到 {len(kb_list)} 个知识库")

        page.remove_listener("response", on_response)

        logger.info("🔒 登录成功，关闭浏览器")
        await browser.close()

    return captured
