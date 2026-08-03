import { useEffect, useState } from "react";
import { api, ApiError } from "../api";

export default function ExportPage() {
  const [fmt, setFmt] = useState("xlsx");
  const [includeArchived, setIncludeArchived] = useState(false);
  const [job, setJob] = useState<any>(null);
  const [msg, setMsg] = useState("");

  async function start() {
    setMsg("");
    try {
      setJob(await api.startExport(fmt, includeArchived));
    } catch (e) {
      setMsg((e as ApiError).message);
    }
  }

  useEffect(() => {
    if (!job || job.status === "done" || job.status === "error") return;
    const t = setInterval(async () => setJob(await api.exportStatus(job.id)), 800);
    return () => clearInterval(t);
  }, [job]);

  return (
    <div>
      <div className="page-head">
        <h1>Export</h1>
      </div>
      <div className="card" style={{ maxWidth: 480 }}>
        <p className="muted" style={{ marginTop: 0 }}>
          Generate a full spreadsheet of all records (all 120 columns).
        </p>
        <div className="field" style={{ marginBottom: 12 }}>
          <label>Format</label>
          <select value={fmt} onChange={(e) => setFmt(e.target.value)}>
            <option value="xlsx">Excel (.xlsx)</option>
            <option value="csv">CSV (.csv)</option>
          </select>
        </div>
        <label className="row muted" style={{ marginBottom: 14 }}>
          <input
            type="checkbox"
            checked={includeArchived}
            onChange={(e) => setIncludeArchived(e.target.checked)}
          />
          Include archived records
        </label>
        <div>
          <button className="btn" onClick={start}>
            Generate export
          </button>
        </div>
        {msg && <div className="error" style={{ marginTop: 10 }}>{msg}</div>}
        {job && (
          <div style={{ marginTop: 16 }}>
            Job #{job.id}: <span className="badge">{job.status}</span>
            {job.status === "done" && (
              <p style={{ marginTop: 10 }}>
                <a className="btn sm" href={api.exportDownloadUrl(job.id)}>
                  ⭳ Download ({job.row_count} rows)
                </a>
              </p>
            )}
            {job.status === "error" && <div className="error">{job.error}</div>}
          </div>
        )}
      </div>
    </div>
  );
}
