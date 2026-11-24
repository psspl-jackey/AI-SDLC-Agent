"use client";
// Customer website starter: browse, search, details, favourites, post, dummy payment.
import { useCallback, useEffect, useState } from "react";
import { api, AppConfig, Category, getToken, Item, money, setToken, User } from "./api";

const S = {
  page: { fontFamily: "system-ui, sans-serif", maxWidth: 1100, margin: "0 auto", padding: 16, color: "#1f2933" },
  card: { border: "1px solid #d9dee5", borderRadius: 8, padding: 12, background: "#fff" },
  btn: { padding: "6px 12px", borderRadius: 6, border: "1px solid #9aa5b1", background: "#f5f7fa", cursor: "pointer" },
  primary: { padding: "6px 12px", borderRadius: 6, border: "none", background: "#2563eb", color: "#fff", cursor: "pointer" },
  input: { padding: 8, borderRadius: 6, border: "1px solid #9aa5b1", boxSizing: "border-box" as const },
};

export default function App() {
  const [config, setConfig] = useState<AppConfig | null>(null);
  const [user, setUser] = useState<User | null>(null);
  const [categories, setCategories] = useState<Category[]>([]);
  const [items, setItems] = useState<Item[]>([]);
  const [q, setQ] = useState("");
  const [category, setCategory] = useState("");
  const [city, setCity] = useState("");
  const [selected, setSelected] = useState<Item | null>(null);
  const [view, setView] = useState<"browse" | "favourites" | "post" | "login" | "mine">("browse");
  const [message, setMessage] = useState("");
  const [form, setForm] = useState({ email: "{{user_email}}", password: "", title: "", price: "", description: "", category_id: "" });

  useEffect(() => {
    api<AppConfig>("/config").then(setConfig).catch((e) => setMessage(`Backend not reachable: ${e.message}`));
    api<Category[]>("/categories").then(setCategories).catch(() => undefined);
    if (getToken()) api<User>("/me").then(setUser).catch(() => setToken(""));
  }, []);

  const search = useCallback(async () => {
    const params = new URLSearchParams({ q, city, ...(category ? { category_id: category } : {}) });
    try { setItems(await api<Item[]>(`/items?${params}`)); } catch (e) { setMessage((e as Error).message); }
  }, [q, city, category]);

  useEffect(() => { if (view === "browse") search(); }, [view, search]);

  const show = async (path: string) => { try { setItems(await api<Item[]>(path)); } catch (e) { setMessage((e as Error).message); } };
  const login = async () => {
    try {
      const r = await api<{ token: string; user: User }>("/auth/login", { method: "POST", body: { email: form.email, password: form.password } });
      setToken(r.token); setUser(r.user); setView("browse"); setMessage(`Welcome, ${r.user.name}`);
    } catch (e) { setMessage((e as Error).message); }
  };
  const post = async () => {
    try {
      await api("/items", { method: "POST", body: { title: form.title, price: Number(form.price) || 0, description: form.description,
        category_id: Number(form.category_id), city: user?.city || "" } });
      setMessage("Posted. It goes live after an admin approves it."); setView("mine"); show("/my/items");
    } catch (e) { setMessage((e as Error).message); }
  };
  const favourite = async (id: number) => {
    if (!user) return setView("login");
    try { await api(`/favourites/${id}`, { method: "POST" }); setMessage("Saved to favourites"); } catch (e) { setMessage((e as Error).message); }
  };
  const pay = async (item: Item) => {
    if (!user) return setView("login");
    try {
      const r = await api<{ status: string; reference: string | null; message: string }>("/payments/dummy",
        { method: "POST", body: { amount: 99, purpose: `Feature item ${item.id}` } });
      setMessage(`${r.message}${r.reference ? ` · ref ${r.reference}` : ""}`);
    } catch (e) { setMessage((e as Error).message); }
  };

  const cur = config?.currency || "INR";
  const label = config?.items_label || "Items";
  return (
    <div style={S.page}>
      <header style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
        <h1 style={{ margin: 0, fontSize: 22, cursor: "pointer" }} onClick={() => setView("browse")}>{config?.app_name || "Store"}</h1>
        <nav style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
          <button style={S.btn} onClick={() => setView("browse")}>{label}</button>
          {user ? (<>
            <button style={S.btn} onClick={() => { setView("favourites"); show("/favourites"); }}>Favourites</button>
            <button style={S.btn} onClick={() => { setView("mine"); show("/my/items"); }}>My {label.toLowerCase()}</button>
            <button style={S.primary} onClick={() => setView("post")}>Post {config?.item_label.toLowerCase() || "item"}</button>
            <button style={S.btn} onClick={() => { setToken(""); setUser(null); }}>Log out</button>
          </>) : <button style={S.primary} onClick={() => setView("login")}>Log in</button>}
        </nav>
      </header>
      {message && <p style={{ background: "#eef2ff", padding: 8, borderRadius: 6 }}>{message}</p>}

      {view === "login" && (
        <div style={{ ...S.card, maxWidth: 360, margin: "40px auto", display: "grid", gap: 10 }}>
          <input style={S.input} value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} placeholder="Email" />
          <input style={S.input} type="password" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} placeholder="Password" />
          <button style={S.primary} onClick={login}>Log in</button>
          <small>Demo user: {{user_email}} / {{user_password}}</small>
        </div>
      )}

      {view === "post" && (
        <div style={{ ...S.card, maxWidth: 480, margin: "24px auto", display: "grid", gap: 10 }}>
          <input style={S.input} placeholder="Title" value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} />
          <input style={S.input} placeholder="Price" inputMode="numeric" value={form.price} onChange={(e) => setForm({ ...form, price: e.target.value })} />
          <select style={S.input} value={form.category_id} onChange={(e) => setForm({ ...form, category_id: e.target.value })}>
            <option value="">Category</option>{categories.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
          <textarea style={S.input} rows={4} placeholder="Description" value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} />
          <button style={S.primary} onClick={post} disabled={!form.title || !form.category_id}>Post</button>
        </div>
      )}

      {(view === "browse" || view === "favourites" || view === "mine") && (<>
        {view === "browse" && (
          <div style={{ display: "flex", gap: 6, margin: "12px 0", flexWrap: "wrap" }}>
            <input style={{ ...S.input, flex: "1 1 200px" }} placeholder="Search" value={q} onChange={(e) => setQ(e.target.value)} onKeyDown={(e) => e.key === "Enter" && search()} />
            <select style={S.input} value={category} onChange={(e) => setCategory(e.target.value)}>
              <option value="">All categories</option>{categories.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
            </select>
            <select style={S.input} value={city} onChange={(e) => setCity(e.target.value)}>
              <option value="">All cities</option>{(config?.cities || []).map((c) => <option key={c}>{c}</option>)}
            </select>
            <button style={S.primary} onClick={search}>Search</button>
          </div>
        )}
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(220px, 1fr))", gap: 12 }}>
          {items.map((i) => (
            <div key={i.id} style={{ ...S.card, cursor: "pointer" }} onClick={() => setSelected(i)}>
              {i.image_url && <img src={i.image_url} alt="" style={{ width: "100%", height: 140, objectFit: "cover", borderRadius: 6 }} />}
              {i.featured && <span style={{ fontSize: 12, background: "#fde68a", padding: "2px 6px", borderRadius: 4 }}>Featured</span>}
              <h3 style={{ margin: "6px 0", fontSize: 16 }}>{i.title}</h3>
              <div style={{ fontWeight: 600 }}>{money(i.price, cur)}</div>
              <div style={{ color: "#616e7c", fontSize: 13 }}>{i.category} · {i.city}{view === "mine" ? ` · ${i.status}` : ""}</div>
            </div>
          ))}
          {!items.length && <p>Nothing found.</p>}
        </div>
      </>)}

      {selected && (
        <div onClick={() => setSelected(null)} style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,.4)", display: "grid", placeItems: "center", padding: 16 }}>
          <div onClick={(e) => e.stopPropagation()} style={{ ...S.card, maxWidth: 520, width: "100%" }}>
            {selected.image_url && <img src={selected.image_url} alt="" style={{ width: "100%", maxHeight: 260, objectFit: "cover", borderRadius: 6 }} />}
            <h2>{selected.title}</h2>
            <div style={{ fontSize: 20, fontWeight: 600 }}>{money(selected.price, cur)}</div>
            <p>{selected.description}</p>
            <p style={{ color: "#616e7c" }}>{selected.category} · {selected.city} · Seller: {selected.seller?.name}</p>
            <div style={{ display: "flex", gap: 6 }}>
              <button style={S.btn} onClick={() => favourite(selected.id)}>Save</button>
              <button style={S.primary} onClick={() => pay(selected)}>Feature for {money(99, cur)} (dummy payment)</button>
              <button style={S.btn} onClick={() => setSelected(null)}>Close</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
