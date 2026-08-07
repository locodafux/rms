import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api, ApiError } from "../api";
import { useAuth } from "../auth";
import type {
  Attachment,
  AuditEntry,
  FieldDef,
  RecordEvent,
  RecordItem,
} from "../types";

function FieldInput({
  f,
  value,
  disabled,
  onChange,
}: {
  f: FieldDef;
  value: any;
  disabled: boolean;
  onChange: (v: any) => void;
}) {
  const common = { disabled, value: value ?? "", onChange: (e: any) => onChange(e.target.value) };
  // A tick means the document arrived. Undo it while it's still unsaved; once
  // saved the caller disables it, so a recorded document can't be un-recorded.
  if (f.section === "Document Checklist")
    return (
      <input
        type="checkbox"
        checked={!!value}
        disabled={disabled}
        onChange={() => onChange(value ? "" : "Yes")}
      />
    );
  if (f.type === "enum")
    return (
      <select {...common}>
        <option value="">—</option>
        {f.options.map((o) => (
          <option key={o} value={o}>
            {o}
          </option>
        ))}
      </select>
    );
  if (f.type === "longtext") return <textarea rows={2} {...common} />;
  const inputType =
    f.type === "date" ? "date" : f.type === "email" ? "email" : f.type === "number" || f.type === "integer" ? "number" : "text";
  return <input type={inputType} {...common} />;
}

