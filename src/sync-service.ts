import { App, normalizePath, requestUrl } from "obsidian";

import type { GetSyncSettings } from "./settings";
import { GetClient } from "./get-client";
import {
  buildCanvasPayload,
  buildNoteMarkdown,
  buildNoteSignature,
  buildRenderConfigHash,
  buildTimelineMarkdown,
  sanitizeFilePart,
  type AttachmentRenderEntry,
} from "./markdown";
import type { GetNote, SyncSummary, SyncedNoteState } from "./types";

interface AttachmentSyncResult {
  entries: AttachmentRenderEntry[];
  savedPaths: string[];
  downloadedCount: number;
}

export class SyncService {
  readonly state: Record<string, SyncedNoteState>;

  private readonly renderConfigHash: string;

  constructor(
    private readonly app: App,
    private readonly settings: GetSyncSettings,
    initialState: Record<string, SyncedNoteState>,
  ) {
    this.state = { ...initialState };
    this.renderConfigHash = buildRenderConfigHash(settings);
  }

  async sync(trigger: string): Promise<SyncSummary> {
    const startedAt = Date.now();
    const client = new GetClient(this.settings.apiKey, this.settings.clientId);
    const listed = await client.listAllNotes();
    const rootNotes = listed
      .filter((note) => !note.isChildNote)
      .sort((left, right) => sortByMostRecent(right, left));

    let created = 0;
    let updated = 0;
    let skipped = 0;
    let failed = 0;
    let attachmentsDownloaded = 0;

    for (const summary of rootNotes) {
      try {
        if (await this.canSkip(summary)) {
          skipped += 1;
          continue;
        }

        const expanded = await client.expandNote(summary);
        const notePath = this.buildNotePath(expanded);
        const signature = buildNoteSignature(expanded, this.renderConfigHash);
        const existing = this.state[expanded.noteId];

        if (
          existing &&
          existing.signature === signature &&
          existing.renderConfigHash === this.renderConfigHash &&
          existing.filePath === notePath &&
          (await this.fileExists(notePath)) &&
          (await this.attachmentsHealthy(existing.attachmentPaths))
        ) {
          this.state[expanded.noteId] = {
            ...existing,
            title: expanded.title,
            childrenCount: expanded.childrenCount,
            createdAt: expanded.createdAt,
            updatedAt: expanded.updatedAt,
          };
          skipped += 1;
          continue;
        }

        const attachmentResult = await this.syncAttachments(expanded, existing);
        attachmentsDownloaded += attachmentResult.downloadedCount;

        const markdown = buildNoteMarkdown(expanded, {
          syncedAt: new Date().toISOString(),
          includeReferenceText: this.settings.includeReferenceText,
          includeOriginalText: this.settings.includeOriginalText,
          inlineChildNotes: this.settings.inlineChildNotes,
          attachments: attachmentResult.entries,
        });

        await this.writeTextFile(notePath, markdown);

        if (existing?.filePath && existing.filePath !== notePath) {
          await this.removeFile(existing.filePath);
        }

        await this.deleteRemovedAttachments(existing?.attachmentPaths ?? [], attachmentResult.savedPaths);

        this.state[expanded.noteId] = {
          filePath: notePath,
          signature,
          renderConfigHash: this.renderConfigHash,
          title: expanded.title,
          childrenCount: expanded.childrenCount,
          createdAt: expanded.createdAt,
          updatedAt: expanded.updatedAt,
          attachmentPaths: attachmentResult.savedPaths,
          lastSyncedAt: Date.now(),
        };

        if (existing) {
          updated += 1;
        } else {
          created += 1;
        }
      } catch (error) {
        failed += 1;
        console.error(`Failed to sync Get note ${summary.noteId}`, error);
      }
    }

    let timelineUpdated = false;
    let canvasUpdated = false;
    const syncedStates = Object.values(this.state);
    const nowIso = new Date().toISOString();

    if (this.settings.generateTimeline) {
      await this.writeTextFile(this.settings.timelineNote, buildTimelineMarkdown(syncedStates, nowIso));
      timelineUpdated = true;
    }

    if (this.settings.generateCanvas) {
      await this.writeTextFile(this.settings.canvasFile, buildCanvasPayload(syncedStates, nowIso));
      canvasUpdated = true;
    }

    return {
      trigger,
      totalListed: listed.length,
      rootNotes: rootNotes.length,
      created,
      updated,
      skipped,
      failed,
      attachmentsDownloaded,
      timelineUpdated,
      canvasUpdated,
      startedAt,
      finishedAt: Date.now(),
    };
  }

