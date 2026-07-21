# -*- coding: utf-8 -*-
"""OpenAI 兼容 API 服务 - 浏览器直连版本

支持两个端点:
  - /v1/chat/completions  (OpenAI 标准 Chat Completions, 龙虾/LobeChat 等默认用这个)
  - /v1/responses         (OpenAI Responses API)

后端: DrissionPage 操控 Edge(9333) 访问 ultraspeed.xiaomimimo.com/#/ 网页爬取
前置: Edge 已用 --remote-debugging-port=9333 启动并登录 ultraspeed 有体验权限
启动: python openai_api.py   端口 8000  无鉴权
"""
import json
import re
import time
import uuid
import threading
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse

EDGE_DEBUG_PORT = 9333
ULTRASPEED_URL = "https://ultraspeed.xiaomimimo.com/#/"
DEFAULT_MODEL = "mimo-v2.5-pro-ultraspeed"
DEFAULT_INSTRUCTIONS = (
    "你是 MiMo AI 助手。请注意：你不能联网，无法访问互联网、网页或实时数据。"
    "请基于你已有的知识回答问题。"
)

app = FastAPI(
    title="MiMo OpenAI-Compatible API (Browser Direct)",
    version="2.2.0",
    description="DrissionPage 操控 Edge 直连 ultraspeed 网页, 包装为 OpenAI 兼容 API",
)

_page_lock = threading.Lock()
_page = None


def get_page():
    global _page
    with _page_lock:
        if _page is not None:
            try:
                _ = _page.url
                if "ultraspeed" in (_page.url or ""):
                    return _page
            except Exception:
                _page = None
        from DrissionPage import ChromiumPage, ChromiumOptions
        co = ChromiumOptions().set_local_port(EDGE_DEBUG_PORT)
        _page = ChromiumPage(co)
        if "ultraspeed" not in (_page.url or ""):
            _page.get(ULTRASPEED_URL)
            _page.wait.doc_loaded()
            time.sleep(5)
        return _page


