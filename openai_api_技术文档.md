# openai_api.py 技术文档

> **版本**: 2.2.0
> **对应模块**: 23-高速AI问答 (v1.2.1)
> **创建日期**: 2026-07-21
> **作者**: AI Hub 项目组

---

## 一、项目概述

`openai_api.py` 是一个独立的 FastAPI 服务，把 **小米 MiMo ultraspeed 网页** 包装成 **OpenAI 兼容 API**，让龙虾、LobeChat、OpenWebUI 等支持自定义 OpenAI 端点的客户端可以直接调用。

**核心特点**：
- 不走官方 API（不消耗 sk-key 额度）
- 通过 DrissionPage 操控 Edge 浏览器访问 `ultraspeed.xiaomimimo.com/#/` 网页爬取回复
- 兼容 OpenAI Chat Completions API 和 Responses API 两种协议
- 保留完整的 Markdown 格式（标题、列表、代码块、表格、粗体等）

---

## 二、技术栈

| 组件 | 技术/库 | 说明 |
|------|---------|------|
| Web 框架 | FastAPI + Uvicorn | 异步 ASGI 框架，高性能 |
| 浏览器自动化 | DrissionPage | 国产浏览器自动化库，比 Selenium 更轻量 |
| 浏览器 | Microsoft Edge (Chromium) | 通过 `--remote-debugging-port=9333` 启动调试模式 |
| 目标网页 | ultraspeed.xiaomimimo.com | 小米 MiMo 超高速模型体验页面 |
| 模型 | mimo-v2.5-pro-ultraspeed | 小米超高速模型 |
| API 协议 | OpenAI Chat Completions + Responses API | 兼容主流客户端 |
| 流式传输 | Server-Sent Events (SSE) | 标准 SSE 协议，支持流式输出 |
| 数据格式 | JSON + Markdown | 请求/响应用 JSON，内容用 Markdown |
| 正则处理 | Python re 模块 | 清洗客户端污染的系统提示词 |

---

## 三、架构设计

### 3.1 整体架构

```
┌─────────────────────────────────────────────────────────────┐
│  客户端 (龙虾 / LobeChat / OpenWebUI / curl)                │
└────────────────────────┬────────────────────────────────────┘
                         │ HTTP POST
                         │ /v1/chat/completions  (OpenAI 标准)
                         │ /v1/responses         (OpenAI Responses)
                         ▼
┌─────────────────────────────────────────────────────────────┐
│  openai_api.py (FastAPI, 0.0.0.0:8000)                      │
│  ├─ _extract_user_query()  清洗消息，提取 <user_query>      │
│  ├─ _messages_to_prompt()  messages 数组 → 单条提示词       │
│  ├─ get_page()             浏览器连接管理（线程安全单例）   │
│  ├─ send_and_collect()     发送消息 + 轮询收集回复          │
│  ├─ extract_last_reply()   HTML → Markdown 转换            │
│  └─ _stream_*_sse()        SSE 流式输出                    │
└────────────────────────┬────────────────────────────────────┘
                         │ DrissionPage (CDP 协议)
                         ▼
┌─────────────────────────────────────────────────────────────┐
│  Edge 浏览器 (端口 9333, 已登录 ultraspeed)                 │
│  └─ ultraspeed.xiaomimimo.com/#/ 页面                       │
└────────────────────────┬────────────────────────────────────┘
                         │ 网页交互
                         ▼
┌─────────────────────────────────────────────────────────────┐
│  MiMo ultraspeed 服务端 (mimo-v2.5-pro-ultraspeed 模型)     │
└─────────────────────────────────────────────────────────────┘
```

### 3.2 请求处理流程

