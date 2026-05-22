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

#### Claude Desktop

编辑 `~/Library/Application Support/Claude/claude_desktop_config.json`：

```json
{
  "mcpServers": {
    "ima-copilot": {
      "command": "python",
      "args": ["-c", "import sys; sys.path.insert(0,'src'); from ima_server_simple import mcp; mcp.run(transport='stdio')"],
      "cwd": "/path/to/tencent-ima-copilot-mcp"
    }
  }
}
```

#### 其他 MCP 客户端

根据你的 MCP 客户端配置方式，使用以下命令启动服务器：

```bash
python -c "import sys; sys.path.insert(0,'src'); from ima_server_simple import mcp; mcp.run(transport='stdio')"
```

### 3. 登录

启动 MCP 客户端后，直接告诉你的 AI 助手：

> "登录 IMA" 或 "login to IMA"

`login` 工具会自动：
1. 检测你系统上已安装的浏览器（Chrome/Edge/QQ 浏览器/360/Firefox 等）
2. 打开 IMA 登录页面（https://ima.qq.com）
3. 等待你在浏览器中完成登录
4. 自动捕获并保存认证 Cookie

登录成功后，你就可以使用 `ask` 或 `ask_with_kb` 工具提问了！

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