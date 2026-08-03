import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";
import type { Bucket, RecordItem, RoleStat, Stats } from "../types";

// CVD-safe status palette (validated light-mode): done / incoming / pending.
const C = {
  done: "#2f9e44",
  incoming: "#4c6ef5",
  pending: "#c77800",
};

const BUCKETS: { key: Bucket; label: string; color: string }[] = [
  { key: "done", label: "Done", color: C.done },
  { key: "incoming", label: "Incoming", color: C.incoming },
  { key: "pending", label: "Pending", color: C.pending },
];

/** Drill-down for one role: the raw status values behind each bucket. Rows link
 *  to that value filtered on the records list. "(not set)" is the server's label
 *  for a blank status — the records filter matches substrings and can't express
 *  "is empty", so those rows stay unlinked. */
function RoleSummary({ s, onClose }: { s: RoleStat; onClose: () => void }) {
  const nav = useNavigate();
  const total = Math.max(s.total, 1);

  useEffect(() => {
    const esc = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", esc);
    return () => window.removeEventListener("keydown", esc);
  }, [onClose]);

  function open(value: string) {
    nav(`/records?view=${s.role}&filter=${encodeURIComponent(`${s.field}:${value}`)}`);
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div
        className="modal"
        role="dialog"
        aria-modal="true"
        aria-label={`${s.label} status breakdown`}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="modal-head">
          <div>
            <h3 style={{ margin: 0 }}>{s.label}</h3>
            <div className="muted" style={{ fontSize: 12 }}>
              {s.total.toLocaleString()} records · <code>{s.field}</code>
            </div>
          </div>
          <button className="chat-close" onClick={onClose} aria-label="Close">
            ✕
          </button>
        </div>

        <div className="modal-body">
          {BUCKETS.map(({ key, label, color }) => {
            const rows = s.breakdown[key] ?? [];
            const n = s[key];
            return (
              <div key={key} className="bd-group">
                <div className="bd-head">
                  <span className="legend-dot" style={{ background: color }} />
                  <span className="bd-title">{label}</span>
                  <span className="legend-n">
                    {n.toLocaleString()}{" "}
                    <span className="muted">({Math.round((100 * n) / total)}%)</span>
                  </span>
                </div>
                {rows.length === 0 && <div className="bd-empty muted">None</div>}
                {rows.map((r) => {
                  const blank = r.value === "(not set)";
                  return (
                    <button
                      key={r.value}
                      className="bd-row"
                      disabled={blank}
                      title={blank ? "Blank values can't be filtered" : `Show these ${r.n} records`}
                      onClick={() => open(r.value)}
                    >
                      <span className="bd-val">{r.value}</span>
                      <span className="bd-n">{r.n.toLocaleString()}</span>
                      <span className="bd-bar">
                        <span style={{ width: `${(r.n / Math.max(n, 1)) * 100}%`, background: color }} />
                      </span>
                      <span className="bd-go">{blank ? "" : "›"}</span>
                    </button>
                  );
                })}
              </div>
            );
          })}
        </div>

        <div className="modal-foot">
          <button className="btn ghost sm" onClick={onClose}>
            Close
          </button>
          <button className="btn sm" onClick={() => nav(`/records?view=${s.role}`)}>
            Open {s.label} list →
          </button>
        </div>
      </div>
    </div>
  );
}

// r chosen so the circumference is exactly 100 — every dash length is then literally
// the percentage, and the whole donut needs no trigonometry.
const R = 15.915;
const GAP = 1; // ≈2px at the rendered size: the surface gap between arcs.
// A non-zero bucket always gets at least this much ring. Without it, "Incoming 1"
// of 5,993 is a 0.06px arc — invisible, so the reader concludes zero, which is a
// worse lie than a slightly fat sliver. Lengths are renormalised after flooring so
// the ring still closes at exactly 100 and no arc overlaps its neighbour.
const MIN_ARC = 1.2;