def extract_last_reply(page) -> str:
    """从 DOM 提取最后一个'已深度思考'回复正文，保留 markdown 格式

    策略：找到回复容器后，遍历其子节点把 HTML 转成 markdown，
    保留标题/列表/代码块/粗体/斜体/链接等格式。
    """
    return page.run_js(r"""
        // 第一步：找到最后一个含"已深度思考"的容器
        const allDivs = document.querySelectorAll("div");
        let lastThinkDiv = null;
        for (const d of allDivs) {
            const txt = (d.innerText || "");
            if (txt.includes("已深度思考") && txt.length > 20) {
                lastThinkDiv = d;
            }
        }
        if (!lastThinkDiv) return "";
        let bestContainer = lastThinkDiv;
        let container = lastThinkDiv;
        for (let i = 0; i < 5; i++) {
            const parent = container.parentElement;
            if (!parent) break;
            const ptxt = parent.innerText || "";
            if (ptxt.length > bestContainer.innerText.length + 10) {
                bestContainer = parent;
            }
            container = parent;
        }

        // 第二步：在 bestContainer 内找"已深度思考"之后的兄弟元素
        // 通常回复正文在"已深度思考"所在元素的下一个兄弟元素里
        let replyRoot = null;
        // 递归查找包含"已深度思考"的最深层元素
        function findThinkElement(root) {
            const walker = document.createTreeWalker(root, NodeFilter.SHOW_ELEMENT);
            let node = walker.currentNode;
            let found = null;
            while (node) {
                if (node.innerText && node.innerText.includes("已深度思考") && node.children.length <= 3) {
                    if (!found || node.innerText.length < found.innerText.length + 50) {
                        found = node;
                    }
                }
                node = walker.nextNode();
            }
            return found;
        }
        const thinkEl = findThinkElement(bestContainer);
        if (thinkEl) {
            // 找 thinkEl 的下一个兄弟元素（通常是回复正文）
            let next = thinkEl.nextElementSibling;
            while (next && next.innerText && next.innerText.trim().length < 5) {
                next = next.nextElementSibling;
            }
            if (next) replyRoot = next;
        }
        if (!replyRoot) {
            // 退回：用 bestContainer，但需要跳过"已深度思考"行
            replyRoot = bestContainer;
        }

        // 第三步：HTML -> Markdown 转换
        function htmlToMd(node, depth) {
            if (depth > 20) return "";
            let result = "";
            for (const child of node.childNodes) {
                if (child.nodeType === Node.TEXT_NODE) {
                    result += child.textContent || "";
                } else if (child.nodeType === Node.ELEMENT_NODE) {
                    const tag = (child.tagName || "").toLowerCase();
                    const inner = htmlToMd(child, depth + 1);
                    if (tag === "h1") result += "\n# " + inner + "\n\n";
                    else if (tag === "h2") result += "\n## " + inner + "\n\n";
                    else if (tag === "h3") result += "\n### " + inner + "\n\n";
                    else if (tag === "h4") result += "\n#### " + inner + "\n\n";
                    else if (tag === "h5") result += "\n##### " + inner + "\n\n";
                    else if (tag === "h6") result += "\n###### " + inner + "\n\n";
                    else if (tag === "p") result += inner + "\n\n";
                    else if (tag === "br") result += "\n";
                    else if (tag === "hr") result += "\n---\n\n";
                    else if (tag === "strong" || tag === "b") result += "**" + inner + "**";
                    else if (tag === "em" || tag === "i") result += "*" + inner + "*";
                    else if (tag === "del" || tag === "s") result += "~~" + inner + "~~";
                    else if (tag === "code") {
                        // 行内 code（不在 pre 里）
                        result += "`" + (child.textContent || "") + "`";
                    }
                    else if (tag === "pre") {
                        // 代码块处理：ultraspeed 的代码块有 3 层嵌套 pre
                        // - pre.style_code__  (placeholder, 显示用)
                        // - pre[shiki-container]  (overlay 容器)
                        // - pre.shiki  (实际代码, 最内层)
                        // 只提取 pre.shiki 的内容，跳过外层避免重复
                        const preCls = child.className || "";
                        const isShiki = preCls.includes("shiki");
                        const isContainer = child.getAttribute("data-testid") === "shiki-container";
                        const isPlaceholder = preCls.includes("style_code__");

                        if (isPlaceholder && !isContainer) {
                            // 纯占位符 pre（无嵌套 shiki），跳过不输出
                        } else if (isContainer) {
                            // shiki-container：直接找内部的 pre.shiki，不递归其他子节点
                            // （避免 languageLabel span 的内容泄漏）
                            const shikiPre = child.querySelector("pre.shiki");
                            if (shikiPre) {
                                let lang = "";
                                const langLabel = child.querySelector(".languageLabel");
                                if (langLabel) lang = (langLabel.textContent || "").trim();
                                let codeText = (shikiPre.textContent || "").replace(/\n$/, "");
                                result += "\n```" + lang + "\n" + codeText + "\n```\n\n";
                            }
                        } else if (isShiki) {
                            // 这是最内层的实际代码
                            let lang = "";
                            let codeText = child.textContent || "";
                            // 从父元素找语言标签
                            const parent = child.parentElement;
                            if (parent) {
                                const langLabel = parent.querySelector(".languageLabel");
                                if (langLabel) {
                                    lang = (langLabel.textContent || "").trim();
                                }
                            }
                            if (!lang) {
                                const langMatch = preCls.match(/language-([\w]+)/);
                                if (langMatch) lang = langMatch[1];
                            }
                            codeText = codeText.replace(/\n$/, "");
                            result += "\n```" + lang + "\n" + codeText + "\n```\n\n";
                        } else {
                            // 未知 pre 类型，保守处理
                            let codeText = (child.textContent || "").replace(/\n$/, "");
                            result += "\n```\n" + codeText + "\n```\n\n";
                        }
                    }
                    else if (tag === "blockquote") {
                        const lines = inner.split("\n");
                        result += "\n" + lines.map(l => "> " + l).join("\n") + "\n\n";
                    }
                    else if (tag === "ul") {
                        let items = "";
                        for (const li of child.children) {
                            if (li.tagName.toLowerCase() === "li") {
                                items += "- " + htmlToMd(li, depth + 1).trim() + "\n";
                            }
                        }
                        result += "\n" + items + "\n";
                    }
                    else if (tag === "ol") {
                        let items = "";
                        let idx = 1;
                        for (const li of child.children) {
                            if (li.tagName.toLowerCase() === "li") {
                                items += idx + ". " + htmlToMd(li, depth + 1).trim() + "\n";
                                idx++;
                            }
                        }
                        result += "\n" + items + "\n";
                    }
                    else if (tag === "a") {
                        const href = child.getAttribute("href") || "";
                        result += "[" + inner + "](" + href + ")";
                    }
                    else if (tag === "img") {
                        const alt = child.getAttribute("alt") || "";
                        const src = child.getAttribute("src") || "";
                        result += "![" + alt + "](" + src + ")";
                    }
                    else if (tag === "table") {
                        // 简单表格保留
                        result += "\n" + inner + "\n\n";
                    }
                    else if (tag === "thead") {
                        const cells = [];
                        child.querySelectorAll("th").forEach(th => cells.push(th.textContent || ""));
                        result += "| " + cells.join(" | ") + " |\n";
                        result += "| " + cells.map(() => "---").join(" | ") + " |\n";
                    }
                    else if (tag === "tbody") {
                        child.querySelectorAll("tr").forEach(tr => {
                            const cells = [];
                            tr.querySelectorAll("td").forEach(td => cells.push(td.textContent || ""));
                            result += "| " + cells.join(" | ") + " |\n";
                        });
                    }
                    else if (tag === "span") {
                        // 跳过语言标签 span（代码块语言名，已在 pre 处理时提取）
                        const spanCls = child.className || "";
                        if (!spanCls.includes("languageLabel")) {
                            result += inner;
                        }
                    }
                    else if (tag === "div" || tag === "section" || tag === "article") {
                        const divCls = child.className || "";
                        // 跳过代码块标题栏（含语言名 span 和复制按钮，会泄漏语言名到正文）
                        if (divCls.includes("flex items-center gap-2")) {
                            // 跳过
                        } else {
                            result += inner;
                        }
                    }
                    else {
                        // 其他标签：直接取内容
                        result += inner;
                    }
                }
            }
            return result;
        }

        let md = htmlToMd(replyRoot, 0);

        // 如果用了 bestContainer，需要跳过"已深度思考"行
        if (replyRoot === bestContainer) {
            const thinkIdx = md.indexOf("已深度思考");
            if (thinkIdx !== -1) {
                let lineEnd = md.indexOf("\n", thinkIdx);
                if (lineEnd === -1) lineEnd = thinkIdx + 5;
                md = md.substring(lineEnd);
            }
        }

        // 清理结尾固定提示
        const tails = ["本网站为面向开发者的模型能力演示平台", "引用来源", "API 服务", "本次体验剩余时间"];
        for (const tail of tails) {
            const ti = md.indexOf(tail);
            if (ti !== -1) { md = md.substring(0, ti).trim(); break; }
        }

        // 格式清理
        md = md.replace(/\r\n/g, "\n").replace(/\r/g, "\n");
        md = md.replace(/\n{3,}/g, "\n\n");
        md = md.replace(/^\n+/, "").replace(/\n+$/, "");
        return md;
    """) or ""


