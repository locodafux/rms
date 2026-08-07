export type Role =
  | "admin"
  | "document_compliance"
  | "scanning"
  | "filing"
  | "notary";

export interface User {
  id: number;
  email: string;
  full_name: string | null;
  role: Role | null;
  is_active: boolean;
  is_superuser: boolean;
  created_at: string;
  /** Geo areas this user covers; empty = unrestricted (imports not gated). */
  geos: string[];
}

/** Presence row from GET /api/meta/online — last activity, not a real session. */
export interface OnlineUser {
  id: number;
  full_name: string | null;
  role: Role | null;
  last_seen: string;
}

/** One message in the shared team room (GET/POST /api/chat). */
export interface ChatMessage {
  id: number;
  user_id: number | null;
  full_name: string | null;
  role: Role | null;
  body: string;
  created_at: string;
}

/** One upload in the Files tab (GET /api/import). */
export interface ImportFile {
  id: number;
  status: string;
  filename: string;
  total_rows: number;
  processed_rows: number;
  inserted: number;
  updated: number;
  errors: { row: number | null; sheet?: string | null; error: string }[];
  created_at: string;
  uploaded_by: string | null;
  uploaded_by_role: Role | null;
  /** False once the original has been cleared from job storage. */
  file_available: boolean;
}

export interface FieldDef {
  key: string;
  label: string;
  section: string;
  owner: string;
  type: "text" | "longtext" | "date" | "email" | "number" | "integer" | "enum";
  options: string[];
  editable: boolean;
  creatable: boolean;
  /** Must be filled before this role can save its section (admin: never). */
  required: boolean;
}

export interface SchemaResponse {
  role: Role;
  can_create: boolean;
  can_import: boolean;
  can_export: boolean;
  can_manage_users: boolean;
  /** role -> sections that role's import may fill. Admin gets every role. */
  import_scopes: Record<string, string[]>;
  fields: FieldDef[];
}

export interface RecordItem {
  id: number;
  unit_code: string;
  data: Record<string, any>;
  is_archived: boolean;
  version: number;
  created_by: number | null;
  created_at: string;
  updated_at: string;
  attachments: Attachment[];
  archive_countdown_days: number | null;
  /** This role hasn't worked this record yet, so other sections' values are
   *  withheld — a missing key here may be hidden rather than empty. */
  restricted: boolean;
}

/** One imported filing / pullout / scanning event (GET /api/records/:id/events). */
export interface RecordEvent {
  id: number;
  kind: "filed" | "pullout" | "scanned";
  event_date: string | null;
  data: Record<string, any>;
  source_job_id: number | null;
}

/** A row on the cross-record History page (GET /api/history). */
export interface HistoryItem extends RecordEvent {
  record_id: number;
  unit_code: string;
}

export interface HistoryPage {
  items: HistoryItem[];
  total: number;
  page: number;
  page_size: number;
}

export interface RecordPage {
  items: RecordItem[];
  total: number;
  page: number;
  page_size: number;
}

export interface Attachment {
  id: number;
  record_id: number;
  filename: string;
  size: number;
  mime_type: string;
  uploaded_by: number | null;
  uploaded_at: string;
}

export type Bucket = "done" | "incoming" | "pending";

/** One raw status value behind a bucket, biggest first. */
export interface BreakdownEntry {
  value: string;
  n: number;
}

export interface RoleStat {
  role: Role;
  label: string;
  field: string;
  total: number;
  done: number;
  incoming: number;
  pending: number;
  done_pct: number;
  breakdown: Record<Bucket, BreakdownEntry[]>;
}

export interface SoonToArchive {
  id: number;
  unit_code: string;
  company: string | null;
  arch_accounts_status: string | null;
  days: number;
}

export interface Stats {
  total_records: number;
  roles: RoleStat[];
  unit_status: Record<string, number>;
  soon_to_archive: SoonToArchive[];
}

export interface AuditEntry {
  id: number;
  record_id: number;
  field_name: string;
  old_value: string | null;
  new_value: string | null;
  changed_by: number | null;
  changed_at: string;
}
