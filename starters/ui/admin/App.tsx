"use client";
// Admin panel starter: moderation of {{items_label}}, users and categories.
import { useCallback, useEffect, useState } from "react";
import { api, AppConfig, Category, getToken, Item, money, setToken, User } from "./api";

type Stats = { users: number; items_active: number; items_pending: number; items_removed: number; categories: number };
const S = {
  page: { fontFamily: "system-ui, sans-serif", maxWidth: 1100, margin: "0 auto", padding: 16, color: "#1f2933" },
  card: { border: "1px solid #d9dee5", borderRadius: 8, padding: 12, background: "#fff" },
  btn: { padding: "6px 12px", borderRadius: 6, border: "1px solid #9aa5b1", background: "#f5f7fa", cursor: "pointer" },
  primary: { padding: "6px 12px", borderRadius: 6, border: "none", background: "#2563eb", color: "#fff", cursor: "pointer" },
  input: { padding: 8, borderRadius: 6, border: "1px solid #9aa5b1", width: "100%", boxSizing: "border-box" as const },
  table: { width: "100%", borderCollapse: "collapse" as const, fontSize: 14 },
  cell: { borderBottom: "1px solid #e4e7eb", padding: "8px 6px", textAlign: "left" as const, verticalAlign: "top" as const },
};

function Login({ onDone }: { onDone: (u: User) => void }) {
  const [email, setEmail] = useState("{{admin_email}}");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const submit = async () => {
    try {
      const r = await api<{ token: string; user: User }>("/auth/login", { method: "POST", body: { email, password } });
      if (r.user.role !== "admin") throw new Error("This account is not an admin");
      setToken(r.token);
      onDone(r.user);
    } catch (e) { setError((e as Error).message); }
  };
  return (
    <div style={{ ...S.card, maxWidth: 360, margin: "80px auto", display: "grid", gap: 10 }}>
      <h2 style={{ margin: 0 }}>Admin login</h2>
      <input style={S.input} value={email} onChange={(e) => setEmail(e.target.value)} placeholder="Email" />
      <input style={S.input} type="password" value={password} onChange={(e) => setPassword(e.target.value)}
        placeholder="Password" onKeyDown={(e) => e.key === "Enter" && submit()} />
      <button style={S.primary} onClick={submit}>Log in</button>
      {error && <div style={{ color: "#b91c1c" }}>{error}</div>}
      <small style={{ color: "#616e7c" }}>Demo admin: {{admin_email}} / {{admin_password}}</small>
    </div>
  );
}