def click_new_chat(page) -> bool:
    btn = page.ele("xpath://*[@data-track-id='navbar_new_chat_btn']", timeout=2)
    if not btn:
        btn = page.ele("xpath://*[contains(text(), '新对话')]", timeout=2)
    if btn:
        btn.click()
        time.sleep(2)
        return True
    return False


def check_and_click_reapply(page) -> bool:
    """检测并点击"重新申请"按钮

    ultraspeed 页面超过 10 分钟不对话会显示"您已退出体验 重新申请"提示，
    此时 textarea 被 disabled 无法输入。本函数检测到该状态时自动点击"重新申请"。

    Returns:
        True 如果点击了"重新申请"按钮，False 如果页面正常无需点击
    """
    try:
        # 方法1：检测 textarea 是否被 disabled
        ta_disabled = page.run_js("""
            const ta = document.querySelector("textarea");
            if (!ta) return false;
            return ta.disabled === true;
        """)
        if not ta_disabled:
            # textarea 正常，无需点击
            return False

        # textarea 被 disabled，查找"重新申请"按钮
        # 方法2：用 xpath 查找包含"重新申请"文本的 button
        btn = page.ele("xpath://button[contains(text(), '重新申请')]", timeout=2)
        if not btn:
            # 尝试查找包含"重新申请"文本的 span，然后找其父级 button
            btn = page.ele("xpath://span[contains(text(), '重新申请')]/ancestor::button", timeout=2)
        if not btn:
            # 兜底：用文本查找任意可点击元素
            btn = page.ele("xpath://*[contains(text(), '重新申请')]", timeout=2)

        if btn:
            print("[check_and_click_reapply] 检测到'您已退出体验'，点击'重新申请'按钮")
            btn.click()
            time.sleep(3)  # 等待页面刷新

            # 验证 textarea 是否恢复可用
            ta_still_disabled = page.run_js("""
                const ta = document.querySelector("textarea");
                if (!ta) return true;
                return ta.disabled === true;
            """)
            if ta_still_disabled:
                # 再等一会
                time.sleep(3)
                # 如果还是 disabled，尝试刷新页面
                print("[check_and_click_reapply] 点击后 textarea 仍 disabled，尝试刷新页面")
                page.refresh()
                page.wait.doc_loaded()
                time.sleep(5)
            else:
                print("[check_and_click_reapply] '重新申请'点击成功，textarea 已恢复")
            return True
        else:
            # textarea disabled 但找不到"重新申请"按钮，可能页面结构变化
            print("[check_and_click_reapply] textarea disabled 但未找到'重新申请'按钮，尝试刷新页面")
            page.refresh()
            page.wait.doc_loaded()
            time.sleep(5)
            return True
    except Exception as e:
        print(f"[check_and_click_reapply] 检测异常: {e}")
        return False


