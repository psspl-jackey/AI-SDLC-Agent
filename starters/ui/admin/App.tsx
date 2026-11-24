"use client";
// Admin panel starter: moderation queue first, then listings, users and categories. Look from theme.ts.
import { useCallback, useEffect, useMemo, useState } from "react";
import { api, AppConfig, Category, getToken, Item, money, setToken, User } from "./api";
import { BrandMark, Empty, Initials, StatusBadge, Styles, Thumb, timeAgo, useToasts } from "./kit";
import { theme } from "./theme";

type Stats = { users: number; items_active: number; items_pending: number; items_sold: number; items_removed: number; categories: number };
type Tab = "overview" | "queue" | "items" | "users" | "categories";
const c = theme.colors;
const css = `
.shell{display:grid;grid-template-columns:240px 1fr;min-height:100vh}
.side{background:${c.surface};border-right:1px solid ${c.border};padding:16px 12px;display:flex;flex-direction:column;gap:4px;position:sticky;top:0;height:100vh}
.side .brand{display:flex;gap:10px;align-items:center;font-weight:800;padding:4px 8px 16px}
.nav{display:flex;align-items:center;gap:10px;padding:10px 12px;border-radius:${theme.radius.control}px;cursor:pointer;border:none;background:none;text-align:left;font-weight:600;color:${c.text}}
.nav:hover{background:${c.background}}
.nav.on{background:${c.primary}18;color:${c.primary}}
.count{margin-left:auto;background:${c.warning};color:#fff;border-radius:999px;font-size:12px;padding:1px 8px}
.main{padding:20px 24px;min-width:0}
.top{display:flex;justify-content:space-between;align-items:center;margin-bottom:18px;gap:12px;flex-wrap:wrap}
.top h1{margin:0;font-size:24px}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:14px;margin-bottom:22px}
.kpi{padding:16px}
.kpi .n{font-size:30px;font-weight:800;letter-spacing:-.02em}
.queue{display:grid;gap:12px}
.qitem{display:grid;grid-template-columns:120px 1fr auto;gap:14px;align-items:center;padding:12px;overflow:hidden}
table{width:100%;border-collapse:collapse;font-size:14px}
th{text-align:left;color:${c.muted};font-weight:600;font-size:12px;text-transform:uppercase;letter-spacing:.04em;padding:10px;border-bottom:1px solid ${c.border}}
td{padding:10px;border-bottom:1px solid ${c.border};vertical-align:middle}
tr:hover td{background:${c.background}}
.tools{display:flex;gap:8px;margin-bottom:12px;flex-wrap:wrap}
@media (max-width:860px){.shell{grid-template-columns:1fr}.side{position:static;height:auto;flex-direction:row;overflow-x:auto}.side .brand{display:none}.qitem{grid-template-columns:1fr}}
`;

function Login({ onDone, push }: { onDone: (u: User) => void; push: (t: string, e?: boolean) => void }) {
  const [email, setEmail] = useState("{{admin_email}}");
  const [password, setPassword] = useState("");
  const submit = async () => {
    try {
      const r = await api<{ token: string; user: User }>("/auth/login", { method: "POST", body: { email, password } });
      if (r.user.role !== "admin") throw new Error("This account is not an admin");
      setToken(r.token);
      onDone(r.user);
    } catch (e) { push((e as Error).message, true); }
  };
  return (
    <div style={{ minHeight: "100vh", display: "grid", placeItems: "center", padding: 16 }}>
      <div className="card" style={{ width: "100%", maxWidth: 380, padding: 24, display: "grid", gap: 14 }}>
        <div style={{ display: "flex", gap: 10, alignItems: "center" }}><BrandMark /><div>
          <div style={{ fontWeight: 800 }}>{theme.brandName}</div><div className="muted" style={{ fontSize: 13 }}>Admin panel</div></div></div>
        <div><label className="label" htmlFor="e">Email</label><input id="e" className="input" value={email} onChange={(e) => setEmail(e.target.value)} /></div>
        <div><label className="label" htmlFor="p">Password</label><input id="p" className="input" type="password" value={password}
          onChange={(e) => setPassword(e.target.value)} onKeyDown={(e) => e.key === "Enter" && submit()} /></div>
        <button className="btn btn-primary" onClick={submit}>Log in</button>
        <div className="muted" style={{ fontSize: 13 }}>Demo admin: {{admin_email}} / {{admin_password}}</div>
      </div>
    </div>
  );
}

