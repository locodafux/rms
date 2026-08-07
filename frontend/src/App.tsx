import { Link, NavLink, Navigate, Route, Routes, useLocation } from "react-router-dom";
import { useAuth } from "./auth";
import Login from "./pages/Login";
import Dashboard from "./pages/Dashboard";
import Records from "./pages/Records";
import RecordDetail from "./pages/RecordDetail";
import ImportPage from "./pages/ImportPage";
import Files from "./pages/Files";
import History from "./pages/History";
import ExportPage from "./pages/ExportPage";
import Users from "./pages/Users";
import ChatBox from "./ChatBox";
import { getTheme, setTheme, Theme, THEMES } from "./theme";
import { useState } from "react";

const ROLE_LABEL: Record<string, string> = {
  admin: "Admin",
  document_compliance: "Doc Compliance",
  scanning: "Scanning",
  filing: "Filing",
  notary: "Notary",
};

const cap = (s: string) => s[0].toUpperCase() + s.slice(1);

const THEME_ICON: Record<Theme, string> = { system: "◐", light: "☀", dark: "☾" };

/* One button cycling System → Light → Dark. Keeps state only because the icon
   has to track the choice; localStorage stays the source of truth. */
function ThemeToggle() {
  const [theme, setLocal] = useState(getTheme);
  const next = THEMES[(THEMES.indexOf(theme) + 1) % THEMES.length];
  return (
    <button
      className="theme-toggle"
      aria-label={`Color theme: ${cap(theme)}. Switch to ${cap(next)}.`}
      title={`Theme: ${cap(theme)} — click for ${cap(next)}`}
      onClick={() => {
        setTheme(next);
        setLocal(next);
      }}
    >
      {THEME_ICON[theme]}
    </button>
  );
}

function Shell() {
  const { user, schema, logout } = useAuth();
  const loc = useLocation();
  const [navOpen, setNavOpen] = useState(() => localStorage.getItem("dt_nav") !== "0");
  if (!user) return null;

  function toggleNav() {
    setNavOpen((open) => {
      localStorage.setItem("dt_nav", open ? "0" : "1");
      return !open;
    });
  }

  const initials = (user.full_name ?? user.email)
    .split(/[\s@.]+/)
    .slice(0, 2)
    .map((s) => s[0]?.toUpperCase())
    .join("");

  // NavLink ignores the query string, so the /records views are matched by hand.
  function navCls(view: string) {
    let current = new URLSearchParams(loc.search).get("view") ?? "filing";
    if (current === "document_compliance") current = "compliance";
    const active = loc.pathname === "/records" && current === view;
    return `navlink ${active ? "active" : ""}`;
  }

  return (
    <div className={`shell ${navOpen ? "" : "nav-closed"}`}>
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-name">Records Management</div>
        </div>
        <NavLink to="/" end className="navlink">
          Dashboard
        </NavLink>
        <Link to="/records?view=compliance" className={navCls("compliance")}>
          Compliance
        </Link>
        <Link to="/records?view=scanning" className={navCls("scanning")}>
          Scanning
        </Link>
        <Link to="/records?view=notary" className={navCls("notary")}>
          Notary
        </Link>
        <Link to="/records?view=filing" className={navCls("filing")}>
          Filing
        </Link>
        {schema?.can_import && (
          <NavLink to="/import" className="navlink">
            Import
          </NavLink>
        )}
        <NavLink to="/history" className="navlink">
          History
        </NavLink>
        {schema?.can_import && (
          <NavLink to="/files" className="navlink">
            Files
          </NavLink>
        )}
        {schema?.can_export && (
          <NavLink to="/export" className="navlink">
            Export
          </NavLink>
        )}
        {schema?.can_manage_users && (
          <NavLink to="/users" className="navlink">
            Users
          </NavLink>
        )}
      </aside>
      <div className="main">
        <header className="topbar">
          <button
            className="navtoggle"
            onClick={toggleNav}
            aria-expanded={navOpen}
            aria-label={navOpen ? "Hide menu" : "Show menu"}
            title="Toggle menu"
          >
            {navOpen ? "«" : "»"}
          </button>
          <div className="spacer" />
          <div className="userbox">
            <span className="rolebadge">{ROLE_LABEL[user.role ?? ""] ?? "No role"}</span>
            <div className="avatar">{initials}</div>
            <ThemeToggle />
            <button className="btn ghost sm" onClick={logout}>
              Logout
            </button>
          </div>
        </header>
        <div className="content">
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/records" element={<Records />} />
            <Route path="/records/new" element={<RecordDetail mode="new" />} />
            <Route path="/records/:id" element={<RecordDetail mode="edit" />} />
            <Route path="/history" element={<History />} />
            {schema?.can_import && <Route path="/import" element={<ImportPage />} />}
            {schema?.can_import && <Route path="/files" element={<Files />} />}
            {schema?.can_export && <Route path="/export" element={<ExportPage />} />}
            {schema?.can_manage_users && <Route path="/users" element={<Users />} />}
            <Route path="*" element={<Navigate to="/" />} />
          </Routes>
        </div>
      </div>
      {/* Inside Shell, not main.tsx: chat needs the logged-in user, and it must
          not show on the login / awaiting-approval screens. */}
      <ChatBox />
    </div>
  );
}

export default function App() {
  const { user, loading } = useAuth();
  if (loading)
    return (
      <div className="auth-wrap">
        <div className="muted">Loading…</div>
      </div>
    );
  if (!user) return <Login />;
  if (!user.role)
    return (
      <div className="auth-wrap">
        <div className="auth-card">
          <h1>Awaiting approval</h1>
          <p className="muted">
            Your account <b>{user.email}</b> is registered but not yet activated.
            An administrator must approve it and assign a role before you can
            continue.
          </p>
          <button className="btn" onClick={() => window.location.reload()}>
            Refresh
          </button>
        </div>
      </div>
    );
  return <Shell />;
}