def send_and_collect(page, msg, on_chunk=None):
    """发送消息并轮询收集回复。每次发送前先点'新对话'清空上下文。
    Returns: (final_text, status)  status: done / timeout / error
    """
    # 先检测是否处于"您已退出体验"状态，如果是则点击"重新申请"
    check_and_click_reapply(page)
    # 再点"新对话"清空上下文
    click_new_chat(page)
    time.sleep(2)
    ta = page.ele("tag:textarea", timeout=5)
    if not ta:
        return "", "error"
    base_len = page.run_js("return document.body.innerText.length;") or 0
    base_reply = extract_last_reply(page) or ""
    ta.click()
    time.sleep(0.3)
    ta.input(msg)
    time.sleep(0.5)
    ta.input("\n")
    t0 = time.time()
    last_len = base_len
    stable = 0
    max_rounds = 480
    reply_started = False
    last_reply = ""
    for i in range(max_rounds):
        time.sleep(0.5)
        cur_len = page.run_js("return document.body.innerText.length;") or 0
        if not reply_started:
            if cur_len != last_len:
                reply_started = True
            else:
                last_len = cur_len
                continue
        cur_reply = extract_last_reply(page)
        if cur_reply and cur_reply != base_reply and cur_reply != last_reply:
            last_reply = cur_reply
            if on_chunk:
                try:
                    on_chunk(last_reply)
                except Exception:
                    pass
        if cur_len == last_len:
            stable += 1
            if stable >= 3 and reply_started:
                final_reply = extract_last_reply(page)
                if final_reply and final_reply != base_reply:
                    return final_reply, "done"
                elif final_reply == base_reply:
                    stable = 0
        else:
            stable = 0
        last_len = cur_len
    return last_reply, "timeout"


# ============================================================
# 格式工具
# ============================================================
def _sse(event, data):
    return "event: " + event + "\ndata: " + json.dumps(data, ensure_ascii=False) + "\n\n"