/** SVG, not a conic-gradient: arcs need their own hit targets to carry a tooltip,
 *  and real gaps rather than painted-on ones. Segments run done → incoming →
 *  pending, the validated adjacency order. */
function Donut({ s }: { s: RoleStat }) {
  const total = Math.max(s.total, 1);
  const arcs = BUCKETS.map((b) => ({ ...b, n: s[b.key] })).filter((a) => a.n > 0);
  const floored = arcs.map((a) => Math.max((a.n / total) * 100, MIN_ARC));
  const scale = 100 / floored.reduce((x, y) => x + y, 0);
  let offset = 0;

  return (
    <div className="donut">
      <svg viewBox="0 0 42 42" aria-hidden="true">
        <circle className="donut-track" cx="21" cy="21" r={R} />
        {arcs.map((a, i) => {
          const len = floored[i] * scale;
          // A lone arc must close the ring; with neighbours, carve the gap out of
          // each. Never draw longer than the slot, or arcs overlap.
          const dash = arcs.length > 1 ? Math.max(len - GAP, 0.4) : len;
          const start = offset;
          offset += len;
          return (
            <circle
              key={a.key}
              cx="21"
              cy="21"
              r={R}
              stroke={a.color}
              strokeDasharray={`${dash} ${100 - dash}`}
              strokeDashoffset={-start}
              transform="rotate(-90 21 21)"
            >
              <title>{`${a.label}: ${a.n.toLocaleString()} (${Math.round((100 * a.n) / total)}%)`}</title>
            </circle>
          );
        })}
      </svg>
      <div className="donut-hole">
        <div className="donut-pct">{s.done_pct}%</div>
        <div className="donut-sub">done</div>
      </div>
    </div>
  );
}

function LegendRow({ color, label, n, total }: { color: string; label: string; n: number; total: number }) {
  const pct = total ? Math.round((100 * n) / total) : 0;
  return (
    <div className="legend-row">
      <span className="legend-dot" style={{ background: color }} />
      <span className="legend-label">{label}</span>
      <span className="legend-n">
        {n.toLocaleString()} <span className="muted">({pct}%)</span>
      </span>
    </div>
  );
}

/** A real <button>, so Enter/Space work without a hand-rolled key handler. The
 *  aria-label carries every count, so nothing is gated behind the arc tooltips. */
function RoleCard({ s, onOpen }: { s: RoleStat; onOpen: () => void }) {
  return (
    <button
      className="card role-card"
      onClick={onOpen}
      aria-label={
        `${s.label}: ${s.done_pct}% done. ` +
        BUCKETS.map((b) => `${s[b.key].toLocaleString()} ${b.label.toLowerCase()}`).join(", ") +
        ` of ${s.total.toLocaleString()}. Open status breakdown.`
      }
    >
      {/* A span, not an <h3>: headings aren't phrasing content and don't belong
          inside a button. */}
      <span className="role-title">{s.label}</span>
      <div className="role-card-body">
        <Donut s={s} />
        <div className="legend">
          {BUCKETS.map((b) => (
            <LegendRow key={b.key} color={b.color} label={b.label} n={s[b.key]} total={s.total} />
          ))}
        </div>
      </div>
    </button>
  );
}

