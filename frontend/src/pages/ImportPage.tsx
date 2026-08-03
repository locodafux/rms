import { useEffect, useRef, useState } from "react";
import { api, ApiError } from "../api";

export default function ImportPage() {
  const [file, setFile] = useState<File | null>(null);
  const [job, setJob] = useState<any>(null);
  const [msg, setMsg] = useState<string>("");
  const [busy, setBusy] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  // One-click import: choosing a file starts the job immediately.
  async function runImport(f: File) {
    setMsg("");
    setBusy(true);
    setJob(null);
    try {
      setJob(await api.startImport(f));
    } catch (e) {
      setMsg((e as ApiError).message);
    } finally {
      setBusy(false);
    }
  }

  // poll job status
  useEffect(() => {
    if (!job || job.status === "done" || job.status === "error") return;
    const t = setInterval(async () => {
      setJob(await api.importStatus(job.id));
    }, 1000);
    return () => clearInterval(t);
  }, [job]);

  return (
    <div>
      <div className="page-head">
        <h1>Import</h1>
      </div>
      <div className="card">
        <p className="muted" style={{ marginTop: 0 }}>
          Upload an <b>.xlsx</b> or <b>.csv</b> — the import runs immediately.
          Headers are matched to the canonical 120 fields; rows are upserted on{" "}
          <b>Unit Code</b> (existing records are updated, new ones inserted).
        </p>
        <div
          className="dropzone"
          onClick={() => !busy && fileRef.current?.click()}
          onDragOver={(e) => e.preventDefault()}
          onDrop={(e) => {
            e.preventDefault();
            if (busy) return;
            const f = e.dataTransfer.files?.[0];
            if (f) {
              setFile(f);
              runImport(f);
            }
          }}
        >
          {busy ? (
            <b>Importing {file?.name}…</b>
          ) : file ? (
            <b>{file.name}</b>
          ) : (
            "Drag & drop a spreadsheet here, or click to choose"
          )}
          <input
            ref={fileRef}
            type="file"
            hidden
            accept=".xlsx,.xls,.csv"
            onChange={(e) => {
              const f = e.target.files?.[0] ?? null;
              setFile(f);
              if (f) runImport(f);
            }}
          />
        </div>
        {msg && <div className="error" style={{ marginTop: 10 }}>{msg}</div>}
      </div>

      {job && (
        <div className="card" style={{ marginTop: 18 }}>
          <h3 style={{ marginTop: 0 }}>
            Import job #{job.id} — <span className="badge">{job.status}</span>
          </h3>
          <p>
            Processed {job.processed_rows}/{job.total_rows} · inserted{" "}
            <b>{job.inserted}</b> · updated <b>{job.updated}</b>
          </p>
          {job.status === "done" && (
            <div className="ok">
              Import complete — {job.inserted} inserted, {job.updated} updated
              {job.errors?.length ? `, ${job.errors.length} skipped` : ""}.
            </div>
          )}
          {job.errors?.length > 0 && (
            <details style={{ marginTop: 8 }}>
              <summary className="error">{job.errors.length} row error(s)</summary>
              <ul>
                {job.errors.slice(0, 50).map((e: any, i: number) => (
                  <li key={i} className="muted">
                    Row {e.row ?? "?"}: {e.error}
                  </li>
                ))}
              </ul>
            </details>
          )}
          <button
            className="btn ghost sm"
            style={{ marginTop: 12 }}
            disabled={busy}
            onClick={() => {
              setJob(null);
              setFile(null);
              if (fileRef.current) fileRef.current.value = "";
            }}
          >
            Import another file
          </button>
        </div>
      )}
    </div>
  );
}
