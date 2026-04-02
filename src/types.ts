export interface GetNamedEntityPayload {
  name?: string;
}

export interface GetAttachmentPayload {
  name?: string;
  url?: string;
  mime_type?: string;
  content_type?: string;
}

export interface GetWebPagePayload {
  url?: string;
  content?: string;
}

export interface GetNotePayload {
  note_id?: string | number;
  title?: string;
  content?: string;
  ref_content?: string;
  note_type?: string;
  source?: string;
  tags?: GetNamedEntityPayload[];
  topics?: GetNamedEntityPayload[];
  is_child_note?: boolean;
  children_count?: number;
  children_ids?: Array<string | number>;
  parent_id?: string | number | null;
  attachments?: GetAttachmentPayload[];
  web_page?: GetWebPagePayload;
  created_at?: string;
  updated_at?: string;
}

export interface GetListResponse {
  data?: {
    notes?: GetNotePayload[];
    has_more?: boolean;
    next_cursor?: string | number | null;
  };
}

export interface GetDetailResponse {
  data?: {
    note?: GetNotePayload;
  };
}

export interface AttachmentRef {
  name: string;
  url: string;
  contentType?: string;
}

export interface GetNote {
  noteId: string;
  title: string;
  content: string;
  refContent: string;
  noteType: string;
  source: string;
  tags: string[];
  topics: string[];
  isChildNote: boolean;
  childrenCount: number;
  childrenIds: string[];
  parentId?: string;
  attachments: AttachmentRef[];
  webPageUrl?: string;
  originalText: string;
  createdAt?: string;
  updatedAt?: string;
  childNotes: GetNote[];
}

export interface SyncedNoteState {
  filePath: string;
  signature: string;
  renderConfigHash: string;
  title: string;
  childrenCount: number;
  createdAt?: string;
  updatedAt?: string;
  attachmentPaths: string[];
  lastSyncedAt: number;
}

export interface SyncSummary {
  trigger: string;
  totalListed: number;
  rootNotes: number;
  created: number;
  updated: number;
  skipped: number;
  failed: number;
  attachmentsDownloaded: number;
  timelineUpdated: boolean;
  canvasUpdated: boolean;
  startedAt: number;
  finishedAt: number;
}
