const BASE = (import.meta as any).env?.VITE_API_BASE ?? "";

let accessToken: string | null = localStorage.getItem("dt_access");
let refreshToken: string | null = localStorage.getItem("dt_refresh");

export function setTokens(access: string | null, refresh: string | null) {
  accessToken = access;
  refreshToken = refresh;
  if (access) localStorage.setItem("dt_access", access);
  else localStorage.removeItem("dt_access");
  if (refresh) localStorage.setItem("dt_refresh", refresh);
  else localStorage.removeItem("dt_refresh");
}

export function getAccessToken() {
  return accessToken;
}

export class ApiError extends Error {
  status: number;
  detail: any;
  constructor(status: number, detail: any) {
    super(
      typeof detail === "string"
        ? detail
        : // FastAPI/pydantic validation errors arrive as a list of {loc, msg}.
          Array.isArray(detail)
          ? detail.map((d: any) => d?.msg ?? String(d)).join("; ")
          : detail?.message ?? "Request failed",
    );
    this.status = status;
    this.detail = detail;
  }
}

async function refreshAccess(): Promise<boolean> {
  if (!refreshToken) return false;
  const r = await fetch(`${BASE}/api/auth/refresh`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh_token: refreshToken }),
  });
  if (!r.ok) return false;
  const data = await r.json();
  setTokens(data.access_token, data.refresh_token);
  return true;
}

async function request<T>(
  path: string,
  opts: RequestInit = {},
  retry = true,
): Promise<T> {
  const headers = new Headers(opts.headers ?? {});
  if (accessToken) headers.set("Authorization", `Bearer ${accessToken}`);
  const isForm = opts.body instanceof FormData;
  if (!isForm && opts.body && !headers.has("Content-Type"))
    headers.set("Content-Type", "application/json");

  const resp = await fetch(`${BASE}${path}`, { ...opts, headers });
  if (resp.status === 401 && retry && (await refreshAccess())) {
    return request<T>(path, opts, false);
  }
  if (!resp.ok) {
    let detail: any = resp.statusText;
    try {
      const body = await resp.json();
      detail = body.detail ?? body;
    } catch {
      /* non-json */
    }
    throw new ApiError(resp.status, detail);
  }
  if (resp.status === 204) return undefined as T;
  const ct = resp.headers.get("content-type") ?? "";
  return (ct.includes("application/json") ? resp.json() : (resp as any)) as T;
}

export const api = {
  async login(email: string, password: string) {
    const form = new URLSearchParams({ username: email, password });
    const r = await fetch(`${BASE}/api/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: form,
    });
    if (!r.ok) {
      const b = await r.json().catch(() => ({}));
      throw new ApiError(r.status, b.detail ?? "Login failed");
    }
    const data = await r.json();
    setTokens(data.access_token, data.refresh_token);
    return data;
  },
  register: (body: { email: string; password: string; full_name?: string }) =>
    request("/api/auth/register", { method: "POST", body: JSON.stringify(body) }),
  me: () => request<import("./types").User>("/api/auth/me"),
  schema: () => request<import("./types").SchemaResponse>("/api/meta/schema"),
  stats: () => request<import("./types").Stats>("/api/meta/stats"),
  online: () => request<import("./types").OnlineUser[]>("/api/meta/online"),

  chat: (after?: number) =>
    request<import("./types").ChatMessage[]>(
      `/api/chat${after ? `?after=${after}` : ""}`,
    ),
  sendChat: (body: string) =>
    request<import("./types").ChatMessage>("/api/chat", {
      method: "POST",
      body: JSON.stringify({ body }),
    }),

  records: (qs: string) =>
    request<import("./types").RecordPage>(`/api/records${qs}`),
  record: (id: number) => request<import("./types").RecordItem>(`/api/records/${id}`),
  createRecord: (body: { unit_code: string; data: Record<string, any> }) =>
    request<import("./types").RecordItem>("/api/records", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  patchRecord: (id: number, data: Record<string, any>, version: number) =>
    request<import("./types").RecordItem>(`/api/records/${id}`, {
      method: "PATCH",
      body: JSON.stringify({ data, version }),
    }),
  archive: (id: number) =>
    request(`/api/records/${id}/archive`, { method: "POST" }),
  unarchive: (id: number) =>
    request(`/api/records/${id}/unarchive`, { method: "POST" }),
  audit: (id: number) =>
    request<import("./types").AuditEntry[]>(`/api/records/${id}/audit`),

  attachments: (id: number) =>
    request<import("./types").Attachment[]>(`/api/records/${id}/attachments`),
  upload: (id: number, file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    return request<import("./types").Attachment>(
      `/api/records/${id}/attachments`,
      { method: "POST", body: fd },
    );
  },
  downloadUrl: (recordId: number, attId: number) =>
    `${BASE}/api/records/${recordId}/attachments/${attId}/download`,

  users: () => request<import("./types").User[]>("/api/users"),
  updateUser: (id: number, body: { role?: string; is_active?: boolean }) =>
    request<import("./types").User>(`/api/users/${id}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),

  importPreview: (file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    return request<any>("/api/import/preview", { method: "POST", body: fd });
  },
  startImport: (file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    return request<any>("/api/import", { method: "POST", body: fd });
  },
  importStatus: (id: number) => request<any>(`/api/import/${id}`),
  startExport: (fmt: string, includeArchived: boolean) => {
    const fd = new FormData();
    fd.append("fmt", fmt);
    fd.append("include_archived", String(includeArchived));
    return request<any>("/api/export", { method: "POST", body: fd });
  },
  exportStatus: (id: number) => request<any>(`/api/export/${id}`),
  exportDownloadUrl: (id: number) => `${BASE}/api/export/${id}/download`,
};