export default function RecordDetail({ mode }: { mode: "new" | "edit" }) {
  const { id } = useParams();
  const nav = useNavigate();
  const { schema, user } = useAuth();
  const [record, setRecord] = useState<RecordItem | null>(null);
  const [form, setForm] = useState<Record<string, any>>({});
  const [unitCode, setUnitCode] = useState("");
  const [dirty, setDirty] = useState<Set<string>>(new Set());
  const [msg, setMsg] = useState<{ err?: string; ok?: string }>({});
  const [busy, setBusy] = useState(false);
  const [attachments, setAttachments] = useState<Attachment[]>([]);
  const [audit, setAudit] = useState<AuditEntry[]>([]);
  const [events, setEvents] = useState<RecordEvent[]>([]);
  const [tab, setTab] = useState<"form" | "attachments" | "history" | "audit">("form");
  const fileRef = useRef<HTMLInputElement>(null);

  const fields = schema?.fields ?? [];
  const isNew = mode === "new";

  useEffect(() => {
    if (isNew) return;
    const rid = Number(id);
    api.record(rid).then((r) => {
      setRecord(r);
      setForm(r.data);
      setUnitCode(r.unit_code);
    });
    api.attachments(rid).then(setAttachments);
    api.audit(rid).then(setAudit);
    api.events(rid).then(setEvents);
  }, [id, isNew]);

  // group fields by section preserving registry order
  const sections = useMemo(() => {
    const map: { name: string; fields: FieldDef[] }[] = [];
    for (const f of fields) {
      let s = map.find((m) => m.name === f.section);
      if (!s) {
        s = { name: f.section, fields: [] };
        map.push(s);
      }
      s.fields.push(f);
    }
    // Registry order is workbook column order, which strands two compliance-owned
    // sections down in the filing block. On screen they belong above the
    // compliance section they feed. Order of the calls is the order on screen.
    const lift = (name: string) => {
      const i = map.findIndex((m) => m.name === name);
      const j = map.findIndex((m) => m.name === "Compliance Team");
      if (i > j && j > -1) map.splice(j, 0, ...map.splice(i, 1));
    };
    lift("BOI Status Entry");
    lift("Document Checklist");
    return map;
  }, [fields]);

  function canWrite(f: FieldDef) {
    return isNew ? f.creatable : f.editable;
  }

  /** Until this role has filled its own section, the other sections arrive empty
   *  because the server withholds them — say so rather than showing bare blanks. */
  function isWithheld(s: { fields: FieldDef[] }) {
    return (
      !!record?.restricted &&
      s.fields.every((f) => f.owner !== "base" && f.owner !== schema?.role)
    );
  }

  function setField(key: string, v: any) {
    setForm((prev) => ({ ...prev, [key]: v }));
    setDirty((d) => new Set(d).add(key));
  }

  // Already saved checklist ticks are permanent.
  function isLocked(f: FieldDef) {
    return f.section === "Document Checklist" && !!record?.data?.[f.key];
  }

  // Fields this role must complete before the server will accept a save.
  // Mirrors rbac.assert_own_section_complete; the server re-checks regardless.
  const missing = isNew
    ? []
    : fields.filter((f) => f.required && (form[f.key] ?? "") === "");

  /** `extra` carries a value React state hasn't committed yet (checklist ticks,
   *  which save the moment they're clicked). */
  async function save(extra?: Record<string, any>) {
    setMsg({});
    if (missing.length) {
      setMsg({
        err: `Fill in every field in your section before saving. Still empty: ${missing
          .map((f) => f.label.replace(/^.*? — /, ""))
          .join(", ")}`,
      });
      return;
    }
    setBusy(true);
    try {
      if (isNew) {
        const payload: Record<string, any> = {};
        for (const k of dirty) if (k !== "unit_code") payload[k] = form[k];
        const created = await api.createRecord({ unit_code: unitCode, data: payload });
        setMsg({ ok: "Record created." });
        nav(`/records/${created.id}`);
      } else {
        const payload: Record<string, any> = { ...extra };
        for (const k of dirty) payload[k] ??= form[k];
        const updated = await api.patchRecord(record!.id, payload, record!.version);
        setRecord(updated);
        setForm(updated.data);
        setDirty(new Set());
        setAudit(await api.audit(updated.id));
        setMsg({ ok: "Saved." });
      }
    } catch (e) {
      const err = e as ApiError;
      if (err.status === 409 && err.detail?.current_version) {
        setMsg({ err: "This record changed elsewhere. Reload to see the latest, then re-apply your edits." });
      } else if (err.status === 422 && err.detail?.missing_labels) {
        setMsg({
          err: `${err.detail.message} Still empty: ${err.detail.missing_labels.join(", ")}`,
        });
      } else if (err.status === 403) {
        setMsg({
          err: `Not permitted: ${(err.detail?.forbidden_fields ?? []).join(", ") || err.message}`,
        });
      } else {
        setMsg({ err: typeof err.detail === "string" ? err.detail : err.message });
      }
    } finally {
      setBusy(false);
    }
  }

  async function onUpload(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file || !record) return;
    try {
      await api.upload(record.id, file);
      setAttachments(await api.attachments(record.id));
      setMsg({ ok: `Uploaded ${file.name}` });
    } catch (err) {
      setMsg({ err: (err as ApiError).message });
    } finally {
      if (fileRef.current) fileRef.current.value = "";
    }
  }

  const anyWritable = fields.some(canWrite);

  return (
    <div>
      <div className="page-head">
        <button className="btn ghost sm" onClick={() => nav("/records")}>
          ← Back
        </button>
        <h1>{isNew ? "New Record" : record?.unit_code ?? "…"}</h1>
        {record?.is_archived && <span className="badge">Archived</span>}
        {record?.archive_countdown_days != null && !record.is_archived && (
          <span
            className="badge"
            style={record.archive_countdown_days <= 0 ? { color: "var(--danger)" } : undefined}
          >
            {record.archive_countdown_days > 0
              ? `Archive in ${record.archive_countdown_days}d`
              : `Overdue for archiving (${-record.archive_countdown_days}d)`}
          </span>
        )}
        <div className="spacer" />
        {!isNew && user?.role === "admin" && record && (
          <button
            className="btn ghost sm"
            onClick={async () => {
              record.is_archived
                ? await api.unarchive(record.id)
                : await api.archive(record.id);
              setRecord(await api.record(record.id));
            }}
          >
            {record.is_archived ? "Unarchive" : "Archive"}
          </button>
        )}
        {(anyWritable || isNew) && (
          <button className="btn" onClick={() => save()} disabled={busy || (dirty.size === 0 && !isNew)}>
            {busy ? "…" : isNew ? "Create" : "Save changes"}
          </button>
        )}
      </div>

      {msg.err && <div className="error" style={{ marginBottom: 10 }}>{msg.err}</div>}
      {msg.ok && <div className="ok" style={{ marginBottom: 10 }}>{msg.ok}</div>}

      {!isNew && (
        <div className="tabs">
          <button className={`tab ${tab === "form" ? "active" : ""}`} onClick={() => setTab("form")}>
            Details
          </button>
          <button
            className={`tab ${tab === "attachments" ? "active" : ""}`}
            onClick={() => setTab("attachments")}
          >
            Attachments ({attachments.length})
          </button>
          <button
            className={`tab ${tab === "history" ? "active" : ""}`}
            onClick={() => setTab("history")}
          >
            History ({events.length})
          </button>
          <button className={`tab ${tab === "audit" ? "active" : ""}`} onClick={() => setTab("audit")}>
            Audit ({audit.length})
          </button>
        </div>
      )}

      {tab === "form" && (
        <div className="card">
          <div className="form-section">
            <h3>Identity</h3>
            <div className="grid">
              <div className="field">
                <label>Unit Code {isNew && "*"}</label>
                <input
                  disabled={!isNew}
                  value={isNew ? unitCode : record?.unit_code ?? ""}
                  onChange={(e) => setUnitCode(e.target.value)}
                />
              </div>
            </div>
          </div>
          {sections.map((s) => (
            <div className="form-section" key={s.name}>
              <h3>{s.name}</h3>
              {isWithheld(s) && (
                <p className="muted" style={{ marginTop: -8, fontSize: 13 }}>
                  🔒 Hidden until you fill in your own section.
                </p>
              )}
              <div className={`grid ${s.name === "Document Checklist" ? "grid-3" : ""}`}>
                {s.fields
                  .filter((f) => f.key !== "unit_code")
                  .map((f) => (
                    <div className="field" key={f.key}>
                      <label>
                        {f.label.replace(/^.*? — /, "")}
                        {f.required && <span className="req"> *</span>}
                      </label>
                      <FieldInput
                        f={f}
                        value={form[f.key]}
                        disabled={!canWrite(f) || isLocked(f)}
                        onChange={(v) => {
                          setField(f.key, v);
                          if (v && !isNew && f.section === "Document Checklist")
                            save({ [f.key]: v });
                        }}
                      />
                    </div>
                  ))}
              </div>
            </div>
          ))}
        </div>
      )}

      {tab === "attachments" && record && (
        <div className="card">
          <div
            className="dropzone"
            onClick={() => fileRef.current?.click()}
            onDragOver={(e) => e.preventDefault()}
            onDrop={(e) => {
              e.preventDefault();
              const f = e.dataTransfer.files?.[0];
              if (f && fileRef.current) {
                const dt = new DataTransfer();
                dt.items.add(f);
                fileRef.current.files = dt.files;
                fileRef.current.dispatchEvent(new Event("change", { bubbles: true }));
              }
            }}
          >
            Drag & drop a scanned PDF/image here, or click to browse (max 10MB).
            <input
              ref={fileRef}
              type="file"
              hidden
              accept=".pdf,image/*"
              onChange={onUpload}
            />
          </div>
          <div className="table-wrap" style={{ marginTop: 16 }}>
            <table>
              <thead>
                <tr>
                  <th>File</th>
                  <th>Type</th>
                  <th>Size</th>
                  <th>Uploaded</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {attachments.map((a) => (
                  <tr key={a.id}>
                    <td>{a.filename}</td>
                    <td className="muted">{a.mime_type}</td>
                    <td>{(a.size / 1024).toFixed(0)} KB</td>
                    <td className="muted">{new Date(a.uploaded_at).toLocaleString()}</td>
                    <td>
                      <button
                        className="btn ghost sm"
                        onClick={() =>
                          api.download(
                            `/api/records/${record.id}/attachments/${a.id}/download`,
                            a.filename,
                          )
                        }
                      >
                        Download
                      </button>
                    </td>
                  </tr>
                ))}
                {attachments.length === 0 && (
                  <tr>
                    <td colSpan={5} className="muted">
                      No attachments yet.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {tab === "history" && (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Date</th>
                <th>Event</th>
                <th>Details</th>
              </tr>
            </thead>
            <tbody>
              {events.map((ev) => (
                <tr key={ev.id}>
                  <td className="muted">{ev.event_date ?? "no date"}</td>
                  <td>
                    <span className="badge">{ev.kind}</span>
                  </td>
                  <td>
                    {/* Field labels come from the registry, so a renamed column
                        never leaves a raw key on screen. */}
                    {Object.entries(ev.data).map(([k, v]) => (
                      <div key={k}>
                        <span className="muted">
                          {fields.find((f) => f.key === k)?.label ?? k}:
                        </span>{" "}
                        {String(v)}
                      </div>
                    ))}
                  </td>
                </tr>
              ))}
              {events.length === 0 && (
                <tr>
                  <td colSpan={3} className="muted">
                    No imported filing, pullout or scanning events for this unit.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}

      {tab === "audit" && (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>When</th>
                <th>Field</th>
                <th>Old</th>
                <th>New</th>
                <th>By (user id)</th>
              </tr>
            </thead>
            <tbody>
              {audit.map((a) => (
                <tr key={a.id}>
                  <td className="muted">{new Date(a.changed_at).toLocaleString()}</td>
                  <td>{a.field_name}</td>
                  <td className="muted">{a.old_value ?? "—"}</td>
                  <td>{a.new_value ?? "—"}</td>
                  <td className="muted">{a.changed_by ?? "—"}</td>
                </tr>
              ))}
              {audit.length === 0 && (
                <tr>
                  <td colSpan={5} className="muted">
                    No changes recorded.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
