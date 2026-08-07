import { useEffect, useState } from "react";
import { api, ApiError } from "../api";
import { useAuth } from "../auth";
import type { Role, User } from "../types";

const ROLES: Role[] = ["admin", "document_compliance", "scanning", "filing", "notary"];

export default function Users() {
  const { schema } = useAuth();
  const [users, setUsers] = useState<User[]>([]);
  const [msg, setMsg] = useState("");
  // The GEO enum lives in the field registry — no second copy to drift.
  const geos = schema?.fields.find((f) => f.key === "geo")?.options ?? [];

  function load() {
    api.users().then(setUsers);
  }
  useEffect(load, []);

  async function update(
    u: User,
    body: { role?: string; is_active?: boolean; geos?: string[] },
  ) {
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
              <th>Work areas</th>
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
                  {u.role === "admin" ? (
                    <span className="muted">all areas</span>
                  ) : (
                    <div className="geo-picker">
                      {geos.map((g) => (
                        <label key={g} className="badge">
                          <input
                            type="checkbox"
                            checked={u.geos.includes(g)}
                            onChange={(e) =>
                              update(u, {
                                geos: e.target.checked
                                  ? [...u.geos, g]
                                  : u.geos.filter((x) => x !== g),
                              })
                            }
                          />
                          {g}
                        </label>
                      ))}
                      {u.geos.length === 0 && (
                        // Not a gap to flag: it's the documented "unrestricted" default.
                        <span className="muted">none set — imports not limited</span>
                      )}
                    </div>
                  )}
                </td>
                <td>
                  {u.is_active ? (
                    <span className="badge ok-badge">
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
