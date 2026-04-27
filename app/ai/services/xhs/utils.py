"""Shared helpers for XHS services."""
from __future__ import annotations

import re
from typing import List, Tuple, Dict, Any

try:
    import orjson
    def _json_loads(s):
        return orjson.loads(s)
except ImportError:
    import json
    def _json_loads(s):
        return json.loads(s)

from app.ai.services.xhs.schemas import XHSPage

_PAGE_SPLIT_REGEX = re.compile(r"<page>", re.IGNORECASE)
_PAGE_TYPE_REGEX = re.compile(r"^\[(.+?)\]\s*$")

_PAGE_TYPE_MAP = {
    "封面": "cover",
    "内容": "content",
    "总结": "summary",
}
_PAGE_TYPE_CN = {
    "cover": "封面",
    "content": "内容",
    "summary": "总结",
}
_TITLE_LINE_PATTERNS = [
    re.compile(r"^\s*[【\[]\s*(?:标题|主标题|封面标题|页面标题)\s*[】\]]\s*[:：]?\s*(.+?)\s*$"),
    re.compile(r"^\s*(?:标题|主标题|封面标题|页面标题)\s*[:：]\s*(.+?)\s*$"),
    re.compile(r"^\s*#{1,3}\s+(.+?)\s*$"),
]
_LABEL_PREFIX_REGEX = re.compile(
    r"^\s*[【\[]\s*(?:标题|主标题|封面标题|页面标题|副标题|内容|总结)\s*[】\]]\s*[:：]?\s*"
)


def normalize_page_type(value: str) -> str:
    if not value:
        return "content"
    value = value.strip().lower()
    if value in {"cover", "content", "summary"}:
        return value
    return "content"


def page_type_to_cn(value: str) -> str:
    return _PAGE_TYPE_CN.get(normalize_page_type(value), "内容")


def _extract_page_type(text: str) -> Tuple[str, str]:
    lines = [line.rstrip() for line in text.splitlines() if line.strip()]
    if not lines:
        return "content", ""
    first = lines[0].strip()
    match = _PAGE_TYPE_REGEX.match(first)
    if match:
        mapped = _PAGE_TYPE_MAP.get(match.group(1).strip(), "content")
        remaining = "\n".join(lines[1:]).strip()
        return mapped, remaining
    return "content", "\n".join(lines).strip()


def _clean_page_title(value: str, max_len: int = 80) -> str:
    title = _LABEL_PREFIX_REGEX.sub("", value or "").strip()
    title = title.strip(" \t\r\n\"'“”‘’`#*-：:")
    title = re.sub(r"\s+", " ", title)
    if len(title) > max_len:
        return title[:max_len].rstrip()
    return title


def extract_page_title_and_content(text: str) -> tuple[str | None, str]:
    """Extract a page title from common AI outline formats.

    The model often puts titles in the first content line, for example
    ``【标题】石家庄周边游``. Previously that line stayed only in ``content``,
    leaving ``XHSPage.title`` empty and the frontend displayed "未命名画面".
    """
    if not text:
        return None, ""

    lines = text.splitlines()
    non_empty = [(idx, line.strip()) for idx, line in enumerate(lines) if line.strip()]
    if not non_empty:
        return None, text.strip()

    first_idx, first_line = non_empty[0]
    for pattern in _TITLE_LINE_PATTERNS:
        match = pattern.match(first_line)
        if match:
            title = _clean_page_title(match.group(1))
            remaining = [
                line
                for idx, line in enumerate(lines)
                if idx != first_idx
            ]
            return title or None, "\n".join(remaining).strip()

    fallback_title = _clean_page_title(first_line)
    return fallback_title or None, text.strip()


def derive_page_title(content: str, fallback: str = "", max_len: int = 80) -> str:
    title, _content = extract_page_title_and_content(content or "")
    if title:
        return title[:max_len].rstrip()
    return _clean_page_title(fallback, max_len=max_len)


def get_page_num(page: Any, fallback: int) -> int:
    """Return a stable 1-based page number from dict/model page payloads."""
    if fallback <= 0:
        fallback = 1

    if hasattr(page, "model_dump"):
        page = page.model_dump()

    if not isinstance(page, dict):
        return fallback

    for key in ("page_num", "page"):
        raw = page.get(key)
        try:
            value = int(raw)
        except (TypeError, ValueError):
            continue
        if value > 0:
            return value

    raw_index = page.get("index")
    try:
        index = int(raw_index)
    except (TypeError, ValueError):
        return fallback
    return index + 1 if index >= 0 else fallback


def normalize_page_order(pages: list[Any] | None) -> list[dict[str, Any]]:
    """Sort page payloads by stable page number and re-number them sequentially.

    History/detail views must not depend on JSON array insertion order because
    image generation events can complete concurrently. ``page_num`` is the
    canonical user-visible order.
    """
    if not pages:
        return []

    indexed: list[tuple[int, int, dict[str, Any]]] = []
    for index, page in enumerate(pages):
        page_dict = page.model_dump() if hasattr(page, "model_dump") else dict(page)
        page_num = get_page_num(page_dict, index + 1)
        page_dict["page_num"] = page_num
        indexed.append((page_num, index, page_dict))

    ordered = [
        page
        for _page_num, _index, page in sorted(
            indexed, key=lambda item: (item[0], item[1])
        )
    ]
    for index, page in enumerate(ordered, start=1):
        page["page_num"] = index
    return ordered


def parse_outline(outline_text: str) -> List[XHSPage]:
    if not outline_text:
        return []

    if "<page>" in outline_text.lower():
        raw_pages = _PAGE_SPLIT_REGEX.split(outline_text)
    else:
        raw_pages = outline_text.split("---")

    pages: List[XHSPage] = []
    for raw in raw_pages:
        content = raw.strip()
        if not content:
            continue
        page_type, cleaned = _extract_page_type(content)
        title, cleaned_without_title = extract_page_title_and_content(cleaned or content)
        pages.append(
            XHSPage(
                index=len(pages),
                content=cleaned_without_title or cleaned or content,
                page_type=page_type,
                title=title,
            )
        )

    if pages and all(p.page_type == "content" for p in pages):
        pages[0].page_type = "cover"

    return pages


def parse_json_response(text: str) -> Dict[str, Any]:
    """从 AI 响应中解析 JSON（增强版，多级 fallback）"""
    if not text:
        raise ValueError("empty response")

    # 预处理：去除首尾空白
    text = text.strip()

    try:
        return _json_loads(text)
    except (ValueError, TypeError):
        pass

    match = re.search(r"```(?:json|JSON)?\s*\n([\s\S]+?)\n\s*```", text)
    if match:
        try:
            return _json_loads(match.group(1).strip())
        except (ValueError, TypeError):
            pass

    blocks = re.findall(r"```(?:json|JSON)?\s*\n?([\s\S]*?)\n?\s*```", text)
    for block in blocks:
        try:
            return _json_loads(block.strip())
        except (ValueError, TypeError):
            continue

    start_idx = text.find("{")
    end_idx = text.rfind("}")
    if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
        try:
            return _json_loads(text[start_idx : end_idx + 1])
        except (ValueError, TypeError):
            pass

    start_idx = text.find("[")
    end_idx = text.rfind("]")
    if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
        try:
            result = _json_loads(text[start_idx : end_idx + 1])
            return {"prompts": result} if isinstance(result, list) else result
        except (ValueError, TypeError):
            pass

    raise ValueError(f"invalid json response (len={len(text)}, preview={text[:200]})")