export default function App() {
  const toast = useToasts();
  const [user, setUser] = useState<User | null>(null);
  const [checked, setChecked] = useState(false);
  const [tab, setTab] = useState<Tab>("overview");
  const [config, setConfig] = useState<AppConfig | null>(null);
  const [stats, setStats] = useState<Stats | null>(null);
  const [offline, setOffline] = useState(false);

  useEffect(() => {
    api<AppConfig>("/config").then(setConfig).catch(() => setOffline(true));
    if (getToken()) api<User>("/me").then((u) => u.role === "admin" && setUser(u)).catch(() => setToken("")).finally(() => setChecked(true));
    else setChecked(true);
  }, []);
  const refreshStats = useCallback(() => { api<Stats>("/admin/stats").then(setStats).catch(() => undefined); }, []);
  useEffect(() => { if (user) refreshStats(); }, [user, tab, refreshStats]);

  if (!checked) return <Styles />;
  if (!user) return <><Styles />{offline && <p style={{ textAlign: "center", color: c.danger }}>The server is not reachable. Start the backend first.</p>}
    <Login onDone={setUser} push={toast.push} />{toast.view}</>;

  const label = config?.items_label || "Items";
  const nav: [Tab, string, string][] = [["overview", "📊", "Overview"], ["queue", "🕒", "Review queue"], ["items", "📋", `All ${label.toLowerCase()}`],
    ["users", "👥", "Users"], ["categories", "🏷️", "Categories"]];
  return (
    <>
      <Styles css={css} />
      <div className="shell">
        <aside className="side">
          <div className="brand"><BrandMark size={32} /><div>{theme.brandName}<div className="muted" style={{ fontSize: 12, fontWeight: 500 }}>Admin</div></div></div>
          {nav.map(([key, icon, text]) => (
            <button key={key} className={`nav${tab === key ? " on" : ""}`} onClick={() => setTab(key)}>
              <span aria-hidden>{icon}</span>{text}{key === "queue" && !!stats?.items_pending && <span className="count">{stats.items_pending}</span>}
            </button>
          ))}
          <div style={{ flex: 1 }} />
          <div style={{ display: "flex", gap: 8, alignItems: "center", padding: 8 }}>
            <Initials name={user.name} size={32} /><div style={{ fontSize: 13, flex: 1 }}>{user.name}</div>
            <button className="btn btn-ghost" onClick={() => { setToken(""); setUser(null); }}>Log out</button>
          </div>
        </aside>
        <main className="main">
          {tab === "overview" && <Overview stats={stats} label={label} goQueue={() => setTab("queue")} config={config} />}
          {tab === "queue" && <Queue config={config} push={toast.push} onChange={refreshStats} />}
          {tab === "items" && <Items config={config} push={toast.push} onChange={refreshStats} />}
          {tab === "users" && <Users me={user} push={toast.push} />}
          {tab === "categories" && <Categories config={config} push={toast.push} />}
        </main>
      </div>
      {toast.view}
    </>
  );
}

function Overview({ stats, label, goQueue, config }: { stats: Stats | null; label: string; goQueue: () => void; config: AppConfig | null }) {
  const [pending, setPending] = useState<Item[]>([]);
  useEffect(() => { api<Item[]>("/admin/items?status=pending").then(setPending).catch(() => undefined); }, []);
  const kpis: [string, number | undefined, string][] = [
    ["Waiting for review", stats?.items_pending, c.warning], [`Live ${label.toLowerCase()}`, stats?.items_active, c.success],
    ["Sold", stats?.items_sold, c.muted], ["Removed", stats?.items_removed, c.danger], ["Users", stats?.users, c.primary]];
  return (
    <>
      <div className="top"><h1>Overview</h1></div>
      <div className="kpis">{kpis.map(([k, v, color]) => (
        <div key={k} className="card kpi"><div className="muted" style={{ fontSize: 13 }}>{k}</div>
          <div className="n" style={{ color }}>{v ?? "–"}</div></div>))}</div>
      <div className="top"><h2 style={{ margin: 0, fontSize: 18 }}>Needs your attention</h2>{!!pending.length && <button className="btn btn-primary" onClick={goQueue}>Open review queue</button>}</div>
      {pending.length ? (
        <div className="card">{pending.slice(0, 5).map((i) => (
          <div key={i.id} style={{ display: "flex", gap: 12, padding: 12, borderBottom: `1px solid ${c.border}`, alignItems: "center" }}>
            <span style={{ fontSize: 24 }}>{config?.category_icons[i.category] || "🏷️"}</span>
            <div style={{ flex: 1 }}><b>{i.title}</b><div className="muted" style={{ fontSize: 13 }}>{i.seller?.name} · {i.city} · {timeAgo(i.created_at)}</div></div>
            <StatusBadge status={i.status} /></div>))}</div>
      ) : <Empty icon="✅" title="All caught up">No listings are waiting for review.</Empty>}
    </>
  );
}