def _normalize_input(user_input):
    if user_input is None:
        return ""
    if isinstance(user_input, str):
        return user_input
    if isinstance(user_input, list):
        parts = []
        for item in user_input:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                if item.get("type") == "message":
                    content = item.get("content", "")
                    if isinstance(content, str):
                        parts.append(content)
                    elif isinstance(content, list):
                        for c in content:
                            if isinstance(c, dict):
                                if c.get("type") in ("input_text", "text"):
                                    parts.append(c.get("text", ""))
                            elif isinstance(c, str):
                                parts.append(c)
                elif item.get("type") in ("input_text", "text"):
                    parts.append(item.get("text", ""))
        return "\n".join(p for p in parts if p)
    return str(user_input)


def _extract_user_query(text):
    """从可能被客户端污染的 content 中提取真正的用户问题

    客户端（龙虾/WorkBuddy 等）常把大量系统提示词塞进 user 消息 content，
    真正的用户问题用 <user_query>...</user_query> 标签包裹。
    本函数只提取最后一个 user_query 标签的内容；如果没有标签，做激进清洗。
    """
    if not text:
        return ""
    # 优先：提取所有 <user_query>...</user_query>，取最后一个
    matches = re.findall(r"<user_query>(.*?)</user_query>", text, re.DOTALL)
    if matches:
        return matches[-1].strip()
    # 次选：提取 <user_query>...</user_query>（无闭合标签的情况）
    m = re.search(r"<user_query>(.*?)$", text, re.DOTALL)
    if m:
        return m.group(1).strip()
    # 兜底：激进清洗——移除所有 <...> 标签块及其内容，移除系统提示段落
    cleaned = text
    # 移除 <system-reminder>...</system-reminder> 整块
    cleaned = re.sub(r"<system-reminder[\s\S]*?</system-reminder>", "", cleaned, flags=re.IGNORECASE)
    # 移除其他常见 XML/HTML 标签块（成对标签，用 lambda 避免反向引用问题）
    block_tags = [
        "user_info", "identity_context", "product_identity", "project_context",
        "additional_data", "connector-status", "memory_and_skills_reminder",
        "current-working-directory", "final_answer_instructions", "agent_loop",
        "result_presentation", "sharing_files", "content_policy",
        "personal_files_safety", "regional_conventions", "working_modes",
        "code-explorer_subagent_usage", "automations", "memory_system",
        "user_context", "project_layout", "working_memory_files",
        "agent_skills", "available_skills", "system-reminder",
    ]
    for tag in block_tags:
        pattern = r"<" + tag + r"[\s\S]*?</" + tag + r">"
        cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE)
    # 移除剩余的所有 XML/HTML 标签（保留标签内文本）
    cleaned = re.sub(r"<[^>]+>", "", cleaned)
    # 压缩空白
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    # 如果清洗后还是太长（>1000字符），只取最后 500 字符（假设真正问题在末尾）
    if len(cleaned) > 1000:
        cleaned = cleaned[-500:].strip()
    return cleaned


def _messages_to_prompt(messages):
    """把 OpenAI Chat Completions 的 messages 数组转为单条提示词

    激进策略：
    1. 完全丢弃所有 system 消息（客户端注入的系统提示词不传给网页）
    2. 对每条 user 消息，用 _extract_user_query 提取真正的用户问题
    3. 丢弃 assistant 消息（避免网页上下文混乱）
    4. 只把提取出的纯用户问题发给网页
    """
    user_queries = []
    for m in messages or []:
        role = m.get("role", "user")
        content = m.get("content", "")
        if isinstance(content, list):
            texts = []
            for c in content:
                if isinstance(c, dict):
                    texts.append(c.get("text", ""))
                else:
                    texts.append(str(c))
            content = " ".join(texts)
        if role == "user":
            query = _extract_user_query(content)
            if query:
                user_queries.append(query)
        # system 和 assistant 消息全丢弃
    if not user_queries:
        return ""
    # 如果只有一个问题，直接返回
    if len(user_queries) == 1:
        return user_queries[0]
    # 多个问题合并
    return "\n\n".join(user_queries)


