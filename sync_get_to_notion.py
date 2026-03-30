#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import hashlib
import os
import re
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Any


SHANGHAI_TZ = timezone(timedelta(hours=8))
NOTION_VERSION = "2022-06-28"
NOTION_API_BASE = "https://api.notion.com/v1"
GET_API_BASE = "https://openapi.biji.com/open/api/v1"
HTTP_TIMEOUT_SECONDS = 60
HTTP_MAX_RETRIES = 8


RECOMMENDED_FIELDS = {
    "Get ID": {"rich_text": {}},
    "内容指纹": {"rich_text": {}},
    "元信息": {"rich_text": {}},
    "笔记链接": {"url": {}},
    "笔记类型": {"rich_text": {}},
    "来源": {"rich_text": {}},
    "标签": {"multi_select": {}},
    "主题": {"multi_select": {}},
    "创建时间": {"date": {}},
    "更新时间": {"date": {}},
    "是否子笔记": {"checkbox": {}},
    "子笔记数": {"number": {"format": "number"}},
    "同步时间": {"date": {}},
}


def require_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise SystemExit(f"Missing required environment variable: {name}")
    return value


def parse_notion_id(value: str) -> str:
    value = value.strip()
    uuid_match = re.search(r"([0-9a-fA-F]{32})", value)
    if uuid_match:
        raw = uuid_match.group(1).lower()
        return f"{raw[:8]}-{raw[8:12]}-{raw[12:16]}-{raw[16:20]}-{raw[20:]}"
    hyphenated_match = re.search(
        r"([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})",
        value,
    )
    if hyphenated_match:
        return hyphenated_match.group(1).lower()
    raise SystemExit("NOTION_DATABASE_ID must be a Notion database ID or URL.")


def truncate_text(value: str, limit: int = 2000) -> str:
    if len(value) <= limit:
        return value
    return value[: limit - 1] + "…"


def rich_text_array(text: str) -> list[dict[str, Any]]:
    if not text:
        return []
    chunks = [text[i : i + 1800] for i in range(0, len(text), 1800)]
    return [{"type": "text", "text": {"content": chunk}} for chunk in chunks]


def first_rich_text_plain_text(prop: dict[str, Any]) -> str:
    items = prop.get("rich_text", [])
    return "".join(item.get("plain_text", "") for item in items)


def first_title_plain_text(prop: dict[str, Any]) -> str:
    items = prop.get("title", [])
    return "".join(item.get("plain_text", "") for item in items)


def parse_get_datetime(value: str) -> str | None:
    if not value:
        return None
    dt = datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
    return dt.replace(tzinfo=SHANGHAI_TZ).isoformat()


def strip_markdown_emphasis(text: str) -> str:
    text = re.sub(r"\*\*(.*?)\*\*", r"\1", text)
    text = re.sub(r"\*(.*?)\*", r"\1", text)
    text = re.sub(r"`(.*?)`", r"\1", text)
    return text.strip()


def strip_leading_decorations(text: str) -> str:
    text = re.sub(r"^[\s\W_]+", "", text, flags=re.UNICODE)
    return text.strip()


def is_markdown_table_line(line: str) -> bool:
    stripped = line.strip()
    return stripped.startswith("|") and stripped.endswith("|") and stripped.count("|") >= 2


def is_markdown_table_separator(line: str) -> bool:
    stripped = line.strip().replace(" ", "")
    return bool(stripped) and all(char in "|:-" for char in stripped) and "-" in stripped


def parse_markdown_table(lines: list[str]) -> list[str]:
    if len(lines) < 2 or not is_markdown_table_separator(lines[1]):
        return [strip_markdown_emphasis(line) for line in lines]

    def split_row(line: str) -> list[str]:
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        return [strip_markdown_emphasis(cell) for cell in cells]

    headers = split_row(lines[0])
    output = ["## 表格"]
    for row in lines[2:]:
        values = split_row(row)
        pairs = []
        for index, value in enumerate(values):
            header = headers[index] if index < len(headers) else f"列{index + 1}"
            pairs.append(f"{header}: {value}")
        output.append(f"- {' | '.join(pairs)}")
    return output


def extract_note_links(raw: dict[str, Any]) -> list[str]:
    links: list[str] = []

    web_page = raw.get("web_page") or {}
    web_url = (web_page.get("url") or "").strip()
    if web_url:
        links.append(web_url)

    for attachment in raw.get("attachments", []):
        url = (attachment.get("url") or "").strip()
        if url and url not in links:
            links.append(url)

    return links