function Queue({ config, push, onChange }: { config: AppConfig | null; push: (t: string, e?: boolean) => void; onChange: () => void }) {
  const [items, setItems] = useState<Item[] | null>(null);
  const load = useCallback(() => { api<Item[]>("/admin/items?status=pending").then(setItems).catch((e) => push(e.message, true)); }, [push]);
  useEffect(() => { load(); }, [load]);
  const decide = async (i: Item, status: string) => {
    try {
      await api(`/admin/items/${i.id}`, { method: "PATCH", body: { status } });
      push(status === "active" ? `Approved: ${i.title}` : `Rejected: ${i.title}`);
      load(); onChange();
    } catch (e) { push((e as Error).message, true); }
  };
  const cur = config?.currency || "INR";
  return (
    <>
      <div className="top"><h1>Review queue</h1><span className="muted">New listings stay hidden until approved</span></div>
      {items === null ? <div className="skeleton" style={{ height: 200 }} /> : items.length ? (
        <div className="queue">{items.map((i) => (
          <div key={i.id} className="card qitem">
            <Thumb category={i.category} icon={config?.category_icons[i.category]} imageUrl={i.image_url} height={90} rounded={false} />
            <div style={{ minWidth: 0 }}>
              <div style={{ fontWeight: 700 }}>{i.title}</div>
              <div className="price" style={{ fontSize: 16 }}>{money(i.price, cur)}</div>
              <div className="muted" style={{ fontSize: 13 }}>{i.category} · {i.city} · by {i.seller?.name} · {timeAgo(i.created_at)}</div>
              {i.description && <div style={{ fontSize: 14, marginTop: 4 }}>{i.description}</div>}
            </div>
            <div style={{ display: "flex", gap: 8 }}>
              <button className="btn btn-primary" onClick={() => decide(i, "active")}>✓ Approve</button>
              <button className="btn btn-danger" onClick={() => decide(i, "removed")}>✕ Reject</button>
            </div>
          </div>))}</div>
      ) : <Empty icon="✅" title="Queue is empty">New listings from users appear here for review.</Empty>}
    </>
  );
}

function Items({ config, push, onChange }: { config: AppConfig | null; push: (t: string, e?: boolean) => void; onChange: () => void }) {
  const [status, setStatus] = useState("active");
  const [q, setQ] = useState("");
  const [items, setItems] = useState<Item[] | null>(null);
  const load = useCallback(() => { setItems(null); api<Item[]>(`/admin/items?status=${status}`).then(setItems).catch((e) => push(e.message, true)); }, [status, push]);
  useEffect(() => { load(); }, [load]);
  const shown = useMemo(() => (items || []).filter((i) => !q || `${i.title} ${i.city} ${i.seller?.name}`.toLowerCase().includes(q.toLowerCase())), [items, q]);
  const update = async (i: Item, body: { status?: string; featured?: boolean }, msg: string) => {
    if (body.status === "removed" && !window.confirm(`Remove "${i.title}"? The seller will see it as removed.`)) return;
    try { await api(`/admin/items/${i.id}`, { method: "PATCH", body }); push(msg); load(); onChange(); } catch (e) { push((e as Error).message, true); }
  };
  return (
    <>
      <div className="top"><h1>All {config?.items_label.toLowerCase() || "items"}</h1></div>
      <div className="tools">
        {["active", "pending", "sold", "removed"].map((s) => <button key={s} className={`chip${status === s ? " on" : ""}`} onClick={() => setStatus(s)}><StatusBadge status={s} /></button>)}
        <input className="input" style={{ maxWidth: 280, marginLeft: "auto" }} placeholder="Search title, city, seller" value={q} onChange={(e) => setQ(e.target.value)} />
      </div>
      <div className="card" style={{ overflowX: "auto" }}>
        <table><thead><tr><th>Listing</th><th>Price</th><th>Seller</th><th>Posted</th><th>Status</th><th></th></tr></thead>
          <tbody>{items === null ? <tr><td colSpan={6}><div className="skeleton" style={{ height: 80 }} /></td></tr> : shown.map((i) => (
            <tr key={i.id}>
              <td><b>{config?.category_icons[i.category]} {i.title}</b>{i.featured && <> <span className="badge badge-featured">★</span></>}<div className="muted" style={{ fontSize: 12 }}>{i.category} · {i.city}</div></td>
              <td>{money(i.price, config?.currency || "INR")}</td><td>{i.seller?.name}</td><td className="muted">{timeAgo(i.created_at)}</td>
              <td><StatusBadge status={i.status} /></td>
              <td style={{ whiteSpace: "nowrap", textAlign: "right" }}>
                {i.status !== "active" && i.status !== "sold" && <button className="btn" onClick={() => update(i, { status: "active" }, "Approved")}>Approve</button>}{" "}
                <button className="btn" onClick={() => update(i, { featured: !i.featured }, i.featured ? "Unfeatured" : "Featured")}>{i.featured ? "Unfeature" : "★ Feature"}</button>{" "}
                {i.status !== "removed" && <button className="btn btn-danger" onClick={() => update(i, { status: "removed" }, "Removed")}>Remove</button>}
              </td></tr>))}
            {items !== null && !shown.length && <tr><td colSpan={6}><Empty icon="📭" title="Nothing here" /></td></tr>}
          </tbody></table>
      </div>
    </>
  );
}