1. **接收请求**：FastAPI 接收 POST `/v1/chat/completions` 或 `/v1/responses`
2. **消息清洗**：`_extract_user_query()` 从可能被污染的 content 中提取真正的用户问题
3. **浏览器连接**：`get_page()` 获取/初始化 Edge(9333) 上的 ultraspeed 页面（单例）
4. **权限检查**：检查账号是否有 ultraspeed 体验权限
5. **发送消息**：`send_and_collect()` 先点"新对话"清空上下文，再输入问题
6. **轮询回复**：每 0.5 秒检查页面内容变化，调用 `extract_last_reply()` 提取最新回复
7. **格式转换**：`extract_last_reply()` 把 HTML DOM 转换为 Markdown
8. **返回响应**：包装成 OpenAI 格式返回（流式用 SSE，非流式用 JSON）

---

## 四、遇到的问题与解决方案

### 问题 1：龙虾客户端 404 Not Found

**现象**：龙虾客户端配置 `http://192.168.2.120:8000` 后请求返回 `404 {"detail":"Not Found"}`。

**原因**：龙虾默认调用 OpenAI 标准的 `/v1/chat/completions` 端点，但 v1.0 版本只实现了 `/v1/responses`。

**解决方案**：新增 `/v1/chat/completions` 端点，同时保留 `/v1/responses`。两个端点共用核心逻辑，只是响应格式不同。

```python
@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    # OpenAI Chat Completions 格式
    ...

@app.post("/v1/responses")
async def responses(request: Request):
    # OpenAI Responses API 格式
    ...
```

---

### 问题 2：客户端系统提示词污染回复

**现象**：龙虾/WorkBuddy 客户端把几千字的系统提示词（SOUL.md、BOOTSTRAP.md、connector-status 等）作为 `system` 消息发送，MiMo 把系统提示当作问题处理，回复错乱。

**原因**：旧版 `_messages_to_prompt()` 把所有 system 消息前缀 `[系统提示]` 全文发给网页。

**解决方案（分两步）**：

**第一步**：丢弃超长 system 消息
```python
SYSTEM_MAX_LEN = 200  # 超过 200 字符的 system 消息直接丢弃
if role == "system":
    if len(content) <= SYSTEM_MAX_LEN:
        parts.append("[系统提示] " + content)
    # 否则丢弃
```

**第二步**：从 user 消息中提取 `<user_query>` 标签

客户端把真正的用户问题用 `<user_query>讲5个笑话</user_query>` 标签包裹，外面是大量污染内容。用正则提取：

```python
def _extract_user_query(text):
    # 优先：提取 <user_query>...</user_query> 标签内容，取最后一个
    matches = re.findall(r"<user_query>(.*?)</user_query>", text, re.DOTALL)
    if matches:
        return matches[-1].strip()
    # 兜底：激进清洗，移除所有 XML 标签块
    ...
```

---

### 问题 3：Markdown 格式丢失

**现象**：API 返回的内容没有 Markdown 标记（`#`、`**`、` ``` ` 等），客户端渲染后不美观。

**原因**：旧版 `extract_last_reply()` 用 DOM 的 `innerText` 提取文本，丢失了所有 HTML 标签的语义信息。

**解决方案**：重写 `extract_last_reply()`，实现 HTML → Markdown 转换器：

```javascript
function htmlToMd(node, depth) {
    // 递归遍历 DOM 节点，根据标签类型转换为 Markdown
    if (tag === "h1") result += "\n# " + inner + "\n\n";
    else if (tag === "h2") result += "\n## " + inner + "\n\n";
    else if (tag === "strong") result += "**" + inner + "**";
    else if (tag === "em") result += "*" + inner + "*";
    else if (tag === "code") result += "`" + textContent + "`";
    else if (tag === "pre") result += "\n```" + lang + "\n" + code + "\n```\n\n";
    else if (tag === "ul") result += "- " + item + "\n";
    else if (tag === "ol") result += "1. " + item + "\n";
    else if (tag === "blockquote") result += "> " + line + "\n";
    else if (tag === "table") /* 生成 Markdown 表格 */;
    ...
}
```

支持的格式：
- 标题 h1-h6 → `#` - `######`
- 段落 p → 换行
- 粗体 strong/b → `**text**`
- 斜体 em/i → `*text*`
- 删除线 del/s → `~~text~~`
- 行内代码 code → `` `code` ``
- 代码块 pre → ` ```lang\ncode\n``` `
- 引用 blockquote → `> text`
- 无序列表 ul/li → `- item`
- 有序列表 ol/li → `1. item`
- 链接 a → `[text](url)`
- 图片 img → `![alt](src)`
- 表格 table/thead/tbody → `| cell | cell |`