def clean_markdown(markdown: str) -> str:
    markdown = markdown.replace("\r\n", "\n").replace("\r", "\n").replace("\u00a0", " ")
    lines: list[str] = []
    raw_lines = markdown.splitlines()
    index = 0

    while index < len(raw_lines):
        raw_line = raw_lines[index]
        line = raw_line.rstrip()
        if not line.strip():
            lines.append("")
            index += 1
            continue

        if is_markdown_table_line(line):
            table_lines = [line]
            index += 1
            while index < len(raw_lines) and is_markdown_table_line(raw_lines[index].rstrip()):
                table_lines.append(raw_lines[index].rstrip())
                index += 1
            lines.extend(parse_markdown_table(table_lines))
            lines.append("")
            continue

        heading_match = re.match(r"^(#{1,6})\s+(.*)$", line)
        if heading_match:
            level = heading_match.group(1)
            title = strip_markdown_emphasis(heading_match.group(2))
            title = strip_leading_decorations(title)
            lines.append(f"{level} {title}".rstrip())
            index += 1
            continue

        bullet_match = re.match(r"^(\s*[-*]\s+)(.*)$", line)
        if bullet_match:
            item_text = strip_markdown_emphasis(bullet_match.group(2))
            lines.append(f"{bullet_match.group(1)}{item_text}".rstrip())
            index += 1
            continue

        numbered_match = re.match(r"^(\s*\d+\.\s+)(.*)$", line)
        if numbered_match:
            item_text = strip_markdown_emphasis(numbered_match.group(2))
            lines.append(f"{numbered_match.group(1)}{item_text}".rstrip())
            index += 1
            continue

        lines.append(strip_markdown_emphasis(line))
        index += 1

    cleaned = "\n".join(lines)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def chunk_rich_text(text: str) -> list[dict[str, Any]]:
    return rich_text_array(text) or [{"type": "text", "text": {"content": ""}}]


def paragraph_block(text: str) -> dict[str, Any]:
    return {"object": "block", "type": "paragraph", "paragraph": {"rich_text": chunk_rich_text(text)}}


def heading_block(level: int, text: str) -> dict[str, Any]:
    block_type = f"heading_{level}"
    return {
        "object": "block",
        "type": block_type,
        block_type: {"rich_text": chunk_rich_text(text)},
    }


def toggle_block(text: str, children: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "object": "block",
        "type": "toggle",
        "toggle": {"rich_text": chunk_rich_text(text), "children": children[:100]},
    }


def markdown_to_blocks(markdown: str) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    buffer: list[str] = []
    code_lines: list[str] = []
    in_code = False

    def flush_paragraph() -> None:
        nonlocal buffer
        if buffer:
            text = "\n".join(buffer).strip()
            if text:
                blocks.append(paragraph_block(text))
        buffer = []

    for raw_line in markdown.splitlines():
        line = raw_line.rstrip()

        if line.startswith("```"):
            flush_paragraph()
            if in_code:
                code_text = "\n".join(code_lines).strip("\n")
                if code_text:
                    blocks.append(
                        {
                            "object": "block",
                            "type": "code",
                            "code": {
                                "language": "plain text",
                                "rich_text": chunk_rich_text(code_text),
                            },
                        }
                    )
                code_lines = []
                in_code = False
            else:
                in_code = True
            continue

        if in_code:
            code_lines.append(raw_line)
            continue

        if not line.strip():
            flush_paragraph()
            continue

        heading_match = re.match(r"^(#{1,6})\s+(.*)$", line)
        if heading_match:
            flush_paragraph()
            level = min(len(heading_match.group(1)), 3)
            text = strip_leading_decorations(strip_markdown_emphasis(heading_match.group(2)))
            block_type = f"heading_{level}"
            blocks.append(
                {
                    "object": "block",
                    "type": block_type,
                    block_type: {"rich_text": chunk_rich_text(text)},
                }
            )
            continue

        bullet_match = re.match(r"^\s*[-*]\s+(.*)$", line)
        if bullet_match:
            flush_paragraph()
            blocks.append(
                {
                    "object": "block",
                    "type": "bulleted_list_item",
                    "bulleted_list_item": {
                        "rich_text": chunk_rich_text(strip_markdown_emphasis(bullet_match.group(1)))
                    },
                }
            )
            continue

        numbered_match = re.match(r"^\s*\d+\.\s+(.*)$", line)
        if numbered_match:
            flush_paragraph()
            blocks.append(
                {
                    "object": "block",
                    "type": "numbered_list_item",
                    "numbered_list_item": {
                        "rich_text": chunk_rich_text(strip_markdown_emphasis(numbered_match.group(1)))
                    },
                }
            )
            continue

        buffer.append(line)

    flush_paragraph()
    if in_code and code_lines:
        blocks.append(
            {
                "object": "block",
                "type": "code",
                "code": {"language": "plain text", "rich_text": chunk_rich_text("\n".join(code_lines))},
            }
        )

    return blocks[:1000]


def child_note_title(note: GetNote, index: int) -> str:
    return note.title or f"追加笔记 {index}"


def build_child_toggle(note: GetNote, index: int) -> dict[str, Any]:
    children: list[dict[str, Any]] = []

    note_body = clean_markdown(note.content)
    if note_body:
        children.append(heading_block(3, "笔记"))
        children.extend(markdown_to_blocks(note_body))

    ref_body = clean_markdown(note.ref_content)
    if ref_body:
        children.append(heading_block(3, "引用内容"))
        children.extend(markdown_to_blocks(ref_body))

    for child_index, child in enumerate(note.child_notes, start=1):
        children.append(build_child_toggle(child, child_index))

    return toggle_block(child_note_title(note, index), children[:100])