function Users({ me, push }: { me: User; push: (t: string, e?: boolean) => void }) {
  const [users, setUsers] = useState<User[]>([]);
  const [q, setQ] = useState("");
  const load = useCallback(() => { api<User[]>("/admin/users").then(setUsers).catch((e) => push(e.message, true)); }, [push]);
  useEffect(() => { load(); }, [load]);
  const toggle = async (u: User) => {
    if (u.active && !window.confirm(`Block ${u.name}? They will not be able to log in.`)) return;
    try { await api(`/admin/users/${u.id}?active=${!u.active}`, { method: "PATCH" }); push(u.active ? "User blocked" : "User unblocked"); load(); }
    catch (e) { push((e as Error).message, true); }
  };
  const shown = users.filter((u) => !q || `${u.name} ${u.email} ${u.city}`.toLowerCase().includes(q.toLowerCase()));
  return (
    <>
      <div className="top"><h1>Users</h1><input className="input" style={{ maxWidth: 280 }} placeholder="Search name, email, city" value={q} onChange={(e) => setQ(e.target.value)} /></div>
      <div className="card" style={{ overflowX: "auto" }}>
        <table><thead><tr><th>User</th><th>City</th><th>Role</th><th>Member since</th><th>Status</th><th></th></tr></thead>
          <tbody>{shown.map((u) => (
            <tr key={u.id}>
              <td><div style={{ display: "flex", gap: 10, alignItems: "center" }}><Initials name={u.name} size={32} /><div><b>{u.name}</b><div className="muted" style={{ fontSize: 12 }}>{u.email}</div></div></div></td>
              <td>{u.city}</td><td>{u.role}</td><td>{u.member_since}</td>
              <td>{u.active ? <span className="badge badge-active">Active</span> : <span className="badge badge-removed">Blocked</span>}</td>
              <td style={{ textAlign: "right" }}>{u.id !== me.id && <button className={`btn${u.active ? " btn-danger" : ""}`} onClick={() => toggle(u)}>{u.active ? "Block" : "Unblock"}</button>}</td>
            </tr>))}</tbody></table>
      </div>
    </>
  );
}

function Categories({ config, push }: { config: AppConfig | null; push: (t: string, e?: boolean) => void }) {
  const [cats, setCats] = useState<Category[]>([]);
  const [name, setName] = useState("");
  const load = useCallback(() => { api<Category[]>("/categories").then(setCats).catch(() => undefined); }, []);
  useEffect(() => { load(); }, [load]);
  const add = async () => {
    if (!name.trim()) return;
    try { await api(`/admin/categories?name=${encodeURIComponent(name.trim())}`, { method: "POST" }); setName(""); push("Category added"); load(); }
    catch (e) { push((e as Error).message, true); }
  };
  return (
    <>
      <div className="top"><h1>Categories</h1></div>
      <div className="tools" style={{ maxWidth: 480 }}>
        <input className="input" style={{ flex: 1 }} placeholder="New category" value={name} onChange={(e) => setName(e.target.value)} onKeyDown={(e) => e.key === "Enter" && add()} />
        <button className="btn btn-primary" onClick={add}>Add</button>
      </div>
      <div className="kpis">{cats.map((cat) => (
        <div key={cat.id} className="card kpi" style={{ display: "flex", gap: 10, alignItems: "center" }}>
          <span style={{ fontSize: 26 }}>{config?.category_icons[cat.name] || "🏷️"}</span><b>{cat.name}</b></div>))}</div>
    </>
  );
}
