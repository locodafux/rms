import { useEffect, useRef, useState } from "react";
import { api, ApiError } from "../api";
import { useAuth } from "../auth";
import type { User } from "../types";

// Roles that may insert brand-new records; everyone else can only update
// existing Unit Codes (mirrors rbac.CREATE_ROLES).
const CREATE_ROLES = ["admin", "document_compliance"];

/** One drop area's state. Zones are independent — several imports run at once. */
type Zone = { file: string; job: any | null; error?: string };

const finished = (z?: Zone) =>
  !!z?.error || z?.job?.status === "done" || z?.job?.status === "error";

function Dropzone({
  label,
  disabled,
  onFile,
}: {
  label: string;
  disabled: boolean;
  onFile: (f: File) => void;
}) {
  const ref = useRef<HTMLInputElement>(null);
  return (
    <div
      className="dropzone"
      onClick={() => !disabled && ref.current?.click()}
      onDragOver={(e) => e.preventDefault()}
      onDrop={(e) => {
        e.preventDefault();
        if (disabled) return;
        const f = e.dataTransfer.files?.[0];
        if (f) onFile(f);
      }}
    >
      {label}
      <input
        ref={ref}
        type="file"
        hidden
        accept=".xlsx,.xls,.csv"
        onChange={(e) => {
          const f = e.target.files?.[0];
          // Reset so re-picking the same file still fires onChange.
          e.target.value = "";
          if (f) onFile(f);
        }}
      />
    </div>
  );
}

function JobResult({ zone }: { zone: Zone }) {
  if (zone.error) return <div className="error">{zone.error}</div>;
  const job = zone.job;
  if (!job) return <p className="muted">Uploading {zone.file}…</p>;
  // The job's errors array mixes per-row failures with job-level notes
  // (row: null), e.g. "N column(s) skipped" or "N row(s) outside SOMA1". Only
  // the former are skipped rows; counting both made the totals not add up.
  const rowErrors = (job.errors ?? []).filter((e: any) => e.row != null);
  const notes = (job.errors ?? []).filter((e: any) => e.row == null);
  return (
    <>
      <p>
        <b>{zone.file}</b> — job #{job.id} <span className="badge">{job.status}</span>
        {" · "}processed {job.processed_rows}/{job.total_rows} · inserted{" "}
        <b>{job.inserted}</b> · updated <b>{job.updated}</b>
      </p>
      {job.status === "done" && (
        <div className="ok">
          Import complete — {job.inserted} inserted, {job.updated} updated
          {rowErrors.length ? `, ${rowErrors.length} skipped` : ""}.
        </div>
      )}
      {notes.map((e: any, i: number) => (
        // Informational when the job succeeded; on status "error" the same
        // slot carries the fatal message, which must not read as a footnote.
        <p
          key={i}
          className={job.status === "error" ? "error" : "muted"}
          style={{ marginBottom: 0 }}
        >
          {e.error}
        </p>
      ))}
      {rowErrors.length > 0 && (
        <details style={{ marginTop: 8 }}>
          <summary className="error">{rowErrors.length} row error(s)</summary>
          <ul>
            {rowErrors.slice(0, 50).map((e: any, i: number) => (
              <li key={i} className="muted">
                {e.sheet ? `${e.sheet} row ${e.row}` : `Row ${e.row}`}: {e.error}
              </li>
            ))}
          </ul>
        </details>
      )}
    </>
  );
}

export default function ImportPage() {
  const { user, schema } = useAuth();
  const isAdmin = !!schema?.can_manage_users;
  const [users, setUsers] = useState<User[]>([]);
  const [zones, setZones] = useState<Record<number, Zone>>({});

  // Admin uploads on behalf of each activated user; everyone else has one zone
  // for themselves. Users with no role can't import, so they get no zone.
  useEffect(() => {
    if (!isAdmin) return;
    api.users().then((all) => setUsers(all.filter((u) => u.is_active && u.role)));
  }, [isAdmin]);
  const targets = isAdmin
    ? [...users].sort((a, b) =>
        a.id === user?.id ? -1 : b.id === user?.id ? 1 : (a.role ?? "").localeCompare(b.role ?? "")
      )
    : user
    ? [user]
    : [];

  function patch(id: number, p: Partial<Zone>) {
    setZones((z) => ({ ...z, [id]: { ...(z[id] ?? { file: "", job: null }), ...p } }));
  }

  // One-click import: choosing a file starts that zone's job immediately. Other
  // zones stay usable, so several designations can be imported in one go (the
  // server queues them — see importer._WRITE_LOCK).
  async function runImport(t: User, f: File) {
    patch(t.id, { file: f.name, job: null, error: undefined });
    try {
      patch(t.id, { job: await api.startImport(f, t.id) });
    } catch (e) {
      patch(t.id, { error: (e as ApiError).message });
    }
  }

  // Poll every unfinished job together.
  useEffect(() => {
    const running = Object.entries(zones).filter(
      ([, z]) => z.job && z.job.status !== "done" && z.job.status !== "error",
    );
    if (!running.length) return;
    const t = setInterval(async () => {
      const done = await Promise.all(
        running.map(async ([id, z]) => [Number(id), await api.importStatus(z.job.id)] as const),
      );
      setZones((prev) => {
        const next = { ...prev };
        for (const [id, job] of done) next[id] = { ...next[id], job };
        return next;
      });
    }, 1000);
    return () => clearInterval(t);
  }, [zones]);

  return (
    <div>
      <div className="page-head">
        <h1>Import</h1>
      </div>
      <p className="muted" style={{ marginTop: 0 }}>
        Upload an <b>.xlsx</b> or <b>.csv</b> — the import runs immediately. Headers are
        matched to the canonical 133 fields; rows are upserted on <b>Unit Code</b>{" "}
        (existing records are updated, new ones inserted). Every sheet with a Unit Code column is read, and filing/pullout/scanning rows are kept as history on the unit.
        {isAdmin &&
          " Each activated user has their own drop area — you can start several at once. A file dropped in a zone fills only that user's columns, in that user's work areas, and is credited to them."}
      </p>

      {targets.map((t) => {
        const sections = schema?.import_scopes?.[t.role ?? ""] ?? [];
        const zone = zones[t.id];
        const busy = !!zone && !finished(zone);
        return (
          <div className="card" key={t.id} style={{ marginBottom: 14 }}>
            <h3 style={{ marginTop: 0 }}>
              {t.full_name || t.email}
              {t.id === user?.id && <span className="muted"> (you)</span>}{" "}
              <span className="badge">{t.role?.replace(/_/g, " ")}</span>
              {t.geos?.map((g) => (
                <span key={g} className="badge">
                  {g}
                </span>
              ))}
            </h3>
            <p className="muted" style={{ marginTop: 0 }}>
              Fills <b>{sections.join(", ") || "no"}</b> column(s); anything else in the
              file is ignored.
              {t.role !== "admin" &&
                (t.geos?.length
                  ? ` Rows outside ${t.geos.join(", ")} are skipped.`
                  : " No work areas set — rows from any area are accepted.")}
              {!CREATE_ROLES.includes(t.role ?? "") &&
                " Rows whose Unit Code doesn't exist yet are skipped."}
            </p>
            <Dropzone
              disabled={busy}
              onFile={(f) => runImport(t, f)}
              label={
                busy
                  ? `Importing ${zone.file}…`
                  : "Drag & drop a spreadsheet here, or click to choose"
              }
            />
            {zone && (
              <div style={{ marginTop: 12 }}>
                <JobResult zone={zone} />
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
