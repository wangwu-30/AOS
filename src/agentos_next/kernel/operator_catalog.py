from __future__ import annotations

from typing import Any


def _catalog_entries() -> list[dict[str, Any]]:
    return [
        {
            "operator_ref": "builtin://fs.list",
            "summary": "List files in the local workspace.",
            "match_terms": ["list", "file", "目录", "结构", "workspace", "project"],
            "required_capabilities": ["fs_read"],
            "policy_disposition": "allow",
        },
        {
            "operator_ref": "builtin://fs.read",
            "summary": "Read a local file from the workspace.",
            "match_terms": ["read", "file", "内容", "代码", "workspace", "project"],
            "required_capabilities": ["fs_read"],
            "policy_disposition": "allow",
        },
        {
            "operator_ref": "builtin://shell.exec",
            "summary": "Run a local shell command in the workspace.",
            "match_terms": ["shell", "command", "find", "grep", "scan", "inspect"],
            "required_capabilities": ["shell_exec"],
            "policy_disposition": "allow",
        },
        {
            "operator_ref": "builtin://memory.search",
            "summary": "Search layered memory and evidence records.",
            "match_terms": ["memory", "remember", "检索", "历史", "上下文"],
            "required_capabilities": ["memory_search"],
            "policy_disposition": "allow",
        },
        {
            "operator_ref": "builtin://memory.write",
            "summary": "Persist durable memory notes or facts.",
            "match_terms": ["remember", "save", "记住", "保存"],
            "required_capabilities": ["memory_write"],
            "policy_disposition": "ask",
        },
        {
            "operator_ref": "builtin://memory.compact",
            "summary": "Merge conflicting memory records into a structured winner record.",
            "match_terms": ["memory", "compact", "merge", "summarize", "合并", "压缩"],
            "required_capabilities": ["memory_compact"],
            "policy_disposition": "ask",
        },
        {
            "operator_ref": "builtin://memory.delete",
            "summary": "Logically forget or tombstone memory records by record id.",
            "match_terms": ["memory", "forget", "delete", "遗忘", "删除"],
            "required_capabilities": ["memory_delete"],
            "policy_disposition": "ask",
        },
        {
            "operator_ref": "builtin://time.now",
            "summary": "Read the runtime local date, time, timezone, and relative-date anchor.",
            "match_terms": ["time", "date", "today", "tomorrow", "yesterday", "时间", "日期", "今天", "明天", "昨天"],
            "required_capabilities": ["time_read"],
            "policy_disposition": "allow",
        },
        {
            "operator_ref": "builtin://web.search",
            "summary": "Search the web for live or external facts.",
            "match_terms": ["web", "latest", "news", "搜索", "最新", "外部"],
            "required_capabilities": ["web_search"],
            "policy_disposition": "allow",
        },
        {
            "operator_ref": "builtin://web.browse",
            "summary": "Open a web page and extract readable source text.",
            "match_terms": ["browse", "open", "source", "网页", "打开", "来源", "核实"],
            "required_capabilities": ["web_browse"],
            "policy_disposition": "allow",
        },
        {
            "operator_ref": "builtin://research.run",
            "summary": "Run explicit multi-source research and produce a cited report.",
            "match_terms": ["research", "report", "citation", "sources", "调研", "报告", "引用", "多来源", "对比"],
            "required_capabilities": ["research_run"],
            "policy_disposition": "allow",
        },
        {
            "operator_ref": "builtin://channel.send_message",
            "summary": "Create an explicit user-visible message delivery task.",
            "match_terms": ["reply", "respond", "message", "回答", "输出", "沟通", "汇报"],
            "required_capabilities": ["channel_send"],
            "policy_disposition": "allow",
        },
        {
            "operator_ref": "skill://communication.render",
            "summary": "Render a user-visible response from verified state and evidence.",
            "match_terms": ["reply", "respond", "render", "回答", "输出", "沟通"],
            "required_capabilities": [],
            "policy_disposition": "allow",
        },
    ]


def search_operator_catalog(*, query_text: str, available_capabilities: list[str], limit: int = 6) -> list[dict[str, Any]]:
    caps = {str(x).strip() for x in available_capabilities if str(x).strip()}
    text = str(query_text or "").lower()
    ranked: list[tuple[int, dict[str, Any]]] = []
    for entry in _catalog_entries():
        required = [str(x).strip() for x in entry["required_capabilities"] if str(x).strip()]
        if required and not set(required).issubset(caps):
            continue
        score = 0
        for term in entry["match_terms"]:
            if str(term).lower() in text:
                score += 1
        if score <= 0 and text:
            continue
        ranked.append((score, entry))
    ranked.sort(key=lambda item: (-item[0], item[1]["operator_ref"]))
    out: list[dict[str, Any]] = []
    for _, entry in ranked[:limit]:
        out.append(
            {
                "operator_ref": entry["operator_ref"],
                "summary": entry["summary"],
                "policy_disposition": entry["policy_disposition"],
                "required_capabilities": list(entry["required_capabilities"]),
            }
        )
    return out
