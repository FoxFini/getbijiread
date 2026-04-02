import type { GetSyncSettings } from "./settings";
import type { GetNote, SyncedNoteState } from "./types";

export interface AttachmentRenderEntry {
  name: string;
  target: string;
  downloaded: boolean;
  embed: boolean;
}

export function sanitizeFilePart(value: string): string {
  const cleaned = value
    .replace(/[\\/:*?"<>|]/g, " ")
    .replace(/\s+/g, " ")
    .replace(/[. ]+$/g, "")
    .trim();

  return cleaned.slice(0, 96) || "untitled";
}

export function normalizeMarkdown(value: string): string {
  return value.replace(/\r\n/g, "\n").replace(/\r/g, "\n").trim();
}

export function hashString(value: string): string {
  let hash = 2166136261;

  for (let index = 0; index < value.length; index += 1) {
    hash ^= value.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }

  return (hash >>> 0).toString(16).padStart(8, "0");
}

export function buildRenderConfigHash(settings: GetSyncSettings): string {
  return hashString(
    JSON.stringify({
      rootFolder: settings.rootFolder,
      notesFolder: settings.notesFolder,
      attachmentsFolder: settings.attachmentsFolder,
      includeReferenceText: settings.includeReferenceText,
      includeOriginalText: settings.includeOriginalText,
      inlineChildNotes: settings.inlineChildNotes,
      downloadAttachments: settings.downloadAttachments,
    }),
  );
}

export function buildNoteSignature(note: GetNote, renderConfigHash: string): string {
  return hashString(
    JSON.stringify({
      renderConfigHash,
      noteId: note.noteId,
      title: note.title,
      content: note.content,
      refContent: note.refContent,
      noteType: note.noteType,
      source: note.source,
      tags: note.tags,
      topics: note.topics,
      isChildNote: note.isChildNote,
      childrenCount: note.childrenCount,
      childrenIds: note.childrenIds,
      parentId: note.parentId,
      attachments: note.attachments,
      webPageUrl: note.webPageUrl,
      originalText: note.originalText,
      createdAt: note.createdAt,
      updatedAt: note.updatedAt,
      childNotes: note.childNotes.map((child) => buildNoteSignature(child, renderConfigHash)),
    }),
  );
}

export function buildNoteMarkdown(
  note: GetNote,
  options: {
    syncedAt: string;
    includeReferenceText: boolean;
    includeOriginalText: boolean;
    inlineChildNotes: boolean;
    attachments: AttachmentRenderEntry[];
  },
): string {
  const lines: string[] = [];

  lines.push("---");
  lines.push(`get_id: ${yamlString(note.noteId)}`);
  lines.push(`get_title: ${yamlString(note.title)}`);
  lines.push(`get_type: ${yamlString(note.noteType || "")}`);
  lines.push(`get_source: ${yamlString(note.source || "")}`);
  lines.push(`get_is_child_note: ${note.isChildNote ? "true" : "false"}`);
  lines.push(`get_children_count: ${note.childrenCount}`);
  lines.push(`get_parent_id: ${yamlString(note.parentId ?? "")}`);
  lines.push(`get_url: ${yamlString(note.webPageUrl ?? "")}`);
  lines.push(`created_at: ${yamlString(note.createdAt ?? "")}`);
  lines.push(`updated_at: ${yamlString(note.updatedAt ?? "")}`);
  lines.push(`synced_at: ${yamlString(options.syncedAt)}`);
  lines.push(`get_tags: ${yamlArray(note.tags)}`);
  lines.push(`get_topics: ${yamlArray(note.topics)}`);
  lines.push("---");
  lines.push("");
  lines.push(`# ${note.title}`);
  lines.push("");
  lines.push("> [!info] Get Metadata");
  lines.push(`> ID: ${note.noteId}`);
  if (note.noteType) {
    lines.push(`> Type: ${note.noteType}`);
  }
  if (note.source) {
    lines.push(`> Source: ${note.source}`);
  }
  if (note.createdAt) {
    lines.push(`> Created: ${note.createdAt}`);
  }
  if (note.updatedAt) {
    lines.push(`> Updated: ${note.updatedAt}`);
  }
  if (note.webPageUrl) {
    lines.push(`> Link: [Open source](${note.webPageUrl})`);
  }
  if (note.tags.length > 0) {
    lines.push(`> Tags: ${note.tags.join(", ")}`);
  }
  if (note.topics.length > 0) {
    lines.push(`> Topics: ${note.topics.join(", ")}`);
  }

  pushMarkdownSection(lines, "Note", note.content);

  if (options.includeReferenceText) {
    pushMarkdownSection(lines, "Reference", note.refContent);
  }

  if (options.inlineChildNotes && note.childNotes.length > 0) {
    lines.push("");
    lines.push("## Child Notes");
    for (const child of note.childNotes) {
      renderChildNote(lines, child, 3);
    }
  }

  if (options.includeOriginalText) {
    pushMarkdownSection(lines, "Original Article", note.originalText);
  }

  if (options.attachments.length > 0) {
    lines.push("");
    lines.push("## Attachments");
    lines.push("");

    for (const attachment of options.attachments) {
      if (attachment.downloaded) {
        lines.push(
          attachment.embed
            ? `![[${attachment.target}]]`
            : `- [[${attachment.target}|${attachment.name}]]`,
        );
      } else {
        lines.push(`- [${attachment.name}](${attachment.target})`);
      }
    }
  }

  return `${lines.join("\n").replace(/\n{3,}/g, "\n\n").trim()}\n`;
}

export function buildTimelineMarkdown(states: SyncedNoteState[], syncedAt: string): string {
  const sorted = [...states].sort((left, right) =>
    compareDates(right.updatedAt ?? right.createdAt, left.updatedAt ?? left.createdAt),
  );

  const lines: string[] = [
    "---",
    `title: ${yamlString("Get Timeline")}`,
    `synced_at: ${yamlString(syncedAt)}`,
    "---",
    "",
    "# Get Timeline",
    "",
    `Updated: ${syncedAt}`,
    "",
  ];

  let currentDate = "";

  for (const state of sorted) {
    const bucket = (state.updatedAt ?? state.createdAt ?? "Unknown").slice(0, 10) || "Unknown";
    if (bucket !== currentDate) {
      currentDate = bucket;
      lines.push(`## ${bucket}`);
      lines.push("");
    }

    const stamp = compactTime(state.updatedAt ?? state.createdAt);
    lines.push(`- [[${state.filePath}|${state.title}]]${stamp ? ` (${stamp})` : ""}`);
  }

  return `${lines.join("\n").trim()}\n`;
}

export function buildCanvasPayload(states: SyncedNoteState[], syncedAt: string): string {
  const sorted = [...states].sort((left, right) =>
    compareDates(right.updatedAt ?? right.createdAt, left.updatedAt ?? left.createdAt),
  );

  const columns = 4;
  const cardWidth = 360;
  const cardHeight = 260;
  const gutterX = 60;
  const gutterY = 80;

  const nodes = [
    {
      id: "summary",
      type: "text",
      text: `Get Notes Canvas\nSynced: ${syncedAt}\nNotes: ${sorted.length}`,
      x: 0,
      y: 0,
      width: 320,
      height: 160,
    },
    ...sorted.map((state, index) => {
      const row = Math.floor(index / columns);
      const column = index % columns;
      return {
        id: hashString(`${state.filePath}:${index}`),
        type: "file",
        file: state.filePath,
        x: column * (cardWidth + gutterX),
        y: 220 + row * (cardHeight + gutterY),
        width: cardWidth,
        height: cardHeight,
      };
    }),
  ];

  return `${JSON.stringify({ nodes, edges: [] }, null, 2)}\n`;
}

function pushMarkdownSection(lines: string[], title: string, body: string): void {
  const normalized = normalizeMarkdown(body);
  if (!normalized) {
    return;
  }

  lines.push("");
  lines.push(`## ${title}`);
  lines.push("");
  lines.push(normalized);
}

function renderChildNote(lines: string[], note: GetNote, depth: number): void {
  const heading = "#".repeat(Math.min(depth, 6));
  lines.push("");
  lines.push(`${heading} ${note.title}`);
  lines.push("");

  if (note.content) {
    lines.push(normalizeMarkdown(note.content));
  }

  if (note.refContent) {
    lines.push("");
    lines.push(`${"#".repeat(Math.min(depth + 1, 6))} Reference`);
    lines.push("");
    lines.push(normalizeMarkdown(note.refContent));
  }

  for (const child of note.childNotes) {
    renderChildNote(lines, child, depth + 1);
  }
}

function yamlString(value: string): string {
  return JSON.stringify(value);
}

function yamlArray(values: string[]): string {
  if (values.length === 0) {
    return "[]";
  }

  return `[${values.map((item) => yamlString(item)).join(", ")}]`;
}

function compactTime(value?: string): string {
  if (!value) {
    return "";
  }

  const match = value.match(/T(\d{2}:\d{2}:\d{2})/);
  return match?.[1] ?? value;
}

function compareDates(left?: string, right?: string): number {
  if (!left && !right) {
    return 0;
  }

  if (!left) {
    return -1;
  }

  if (!right) {
    return 1;
  }

  return left.localeCompare(right);
}
