import { Notice, Plugin } from "obsidian";

import { GetSyncSettingTab, DEFAULT_SETTINGS, type GetSyncSettings } from "./src/settings";
import { SyncService } from "./src/sync-service";
import type { SyncSummary, SyncedNoteState } from "./src/types";

interface PersistedData {
  settings?: Partial<GetSyncSettings>;
  syncedNotes?: Record<string, SyncedNoteState>;
  lastSyncAt?: number;
  lastSummary?: SyncSummary | null;
}

export default class GetNoteSyncPlugin extends Plugin {
  settings: GetSyncSettings = { ...DEFAULT_SETTINGS };
  syncedNotes: Record<string, SyncedNoteState> = {};
  lastSyncAt = 0;
  lastSummary: SyncSummary | null = null;

  private settingsTab: GetSyncSettingTab | null = null;
  private statusBarEl: HTMLElement | null = null;
  private syncPromise: Promise<SyncSummary | null> | null = null;
  private syncIntervalId: number | null = null;

  async onload(): Promise<void> {
    await this.loadPluginData();

    this.settingsTab = new GetSyncSettingTab(this.app, this);
    this.addSettingTab(this.settingsTab);

    this.statusBarEl = this.addStatusBarItem();
    this.updateStatusBar();

    this.addRibbonIcon("refresh-cw", "Sync Get notes now", () => {
      void this.syncNow("ribbon");
    });

    this.addCommand({
      id: "sync-get-notes-now",
      name: "Sync Get notes now",
      callback: () => {
        void this.syncNow("command");
      },
    });

    this.addCommand({
      id: "reset-get-sync-state",
      name: "Reset Get sync state",
      callback: () => {
        void this.resetSyncState();
      },
    });

    this.refreshAutoSyncSchedule();

    if (this.settings.autoSyncOnStartup) {
      window.setTimeout(() => {
        void this.syncNow("startup");
      }, 2000);
    }
  }

  onunload(): void {
    if (this.syncIntervalId !== null) {
      window.clearInterval(this.syncIntervalId);
      this.syncIntervalId = null;
    }
  }

  async loadPluginData(): Promise<void> {
    const data = ((await this.loadData()) as PersistedData | null) ?? {};
    this.settings = { ...DEFAULT_SETTINGS, ...(data.settings ?? {}) };
    this.syncedNotes = data.syncedNotes ?? {};
    this.lastSyncAt = data.lastSyncAt ?? 0;
    this.lastSummary = data.lastSummary ?? null;
  }

  async savePluginData(): Promise<void> {
    await this.saveData({
      settings: this.settings,
      syncedNotes: this.syncedNotes,
      lastSyncAt: this.lastSyncAt,
      lastSummary: this.lastSummary,
    } satisfies PersistedData);

    this.updateStatusBar();
  }

  validateSettings(): string | null {
    if (!this.settings.apiKey.trim()) {
      return "Missing Get API Key in plugin settings.";
    }

    if (!this.settings.clientId.trim()) {
      return "Missing Get Client ID in plugin settings.";
    }

    if (!this.settings.rootFolder.trim()) {
      return "Root folder cannot be empty.";
    }

    if (!this.settings.notesFolder.trim()) {
      return "Notes folder cannot be empty.";
    }

    if (!this.settings.attachmentsFolder.trim()) {
      return "Attachments folder cannot be empty.";
    }

    return null;
  }

  async syncNow(trigger = "manual"): Promise<SyncSummary | null> {
    if (this.syncPromise) {
      new Notice("Get sync is already running.");
      return this.syncPromise;
    }

    const validationError = this.validateSettings();
    if (validationError) {
      new Notice(validationError, 8000);
      return null;
    }

    this.syncPromise = this.runSync(trigger);
    const result = await this.syncPromise.finally(() => {
      this.syncPromise = null;
      this.updateStatusBar();
      this.settingsTab?.display();
    });

    return result;
  }

  async resetSyncState(): Promise<void> {
    this.syncedNotes = {};
    this.lastSyncAt = 0;
    this.lastSummary = null;
    await this.savePluginData();
    this.settingsTab?.display();
    new Notice("Get sync state has been cleared. Existing files in the vault were left untouched.");
  }

  refreshAutoSyncSchedule(): void {
    if (this.syncIntervalId !== null) {
      window.clearInterval(this.syncIntervalId);
      this.syncIntervalId = null;
    }

    const hours = Number.isFinite(this.settings.autoSyncIntervalHours)
      ? this.settings.autoSyncIntervalHours
      : 0;

    if (hours <= 0) {
      return;
    }

    const intervalMs = Math.max(1, hours) * 60 * 60 * 1000;
    this.syncIntervalId = window.setInterval(() => {
      void this.syncNow("interval");
    }, intervalMs);
  }

  private async runSync(trigger: string): Promise<SyncSummary | null> {
    this.updateStatusBar("Get: syncing...");

    try {
      const service = new SyncService(this.app, this.settings, this.syncedNotes);
      const summary = await service.sync(trigger);

      this.syncedNotes = service.state;
      this.lastSyncAt = summary.finishedAt;
      this.lastSummary = summary;

      await this.savePluginData();

      new Notice(
        `Get sync finished: +${summary.created} new, ${summary.updated} updated, ${summary.skipped} skipped, ${summary.failed} failed.`,
        9000,
      );

      return summary;
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      this.updateStatusBar("Get: sync failed");
      new Notice(`Get sync failed: ${message}`, 10000);
      throw error;
    }
  }

  private updateStatusBar(overrideText?: string): void {
    if (!this.statusBarEl) {
      return;
    }

    this.statusBarEl.addClass("get-note-sync-status");

    if (overrideText) {
      this.statusBarEl.setText(overrideText);
      return;
    }

    if (this.syncPromise) {
      this.statusBarEl.setText("Get: syncing...");
      return;
    }

    if (this.lastSyncAt > 0) {
      const at = new Date(this.lastSyncAt).toLocaleString();
      this.statusBarEl.setText(`Get: last sync ${at}`);
      return;
    }

    this.statusBarEl.setText("Get: idle");
  }
}
