import { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";
import type { RecordItem } from "../types";

// The prototype's tabs, recreated as filtered column views over one table.
// Key order drives the in-page tab strip; keep it matching the sidebar.
const VIEWS = {
  compliance: {
    label: "Document Compliance",
    cols: [
      ["unit_code", "Unit Code"],
      ["company", "Company"],
      ["doc_compliance_officer", "Compliance Officer"],
      ["spa_status", "SPA Status"],
      ["date_received_from_sas", "Received from SAS"],
      ["cleared_date", "Cleared Date"],
    ],
  },
  scanning: {
    label: "Scanning of Document Entry",
    cols: [
      ["unit_code", "Unit Code"],
      ["company", "Company"],
      ["docket_scanning_status", "Scanning Status"],
      ["scanning_ao", "Scanning AO"],
      ["date_received_scanning", "Date Received"],
      ["date_scanned", "Date Scanned"],
    ],
  },
  notary: {
    label: "Notary Status",
    cols: [
      ["unit_code", "Unit Code"],
      ["company", "Company"],
      ["notary_status", "Notary Status"],
      ["notary_account_officer", "Account Officer"],
      ["ncpa_notary_date", "NCPA Notary Date"],
      ["notarized_by", "Notarized By"],
    ],
  },
  filing: {
    label: "Filing System Entry",
    cols: [
      ["unit_code", "Unit Code"],
      ["company", "Company"],
      ["filing_archiving_officer", "Filing Officer"],
      ["file_status", "File Status"],
      ["date_filed", "Date Filed"],
      ["filing_location", "Location"],
    ],
  },
} as const;

export default function Records() {
  const nav = useNavigate();
  const { schema } = useAuth();
  const [params, setParams] = useSearchParams();
  // View lives in the URL, set by the sidebar links and the compliance tab strip.
  // The dashboard deep-links by role key, and the compliance role is named
  // "document_compliance" server-side — alias it here so it doesn't fall through
  // to the default view.
  const raw = params.get("view") ?? "";
  const v = raw === "document_compliance" ? "compliance" : raw;
  const view: keyof typeof VIEWS = v in VIEWS ? (v as keyof typeof VIEWS) : "filing";
  const [page, setPage] = useState(1);
  const [pageSize] = useState(25);
  const [data, setData] = useState<{ items: RecordItem[]; total: number }>({
    items: [],
    total: 0,
  });
  const [sort, setSort] = useState<string>("unit_code");
  const [order, setOrder] = useState<"asc" | "desc">("asc");
  const [showArchived, setShowArchived] = useState(false);
  // Column filters live in the URL, not in state: the dashboard's status breakdown
  // deep-links into a filtered list, switching views clears them for free, and a
  // filtered list is shareable. Split on the first ":" only — values contain them.
  const colFilters: Record<string, string> = Object.fromEntries(
    params
      .getAll("filter")
      .map((f) => f.split(/:(.*)/s).slice(0, 2))
      .filter(([k, v]) => k && v),
  );
  const [openCol, setOpenCol] = useState<string | null>(null);
  const search = params.get("search") ?? "";
  const [q, setQ] = useState(search);

  // Typing is local; the URL (and therefore the fetch) only catches up once you pause.
  useEffect(() => setQ(search), [search]);
  useEffect(() => {
    if (q === search) return;
    const t = setTimeout(() => {
      if (q) params.set("search", q);
      else params.delete("search");
      setParams(params, { replace: true });
      setPage(1);
    }, 250);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [q]);

  // enum options per field key, so status columns get a dropdown of choices.
  const optionsByKey: Record<string, string[]> = {};
  const ownerByKey: Record<string, string> = {};
  for (const f of schema?.fields ?? []) {
    if (f.type === "enum") optionsByKey[f.key] = f.options;
    ownerByKey[f.key] = f.owner;
  }

  /** Cell text. A record this role hasn't worked yet arrives without the other
   *  sections' values — show a lock, so withheld never reads as "not done yet". */
  function cell(r: RecordItem, key: string): string {
    const owner = ownerByKey[key];
    if (r.restricted && owner !== "base" && owner !== schema?.role) return "🔒";
    return String(r.data[key] ?? "—");
  }

  function toggleSort(key: string) {
    if (sort === key) {
      setOrder((o) => (o === "asc" ? "desc" : "asc"));
    } else {
      setSort(key);
      setOrder("asc");
    }
    setPage(1);
  }

  function setColFilter(key: string, value: string) {
    const next = { ...colFilters };
    if (value.trim()) next[key] = value.trim();
    else delete next[key];
    params.delete("filter");
    for (const [k, v] of Object.entries(next)) params.append("filter", `${k}:${v}`);
    setParams(params, { replace: true });
    setPage(1);
  }

  function load() {
    const qs = new URLSearchParams();
    qs.set("page", String(page));
    qs.set("page_size", String(pageSize));
    qs.set("sort", sort);
    qs.set("order", order);
    if (search) qs.set("search", search);
    if (showArchived) qs.set("include_archived", "true");
    for (const [k, v] of Object.entries(colFilters)) qs.append("filter", `${k}:${v}`);
    api.records(`?${qs.toString()}`).then(setData);
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page, view, search, showArchived, sort, order, JSON.stringify(colFilters)]);

  const cols = VIEWS[view].cols;
  const pages = Math.max(1, Math.ceil(data.total / pageSize));

  return (
    <div>
      <div className="page-head">
        <h1>{VIEWS[view].label}</h1>
        <div className="spacer" />
        {schema?.can_create && (
          <button className="btn" onClick={() => nav("/records/new")}>
            + New Record
          </button>
        )}
      </div>

      <div className="row" style={{ marginBottom: 16 }}>
        <div className="search">
          <input
            placeholder={`Search ${VIEWS[view].label}…`}
            value={q}
            onChange={(e) => setQ(e.target.value)}
          />
        </div>
        <label className="row muted" style={{ fontSize: 13 }}>
          <input
            type="checkbox"
            checked={showArchived}
            onChange={(e) => setShowArchived(e.target.checked)}
          />
          Show archived
        </label>
      </div>

      {openCol && (
        <div
          style={{ position: "fixed", inset: 0, zIndex: 5 }}
          onClick={() => setOpenCol(null)}
        />
      )}

      <div className="table-wrap rec-table">
        <table>
          <thead>
            <tr>
              {cols.map(([key, label]) => {
                const active = !!colFilters[key];
                return (
                  <th key={key} style={{ position: "relative", userSelect: "none" }}>
                    <span
                      onClick={() => toggleSort(key)}
                      style={{ cursor: "pointer" }}
                      title="Click to sort"
                    >
                      {label}
                      <span style={{ marginLeft: 6, opacity: sort === key ? 1 : 0.25 }}>
                        {sort === key ? (order === "asc" ? "▲" : "▼") : "↕"}
                      </span>
                    </span>
                    <button
                      className="col-filter-btn"
                      title="Filter this column"
                      style={{ color: active ? "var(--brand-ink)" : "var(--muted)" }}
                      onClick={(e) => {
                        e.stopPropagation();
                        setOpenCol(openCol === key ? null : key);
                      }}
                    >
                      {active ? "▼●" : "▾"}
                    </button>

                    {openCol === key && (
                      <div className="col-pop" onClick={(e) => e.stopPropagation()}>
                        {optionsByKey[key] ? (
                          <select
                            autoFocus
                            value={colFilters[key] ?? ""}
                            onChange={(e) => setColFilter(key, e.target.value)}
                          >
                            <option value="">— all —</option>
                            {optionsByKey[key].map((o) => (
                              <option key={o} value={o}>
                                {o}
                              </option>
                            ))}
                          </select>
                        ) : (
                          <input
                            autoFocus
                            placeholder={`Search ${label}…`}
                            value={colFilters[key] ?? ""}
                            onChange={(e) => setColFilter(key, e.target.value)}
                          />
                        )}
                        <div className="row" style={{ marginTop: 8, justifyContent: "space-between" }}>
                          <button
                            className="btn ghost sm"
                            onClick={() => setColFilter(key, "")}
                          >
                            Clear
                          </button>
                          <button className="btn sm" onClick={() => setOpenCol(null)}>
                            Done
                          </button>
                        </div>
                      </div>
                    )}
                  </th>
                );
              })}
              <th></th>
            </tr>
          </thead>
          <tbody>
            {data.items.map((r) => (
              <tr
                key={r.id}
                style={{ cursor: "pointer", opacity: r.is_archived ? 0.55 : 1 }}
                onClick={() => nav(`/records/${r.id}`)}
              >
                {cols.map(([key]) => (
                  <td key={key}>
                    {key === "unit_code" ? (
                      <b>{r.unit_code}</b>
                    ) : key.endsWith("status") && r.data[key] ? (
                      <span className="badge">{r.data[key]}</span>
                    ) : (
                      cell(r, key)
                    )}
                  </td>
                ))}
                <td className="muted">›</td>
              </tr>
            ))}
            {data.items.length === 0 && (
              <tr>
                <td colSpan={cols.length + 1} className="muted">
                  No matching records.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {/* Phone rendering of the same rows — CSS swaps this for the table at 720px.
          ponytail: sorting and per-column filters live in the <th>s, so they stay
          desktop-only; tabs + search + archived toggle still work here. */}
      <ul className="rec-cards">
        {data.items.map((r) => (
          <li
            key={r.id}
            style={{ opacity: r.is_archived ? 0.55 : 1 }}
            onClick={() => nav(`/records/${r.id}`)}
          >
            <div className="rec-unit">
              {r.unit_code}
              <span className="muted">›</span>
            </div>
            {cols.slice(1).map(([key, label]) => (
              <div className="rec-row" key={key}>
                <span className="muted">{label}</span>
                {key.endsWith("status") && r.data[key] ? (
                  <span className="badge">{r.data[key]}</span>
                ) : (
                  <span>{cell(r, key)}</span>
                )}
              </div>
            ))}
          </li>
        ))}
        {data.items.length === 0 && <li className="muted">No matching records.</li>}
      </ul>

      <div className="pagination">
        <span className="muted">
          {data.total} record{data.total === 1 ? "" : "s"} · page {page}/{pages}
        </span>
        <button
          className="btn ghost sm"
          disabled={page <= 1}
          onClick={() => setPage((p) => p - 1)}
        >
          Prev
        </button>
        <button
          className="btn ghost sm"
          disabled={page >= pages}
          onClick={() => setPage((p) => p + 1)}
        >
          Next
        </button>
      </div>
    </div>
  );
}
