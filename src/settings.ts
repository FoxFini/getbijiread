import { Notice, PluginSettingTab, Setting, App } from "obsidian";

import type GetNoteSyncPlugin from "../main";

export interface GetSyncSettings {
  apiKey: string;
  clientId: string;
  rootFolder: string;
  notesFolder: string;
  attachmentsFolder: string;
  timelineNote: string;
  canvasFile: string;
  includeReferenceText: boolean;
  includeOriginalText: boolean;
  inlineChildNotes: boolean;
  downloadAttachments: boolean;
  autoSyncOnStartup: boolean;
  autoSyncIntervalHours: number;
  generateTimeline: boolean;
  generateCanvas: boolean;
}

export const DEFAULT_SETTINGS: GetSyncSettings = {
  apiKey: "",
  clientId: "",
  rootFolder: "Get",
  notesFolder: "Notes",
  attachmentsFolder: "Attachments",
  timelineNote: "Get/Get Timeline.md",
  canvasFile: "Get/Get Notes.canvas",
  includeReferenceText: true,
  includeOriginalText: true,
  inlineChildNotes: true,
  downloadAttachments: true,
  autoSyncOnStartup: false,
  autoSyncIntervalHours: 0,
  generateTimeline: true,
  generateCanvas: false,
};

export class GetSyncSettingTab extends PluginSettingTab {
  plugin: GetNoteSyncPlugin;

  constructor(app: App, plugin: GetNoteSyncPlugin) {
    super(app, plugin);
    this.plugin = plugin;
  }

