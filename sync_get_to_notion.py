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
            url += "?" + urllib.parse.urlencode(query)

        body = None
        headers = dict(self.headers)
        if payload is not None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"

        for attempt in range(HTTP_MAX_RETRIES):
            request = urllib.request.Request(url, data=body, method=method, headers=headers)
            try:
                with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
                    content = response.read()
                    if not content:
                        return {}
                    return json.loads(content.decode("utf-8"))
            except urllib.error.HTTPError as exc:
                error_body = exc.read().decode("utf-8", "ignore")
                if exc.code in {408, 409, 429, 500, 502, 503, 504} and attempt < HTTP_MAX_RETRIES - 1:
                    wait_seconds = min(30.0, 1.5 * (attempt + 1))
                    print(
                        f"Transient HTTP {exc.code} from {url}; retrying in {wait_seconds:.1f}s "
                        f"({attempt + 1}/{HTTP_MAX_RETRIES})...",
                        file=sys.stderr,
                    )
                    time.sleep(wait_seconds)
                    continue
                raise RuntimeError(f"{method} {url} failed: {exc.code} {error_body}") from exc
            except (urllib.error.URLError, TimeoutError, socket.timeout) as exc:
                if attempt < HTTP_MAX_RETRIES - 1:
                    wait_seconds = min(30.0, 2.0 * (attempt + 1))
                    print(
                        f"Network timeout/error calling {url}: {exc}; retrying in {wait_seconds:.1f}s "
                        f"({attempt + 1}/{HTTP_MAX_RETRIES})...",
                        file=sys.stderr,
                    )
                    time.sleep(wait_seconds)
                    continue
                raise RuntimeError(f"{method} {url} failed after retries: {exc}") from exc


class GetClient:
    def __init__(self, api_key: str, client_id: str) -> None:
        self.http = HttpClient(
            GET_API_BASE,
            {"Authorization": api_key, "X-Client-ID": client_id},
        )

    def list_all_notes(self) -> list[GetNote]:
        notes: list[GetNote] = []
        cursor = 0
        seen_cursors: set[int | str] = set()
        page = 0
        while True:
            if cursor in seen_cursors:
                raise RuntimeError(f"Get notes pagination cursor repeated: {cursor}")
            seen_cursors.add(cursor)
            page += 1
            data = self.http.request("GET", "/resource/note/list", query={"since_id": cursor})
            payload = data.get("data", {})
            batch = [GetNote.from_api(item) for item in payload.get("notes", [])]
            notes.extend(batch)
            print(
                f"Fetched Get page {page}: {len(batch)} notes, total {len(notes)}, "
                f"has_more={bool(payload.get('has_more'))}, next_cursor={payload.get('next_cursor')}"
            )
            if not payload.get("has_more"):
                break
            cursor = payload.get("next_cursor")
            if not cursor:
                break
            time.sleep(0.2)
        return notes

    def get_note_detail(self, note_id: str) -> GetNote:
        data = self.http.request("GET", "/resource/note/detail", query={"id": note_id})
        return GetNote.from_api(data.get("data", {}).get("note", {}))

    def expand_note(self, note: GetNote, seen: set[str] | None = None) -> GetNote:
        seen = seen or set()
        if note.note_id in seen:
            return note
        seen.add(note.note_id)

        try:
            detail = self.get_note_detail(note.note_id)
        except Exception as exc:
            # Keep the sync moving: fall back to list payload when detail API is unstable.
            print(
                f"Warning: failed to fetch note detail for {note.note_id}; "
                f"falling back to list payload. error={exc}",
                file=sys.stderr,
            )
            detail = note
        if detail.children_ids:
            child_notes: list[GetNote] = []
            for child_id in detail.children_ids:
                try:
                    child_detail = self.get_note_detail(child_id)
                    child_note = self.expand_note(child_detail, seen)
                    child_notes.append(child_note)
                except Exception as exc:
                    print(
                        f"Warning: failed to fetch child note detail for {child_id}; "
                        f"skipping this child. error={exc}",
                        file=sys.stderr,
                    )
            detail.child_notes = child_notes
        return detail