export default function Dashboard() {
  const { schema, user } = useAuth();
  const canViewArchive = user?.role === "admin" || user?.role === "filing";
  const nav = useNavigate();
  const [stats, setStats] = useState<Stats | null>(null);
  const [recent, setRecent] = useState<RecordItem[]>([]);
  const [openRole, setOpenRole] = useState<RoleStat | null>(null);

  useEffect(() => {
    api.stats().then(setStats);
    api.records("?page=1&page_size=8&sort=unit_code&order=asc").then((p) =>
      setRecent(p.items),
    );
  }, []);

  const overallDone =
    stats && stats.roles.length
      ? Math.round(
          stats.roles.reduce((a, r) => a + r.done_pct, 0) / stats.roles.length,
        )
      : 0;

  return (
    <div>
      <div className="page-head">
        <h1>Dashboard</h1>
        <div className="spacer" />
        {schema?.can_create && (
          <button className="btn" onClick={() => nav("/records/new")}>
            + New Record
          </button>
        )}
      </div>

      <div className="stat-row">
        <div className="stat">
          <div className="n">{(stats?.total_records ?? 0).toLocaleString()}</div>
          <div className="l">Total records</div>
        </div>
        {/* The value stays in ink; the swatch beside the label carries identity,
            keyed to the same three colours as the bars below. */}
        <div className="stat">
          <div className="n">{overallDone}%</div>
          <div className="l">
            <span className="legend-dot" style={{ background: C.done }} />
            Avg. completion across roles
          </div>
        </div>
        <div className="stat">
          <div className="n">
            {(stats?.roles.reduce((a, r) => a + r.incoming, 0) ?? 0).toLocaleString()}
          </div>
          <div className="l">
            <span className="legend-dot" style={{ background: C.incoming }} />
            Incoming (queued to a team)
          </div>
        </div>
        <div className="stat">
          <div className="n">
            {(stats?.roles.reduce((a, r) => a + r.pending, 0) ?? 0).toLocaleString()}
          </div>
          <div className="l">
            <span className="legend-dot" style={{ background: C.pending }} />
            Pending (not yet reached)
          </div>
        </div>
      </div>

      <h2 style={{ fontSize: 16, margin: "6px 2px 12px" }}>
        Workload by role{" "}
        <span className="muted" style={{ fontWeight: 400, fontSize: 13 }}>
          — click a card for the status breakdown
        </span>
      </h2>
      <div className="role-grid">
        {stats?.roles.map((s) => (
          <RoleCard key={s.role} s={s} onOpen={() => setOpenRole(s)} />
        ))}
        {!stats && <div className="muted">Loading…</div>}
      </div>
      {openRole && <RoleSummary s={openRole} onClose={() => setOpenRole(null)} />}

      {canViewArchive && (
      <div className="card" style={{ marginTop: 22 }}>
        <h3 style={{ marginTop: 0 }}>Archive</h3>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Unit Code</th>
                <th>Company</th>
                <th>Status</th>
                <th>Days</th>
              </tr>
            </thead>
            <tbody>
              {stats?.soon_to_archive.map((r) => (
                <tr key={r.id} style={{ cursor: "pointer" }} onClick={() => nav(`/records/${r.id}`)}>
                  <td>
                    <b>{r.unit_code}</b>
                  </td>
                  <td>{r.company ?? "—"}</td>
                  <td>
                    <span className="badge">{r.arch_accounts_status}</span>
                  </td>
                  <td style={r.days <= 0 ? { color: "var(--danger)", fontWeight: 700 } : undefined}>
                    {r.days > 0 ? `${r.days}d left` : `${-r.days}d overdue`}
                  </td>
                </tr>
              ))}
              {(!stats || stats.soon_to_archive.length === 0) && (
                <tr>
                  <td colSpan={4} className="muted">
                    No accounts currently counting down to archive.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
      )}

      <div className="card" style={{ marginTop: 22 }}>
        <h3 style={{ marginTop: 0 }}>Recently updated</h3>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Unit Code</th>
                <th>Company</th>
                <th>Unit Status</th>
                <th>File Status</th>
                <th>Updated</th>
              </tr>
            </thead>
            <tbody>
              {recent.map((r) => (
                <tr key={r.id} style={{ cursor: "pointer" }} onClick={() => nav(`/records/${r.id}`)}>
                  <td>
                    <b>{r.unit_code}</b>
                  </td>
                  <td>{r.data.company ?? "—"}</td>
                  <td>{r.data.unit_status ? <span className="badge">{r.data.unit_status}</span> : "—"}</td>
                  <td>{r.data.file_status ?? "—"}</td>
                  <td className="muted">{new Date(r.updated_at).toLocaleDateString()}</td>
                </tr>
              ))}
              {recent.length === 0 && (
                <tr>
                  <td colSpan={5} className="muted">
                    No records yet.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
