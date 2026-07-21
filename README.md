# MiMo v2.5-pro-ultraspeed OpenAI-Compatible API

> 将 [ultraspeed.xiaomimimo.com](https://ultraspeed.xiaomimimo.com/) 网页包装为 OpenAI 兼容 API 服务的逆向工程方案。
>
> 通过 DrissionPage 操控 Edge 浏览器直连网页爬取，无需 API Key，支持任意兼容 OpenAI 协议的客户端（龙虾 / LobeChat / NextChat 等）直接接入。

![Python](https://img.shields.io/badge/Python-3.9+-blue.svg)
![FastAPI](https://img.shields.io/badge/FastAPI-0.110+-green.svg)
![License](https://img.shields.io/badge/License-MIT-yellow.svg)
![Version](https://img.shields.io/badge/Version-2.2.0-orange.svg)

---

## 目录

- [项目背景](#项目背景)
- [核心特性](#核心特性)
- [技术栈](#技术栈)
- [架构设计](#架构设计)
- [快速开始](#快速开始)
- [API 接口说明](#api-接口说明)
- [使用示例](#使用示例)
- [遇到的问题与解决方案](#遇到的问题与解决方案)
- [性能与限制](#性能与限制)
- [版本历史](#版本历史)
- [常见问题](#常见问题)
- [免责声明](#免责声明)

---

## 项目背景

[ultraspeed.xiaomimimo.com](https://ultraspeed.xiaomimimo.com/) 是小米推出的 MiMo v2.5-pro-ultraspeed 模型体验平台，提供免费的深度思考 AI 对话能力。但官方仅提供 Web 界面，存在以下限制：

1. **无开放 API**：不提供官方 API Key，无法被第三方客户端接入
2. **10 分钟体验时限**：单次会话超过 10 分钟会自动退出，需手动点击"重新申请"
3. **网页格式限定**：回复以 HTML 渲染呈现，无法直接被程序消费

本项目通过浏览器自动化技术，将网页操作包装为标准 OpenAI 兼容 API，使任意支持 OpenAI 协议的客户端都能直接接入 MiMo 模型，同时自动处理超时恢复、格式转换等问题。

---

## 核心特性

### 端点兼容
- 支持 `/v1/chat/completions`（OpenAI Chat Completions 标准）
- 支持 `/v1/responses`（OpenAI Responses API）
- 龙虾、LobeChat、NextChat、OpenWebUI 等客户端零配置接入

### 智能恢复
- **"重新申请"自动点击**：检测到 10 分钟超时退出时，自动点击按钮恢复对话能力
- **页面异常兜底**：点击失败时自动刷新页面恢复

### 格式保留
- **HTML → Markdown 转换**：自定义递归 DOM walker，保留标题/列表/代码块/粗体/链接等格式
- **代码块去重**：处理 ultraspeed 3 层嵌套 `<pre>` 结构，避免代码重复输出
- **语言名修复**：跳过代码块标题栏，防止语言名（如 python、bash）泄漏到正文

### 输入清洗
- **系统提示词过滤**：完全丢弃客户端注入的 system 角色消息
- **`<user_query>` 提取**：从被污染的 user 消息中精准提取真实问题
- **激进的 XML 标签清理**：兜底移除所有 `<...>` 标签块

### 流式响应
- 支持 SSE（Server-Sent Events）流式输出
- 实时返回生成内容，无需等待完整回复

---

## 技术栈

| 组件 | 作用 | 版本 |
|------|------|------|
| **Python** | 运行时环境 | 3.9+ |
| **FastAPI** | Web 框架，提供 API 端点 | 0.110+ |
| **Uvicorn** | ASGI 服务器 | 0.27+ |
| **DrissionPage** | 浏览器自动化（CDP 协议） | 4.0+ |
| **Microsoft Edge** | 被控浏览器 | 任意版本 |
| **JavaScript** | DOM 解析与 HTML→Markdown 转换 | 浏览器原生 |

---

## 架构设计

```
┌─────────────────────────────────────────────────────────────┐
│  客户端（龙虾 / LobeChat / NextChat / curl 等）              │
└────────────────────────┬────────────────────────────────────┘
                         │ HTTP POST (OpenAI 协议)
                         ▼
┌─────────────────────────────────────────────────────────────┐
│  openai_api.py (FastAPI 服务，监听 0.0.0.0:8000)            │
│                                                              │
│  ┌────────────┐    ┌─────────────┐    ┌──────────────┐     │
│  │ 请求预处理 │ -> │ 输入清洗    │ -> │ 浏览器调度   │     │
│  │ 端点路由   │    │ 提取用户问题│    │ (线程锁)     │     │
│  └────────────┘    └─────────────┘    └──────┬───────┘     │
│                                                │             │
│                                                ▼             │
│                       ┌────────────────────────────────┐    │
│                       │ DrissionPage (CDP 9333)        │    │
│                       │ 操控 Edge 浏览器               │    │
│                       └────────┬───────────────────────┘    │
│                                │                            │
│                                ▼                            │
│                       ┌────────────────────────────────┐    │
│                       │ ultraspeed.xiaomimimo.com      │    │
│                       │ (网页爬取回复)                 │    │
│                       └────────┬───────────────────────┘    │
│                                │                            │
│                                ▼                            │
│                       ┌────────────────────────────────┐    │
│                       │ HTML → Markdown 转换           │    │
│                       │ (JS 递归 DOM walker)           │    │
│                       └────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────┘
```

### 关键设计

1. **线程安全单例**：全局只有一个浏览器实例，通过 `_page_lock` 互斥锁串行化请求
2. **CDP 协议直连**：通过 Edge 的 `--remote-debugging-port=9333` 端口连接，复用已登录会话
3. **轮询收集**：每 500ms 轮询 DOM 变化，检测回复开始与稳定，支持流式推送

---

## 快速开始

### 前置条件

1. **安装 Microsoft Edge 浏览器**（Windows 默认已安装）
2. **Python 3.9+** 环境
3. **ultraspeed 体验权限**：需要一个已登录并拥有体验权限的小米账号

### 安装步骤

#### 1. 克隆仓库

```bash
git clone https://github.com/kuaitoukuai/mimo-v2.5-pro-ultraspeed.git
cd mimo-v2.5-pro-ultraspeed
```

#### 2. 安装依赖

```bash
pip install -r requirements.txt
```

#### 3. 以调试模式启动 Edge

关闭所有 Edge 窗口，然后用以下命令启动（保留窗口打开）：

```bash
# Windows
"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe" --remote-debugging-port=9333

# 或者指定用户数据目录（避免与日常使用冲突）
"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe" --remote-debugging-port=9333 --user-data-dir="C:\edge-debug-profile"
```

#### 4. 在 Edge 中登录 ultraspeed

在启动的 Edge 窗口中访问 [https://ultraspeed.xiaomimimo.com/](https://ultraspeed.xiaomimimo.com/)，登录小米账号并确认有体验权限。

#### 5. 启动 API 服务

```bash
python openai_api.py
```

服务默认监听 `0.0.0.0:8000`，无鉴权。看到以下输出即启动成功：

```
INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
INFO:     Application startup complete.
```

---

## API 接口说明

### 1. Chat Completions（推荐）

**端点**：`POST /v1/chat/completions`

**请求体**（OpenAI 标准格式）：

```json
{
  "model": "mimo-v2.5-pro-ultraspeed",
  "messages": [
    {"role": "user", "content": "讲5个笑话"}
  ],
  "stream": false
}
```

**响应体**（OpenAI 标准格式）：

```json
{
  "id": "chatcmpl-xxx",
  "object": "chat.completion",
  "created": 1234567890,
  "model": "mimo-v2.5-pro-ultraspeed",
  "choices": [
    {
      "index": 0,
      "message": {
        "role": "assistant",
        "content": "1. ...（Markdown 格式回复）"
      },
      "finish_reason": "stop"
    }
  ],
  "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
}
```

### 2. Responses API

**端点**：`POST /v1/responses`

**请求体**：

```json
{
  "model": "mimo-v2.5-pro-ultraspeed",
  "input": "讲5个笑话"
}
```

### 3. 流式响应

设置 `"stream": true`，服务端会以 SSE 格式实时推送增量内容：

```
event: message.delta
data: {"delta":{"content":"..."}}

event: message.done
data: {"done":true}
```

### 4. 健康检查

**端点**：`GET /health`

返回 `{"status": "ok"}`，可用于监控。

---

## 使用示例

### curl 调用

```bash
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "mimo-v2.5-pro-ultraspeed",
    "messages": [{"role": "user", "content": "帮我写一个100行的Python程序"}]
  }'
```

### Python 客户端

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:8000/v1",
    api_key="not-needed"  # 本服务无鉴权
)

response = client.chat.completions.create(
    model="mimo-v2.5-pro-ultraspeed",
    messages=[{"role": "user", "content": "讲5个笑话"}]
)

print(response.choices[0].message.content)
```

### 接入 LobeChat / NextChat

在客户端设置中配置：

| 字段 | 值 |
|------|-----|
| API Base URL | `http://your-server:8000/v1` |
| API Key | 任意值（如 `sk-xxx`） |
| Model | `mimo-v2.5-pro-ultraspeed` |

---

## 遇到的问题与解决方案

### 问题 1：客户端 404 Not Found

**现象**：龙虾客户端默认请求 `/v1/chat/completions`，但初版仅实现了 `/v1/responses`。

**解决**：补充实现 `/v1/chat/completions` 端点，两个端点共享核心逻辑。

### 问题 2：系统提示词污染

**现象**：龙虾/WorkBuddy 等客户端会注入数千字符的系统提示词作为 `system` 角色消息，导致页面无法正确理解问题。

**解决**：完全丢弃所有 `system` 角色消息，只处理 `user` 消息。

### 问题 3：用户消息被标签污染

**现象**：客户端将真实问题包裹在 `<user_query>讲5个笑话</user_query>` 中，但周围环绕大量 `<system-reminder>`、`<identity_context>`、`<product_identity>` 等标签块。

**解决**：实现 `_extract_user_query()` 函数：
1. 优先用正则提取 `<user_query>...</user_query>` 标签内容
2. 兜底用激进清洗，移除所有 `<...>` 标签块

### 问题 4：Markdown 格式丢失

**现象**：初版用 `innerText` 提取回复，所有 HTML 语义丢失，标题/列表/代码块都变成纯文本。

**解决**：重写 `extract_last_reply()` 为 HTML→Markdown 转换器：
- 实现递归 `htmlToMd()` JavaScript 函数
- 支持 12+ HTML 标签类型（h1-h6、p、br、hr、strong、em、code、pre、blockquote、ul、ol、a、img、table）

### 问题 5：代码块重复输出

**现象**：代码块被输出 2-3 次。

**原因**：ultraspeed 的 DOM 有 3 层嵌套 `<pre>`：
- `pre.style_code__`（占位符，显示用）
- `pre[data-testid="shiki-container"]`（overlay 容器）
- `pre.shiki`（实际代码，最内层）

**解决**：分层处理：
- 占位符 `pre`：跳过不输出
- `shiki-container`：直接 `querySelector("pre.shiki")` 取内层，不递归
- `pre.shiki`：输出代码

### 问题 6：语言名泄漏

**现象**：代码块前出现 "python"、"bash" 等语言名作为正文。

**原因**：代码块标题栏 `<div class="flex items-center gap-2">` 包含语言名 `<span>` 和复制按钮。

**解决**：在 div 处理时跳过 `class` 包含 `flex items-center gap-2` 的元素。

### 问题 7：10 分钟超时退出

**现象**：ultraspeed 单次会话 10 分钟后自动退出，textarea 被 disabled，需手动点击"重新申请"才能继续。

**解决**：实现 `check_and_click_reapply()` 函数：
1. 检测 `textarea.disabled` 状态
2. 通过 xpath 查找"重新申请"按钮（3 级兜底）
3. 点击后等待 3 秒，验证 textarea 恢复
4. 失败兜底：刷新页面

### 问题 8：正则表达式错误

**现象**：`re.error: invalid group reference 1`。

**原因**：在 `re.sub()` 替换字符串中使用 `</\1>`，Python 将 `\1` 解析为组引用。

**解决**：改为遍历标签列表，每个标签单独调用 `re.sub()`。

---

## 性能与限制

### 性能

| 指标 | 数值 |
|------|------|
| 单次请求耗时 | 10-60 秒（取决于回复长度） |
| 并发能力 | 1（单浏览器实例串行） |
| 内存占用 | ~200MB（Edge 进程） |
| 支持流式 | 是 |

### 限制

- **单线程**：全局只有一个浏览器实例，请求串行处理
- **依赖 ultraspeed 可用性**：网页改版或下线会导致服务失效
- **无鉴权**：默认无鉴权，部署在公网需自行加反向代理鉴权
- **无上下文**：每次请求都点"新对话"清空上下文，不保留多轮对话

---

## 版本历史

| 版本 | 日期 | 变更 |
|------|------|------|
| 1.0.0 | 2026-07-20 | 初始版本：sk-key 调 api.xiaomimimo.com |
| 2.0.0 | 2026-07-20 | 改为浏览器直连：DrissionPage + Edge(9333) |
| 2.1.0 | 2026-07-21 | 新增 `/v1/chat/completions`；HTML→Markdown；系统提示词清洗；代码块去重；语言名泄漏修复 |
| 2.2.0 | 2026-07-21 | 新增"重新申请"按钮自动点击；超时退出体验自动恢复 |

---

## 常见问题

### Q: 启动报错 "Could not connect to Edge"

**A**: 确保已用 `--remote-debugging-port=9333` 启动 Edge，且端口未被占用。

### Q: 接口返回空内容

**A**: 检查 Edge 窗口中 ultraspeed 页面是否正常，是否已登录且有体验权限。

### Q: 如何保留多轮对话上下文

**A**: 当前版本每次请求都点"新对话"清空上下文。如需保留上下文，可修改 `send_and_collect()` 中的 `click_new_chat()` 调用逻辑。

### Q: 可以部署到 Linux 服务器吗

**A**: 理论上可以，但需要安装 Edge for Linux 或改用 Chrome。推荐用 Docker + headless 浏览器方案。

### Q: PAT 失效后如何更新

**A**: 本服务无鉴权，不涉及 PAT。如果客户端要求 API Key，填任意值即可。

---

## 免责声明

本项目仅供学习和研究使用。使用者需自行承担使用风险，遵守相关法律法规和 ultraspeed.xiaomimimo.com 的服务条款。作者不对任何因使用本项目而产生的直接或间接损失负责。

---

## License

MIT License - 详见 [LICENSE](LICENSE)