class NotionClient:
    def __init__(self, token: str) -> None:
        self.http = HttpClient(
            NOTION_API_BASE,
            {
                "Authorization": f"Bearer {token}",
                "Notion-Version": NOTION_VERSION,
            },
        )

    def retrieve_database(self, database_id: str) -> dict[str, Any]:
        return self.http.request("GET", f"/databases/{database_id}")

    def update_database(self, database_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self.http.request("PATCH", f"/databases/{database_id}", payload=payload)

    def query_database(self, database_id: str, start_cursor: str | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {"page_size": 100}
        if start_cursor:
            payload["start_cursor"] = start_cursor
        return self.http.request("POST", f"/databases/{database_id}/query", payload=payload)

    def create_page(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.http.request("POST", "/pages", payload=payload)

    def create_child_page(self, parent_page_id: str, title: str, children: list[dict[str, Any]]) -> dict[str, Any]:
        payload = {
            "parent": {"page_id": parent_page_id},
            "properties": {
                "title": [
                    {
                        "type": "text",
                        "text": {"content": truncate_text(title, 1800)},
                    }
                ]
            },
            "children": children[:100],
        }
        page = self.create_page(payload)
        if len(children) > 100:
            for batch in batched(children[100:], 100):
                self.append_children(page["id"], batch)
                time.sleep(0.1)
        return page

    def update_page(self, page_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self.http.request("PATCH", f"/pages/{page_id}", payload=payload)

    def archive_page(self, page_id: str) -> dict[str, Any]:
        return self.http.request("PATCH", f"/pages/{page_id}", payload={"archived": True})

    def list_children(self, block_id: str, start_cursor: str | None = None) -> dict[str, Any]:
        query = {"page_size": 100}
        if start_cursor:
            query["start_cursor"] = start_cursor
        return self.http.request("GET", f"/blocks/{block_id}/children", query=query)

    def append_children(self, block_id: str, children: list[dict[str, Any]]) -> dict[str, Any]:
        return self.http.request("PATCH", f"/blocks/{block_id}/children", payload={"children": children})

    def archive_block(self, block_id: str) -> dict[str, Any]:
        return self.http.request("PATCH", f"/blocks/{block_id}", payload={"archived": True})

    def ensure_schema(self, database_id: str) -> tuple[str, dict[str, Any]]:
        database = self.retrieve_database(database_id)
        properties = database.get("properties", {})
        title_property_name = next(
            (name for name, prop in properties.items() if prop.get("type") == "title"),
            None,
        )
        if not title_property_name:
            raise RuntimeError("The Notion database does not have a title property.")

        missing = {name: schema for name, schema in RECOMMENDED_FIELDS.items() if name not in properties}
        if missing:
            self.update_database(database_id, {"properties": missing})
            database = self.retrieve_database(database_id)
        return title_property_name, database

    def list_existing_pages_by_get_id(self, database_id: str) -> dict[str, list[dict[str, Any]]]:
        existing: dict[str, list[dict[str, Any]]] = {}
        cursor = None
        seen_cursors: set[str | None] = set()
        page = 0
        while True:
            if cursor in seen_cursors:
                raise RuntimeError(f"Notion pagination cursor repeated: {cursor}")
            seen_cursors.add(cursor)
            page += 1
            response = self.query_database(database_id, cursor)
            results = response.get("results", [])
            print(
                f"Fetched Notion page {page}: {len(results)} rows, "
                f"has_more={bool(response.get('has_more'))}, next_cursor={response.get('next_cursor')}"
            )
            for item in results:
                props = item.get("properties", {})
                get_id = first_rich_text_plain_text(props.get("Get ID", {})).strip()
                if get_id:
                    existing.setdefault(get_id, []).append(item)
            if not response.get("has_more"):
                break
            cursor = response.get("next_cursor")
        return existing

    def archive_existing_pages(self, existing_pages: list[dict[str, Any]]) -> int:
        archived = 0
        for item in existing_pages:
            self.archive_page(item["id"])
            archived += 1
            time.sleep(0.05)
        return archived


def note_sort_key(note: GetNote) -> tuple[str, str]:
    return (note.updated_at or note.created_at or "", note.note_id)


def note_signature(note: GetNote) -> str:
    payload = {
        "note_id": note.note_id,
        "title": note.title,
        "content": note.content,
        "ref_content": note.ref_content,
        "note_type": note.note_type,
        "source": note.source,
        "tags": note.tags,
        "topics": note.topics,
        "is_child_note": note.is_child_note,
        "children_count": note.children_count,
        "children_ids": note.children_ids,
        "parent_id": note.parent_id,
        "links": note.links,
        "original_text": note.original_text,
        "created_at": note.created_at,
        "updated_at": note.updated_at,
        "child_signatures": [note_signature(child) for child in note.child_notes],
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:16]


def date_property_value(prop: dict[str, Any]) -> str | None:
    date_value = prop.get("date")
    if not date_value:
        return None
    return date_value.get("start")


def normalize_iso_datetime(value: str | None) -> str | None:
    if not value:
        return None
    normalized = value.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(normalized)
    except ValueError:
        return value
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=SHANGHAI_TZ)
    return dt.astimezone(SHANGHAI_TZ).replace(microsecond=0).isoformat()


def multi_select_names(prop: dict[str, Any]) -> set[str]:
    return {item.get("name", "") for item in prop.get("multi_select", []) if item.get("name")}


def page_matches_note(page: dict[str, Any], title_property_name: str, note: GetNote) -> bool:
    props = page.get("properties", {})
    note_link = note.links[0] if note.links else None
    existing_signature = first_rich_text_plain_text(props.get("内容指纹", {})).strip()
    current_signature = note_signature(note)
    existing_updated_at = normalize_iso_datetime(date_property_value(props.get("更新时间", {})))
    note_updated_at = normalize_iso_datetime(note.updated_at)

    if first_rich_text_plain_text(props.get("Get ID", {})).strip() != note.note_id:
        return False

    if existing_signature:
        return existing_signature == current_signature

    # Prefer the source update timestamp for incremental sync decisions.
    if note_updated_at and existing_updated_at:
        return (
            existing_updated_at == note_updated_at
            and (props.get("笔记链接", {}) or {}).get("url") == note_link
            and int((props.get("子笔记数", {}) or {}).get("number") or 0) == note.children_count
        )

    checks = [
        first_title_plain_text(props.get(title_property_name, {})).strip() == note.title,
        (props.get("笔记链接", {}) or {}).get("url") == note_link,
        first_rich_text_plain_text(props.get("笔记类型", {})).strip() == note.note_type,
        first_rich_text_plain_text(props.get("来源", {})).strip() == note.source,
        multi_select_names(props.get("标签", {})) == set(note.tags),
        multi_select_names(props.get("主题", {})) == set(note.topics),
        normalize_iso_datetime(date_property_value(props.get("创建时间", {}))) == normalize_iso_datetime(note.created_at),
        existing_updated_at == note_updated_at,
        (props.get("是否子笔记", {}) or {}).get("checkbox") == note.is_child_note,
        int((props.get("子笔记数", {}) or {}).get("number") or 0) == note.children_count,
    ]
    return all(checks)


def choose_notes_for_sync(notes: list[GetNote]) -> list[GetNote]:
    deduped: dict[str, GetNote] = {}
    for note in notes:
        current = deduped.get(note.note_id)
        if current is None or note_sort_key(note) > note_sort_key(current):
            deduped[note.note_id] = note

    ordered = sorted(deduped.values(), key=note_sort_key, reverse=True)

    sync_note_id = os.getenv("SYNC_NOTE_ID", "").strip()
    sync_latest_only = os.getenv("SYNC_LATEST_ONLY", "").strip().lower() in {"1", "true", "yes", "y"}
    sync_limit_raw = os.getenv("SYNC_LIMIT", "").strip()
    sync_limit = int(sync_limit_raw) if sync_limit_raw else 0

    if sync_note_id:
        return [note for note in ordered if note.note_id == sync_note_id][:1]
    if sync_latest_only:
        return ordered[:1]
    if sync_limit > 0:
        return ordered[:sync_limit]
    return ordered

def build_properties(title_property_name: str, note: GetNote) -> dict[str, Any]:
    return {
        title_property_name: {"title": rich_text_array(truncate_text(note.title, 1800))},
        "Get ID": {"rich_text": rich_text_array(note.note_id)},
        "内容指纹": {"rich_text": rich_text_array(note_signature(note))},
        "元信息": {"rich_text": rich_text_array(note.metadata_text())},
        "笔记链接": {"url": note.links[0] if note.links else None},
        "笔记类型": {"rich_text": rich_text_array(note.note_type)},
        "来源": {"rich_text": rich_text_array(note.source)},
        "标签": {"multi_select": [{"name": truncate_text(name, 100)} for name in note.tags]},
        "主题": {"multi_select": [{"name": truncate_text(name, 100)} for name in note.topics]},
        "创建时间": {"date": {"start": note.created_at}} if note.created_at else {"date": None},
        "更新时间": {"date": {"start": note.updated_at}} if note.updated_at else {"date": None},
        "是否子笔记": {"checkbox": note.is_child_note},
        "子笔记数": {"number": note.children_count},
        "同步时间": {"date": {"start": datetime.now(SHANGHAI_TZ).isoformat()}},
    }


def create_main_note_page(
    notion: NotionClient,
    database_id: str,
    title_property_name: str,
    note: GetNote,
) -> dict[str, Any]:
    properties = build_properties(title_property_name, note)
    blocks = build_page_blocks(note)
    page = notion.create_page(
        {
            "parent": {"database_id": database_id},
            "properties": properties,
        }
    )

    original_blocks = build_original_page_blocks(note)
    if original_blocks:
        notion.create_child_page(page["id"], "原文", original_blocks)

    if blocks:
        for batch in batched(blocks, 100):
            notion.append_children(page["id"], batch)
            time.sleep(0.1)

    return page


def sync_notes() -> None:
    get_api_key = require_env("GETNOTE_API_KEY")
    get_client_id = require_env("GETNOTE_CLIENT_ID")
    notion_token = require_env("NOTION_TOKEN")
    database_id = parse_notion_id(require_env("NOTION_DATABASE_ID"))

    get_client = GetClient(get_api_key, get_client_id)
    notion = NotionClient(notion_token)

    print("Checking Notion database schema...")
    title_property_name, database = notion.ensure_schema(database_id)
    print(f"Database ready: {''.join(part.get('plain_text', '') for part in database.get('title', []))}")

    print("Fetching notes from Get...")
    notes = get_client.list_all_notes()
    print(f"Fetched {len(notes)} notes from Get.")
    notes = choose_notes_for_sync(notes)
    print(f"Selected {len(notes)} notes for this sync run.")

    print("Loading existing Notion pages...")
    existing_pages = notion.list_existing_pages_by_get_id(database_id)
    print(f"Found {sum(len(items) for items in existing_pages.values())} active synced pages in Notion.")

    created = 0
    updated = 0
    deduped_pages = 0
    skipped = 0
    for index, note in enumerate(notes, start=1):
        note = get_client.expand_note(note)
        existing = existing_pages.get(note.note_id, [])

        matching_page = next(
            (page for page in existing if page_matches_note(page, title_property_name, note)),
            None,
        )

        if matching_page:
            duplicates = [page for page in existing if page["id"] != matching_page["id"]]
            if duplicates:
                deduped_pages += notion.archive_existing_pages(duplicates)
                time.sleep(0.1)
            skipped += 1
            action = "skipped"
        elif existing:
            deduped_pages += notion.archive_existing_pages(existing)
            time.sleep(0.2)
            create_main_note_page(notion, database_id, title_property_name, note)
            updated += 1
            action = "recreated"
        else:
            create_main_note_page(notion, database_id, title_property_name, note)
            created += 1
            action = "created"

        print(f"[{index}/{len(notes)}] {action}: {note.title}")
        time.sleep(0.15)

    print("")
    print("Sync complete.")
    print(f"Created: {created}")
    print(f"Updated: {updated}")
    print(f"Skipped: {skipped}")
    print(f"Archived duplicates: {deduped_pages}")
    print("Recommended Notion fields:")
    for field_name in RECOMMENDED_FIELDS:
        print(f"- {field_name}")


if __name__ == "__main__":
    try:
        sync_notes()
    except KeyboardInterrupt:
        sys.exit("Interrupted.")
    except Exception as exc:
        sys.exit(f"Error: {exc}")