def _build_full_prompt(instructions, user_text):
    if instructions and instructions != DEFAULT_INSTRUCTIONS:
        return instructions + "\n\n用户问题：" + user_text
    return user_text


# ============================================================
# /v1/chat/completions 端点 (OpenAI 标准 Chat Completions API)
# ============================================================
@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    """OpenAI Chat Completions 兼容端点 - 龙虾/LobeChat 等默认用这个"""
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    messages = body.get("messages", [])
    display_model = body.get("model") or DEFAULT_MODEL
    stream = bool(body.get("stream", False))

    if not messages:
        raise HTTPException(status_code=400, detail="messages is required")

    prompt = _messages_to_prompt(messages)

    try:
        page = get_page()
    except Exception as e:
        raise HTTPException(status_code=503, detail="无法连接 Edge(9333): " + str(e))

    try:
        body_text = page.run_js("return document.body.innerText;") or ""
        if "体验权限" in body_text and "暂无" in body_text:
            raise HTTPException(status_code=403, detail="当前账号无 ultraspeed 体验权限")
    except HTTPException:
        raise
    except Exception:
        pass

    if stream:
        return StreamingResponse(
            _stream_chat_sse(page, prompt, display_model),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    try:
        final_text, status = send_and_collect(page, prompt)
    except Exception as e:
        raise HTTPException(status_code=500, detail="浏览器交互失败: " + str(e))

    if status == "error":
        raise HTTPException(status_code=500, detail="未找到输入框")
    if status == "timeout" and not final_text:
        raise HTTPException(status_code=504, detail="回复超时")

    return JSONResponse(content=_build_chat_json(display_model, final_text))


def _build_chat_json(display_model, content_text):
    """构造 Chat Completions 非流式响应体"""
    return {
        "id": "chatcmpl-" + uuid.uuid4().hex[:24],
        "object": "chat.completion",
        "created": int(time.time()),
        "model": display_model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content_text},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }


def _stream_chat_sse(page, prompt, display_model):
    """Chat Completions 流式 SSE: 逐块 yield content delta"""
    chat_id = "chatcmpl-" + uuid.uuid4().hex[:24]
    created = int(time.time())
    try:
        final_text, status = send_and_collect(page, prompt)
    except Exception as e:
        yield _sse("error", {"message": "浏览器交互失败: " + str(e)})
        return
    if final_text:
        chunk = {
            "id": chat_id,
            "object": "chat.completion.chunk",
            "created": created,
            "model": display_model,
            "choices": [
                {"index": 0, "delta": {"content": final_text}, "finish_reason": None}
            ],
        }
        yield "data: " + json.dumps(chunk, ensure_ascii=False) + "\n\n"
    done_chunk = {
        "id": chat_id,
        "object": "chat.completion.chunk",
        "created": created,
        "model": display_model,
        "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
    }
    yield "data: " + json.dumps(done_chunk, ensure_ascii=False) + "\n\n"
    yield "data: [DONE]\n\n"


# ============================================================
# /v1/responses 端点 (OpenAI Responses API)
# ============================================================
@app.post("/v1/responses")
async def responses(request: Request):
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")
    instructions = body.get("instructions") or DEFAULT_INSTRUCTIONS
    user_text = _normalize_input(body.get("input", ""))
    display_model = body.get("model") or DEFAULT_MODEL
    stream = bool(body.get("stream", False))
    if not user_text:
        raise HTTPException(status_code=400, detail="input is required")
    prompt = _build_full_prompt(instructions, user_text)
    try:
        page = get_page()
    except Exception as e:
        raise HTTPException(status_code=503, detail="无法连接 Edge(9333): " + str(e))
    try:
        body_text = page.run_js("return document.body.innerText;") or ""
        if "体验权限" in body_text and "暂无" in body_text:
            raise HTTPException(status_code=403, detail="当前账号无 ultraspeed 体验权限")
    except HTTPException:
        raise
    except Exception:
        pass
    if stream:
        return StreamingResponse(
            _stream_responses_sse(page, prompt, display_model),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )
    try:
        final_text, status = send_and_collect(page, prompt)
    except Exception as e:
        raise HTTPException(status_code=500, detail="浏览器交互失败: " + str(e))
    if status == "error":
        raise HTTPException(status_code=500, detail="未找到输入框")
    if status == "timeout" and not final_text:
        raise HTTPException(status_code=504, detail="回复超时")
    return JSONResponse(content=_build_responses_json(display_model, final_text, status))