  private async canSkip(note: GetNote): Promise<boolean> {
    const existing = this.state[note.noteId];
    if (!existing) {
      return false;
    }

    if (existing.renderConfigHash !== this.renderConfigHash) {
      return false;
    }

    if (existing.title !== note.title) {
      return false;
    }

    if (existing.childrenCount !== note.childrenCount) {
      return false;
    }

    if ((existing.updatedAt ?? "") !== (note.updatedAt ?? "")) {
      return false;
    }

    const nextPath = this.buildNotePath(note);
    if (existing.filePath !== nextPath) {
      return false;
    }

    if (!(await this.fileExists(existing.filePath))) {
      return false;
    }

    return this.attachmentsHealthy(existing.attachmentPaths);
  }

  private async attachmentsHealthy(paths: string[]): Promise<boolean> {
    if (!this.settings.downloadAttachments || paths.length === 0) {
      return true;
    }

    for (const path of paths) {
      if (!(await this.fileExists(path))) {
        return false;
      }
    }

    return true;
  }

  private buildNotePath(note: GetNote): string {
    const bucket = (note.createdAt ?? note.updatedAt ?? new Date().toISOString()).slice(0, 10);
    const baseDir = normalizePath(
      `${this.settings.rootFolder}/${this.settings.notesFolder}/${bucket}`,
    );
    const fileName = `${sanitizeFilePart(note.title)}--${note.noteId}.md`;
    return normalizePath(`${baseDir}/${fileName}`);
  }

  private async syncAttachments(
    note: GetNote,
    existing?: SyncedNoteState,
  ): Promise<AttachmentSyncResult> {
    if (note.attachments.length === 0) {
      return {
        entries: [],
        savedPaths: [],
        downloadedCount: 0,
      };
    }

    const entries: AttachmentRenderEntry[] = [];
    const savedPaths: string[] = [];
    let downloadedCount = 0;

    for (const attachment of note.attachments) {
      const extension = inferExtension(attachment.name, attachment.url, attachment.contentType);
      const attachmentName = extension
        ? ensureExtension(sanitizeFilePart(stripExtension(attachment.name)), extension)
        : sanitizeFilePart(attachment.name);

      if (!this.settings.downloadAttachments) {
        entries.push({
          name: attachmentName,
          target: attachment.url,
          downloaded: false,
          embed: isEmbeddable(extension, attachment.contentType),
        });
        continue;
      }

      const targetPath = normalizePath(
        `${this.settings.rootFolder}/${this.settings.attachmentsFolder}/${note.noteId}/${attachmentName}`,
      );

      if (!(await this.fileExists(targetPath))) {
        const response = await requestUrl({
          url: attachment.url,
          method: "GET",
          throw: false,
        });

        if (response.status < 200 || response.status >= 300) {
          throw new Error(`Attachment download failed (${response.status}) for ${attachment.url}`);
        }

        await this.writeBinaryFile(targetPath, response.arrayBuffer);
        downloadedCount += 1;
      }

      savedPaths.push(targetPath);
      entries.push({
        name: attachmentName,
        target: targetPath,
        downloaded: true,
        embed: isEmbeddable(extension, attachment.contentType),
      });
    }

    for (const oldPath of existing?.attachmentPaths ?? []) {
      if (!savedPaths.includes(oldPath) && (await this.fileExists(oldPath))) {
        await this.removeFile(oldPath);
      }
    }

    return {
      entries,
      savedPaths,
      downloadedCount,
    };
  }