---

### 问题 4：代码块重复输出

**现象**：代码块被输出了 2-3 次，且语言名（如 `python`）出现在 ` ``` ` 标记外面。

**原因**：ultraspeed 页面的代码块在 DOM 里有 **3 层嵌套 pre**：

```
<pre class="style_code__...">          ← 占位符（显示用）
  <span class="languageLabel">python</span>
  <code>...</code>
</pre>
<pre data-testid="shiki-container">    ← 容器
  <span class="languageLabel">python</span>
  <pre class="shiki github-light">     ← 实际代码（最内层）
    <code>...</code>
  </pre>
</pre>
```

递归遍历时，每个 pre 都输出了代码内容，导致重复。

**解决方案**：
1. **pre.style_code__**（纯占位符）：跳过不输出
2. **pre[shiki-container]**（容器）：不递归，直接用 `querySelector("pre.shiki")` 找最内层
3. **pre.shiki**（实际代码）：提取 textContent 输出

```javascript
if (isPlaceholder && !isContainer) {
    // 纯占位符，跳过
} else if (isContainer) {
    // 容器：直接找内部的 pre.shiki
    const shikiPre = child.querySelector("pre.shiki");
    if (shikiPre) {
        let codeText = shikiPre.textContent.replace(/\n$/, "");
        result += "\n```" + lang + "\n" + codeText + "\n```\n\n";
    }
} else if (isShiki) {
    // 最内层实际代码
    ...
}
```

---

### 问题 5：语言名泄漏到正文

**现象**：代码块前多出一行 `python` 或 `bash`，出现在 ` ``` ` 标记外面。

**原因**：代码块标题栏 `<div class="flex items-center gap-2">` 里有无 class 的 `<span>` 显示语言名，递归遍历时被当作普通文本输出。

**解决方案**：跳过代码块标题栏 div：

```javascript
else if (tag === "div") {
    const divCls = child.className || "";
    // 跳过代码块标题栏（含语言名 span 和复制按钮）
    if (divCls.includes("flex items-center gap-2")) {
        // 跳过
    } else {
        result += inner;
    }
}
```

---

### 问题 6：正则表达式错误（re.error: invalid group reference）

**现象**：服务启动后请求返回 500，日志显示 `re.error: invalid group reference 1 at position 359`。

**原因**：在 `re.sub()` 的替换字符串里用了 `</\1>`，Python 把 `\1` 当作分组引用，但实际是想匹配闭合标签。

**错误代码**：
```python
cleaned = re.sub(r"<(?:tag1|tag2)[\s\S]*?</\1>", "", cleaned)
#                                                     ^^^^ \1 在替换字符串里无效
```

**解决方案**：改为遍历标签列表，每个标签单独匹配：

```python
block_tags = ["user_info", "identity_context", "connector-status", ...]
for tag in block_tags:
    pattern = r"<" + tag + r"[\s\S]*?</" + tag + r">"
    cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE)
```

---

### 问题 7：读到上一次的旧回复

**现象**：发送新问题后，返回的还是上一次的回复内容。

**原因**：ultraspeed 网页没有清空对话，`extract_last_reply()` 读取到的还是上一个"已深度思考"回复。

**解决方案**：在 `send_and_collect()` 开头先点"新对话"按钮清空上下文，并记录基线回复，只有与基线不同的才认为是本次回复：

