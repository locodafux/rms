import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, ApiError } from "../api";
import { useAuth } from "../auth";
import type { HistoryPage } from "../types";

const WINDOWS = [
  { days: 30, label: "Last 30 days" },
  { days: 90, label: "Last 90 days" },
  { days: 365, label: "Last year" },
  { days: 0, label: "All time" },
];
const KINDS = ["filed", "pullout", "scanned"];
const PAGE_SIZE = 50;

/** Every imported filing / pullout / scanning event, newest first. Scoped per
 *  record by the server, so a role sees the same columns it sees on the record. */
export default function History() {
  const { schema } = useAuth();
  const [search, setSearch] = useState("");
  const [query, setQuery] = useState("");   // committed search — typing doesn't refetch
  const [days, setDays] = useState(90);
  const [kind, setKind] = useState("");
  const [page, setPage] = useState(1);
  const [data, setData] = useState<HistoryPage | null>(null);
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    setBusy(true);
    api
      .history({ search: query, days, kind, page, page_size: PAGE_SIZE })
      .then(setData)
      .catch((e) => setMsg((e as ApiError).message))
      .finally(() => setBusy(false));
  }, [query, days, kind, page]);

  // Any filter change invalidates the current page number.
  function set<T>(fn: (v: T) => void, v: T) {
    fn(v);
    setPage(1);
  }

  const label = (k: string) =>
    schema?.fields.find((f) => f.key === k)?.label ?? k;
  const pages = data ? Math.ceil(data.total / data.page_size) : 0;

  return (
    <div>
      <div className="page-head">
        <h1>History</h1>
      </div>
      <p className="muted" style={{ marginTop: 0 }}>
        Every filing, pullout and scanning event captured from the team workbooks —
        one row per event, so a unit that was filed, relocated and pulled out shows
        all of it.
      </p>

      <div className="card" style={{ marginBottom: 14 }}>
        <form
          className="history-bar"
          onSubmit={(e) => {
            e.preventDefault();
            set(setQuery, search);
          }}
        >
          <input
            style={{ flex: 1, minWidth: 220 }}
            placeholder="Search unit code, officer, documents, cabinet, remarks…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
          <select value={days} onChange={(e) => set(setDays, Number(e.target.value))}>
            {WINDOWS.map((w) => (
              <option key={w.days} value={w.days}>
                {w.label}
              </option>
            ))}
          </select>
          <select value={kind} onChange={(e) => set(setKind, e.target.value)}>
            <option value="">All events</option>
            {KINDS.map((k) => (
              <option key={k} value={k}>
                {k}
              </option>
            ))}
          </select>
          <button className="btn sm" type="submit" disabled={busy}>
            Search
          </button>
          {query && (
            <button
              className="btn ghost sm"
              type="button"
              onClick={() => {
                setSearch("");
                set(setQuery, "");
              }}
            >
              Clear
            </button>
          )}
        </form>
      </div>

      {msg && <div className="error" style={{ marginBottom: 10 }}>{msg}</div>}
      <p className="muted">
        {busy ? "Searching…" : `${data?.total.toLocaleString() ?? 0} event(s)`}
        {days === 0 && " · includes events with no date"}
      </p>

      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Date</th>
              <th>Unit</th>
              <th>Event</th>
              <th>Details</th>
            </tr>
          </thead>
          <tbody>
            {(data?.items ?? []).map((ev) => (
              <tr key={ev.id}>
                <td className="muted">{ev.event_date ?? "no date"}</td>
                <td>
                  <Link to={`/records/${ev.record_id}`}>{ev.unit_code}</Link>
                </td>
                <td>
                  <span className="badge">{ev.kind}</span>
                </td>
                <td>
                  {Object.entries(ev.data).map(([k, v]) => (
                    <div key={k}>
                      <span className="muted">{label(k)}:</span> {String(v)}
                    </div>
                  ))}
                </td>
              </tr>
            ))}
            {!busy && data?.items.length === 0 && (
              <tr>
                <td colSpan={4} className="muted">
                  Nothing matches — try a longer window or a different term.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {pages > 1 && (
        <div className="history-bar" style={{ marginTop: 12 }}>
          <button
            className="btn ghost sm"
            disabled={page <= 1 || busy}
            onClick={() => setPage((p) => p - 1)}
          >
            ← Newer
          </button>
          <span className="muted">
            Page {page} of {pages}
          </span>
          <button
            className="btn ghost sm"
            disabled={page >= pages || busy}
            onClick={() => setPage((p) => p + 1)}
          >
            Older →
          </button>
        </div>
      )}
    </div>
  );
}