def _build_responses_json(display_model, content_text, status):
    return {
        "id": "resp_" + uuid.uuid4().hex[:24],
        "object": "response",
        "created_at": int(time.time()),
        "status": "completed" if status == "done" else "incomplete",
        "model": display_model,
        "output": [
            {
                "type": "message",
                "id": "msg_" + uuid.uuid4().hex[:24],
                "status": "completed",
                "role": "assistant",
                "content": [
                    {"type": "output_text", "text": content_text, "annotations": []}
                ],
            }
        ],
        "usage": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
    }


def _stream_responses_sse(page, prompt, display_model):
    resp_id = "resp_" + uuid.uuid4().hex[:24]
    msg_id = "msg_" + uuid.uuid4().hex[:24]
    created = int(time.time())
    yield _sse("response.created", {
        "id": resp_id, "object": "response", "created_at": created,
        "status": "in_progress", "model": display_model, "output": [],
    })
    yield _sse("response.output_item.added", {
        "output_index": 0,
        "item": {"type": "message", "id": msg_id, "status": "in_progress",
                 "role": "assistant", "content": []},
    })
    yield _sse("response.content_part.added", {
        "item_id": msg_id, "output_index": 0, "content_index": 0,
        "part": {"type": "output_text", "text": "", "annotations": []},
    })
    try:
        final_text, status = send_and_collect(page, prompt)
    except Exception as e:
        yield _sse("error", {"message": "浏览器交互失败: " + str(e)})
        return
    if final_text:
        yield _sse("response.output_text.delta", {
            "item_id": msg_id, "output_index": 0,
            "content_index": 0, "delta": final_text,
        })
    yield _sse("response.content_part.done", {
        "item_id": msg_id, "output_index": 0, "content_index": 0,
        "part": {"type": "output_text", "text": final_text, "annotations": []},
    })
    yield _sse("response.output_item.done", {
        "output_index": 0,
        "item": {"type": "message", "id": msg_id, "status": "completed",
                 "role": "assistant",
                 "content": [{"type": "output_text", "text": final_text, "annotations": []}]},
    })
    yield _sse("response.completed", {
        "id": resp_id, "object": "response", "created_at": created,
        "status": "completed" if status == "done" else "incomplete",
        "model": display_model,
        "output": [{
            "type": "message", "id": msg_id, "status": "completed",
            "role": "assistant",
            "content": [{"type": "output_text", "text": final_text, "annotations": []}],
        }],
        "usage": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
    })


# ============================================================
# 元信息 / 健康检查
# ============================================================
@app.get("/")
async def root():
    return {
        "service": "MiMo OpenAI-Compatible API (Browser Direct)",
        "version": "2.1.0",
        "backend": "DrissionPage + Edge(9333) + ultraspeed.xiaomimimo.com",
        "endpoints": ["/v1/chat/completions", "/v1/responses"],
        "model": DEFAULT_MODEL,
        "auth": "none (any key accepted)",
        "note": "需要先以 --remote-debugging-port=9333 启动 Edge 并登录 ultraspeed",
    }


@app.get("/health")
async def health():
    try:
        page = get_page()
        url = page.url or ""
        return {"status": "ok", "browser_url": url, "ultraspeed_loaded": "ultraspeed" in url}
    except Exception as e:
        return JSONResponse(status_code=503, content={"status": "error", "message": str(e)})


@app.get("/v1/models")
async def list_models():
    return {
        "object": "list",
        "data": [{
            "id": DEFAULT_MODEL, "object": "model",
            "created": int(time.time()), "owned_by": "xiaomi",
        }],
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