  private async deleteRemovedAttachments(previousPaths: string[], nextPaths: string[]): Promise<void> {
    for (const path of previousPaths) {
      if (!nextPaths.includes(path) && (await this.fileExists(path))) {
        await this.removeFile(path);
      }
    }
  }

  private async writeTextFile(path: string, content: string): Promise<void> {
    const normalized = normalizePath(path);
    await this.ensureFolder(parentPath(normalized));
    await this.app.vault.adapter.write(normalized, content);
  }

  private async writeBinaryFile(path: string, data: ArrayBuffer): Promise<void> {
    const normalized = normalizePath(path);
    await this.ensureFolder(parentPath(normalized));
    await this.app.vault.adapter.writeBinary(normalized, data);
  }

  private async ensureFolder(folderPath: string): Promise<void> {
    if (!folderPath) {
      return;
    }

    const parts = normalizePath(folderPath).split("/").filter(Boolean);
    let current = "";

    for (const part of parts) {
      current = current ? `${current}/${part}` : part;
      if (!(await this.app.vault.adapter.exists(current))) {
        await this.app.vault.createFolder(current);
      }
    }
  }

  private async fileExists(path: string): Promise<boolean> {
    return this.app.vault.adapter.exists(normalizePath(path));
  }

  private async removeFile(path: string): Promise<void> {
    const normalized = normalizePath(path);
    if (await this.app.vault.adapter.exists(normalized)) {
      await this.app.vault.adapter.remove(normalized);
    }
  }
}

function parentPath(path: string): string {
  const segments = normalizePath(path).split("/");
  segments.pop();
  return segments.join("/");
}

function sortByMostRecent(left: GetNote, right: GetNote): number {
  return compareTimestamps(left.updatedAt ?? left.createdAt, right.updatedAt ?? right.createdAt);
}

function compareTimestamps(left?: string, right?: string): number {
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

function inferExtension(name: string, url: string, contentType?: string): string {
  const fromName = extractExtension(name);
  if (fromName) {
    return fromName;
  }

  const fromUrl = extractExtension(url);
  if (fromUrl) {
    return fromUrl;
  }

  const lowered = (contentType ?? "").toLowerCase();
  const mapping: Record<string, string> = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/gif": "gif",
    "image/webp": "webp",
    "audio/mpeg": "mp3",
    "audio/mp4": "m4a",
    "audio/wav": "wav",
    "video/mp4": "mp4",
    "application/pdf": "pdf",
  };

  return mapping[lowered] ?? "";
}

function extractExtension(value: string): string {
  try {
    const pathname = value.includes("://") ? new URL(value).pathname : value;
    const match = pathname.match(/\.([a-zA-Z0-9]{1,10})$/);
    return match?.[1]?.toLowerCase() ?? "";
  } catch {
    return "";
  }
}

function stripExtension(value: string): string {
  return value.replace(/\.[a-zA-Z0-9]{1,10}$/, "");
}

function ensureExtension(value: string, extension: string): string {
  return value.toLowerCase().endsWith(`.${extension.toLowerCase()}`) ? value : `${value}.${extension}`;
}

function isEmbeddable(extension: string, contentType?: string): boolean {
  const loweredExtension = extension.toLowerCase();
  const loweredType = (contentType ?? "").toLowerCase();

  return (
    ["png", "jpg", "jpeg", "gif", "webp", "svg", "mp3", "m4a", "wav", "mp4", "pdf"].includes(
      loweredExtension,
    ) ||
    loweredType.startsWith("image/") ||
    loweredType.startsWith("audio/") ||
    loweredType.startsWith("video/") ||
    loweredType === "application/pdf"
  );
}
