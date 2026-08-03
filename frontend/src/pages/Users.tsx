import { useEffect, useState } from "react";
import { api, ApiError } from "../api";
import type { Role, User } from "../types";

const ROLES: Role[] = ["admin", "document_compliance", "scanning", "filing", "notary"];

export default function Users() {
  const [users, setUsers] = useState<User[]>([]);
  const [msg, setMsg] = useState("");

  function load() {
    api.users().then(setUsers);
  }
  useEffect(load, []);

  async function update(u: User, body: { role?: string; is_active?: boolean }) {
    setMsg("");
    try {
      await api.updateUser(u.id, body);
      load();
    } catch (e) {
      setMsg((e as ApiError).message);
    }
  }

  return (
    <div>
      <div className="page-head">
        <h1>User Management</h1>
      </div>
      {msg && <div className="error" style={{ marginBottom: 10 }}>{msg}</div>}
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Email</th>
              <th>Name</th>
              <th>Role</th>
              <th>Status</th>
              <th>Registered</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {users.map((u) => (
              <tr key={u.id}>
                <td>
                  <b>{u.email}</b>
                </td>
                <td>{u.full_name ?? "—"}</td>
                <td>
                  <select
                    value={u.role ?? ""}
                    onChange={(e) => update(u, { role: e.target.value })}
                  >
                    <option value="">— none —</option>
                    {ROLES.map((r) => (
                      <option key={r} value={r}>
                        {r}
                      </option>
                    ))}
                  </select>
                </td>
                <td>
                  {u.is_active ? (
                    <span className="badge" style={{ background: "#e6f7ec", color: "#2f9e44" }}>
                      active
                    </span>
                  ) : (
                    <span className="badge">inactive</span>
                  )}
                </td>
                <td className="muted">{new Date(u.created_at).toLocaleDateString()}</td>
                <td>
                  <button
                    className="btn ghost sm"
                    onClick={() => update(u, { is_active: !u.is_active })}
                  >
                    {u.is_active ? "Deactivate" : "Activate"}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
