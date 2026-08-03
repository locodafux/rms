import { useState } from "react";
import { useAuth } from "../auth";
import { api, ApiError } from "../api";

export default function Login() {
  const { login } = useAuth();
  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [fullName, setFullName] = useState("");
  const [msg, setMsg] = useState<{ err?: string; ok?: string }>({});
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setMsg({});
    setBusy(true);
    try {
      if (mode === "login") {
        await login(email, password);
      } else {
        await api.register({ email, password, full_name: fullName || undefined });
        setMsg({
          ok: "Registered. An admin must activate your account before you can log in.",
        });
        setMode("login");
      }
    } catch (e) {
      setMsg({ err: (e as ApiError).message || "Something went wrong." });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="auth-wrap">
      <form className="auth-card" onSubmit={submit}>
        <img className="auth-logo" src="/logo-wordmark.svg" alt="RMS — Records Management System" />
        <p className="muted" style={{ marginTop: 0 }}>
          {mode === "login" ? "Sign in to continue" : "Create an account"}
        </p>
        {mode === "register" && (
          <div className="field">
            <label>Full name</label>
            <input value={fullName} onChange={(e) => setFullName(e.target.value)} />
          </div>
        )}
        <div className="field">
          <label>Email</label>
          <input
            type="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
        </div>
        <div className="field">
          <label>Password</label>
          <input
            type="password"
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </div>
        {msg.err && <div className="error">{msg.err}</div>}
        {msg.ok && <div className="ok">{msg.ok}</div>}
        <button className="btn" style={{ width: "100%", marginTop: 10 }} disabled={busy}>
          {busy ? "…" : mode === "login" ? "Sign in" : "Register"}
        </button>
        <p className="muted" style={{ textAlign: "center", marginTop: 14, fontSize: 13 }}>
          {mode === "login" ? "Need an account? " : "Already have one? "}
          <a
            href="#"
            onClick={(e) => {
              e.preventDefault();
              setMsg({});
              setMode(mode === "login" ? "register" : "login");
            }}
          >
            {mode === "login" ? "Register" : "Sign in"}
          </a>
        </p>
      </form>
    </div>
  );
}