  display(): void {
    const { containerEl } = this;
    containerEl.empty();

    containerEl.createEl("h2", { text: "Get Note Sync" });
    containerEl.createEl("p", {
      text: "Use the Get OpenAPI to sync notes directly into your Obsidian vault.",
    });

    new Setting(containerEl)
      .setName("Get API Key")
      .setDesc("Used as the Authorization header when requesting the Get OpenAPI.")
      .addText((text) => {
        text.inputEl.type = "password";
        text.setPlaceholder("Paste your Get API Key");
        text.setValue(this.plugin.settings.apiKey);
        text.onChange(async (value) => {
          this.plugin.settings.apiKey = value.trim();
          await this.plugin.savePluginData();
        });
      });

    new Setting(containerEl)
      .setName("Get Client ID")
      .setDesc("Sent as the X-Client-ID header.")
      .addText((text) => {
        text.setPlaceholder("Paste your Get Client ID");
        text.setValue(this.plugin.settings.clientId);
        text.onChange(async (value) => {
          this.plugin.settings.clientId = value.trim();
          await this.plugin.savePluginData();
        });
      });

    containerEl.createEl("h3", { text: "Storage" });

    new Setting(containerEl)
      .setName("Root folder")
      .setDesc("All generated files will be placed under this vault folder.")
      .addText((text) => {
        text.setPlaceholder("Get");
        text.setValue(this.plugin.settings.rootFolder);
        text.onChange(async (value) => {
          this.plugin.settings.rootFolder = value.trim() || DEFAULT_SETTINGS.rootFolder;
          await this.plugin.savePluginData();
        });
      });

    new Setting(containerEl)
      .setName("Notes folder")
      .setDesc("Created under the root folder and grouped by date.")
      .addText((text) => {
        text.setPlaceholder("Notes");
        text.setValue(this.plugin.settings.notesFolder);
        text.onChange(async (value) => {
          this.plugin.settings.notesFolder = value.trim() || DEFAULT_SETTINGS.notesFolder;
          await this.plugin.savePluginData();
        });
      });

    new Setting(containerEl)
      .setName("Attachments folder")
      .setDesc("Created under the root folder for downloaded Get attachments.")
      .addText((text) => {
        text.setPlaceholder("Attachments");
        text.setValue(this.plugin.settings.attachmentsFolder);
        text.onChange(async (value) => {
          this.plugin.settings.attachmentsFolder = value.trim() || DEFAULT_SETTINGS.attachmentsFolder;
          await this.plugin.savePluginData();
        });
      });

    containerEl.createEl("h3", { text: "Sync behavior" });

    new Setting(containerEl)
      .setName("Download attachments")
      .setDesc("Download images, audio, video, and files referenced by Get.")
      .addToggle((toggle) =>
        toggle.setValue(this.plugin.settings.downloadAttachments).onChange(async (value) => {
          this.plugin.settings.downloadAttachments = value;
          await this.plugin.savePluginData();
        }),
      );

    new Setting(containerEl)
      .setName("Include reference content")
      .setDesc("Write the Get ref_content field into each note.")
      .addToggle((toggle) =>
        toggle.setValue(this.plugin.settings.includeReferenceText).onChange(async (value) => {
          this.plugin.settings.includeReferenceText = value;
          await this.plugin.savePluginData();
        }),
      );

    new Setting(containerEl)
      .setName("Include original article text")
      .setDesc("Write web_page.content into a separate section when present.")
      .addToggle((toggle) =>
        toggle.setValue(this.plugin.settings.includeOriginalText).onChange(async (value) => {
          this.plugin.settings.includeOriginalText = value;
          await this.plugin.savePluginData();
        }),
      );

    new Setting(containerEl)
      .setName("Inline child notes")
      .setDesc("Render child notes under the parent note instead of syncing them as separate files.")
      .addToggle((toggle) =>
        toggle.setValue(this.plugin.settings.inlineChildNotes).onChange(async (value) => {
          this.plugin.settings.inlineChildNotes = value;
          await this.plugin.savePluginData();
        }),
      );

    new Setting(containerEl)
      .setName("Auto sync on startup")
      .setDesc("Run a sync a few seconds after Obsidian starts.")
      .addToggle((toggle) =>
        toggle.setValue(this.plugin.settings.autoSyncOnStartup).onChange(async (value) => {
          this.plugin.settings.autoSyncOnStartup = value;
          await this.plugin.savePluginData();
        }),
      );

    new Setting(containerEl)
      .setName("Auto sync interval (hours)")
      .setDesc("Set to 0 to disable scheduled sync.")
      .addText((text) => {
        text.inputEl.type = "number";
        text.setPlaceholder("0");
        text.setValue(String(this.plugin.settings.autoSyncIntervalHours));
        text.onChange(async (value) => {
          const parsed = Number.parseInt(value, 10);
          this.plugin.settings.autoSyncIntervalHours = Number.isFinite(parsed) && parsed > 0 ? parsed : 0;
          await this.plugin.savePluginData();
          this.plugin.refreshAutoSyncSchedule();
        });
      });

    containerEl.createEl("h3", { text: "Generated files" });

    new Setting(containerEl)
      .setName("Generate timeline note")
      .setDesc("Create a grouped overview note with links to all synced files.")
      .addToggle((toggle) =>
        toggle.setValue(this.plugin.settings.generateTimeline).onChange(async (value) => {
          this.plugin.settings.generateTimeline = value;
          await this.plugin.savePluginData();
        }),
      );

    new Setting(containerEl)
      .setName("Timeline note path")
      .setDesc("Vault-relative path for the generated timeline note.")
      .addText((text) => {
        text.setPlaceholder("Get/Get Timeline.md");
        text.setValue(this.plugin.settings.timelineNote);
        text.onChange(async (value) => {
          this.plugin.settings.timelineNote = value.trim() || DEFAULT_SETTINGS.timelineNote;
          await this.plugin.savePluginData();
        });
      });

    new Setting(containerEl)
      .setName("Generate canvas")
      .setDesc("Create a simple Canvas file that links the synced notes as file cards.")
      .addToggle((toggle) =>
        toggle.setValue(this.plugin.settings.generateCanvas).onChange(async (value) => {
          this.plugin.settings.generateCanvas = value;
          await this.plugin.savePluginData();
        }),
      );

    new Setting(containerEl)
      .setName("Canvas file path")
      .setDesc("Vault-relative path for the generated Canvas file.")
      .addText((text) => {
        text.setPlaceholder("Get/Get Notes.canvas");
        text.setValue(this.plugin.settings.canvasFile);
        text.onChange(async (value) => {
          this.plugin.settings.canvasFile = value.trim() || DEFAULT_SETTINGS.canvasFile;
          await this.plugin.savePluginData();
        });
      });

    containerEl.createEl("h3", { text: "Actions" });

    new Setting(containerEl)
      .setName("Run sync now")
      .setDesc("Fetch the latest Get notes and write them into this vault.")
      .addButton((button) =>
        button.setButtonText("Sync now").setCta().onClick(async () => {
          button.setDisabled(true);
          button.setButtonText("Syncing...");
          try {
            await this.plugin.syncNow("settings");
          } finally {
            button.setDisabled(false);
            button.setButtonText("Sync now");
            this.display();
          }
        }),
      );

    new Setting(containerEl)
      .setName("Reset sync state")
      .setDesc("Clear the local sync cache. Existing note files will not be deleted.")
      .addButton((button) =>
        button.setButtonText("Reset").setWarning().onClick(async () => {
          if (!window.confirm("Clear the local sync cache? Existing files in the vault will be kept.")) {
            return;
          }

          await this.plugin.resetSyncState();
          new Notice("Get sync cache cleared.");
          this.display();
        }),
      );

    const summaryEl = containerEl.createDiv({ cls: "get-note-sync-summary" });
    summaryEl.createEl("h3", { text: "Last run" });

    if (!this.plugin.lastSummary) {
      summaryEl.createEl("p", { text: "No sync has completed yet." });
      return;
    }

    const summary = this.plugin.lastSummary;
    summaryEl.createEl("p", { text: `Trigger: ${summary.trigger}` });
    summaryEl.createEl("p", {
      text: `Finished: ${new Date(summary.finishedAt).toLocaleString()}`,
    });
    summaryEl.createEl("p", {
      text: `Created ${summary.created}, updated ${summary.updated}, skipped ${summary.skipped}, failed ${summary.failed}.`,
    });
    summaryEl.createEl("p", {
      text: `Listed ${summary.totalListed} notes, downloaded ${summary.attachmentsDownloaded} attachments.`,
    });
    summaryEl.createEl("p", {
      text: `Timeline ${summary.timelineUpdated ? "updated" : "not updated"}, canvas ${summary.canvasUpdated ? "updated" : "not updated"}.`,
    });
  }
}
