import { requestUrl } from "obsidian";

import type {
  AttachmentRef,
  GetDetailResponse,
  GetListResponse,
  GetNote,
  GetNotePayload,
} from "./types";

const GET_API_BASE = "https://openapi.biji.com/open/api/v1";

export class GetClient {
  private readonly headers: Record<string, string>;

  constructor(apiKey: string, clientId: string) {
    this.headers = {
      Authorization: apiKey,
      "X-Client-ID": clientId,
    };
  }

  async listAllNotes(): Promise<GetNote[]> {
    const notes: GetNote[] = [];
    let cursor: string | number = 0;
    const seen = new Set<string>();

    while (true) {
      const key = String(cursor);
      if (seen.has(key)) {
        throw new Error(`Get pagination repeated cursor ${key}.`);
      }

      seen.add(key);

      const response: GetListResponse = await this.requestJson<GetListResponse>(
        "GET",
        "/resource/note/list",
        { since_id: String(cursor) },
      );

      const payload: GetListResponse["data"] = response.data;
      const batch = (payload?.notes ?? []).map((item: GetNotePayload) => normalizeNote(item));
      notes.push(...batch);

      if (!payload?.has_more || payload.next_cursor === undefined || payload.next_cursor === null) {
        break;
      }

      cursor = payload.next_cursor;
    }

    return notes;
  }

  async getNoteDetail(noteId: string): Promise<GetNote> {
    const response: GetDetailResponse = await this.requestJson<GetDetailResponse>(
      "GET",
      "/resource/note/detail",
      { id: noteId },
    );

    const raw = response.data?.note;
    if (!raw) {
      throw new Error(`Get detail response for ${noteId} did not include a note.`);
    }

    return normalizeNote(raw);
  }

  async expandNote(note: GetNote, seen: Set<string> = new Set()): Promise<GetNote> {
    if (seen.has(note.noteId)) {
      return note;
    }

    seen.add(note.noteId);

    const detail = await this.getNoteDetail(note.noteId);
    const childNotes: GetNote[] = [];

    for (const childId of detail.childrenIds) {
      if (seen.has(childId)) {
        continue;
      }

      const childDetail = await this.getNoteDetail(childId);
      childNotes.push(await this.expandNote(childDetail, seen));
    }

    detail.childNotes = childNotes;
    return detail;
  }

  private async requestJson<T>(
    method: string,
    path: string,
    query?: Record<string, string>,
  ): Promise<T> {
    const url = new URL(path, `${GET_API_BASE}/`);
    for (const [key, value] of Object.entries(query ?? {})) {
      url.searchParams.set(key, value);
    }

    const response = await requestUrl({
      url: url.toString(),
      method,
      headers: this.headers,
      throw: false,
    });

    if (response.status < 200 || response.status >= 300) {
      throw new Error(
        `Get API ${method} ${path} failed with ${response.status}: ${response.text.slice(0, 300)}`,
      );
    }

    return response.json as T;
  }
}

function normalizeNote(raw: GetNotePayload): GetNote {
  const noteId = String(raw.note_id ?? "").trim();
  if (!noteId) {
    throw new Error("Get note payload is missing note_id.");
  }

  const attachments: AttachmentRef[] = [];
  for (const item of raw.attachments ?? []) {
    const url = String(item.url ?? "").trim();
    if (!url) {
      continue;
    }

    attachments.push({
      name: String(item.name ?? "").trim() || extractNameFromUrl(url) || `attachment-${noteId}`,
      url,
      contentType: item.content_type ?? item.mime_type,
    });
  }

  return {
    noteId,
    title: String(raw.title ?? "").trim() || `Untitled ${noteId}`,
    content: String(raw.content ?? "").trim(),
    refContent: String(raw.ref_content ?? "").trim(),
    noteType: String(raw.note_type ?? "").trim(),
    source: String(raw.source ?? "").trim(),
    tags: collectNames(raw.tags),
    topics: collectNames(raw.topics),
    isChildNote: Boolean(raw.is_child_note),
    childrenCount: Number(raw.children_count ?? 0),
    childrenIds: (raw.children_ids ?? []).map((item) => String(item)),
    parentId: raw.parent_id === undefined || raw.parent_id === null ? undefined : String(raw.parent_id),
    attachments,
    webPageUrl: String(raw.web_page?.url ?? "").trim() || undefined,
    originalText: String(raw.web_page?.content ?? "").trim(),
    childNotes: [],
    createdAt: normalizeApiTime(raw.created_at),
    updatedAt: normalizeApiTime(raw.updated_at),
  };
}

function collectNames(values?: { name?: string }[]): string[] {
  return (values ?? [])
    .map((item) => String(item.name ?? "").trim())
    .filter((item) => item.length > 0);
}

function normalizeApiTime(value?: string): string | undefined {
  if (!value) {
    return undefined;
  }

  const trimmed = value.trim();
  const match = trimmed.match(/^(\d{4}-\d{2}-\d{2})[ T](\d{2}:\d{2}:\d{2})$/);
  if (match) {
    return `${match[1]}T${match[2]}+08:00`;
  }

  return trimmed;
}

function extractNameFromUrl(value: string): string {
  try {
    const url = new URL(value);
    const parts = url.pathname.split("/").filter(Boolean);
    return decodeURIComponent(parts.at(-1) ?? "");
  } catch {
    return "";
  }
}
