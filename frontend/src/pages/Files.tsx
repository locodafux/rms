import { useEffect, useState } from "react";
import { api, ApiError } from "../api";
import type { ImportFile } from "../types";

/** Every spreadsheet ever uploaded through Import, newest first. Admin sees the
 *  whole team's; everyone else sees their own. */
export default function Files() {
  const [files, setFiles] = useState<ImportFile[]>([]);
  const [msg, setMsg] = useState("");
  const [open, setOpen] = useState<number | null>(null);

  useEffect(() => {
    api.imports().then(setFiles).catch((e) => setMsg((e as ApiError).message));
  }, []);

  async function get(f: ImportFile) {
    setMsg("");
    try {
      await api.download(`/api/import/${f.id}/download`, f.filename);
    } catch (e) {
      setMsg((e as ApiError).message);
    }
  }

  return (
    <div>
      <div className="page-head">
        <h1>Files</h1>
      </div>
      <p className="muted" style={{ marginTop: 0 }}>
        {files.length} upload(s). The original file is kept, so you can always check
        what a value in a record came from.
      </p>
      {msg && <div className="error" style={{ marginBottom: 10 }}>{msg}</div>}
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>File</th>
              <th>Uploaded by</th>
              <th>When</th>
              <th>Status</th>
              <th>Rows</th>
              <th>Inserted</th>
              <th>Updated</th>
              <th>Notes</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {files.map((f) => {
              const rowErrors = f.errors.filter((e) => e.row != null);
              const notes = f.errors.filter((e) => e.row == null);
              return [
                <tr key={f.id}>
                  <td>
                    <b>{f.filename}</b>
                  </td>
                  <td>
                    {f.uploaded_by ?? "—"}{" "}
                    {f.uploaded_by_role && (
                      <span className="badge">{f.uploaded_by_role.replace(/_/g, " ")}</span>
                    )}
                  </td>
                  <td className="muted">{new Date(f.created_at).toLocaleString()}</td>
                  <td>
                    <span className="badge">{f.status}</span>
                  </td>
                  <td>{f.total_rows}</td>
                  <td>{f.inserted}</td>
                  <td>{f.updated}</td>
                  <td>
                    {f.errors.length ? (
                      <button className="btn ghost sm" onClick={() => setOpen(open === f.id ? null : f.id)}>
                        {notes.length} note(s)
                        {rowErrors.length ? `, ${rowErrors.length} row error(s)` : ""}
                      </button>
                    ) : (
                      <span className="muted">—</span>
                    )}
                  </td>
                  <td>
                    {f.file_available ? (
                      <button className="btn ghost sm" onClick={() => get(f)}>
                        ⭳ Download
                      </button>
                    ) : (
                      <span className="muted">not on disk</span>
                    )}
                  </td>
                </tr>,
                open === f.id && (
                  <tr key={`${f.id}-detail`}>
                    <td colSpan={9}>
                      {notes.map((e, i) => (
                        <p key={i} className="muted" style={{ margin: "2px 0" }}>
                          {e.error}
                        </p>
                      ))}
                      <ul style={{ marginBottom: 0 }}>
                        {rowErrors.slice(0, 50).map((e, i) => (
                          <li key={i} className="muted">
                            {e.sheet ? `${e.sheet} row ${e.row}` : `Row ${e.row}`}: {e.error}
                          </li>
                        ))}
                      </ul>
                    </td>
                  </tr>
                ),
              ];
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