```python
def send_and_collect(page, msg, on_chunk=None):
    click_new_chat(page)  # 先点"新对话"
    time.sleep(2)
    base_reply = extract_last_reply(page) or ""  # 记录基线
    # ...发送消息...
    # 轮询时只有 cur_reply != base_reply 才认为是新回复
```



---

### 问题 8：页面超时"您已退出体验"导致无法输入

**现象**：ultraspeed 页面超过 10 分钟不对话后，会显示"您已退出体验 重新申请"提示，textarea 被 `disabled` 无法输入，API 请求失败。

**原因**：ultraspeed 有体验时长限制，超时后需要手动点击"重新申请"按钮才能恢复对话。

**解决方案**：新增 `check_and_click_reapply(page)` 函数，在 `send_and_collect()` 开头自动检测并点击：

```python
def check_and_click_reapply(page) -> bool:
    # 1. 检测 textarea 是否被 disabled
    ta_disabled = page.run_js('''
        const ta = document.querySelector("textarea");
        return ta ? ta.disabled === true : false;
    ''')
    if not ta_disabled:
        return False  # 页面正常

    # 2. 查找"重新申请"按钮
    btn = page.ele("xpath://button[contains(text(), '重新申请')]", timeout=2)
    if not btn:
        # 兜底：查找包含"重新申请"文本的 span 的父级 button
        btn = page.ele("xpath://span[contains(text(), '重新申请')]/ancestor::button", timeout=2)
    if btn:
        btn.click()
        time.sleep(3)
        # 3. 验证 textarea 是否恢复
        # 4. 如果仍 disabled，刷新页面兜底
    return True
```

**调用位置**：在 `send_and_collect()` 最开头调用，先恢复对话能力再点"新对话"清空上下文：

```python
def send_and_collect(page, msg, on_chunk=None):
    check_and_click_reapply(page)  # 先检测并点击"重新申请"
    click_new_chat(page)            # 再点"新对话"清空上下文
    time.sleep(2)
    ...
```

**DOM 结构**：
```html
<!-- "您已退出体验 重新申请"提示栏 -->
<div class="flex items-center gap-2">
  <span>您已退出体验</span>
  <button type="button" class="inline-flex h-6 ... bg-mimo-btn-primary-bg-default ...">
    <span class="whitespace-nowrap text-xs ...">重新申请</span>
  </button>
</div>
<!-- textarea 被 disabled -->
<textarea disabled placeholder="想做什么，尽管说..."></textarea>
```

---

## 五、API 接口说明

### 5.1 POST /v1/chat/completions

OpenAI 标准 Chat Completions API，龙虾/LobeChat 等默认用这个。

**请求示例**：
```json
{
    "model": "mimo-v2.5-pro-ultraspeed",
    "messages": [
        {"role": "user", "content": "讲个笑话"}
    ],
    "stream": false
}
```

**非流式响应**：
```json
{
    "id": "chatcmpl-xxx",
    "object": "chat.completion",
    "created": 1721539200,
    "model": "mimo-v2.5-pro-ultraspeed",
    "choices": [
        {
            "index": 0,
            "message": {"role": "assistant", "content": "笑话内容..."},
            "finish_reason": "stop"
        }
    ],
    "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
}
```

**流式响应**：标准 SSE 格式，`data: {chunk}\n\n` + `data: [DONE]\n\n`

### 5.2 POST /v1/responses

OpenAI Responses API。

**请求示例**：
```json
{
    "model": "mimo-v2.5-pro-ultraspeed",
    "instructions": "你是 MiMo AI 助手。",
    "input": "讲个笑话",
    "stream": false
}
```

### 5.3 其他端点

- `GET /` - 服务信息
- `GET /health` - 健康检查（含浏览器连接状态）
- `GET /v1/models` - 模型列表

---

## 六、部署与使用

### 6.1 前置条件