export default function App() {
  const [user, setUser] = useState<User | null>(null);
  const [tab, setTab] = useState<"dashboard" | "items" | "users" | "categories">("dashboard");
  const [config, setConfig] = useState<AppConfig | null>(null);
  const [stats, setStats] = useState<Stats | null>(null);
  const [items, setItems] = useState<Item[]>([]);
  const [status, setStatus] = useState("pending");
  const [users, setUsers] = useState<User[]>([]);
  const [categories, setCategories] = useState<Category[]>([]);
  const [newCategory, setNewCategory] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    api<AppConfig>("/config").then(setConfig).catch((e) => setError(`Backend not reachable: ${e.message}`));
    if (getToken()) api<User>("/me").then((u) => u.role === "admin" && setUser(u)).catch(() => setToken(""));
  }, []);

  const load = useCallback(async () => {
    try {
      setError("");
      if (tab === "dashboard") setStats(await api<Stats>("/admin/stats"));
      if (tab === "items") setItems(await api<Item[]>(`/admin/items?status=${status}`));
      if (tab === "users") setUsers(await api<User[]>("/admin/users"));
      if (tab === "categories") setCategories(await api<Category[]>("/categories"));
    } catch (e) { setError((e as Error).message); }
  }, [tab, status]);

  useEffect(() => { if (user) load(); }, [user, load]);

  const moderate = async (id: number, body: { status?: string; featured?: boolean }) => {
    try { await api(`/admin/items/${id}`, { method: "PATCH", body }); load(); } catch (e) { setError((e as Error).message); }
  };
  const setActive = async (id: number, active: boolean) => {
    try { await api(`/admin/users/${id}?active=${active}`, { method: "PATCH" }); load(); } catch (e) { setError((e as Error).message); }
  };
  const addCategory = async () => {
    if (!newCategory.trim()) return;
    try { await api(`/admin/categories?name=${encodeURIComponent(newCategory.trim())}`, { method: "POST" }); setNewCategory(""); load(); }
    catch (e) { setError((e as Error).message); }
  };

  const label = config?.items_label || "Items";
  if (!user) return <div style={S.page}>{error && <div style={{ color: "#b91c1c" }}>{error}</div>}<Login onDone={setUser} /></div>;

  return (
    <div style={S.page}>
      <header style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}>
        <h1 style={{ margin: 0, fontSize: 22 }}>{config?.app_name || "Admin"} · Admin</h1>
        <nav style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
          {(["dashboard", "items", "users", "categories"] as const).map((t) => (
            <button key={t} style={tab === t ? S.primary : S.btn} onClick={() => setTab(t)}>
              {t === "items" ? label : t[0].toUpperCase() + t.slice(1)}
            </button>
          ))}
          <button style={S.btn} onClick={() => { setToken(""); setUser(null); }}>Log out</button>
        </nav>
      </header>
      {error && <p style={{ color: "#b91c1c" }}>{error}</p>}

      {tab === "dashboard" && stats && (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))", gap: 12, marginTop: 16 }}>
          {[["Users", stats.users], [`${label} live`, stats.items_active], [`${label} waiting for approval`, stats.items_pending],
            [`${label} removed`, stats.items_removed], ["Categories", stats.categories]].map(([k, v]) => (
            <div key={k} style={S.card}><div style={{ color: "#616e7c", fontSize: 13 }}>{k}</div><div style={{ fontSize: 28 }}>{v}</div></div>
          ))}
        </div>
      )}

      {tab === "items" && (
        <section style={{ marginTop: 16 }}>
          <div style={{ display: "flex", gap: 6, marginBottom: 10 }}>
            {["pending", "active", "removed"].map((s) => (
              <button key={s} style={status === s ? S.primary : S.btn} onClick={() => setStatus(s)}>{s}</button>
            ))}
          </div>
          <table style={S.table}>
            <thead><tr>{["Title", "Category", "City", "Price", "Seller", "Featured", "Actions"].map((h) => <th key={h} style={S.cell}>{h}</th>)}</tr></thead>
            <tbody>
              {items.map((i) => (
                <tr key={i.id}>
                  <td style={S.cell}><b>{i.title}</b><div style={{ color: "#616e7c" }}>{i.description.slice(0, 80)}</div></td>
                  <td style={S.cell}>{i.category}</td><td style={S.cell}>{i.city}</td>
                  <td style={S.cell}>{money(i.price, config?.currency || "INR")}</td>
                  <td style={S.cell}>{i.seller?.name}</td><td style={S.cell}>{i.featured ? "Yes" : "No"}</td>
                  <td style={{ ...S.cell, display: "flex", gap: 4, flexWrap: "wrap" }}>
                    {i.status !== "active" && <button style={S.primary} onClick={() => moderate(i.id, { status: "active" })}>Approve</button>}
                    {i.status !== "removed" && <button style={S.btn} onClick={() => moderate(i.id, { status: "removed" })}>Remove</button>}
                    <button style={S.btn} onClick={() => moderate(i.id, { featured: !i.featured })}>{i.featured ? "Unfeature" : "Feature"}</button>
                  </td>
                </tr>
              ))}
              {!items.length && <tr><td style={S.cell} colSpan={7}>Nothing here.</td></tr>}
            </tbody>
          </table>
        </section>
      )}

      {tab === "users" && (
        <table style={{ ...S.table, marginTop: 16 }}>
          <thead><tr>{["Name", "Email", "Role", "City", "Status", ""].map((h) => <th key={h} style={S.cell}>{h}</th>)}</tr></thead>
          <tbody>
            {users.map((u) => (
              <tr key={u.id}>
                <td style={S.cell}>{u.name}</td><td style={S.cell}>{u.email}</td><td style={S.cell}>{u.role}</td>
                <td style={S.cell}>{u.city}</td><td style={S.cell}>{u.active ? "Active" : "Blocked"}</td>
                <td style={S.cell}>{u.id !== user.id && (
                  <button style={S.btn} onClick={() => setActive(u.id, !u.active)}>{u.active ? "Block" : "Unblock"}</button>)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {tab === "categories" && (
        <section style={{ marginTop: 16, maxWidth: 480 }}>
          <div style={{ display: "flex", gap: 6, marginBottom: 10 }}>
            <input style={S.input} value={newCategory} onChange={(e) => setNewCategory(e.target.value)} placeholder="New category" />
            <button style={S.primary} onClick={addCategory}>Add</button>
          </div>
          <ul>{categories.map((c) => <li key={c.id}>{c.name}</li>)}</ul>
        </section>
      )}
    </div>
  );
}