def build_page_blocks(note: GetNote) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = [heading_block(1, note.title)]

    if note.child_notes:
        blocks.append(heading_block(2, "追加笔记"))
        for index, child in enumerate(note.child_notes, start=1):
            blocks.append(build_child_toggle(child, index))

    note_body = clean_markdown(note.content)
    if note_body:
        blocks.append(heading_block(2, "笔记"))
        blocks.extend(markdown_to_blocks(note_body))

    ref_body = clean_markdown(note.ref_content)
    if ref_body:
        blocks.append(heading_block(2, "引用内容"))
        blocks.extend(markdown_to_blocks(ref_body))

    return blocks[:1000]


def build_original_page_blocks(note: GetNote) -> list[dict[str, Any]]:
    if not note.original_text:
        return []
    blocks: list[dict[str, Any]] = [heading_block(1, "原文")]
    blocks.extend(markdown_to_blocks(clean_markdown(note.original_text)))
    return blocks[:1000]


def batched(items: list[Any], size: int) -> list[list[Any]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


@dataclass
class GetNote:
    note_id: str
    title: str
    content: str
    ref_content: str
    note_type: str
    source: str
    tags: list[str]
    topics: list[str]
    is_child_note: bool
    children_count: int
    children_ids: list[str]
    parent_id: str | None
    links: list[str]
    original_text: str
    child_notes: list["GetNote"]
    created_at: str | None
    updated_at: str | None

    @classmethod
    def from_api(cls, raw: dict[str, Any]) -> "GetNote":
        title = (raw.get("title") or "").strip() or f"未命名笔记 {raw['note_id']}"
        return cls(
            note_id=str(raw["note_id"]),
            title=title,
            content=(raw.get("content") or "").strip(),
            ref_content=(raw.get("ref_content") or "").strip(),
            note_type=(raw.get("note_type") or "").strip(),
            source=(raw.get("source") or "").strip(),
            tags=[item.get("name", "").strip() for item in raw.get("tags", []) if item.get("name")],
            topics=[item.get("name", "").strip() for item in raw.get("topics", []) if item.get("name")],
            is_child_note=bool(raw.get("is_child_note")),
            children_count=int(raw.get("children_count") or 0),
            children_ids=[str(item) for item in raw.get("children_ids", []) if item],
            parent_id=str(raw.get("parent_id")) if raw.get("parent_id") else None,
            links=extract_note_links(raw),
            original_text=((raw.get("web_page") or {}).get("content") or "").strip(),
            child_notes=[],
            created_at=parse_get_datetime(raw.get("created_at") or ""),
            updated_at=parse_get_datetime(raw.get("updated_at") or ""),
        )

    def metadata_text(self) -> str:
        lines = [
            f"Get ID: {self.note_id}",
            f"笔记类型: {self.note_type or '未提供'}",
            f"来源: {self.source or '未提供'}",
            f"是否子笔记: {'是' if self.is_child_note else '否'}",
            f"子笔记数: {self.children_count}",
        ]
        if self.tags:
            lines.append(f"标签: {', '.join(self.tags)}")
        if self.topics:
            lines.append(f"主题: {', '.join(self.topics)}")
        if self.created_at:
            lines.append(f"创建时间: {self.created_at}")
        if self.updated_at:
            lines.append(f"更新时间: {self.updated_at}")
        if self.parent_id:
            lines.append(f"父笔记 ID: {self.parent_id}")
        if self.links:
            lines.append(f"笔记链接: {' , '.join(self.links)}")
        return "\n".join(lines).strip()


class HttpClient:
    def __init__(self, base_url: str, headers: dict[str, str]) -> None:
        self.base_url = base_url.rstrip("/")
        self.headers = headers
    def request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        query: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        if query:
            params = {"key": str(value) for key, value in query.items() if value is not None}
            url = f"{url}?{urllib.parse.urlencode(params)}"

        body = None
        headers = {self.headers}
        if payload is not None:
            body = json.dums(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"

        retryable_http_errors = {408, 409, 429, 500, 502, 503, 504}
        last_error: Exception | None = None 
        for attempt in range(1, HTTP_MAX_RETRIES + 1):
            try:
                request = urllib.request.Request(url, data=body, headers=headers, method=method)
                with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
                    raw = response.read().decode("utf-8")
                    return json.loads(raw) if raw else {}
            except urllib.error.HTTPError as err:
                raw_error = err.read().decode("utf-8", errors="replace")
                if err.code in retryable_http_errors and attempt < HTTP_MAX_RETRIES:
                    wait_seconds = min(2 * attempt, 16)
                    print(
                        f"HTTP ({err.code}) for {method} {url} (attempt {attempt}/{HTTP_MAX_RETRIES}). "
                        f"Retrying in {wait_seconds}s