1. 安装 Python 3.10+
2. 安装 Microsoft Edge 浏览器
3. 安装依赖：
   ```bash
   pip install fastapi uvicorn drissionpage requests
   ```

### 6.2 启动步骤

**第一步：启动 Edge 调试端口**

```powershell
& "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe" --remote-debugging-port=9333
```

**第二步：登录 ultraspeed**

在 Edge 里访问 `https://ultraspeed.xiaomimimo.com/#/`，登录有体验权限的账号。

**第三步：启动 API 服务**

```powershell
cd ai_hub
python openai_api.py
```

服务启动在 `0.0.0.0:8000`。

### 6.3 客户端配置

**龙虾 / LobeChat / OpenWebUI**：
```
Base URL: http://localhost:8000/v1
API Key: 任意填（如 sk-anything）
Model:    mimo-v2.5-pro-ultraspeed
端点:     /v1/chat/completions
```

**curl 调用**：
```bash
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "mimo-v2.5-pro-ultraspeed",
    "messages": [{"role": "user", "content": "讲个笑话"}],
    "stream": false
  }'
```

### 6.4 局域网访问

服务监听 `0.0.0.0:8000`，局域网内其他设备可用：
```
http://<本机IP>:8000/v1/chat/completions
```

---

## 七、性能与限制

| 指标 | 数值 | 说明 |
|------|------|------|
| 响应时间 | 10-60 秒 | 浏览器直连方式，比 API 慢 |
| 并发能力 | 1（串行） | 浏览器同时只能处理一个对话 |
| 超时时间 | 240 秒 | `max_rounds=480` × 0.5 秒 |
| 流式输出 | 伪流式 | 实际是等完成后一次性输出（DrissionPage 限制） |
| 鉴权 | 无 | API Key 随便填 |
| 格式 | Markdown | 保留标题/列表/代码块/表格/粗体等 |

---

## 八、文件清单

| 文件 | 说明 |
|------|------|
| `ai_hub/openai_api.py` | API 服务主程序 |
| `ai_hub/openai_api_技术文档.md` | 本文档 |
| `ai_hub/config.py` | 版本号与 changelog（mod23 v1.2.0） |
| `ai_hub/modules/mod23_high_speed_qa.py` | Streamlit 模块（三后端切换） |

---

## 九、版本历史

| 版本 | 日期 | 变更 |
|------|------|------|
| 1.0.0 | 2026-07-20 | 初始版本：sk-key 调 api.xiaomimimo.com，仅 /v1/responses |
| 2.0.0 | 2026-07-20 | 改为浏览器直连：DrissionPage + Edge(9333) + ultraspeed 网页 |
| 2.1.0 | 2026-07-21 | 新增 /v1/chat/completions 端点；HTML→Markdown 转换；系统提示词清洗；代码块去重；语言名泄漏修复 |
| 2.2.0 | 2026-07-21 | 新增"重新申请"按钮自动点击；超时退出体验自动恢复；textarea disabled 检测；刷新页面兜底 |

---

## 十、常见问题

**Q1: 提示"无法连接 Edge(9333)"怎么办？**
A: 确保已用 `--remote-debugging-port=9333` 启动 Edge，且 Edge 没有被关闭。

**Q2: 提示"当前账号无 ultraspeed 体验权限"怎么办？**
A: 在 Edge 里手动访问 ultraspeed.xiaomimimo.com，登录有权限的账号。

**Q3: 回复很慢（超过 60 秒）怎么办？**
A: 浏览器直连方式本身较慢。如需快速响应，可用 mod23 的第二个后端（sk-key 调 api.xiaomimimo.com）。

**Q4: 回复格式不对（没有 Markdown）怎么办？**
A: 确保使用 v2.1.0+ 版本，已实现 HTML→Markdown 转换。

**Q5: 龙虾客户端 404 怎么办？**
A: 确保用 `/v1/chat/completions` 端点，Base URL 配置为 `http://IP:8000/v1`。
