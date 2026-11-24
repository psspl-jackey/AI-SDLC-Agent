"use client";
// Customer website starter. Look and feel come from theme.ts (Stage 4 UI theme); flows follow its UX principles:
// search first, photo-first cards, short posting steps, trust signals near contact, visible ad status.
import { useCallback, useEffect, useMemo, useState } from "react";
import { api, AppConfig, Category, getToken, Item, money, setToken, User } from "./api";
import { BrandMark, Empty, Initials, StatusBadge, Styles, Thumb, timeAgo, useToasts } from "./kit";
import { theme } from "./theme";

const c = theme.colors;
const css = `
.top{position:sticky;top:0;z-index:20;background:${c.surface};border-bottom:1px solid ${c.border}}
.bar{max-width:1180px;margin:0 auto;padding:10px 16px;display:flex;align-items:center;gap:12px}
.brand{display:flex;align-items:center;gap:10px;cursor:pointer;font-weight:800;font-size:19px;white-space:nowrap}
.search{flex:1;display:flex;gap:8px;min-width:0}
.wrap{max-width:1180px;margin:0 auto;padding:16px}
.hero{background:linear-gradient(135deg,${c.primary},${c.primary}cc);color:${c.onPrimary};border-radius:${theme.radius.card}px;padding:32px 24px;margin-bottom:20px}
.hero h1{margin:0 0 6px;font-size:clamp(24px,4vw,36px);letter-spacing:-.02em}
.hero p{margin:0 0 18px;opacity:.9}
.hero .search .input{border:none;padding:14px 16px;font-size:16px}
.hero .city{max-width:190px}
.cats{display:grid;grid-template-columns:repeat(auto-fill,minmax(112px,1fr));gap:10px;margin:0 0 24px}
.cat{display:grid;justify-items:center;gap:6px;padding:14px 8px;cursor:pointer;text-align:center;font-weight:600;font-size:14px}
.cat .ico{font-size:30px}
.cat.on{border-color:${c.primary};box-shadow:0 0 0 2px ${c.primary}}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(230px,1fr));gap:16px}
.item{overflow:hidden;cursor:pointer;transition:transform .12s, box-shadow .12s;position:relative}
.item:hover{transform:translateY(-2px);box-shadow:0 10px 24px #0000001a}
.item .body{padding:12px 14px 14px}
.item h3{margin:4px 0 6px;font-size:15px;font-weight:600;line-height:1.3;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.item .meta{display:flex;justify-content:space-between;font-size:13px}
.item .ribbon{position:absolute;top:10px;left:10px}
.item .heart{position:absolute;top:8px;right:8px;background:${c.surface};border:none;border-radius:999px;width:34px;height:34px;cursor:pointer;font-size:16px;box-shadow:0 2px 8px #0002}
.head{display:flex;justify-content:space-between;align-items:center;gap:12px;margin:0 0 12px;flex-wrap:wrap}
.head h2{margin:0;font-size:20px}
.detail{display:grid;grid-template-columns:minmax(0,1.6fr) minmax(280px,1fr);gap:20px;align-items:start}
.panel{padding:18px}
.tips{background:${c.background};border-radius:${theme.radius.control}px;padding:12px 14px;font-size:14px}
.tips li{margin:4px 0}
.steps{display:flex;gap:8px;margin-bottom:18px}
.step{flex:1;height:6px;border-radius:999px;background:${c.border}}
.step.on{background:${c.primary}}
.form{display:grid;gap:14px;max-width:560px}
.err{color:${c.danger};font-size:13px;margin-top:4px}
.foot{color:${c.muted};font-size:13px;text-align:center;padding:32px 16px}
@media (max-width:480px){.brand-name{display:none}}
@media (max-width:760px){.detail{grid-template-columns:1fr}.hide-sm{display:none}.brand{font-size:16px}
.bar{gap:6px}.bar .btn{padding:8px 10px}.hero{padding:22px 16px}.hero .search{flex-wrap:wrap}
.hero .search .input{flex:1}.hero .search .city{max-width:none;flex:1 1 100%}.cats{grid-template-columns:repeat(4,1fr);gap:8px}
.cat{padding:10px 4px;font-size:12px}.cats{margin-bottom:16px}.cat .ico{font-size:24px}.grid{grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}
.item .price{font-size:16px}.item .body{padding:10px}}
`;

type Route = { page: "home" | "item" | "post" | "account" | "favourites"; id?: number };

function parseRoute(): Route {
  const h = typeof window === "undefined" ? "" : window.location.hash.replace(/^#\/?/, "");
  const [page, id] = h.split("/");
  if (page === "item" && id) return { page: "item", id: Number(id) };
  if (page === "post" || page === "account" || page === "favourites") return { page };
  return { page: "home" };
}

function go(path: string) { window.location.hash = path; window.scrollTo({ top: 0 }); }

export default function App() {
  const [route, setRoute] = useState<Route>({ page: "home" });
  const [config, setConfig] = useState<AppConfig | null>(null);
  const [user, setUser] = useState<User | null>(null);
  const [categories, setCategories] = useState<Category[]>([]);
  const [favIds, setFavIds] = useState<Set<number>>(new Set());
  const [offline, setOffline] = useState(false);
  const toast = useToasts();

  useEffect(() => {
    const on = () => setRoute(parseRoute());
    on();
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  useEffect(() => {
    api<AppConfig>("/config").then(setConfig).catch(() => setOffline(true));
    api<Category[]>("/categories").then(setCategories).catch(() => undefined);
    if (getToken()) api<User>("/me").then(setUser).catch(() => setToken(""));
  }, []);
  const loadFavs = useCallback(() => {
    if (!getToken()) return setFavIds(new Set());
    api<Item[]>("/favourites").then((f) => setFavIds(new Set(f.map((i) => i.id)))).catch(() => undefined);
  }, []);
  useEffect(() => { loadFavs(); }, [user, loadFavs]);

  const toggleFav = async (id: number) => {
    if (!user) { toast.push("Log in to save favourites"); return go("/account"); }
    const saved = favIds.has(id);
    try {
      await api(`/favourites/${id}`, { method: saved ? "DELETE" : "POST" });
      loadFavs();
      toast.push(saved ? "Removed from favourites" : "Saved to favourites");
    } catch (e) { toast.push((e as Error).message, true); }
  };

  const icons = config?.category_icons || {};
  const label = config?.item_label || "Item";
  const ctx = { config, user, categories, icons, favIds, toggleFav, toast: toast.push, cur: config?.currency || "INR" };

  return (
    <>
      <Styles css={css} />
      <header className="top">
        <div className="bar">
          <div className="brand" onClick={() => go("/")} role="link" aria-label="Home"><BrandMark /><span className="brand-name">{theme.brandName}</span></div>
          <div style={{ flex: 1 }} />
          {user && <button className="btn btn-ghost hide-sm" onClick={() => go("/favourites")}>♡ Favourites</button>}
          <button className="btn btn-ghost" onClick={() => go("/account")}>{user ? `👤 ${user.name.split(" ")[0]}` : "Log in"}</button>
          <button className="btn btn-accent" onClick={() => go("/post")}>＋ {config?.items_label === "Ads" ? "Sell" : `Add ${label.toLowerCase()}`}</button>
        </div>
      </header>
      <main className="wrap">
        {offline && <div className="card panel" style={{ borderColor: c.danger, marginBottom: 16 }}>
          The server is not reachable. Start the backend from the dashboard (Build → Run the apps).</div>}
        {route.page === "home" && <Home {...ctx} />}
        {route.page === "item" && route.id && <Detail id={route.id} {...ctx} />}
        {route.page === "post" && <Post {...ctx} />}
        {route.page === "account" && <Account {...ctx} onUser={(u) => { setUser(u); if (u) toast.push(`Welcome, ${u.name.split(" ")[0]}`); }} />}
        {route.page === "favourites" && <Favourites {...ctx} />}
      </main>
      <footer className="foot">{theme.brandName} · demo build with dummy data · payments use a dummy gateway</footer>
      {toast.view}
    </>
  );
}

type Ctx = {
  config: AppConfig | null; user: User | null; categories: Category[]; icons: Record<string, string>;
  favIds: Set<number>; toggleFav: (id: number) => void; toast: (t: string, e?: boolean) => void; cur: string;
};

function ItemCard({ item, icons, cur, favIds, toggleFav, showStatus }: Ctx & { item: Item; showStatus?: boolean }) {
  return (
    <article className="card item" onClick={() => go(`/item/${item.id}`)}>
      <Thumb category={item.category} icon={icons[item.category]} imageUrl={item.image_url} />
      {item.featured && <span className="badge badge-featured ribbon">★ Featured</span>}
      <button className="heart" aria-label={favIds.has(item.id) ? "Remove from favourites" : "Save"}
        onClick={(e) => { e.stopPropagation(); toggleFav(item.id); }}>{favIds.has(item.id) ? "♥" : "♡"}</button>
      <div className="body">
        <div className="price">{money(item.price, cur)}</div>
        <h3>{item.title}</h3>
        <div className="meta muted"><span>📍 {item.city}</span><span>{showStatus ? <StatusBadge status={item.status} /> : timeAgo(item.created_at)}</span></div>
      </div>
    </article>
  );
}

function Skeletons() {
  return <div className="grid">{Array.from({ length: 8 }).map((_, i) => <div key={i} className="skeleton" style={{ height: 250 }} />)}</div>;
}

function Home(ctx: Ctx) {
  const { config, categories, icons } = ctx;
  const [q, setQ] = useState("");
  const [city, setCity] = useState("");
  const [categoryId, setCategoryId] = useState<number | null>(null);
  const [sort, setSort] = useState("newest");
  const [items, setItems] = useState<Item[] | null>(null);
  const search = useCallback(async () => {
    setItems(null);
    const params = new URLSearchParams({ q, city, sort, ...(categoryId ? { category_id: String(categoryId) } : {}) });
    try { setItems(await api<Item[]>(`/items?${params}`)); } catch { setItems([]); }
  }, [q, city, sort, categoryId]);
  useEffect(() => { search(); }, [city, sort, categoryId]); // eslint-disable-line react-hooks/exhaustive-deps

  const heading = useMemo(() => {
    const cat = categories.find((x) => x.id === categoryId)?.name;
    const what = cat || (q ? `"${q}"` : `Fresh ${config?.items_label.toLowerCase() || "items"}`);
    return `${what}${city ? ` in ${city}` : ""}`;
  }, [categories, categoryId, q, city, config]);

  return (
    <>
      <section className="hero">
        <h1>{theme.tagline || theme.brandName}</h1>
        <p>{config ? `${config.items_label} from people in ${config.cities.slice(0, 3).join(", ")} and more` : " "}</p>
        <form className="search" onSubmit={(e) => { e.preventDefault(); search(); }}>
          <select className="input city" value={city} onChange={(e) => setCity(e.target.value)} aria-label="City">
            <option value="">📍 All cities</option>{config?.cities.map((x) => <option key={x}>{x}</option>)}
          </select>
          <input className="input" placeholder={`Search ${config?.items_label.toLowerCase() || ""}…`} value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search" />
          <button className="btn btn-accent" type="submit">Search</button>
        </form>
      </section>
      <div className="cats">
        {categories.map((cat) => (
          <div key={cat.id} className={`card cat${categoryId === cat.id ? " on" : ""}`} role="button" tabIndex={0}
            onClick={() => setCategoryId(categoryId === cat.id ? null : cat.id)}
            onKeyDown={(e) => e.key === "Enter" && setCategoryId(categoryId === cat.id ? null : cat.id)}>
            <span className="ico" aria-hidden>{icons[cat.name] || "🏷️"}</span>{cat.name}
          </div>
        ))}
      </div>
      <div className="head">
        <h2>{heading}</h2>
        <select className="input" style={{ width: "auto" }} value={sort} onChange={(e) => setSort(e.target.value)} aria-label="Sort">
          <option value="newest">Newest first</option><option value="price_asc">Price: low to high</option><option value="price_desc">Price: high to low</option>
        </select>
      </div>
      {items === null ? <Skeletons /> : items.length ? (
        <div className="grid">{items.map((i) => <ItemCard key={i.id} item={i} {...ctx} />)}</div>
      ) : (
        <Empty icon="🔍" title="Nothing matches yet">Try another word, city or category.</Empty>
      )}
    </>
  );
}

function Detail({ id, ...ctx }: Ctx & { id: number }) {
  const { user, icons, cur, config, favIds, toggleFav, toast } = ctx;
  const [item, setItem] = useState<Item | null>(null);
  const [phone, setPhone] = useState("");
  const [missing, setMissing] = useState(false);
  useEffect(() => { setItem(null); setPhone(""); api<Item>(`/items/${id}`).then(setItem).catch(() => setMissing(true)); }, [id]);
  if (missing) return <Empty icon="🫥" title="This listing is no longer available"><button className="btn" onClick={() => go("/")}>Back to home</button></Empty>;
  if (!item) return <div className="skeleton" style={{ height: 420 }} />;
  const needLogin = () => { toast("Log in first"); go("/account"); };
  const showPhone = async () => {
    if (!user) return needLogin();
    try { setPhone((await api<{ phone: string }>(`/items/${id}/contact`)).phone); } catch (e) { toast((e as Error).message, true); }
  };
  const boost = async () => {
    if (!user) return needLogin();
    const r = await api<{ status: string; reference: string | null; message: string }>("/payments/dummy",
      { method: "POST", body: { amount: 99, purpose: `Feature ${item.id}` } });
    toast(`${r.message}${r.reference ? ` · ${r.reference}` : ""}`, r.status !== "success");
  };
  const share = async () => {
    try { await navigator.clipboard.writeText(window.location.href); toast("Link copied"); } catch { toast(window.location.href); }
  };
  return (
    <>
      <button className="btn btn-ghost" onClick={() => history.length > 1 ? history.back() : go("/")} style={{ marginBottom: 8 }}>‹ Back</button>
      <div className="detail">
        <div className="card" style={{ overflow: "hidden" }}>
          <Thumb category={item.category} icon={icons[item.category]} imageUrl={item.image_url} height={340} />
          <div className="panel">
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 8 }}>
              {item.featured && <span className="badge badge-featured">★ Featured</span>}
              <span className="badge">{icons[item.category]} {item.category}</span>
              <span className="badge">📍 {item.city}</span>
              <span className="badge">🕒 {timeAgo(item.created_at)}</span>
            </div>
            <h1 style={{ margin: "6px 0", fontSize: 26 }}>{item.title}</h1>
            <div className="price" style={{ fontSize: 30, color: c.primary }}>{money(item.price, cur)}</div>
            <h3 style={{ marginBottom: 4 }}>Description</h3>
            <p style={{ lineHeight: 1.6, marginTop: 0 }}>{item.description || "No description."}</p>
          </div>
        </div>
        <aside style={{ display: "grid", gap: 14 }}>
          <div className="card panel" style={{ display: "grid", gap: 12 }}>
            {item.seller && (
              <div style={{ display: "flex", gap: 12, alignItems: "center" }}>
                <Initials name={item.seller.name} size={48} />
                <div>
                  <div style={{ fontWeight: 700 }}>{item.seller.name}</div>
                  <div className="muted" style={{ fontSize: 13 }}>Member since {item.seller.member_since}
                    {item.seller.verified && <span style={{ color: c.success, fontWeight: 700 }}> · ✓ Phone verified</span>}</div>
                </div>
              </div>
            )}
            <button className="btn btn-primary" onClick={showPhone}>📞 {phone || (item.seller?.phone_masked ? `Show number (${item.seller.phone_masked})` : "Show number")}</button>
            <button className="btn" onClick={() => toast("Chat comes in a later release; call or save the listing for now")}>💬 Chat with seller</button>
            <div style={{ display: "flex", gap: 8 }}>
              <button className="btn" style={{ flex: 1 }} onClick={() => toggleFav(item.id)}>{favIds.has(item.id) ? "♥ Saved" : "♡ Save"}</button>
              <button className="btn" style={{ flex: 1 }} onClick={share}>↗ Share</button>
            </div>
            {user?.id === item.seller?.id && <button className="btn btn-accent" onClick={boost}>★ Feature for {money(99, cur)} (dummy payment)</button>}
          </div>
          {!!config?.safety_tips.length && (
            <div className="card panel">
              <div style={{ fontWeight: 700, marginBottom: 6 }}>🛡️ Stay safe</div>
              <ul className="tips" style={{ margin: 0, paddingLeft: 28 }}>{config.safety_tips.map((t) => <li key={t}>{t}</li>)}</ul>
            </div>
          )}
        </aside>
      </div>
    </>
  );
}

function Post({ user, categories, icons, config, toast }: Ctx) {
  const [step, setStep] = useState(0);
  const [form, setForm] = useState({ category_id: 0, title: "", description: "", price: "", city: user?.city || "" });
  const [done, setDone] = useState(false);
  if (!user) return <Empty icon="🔐" title="Log in to post">It takes less than a minute.<div style={{ marginTop: 12 }}><button className="btn btn-primary" onClick={() => go("/account")}>Log in</button></div></Empty>;
  if (done) return <Empty icon="🎉" title="Posted! It is under review">An admin checks every new listing. You will see it as Live in your account.
    <div style={{ marginTop: 12, display: "flex", gap: 8, justifyContent: "center" }}>
      <button className="btn btn-primary" onClick={() => go("/account")}>See my listings</button>
      <button className="btn" onClick={() => { setDone(false); setStep(0); setForm({ ...form, title: "", description: "", price: "" }); }}>Post another</button></div></Empty>;
  const titleErr = form.title && form.title.trim().length < 5 ? "Use at least 5 characters" : "";
  const priceErr = form.price && !(Number(form.price) >= 0) ? "Enter a number" : "";
  const submit = async () => {
    try {
      await api("/items", { method: "POST", body: { ...form, price: Number(form.price) || 0 } });
      setDone(true);
    } catch (e) { toast((e as Error).message, true); }
  };
  const label = config?.item_label.toLowerCase() || "item";
  return (
    <div className="card panel" style={{ maxWidth: 720, margin: "0 auto" }}>
      <h2 style={{ marginTop: 0 }}>Post your {label}</h2>
      <div className="steps">{[0, 1, 2].map((i) => <div key={i} className={`step${i <= step ? " on" : ""}`} />)}</div>
      {step === 0 && (<>
        <p className="muted">What are you selling?</p>
        <div className="cats">{categories.map((cat) => (
          <div key={cat.id} role="button" tabIndex={0} className={`card cat${form.category_id === cat.id ? " on" : ""}`}
            onClick={() => { setForm({ ...form, category_id: cat.id }); setStep(1); }}>
            <span className="ico">{icons[cat.name] || "🏷️"}</span>{cat.name}</div>))}</div>
      </>)}
      {step === 1 && (
        <div className="form">
          <div><label className="label" htmlFor="t">Title</label>
            <input id="t" className="input" value={form.title} maxLength={80} placeholder="e.g. iPhone 13, 128 GB, with bill" onChange={(e) => setForm({ ...form, title: e.target.value })} />
            {titleErr && <div className="err">{titleErr}</div>}</div>
          <div><label className="label" htmlFor="d">Description</label>
            <textarea id="d" className="input" rows={5} value={form.description} placeholder="Condition, age, what is included" onChange={(e) => setForm({ ...form, description: e.target.value })} /></div>
          <div style={{ display: "flex", gap: 8 }}>
            <button className="btn" onClick={() => setStep(0)}>Back</button>
            <button className="btn btn-primary" disabled={!form.title || !!titleErr} onClick={() => setStep(2)}>Next</button></div>
        </div>
      )}
      {step === 2 && (
        <div className="form">
          <div><label className="label" htmlFor="p">Price ({config?.currency})</label>
            <input id="p" className="input" inputMode="numeric" value={form.price} onChange={(e) => setForm({ ...form, price: e.target.value })} />
            {priceErr && <div className="err">{priceErr}</div>}</div>
          <div><label className="label" htmlFor="c">City</label>
            <select id="c" className="input" value={form.city} onChange={(e) => setForm({ ...form, city: e.target.value })}>
              {config?.cities.map((x) => <option key={x}>{x}</option>)}</select></div>
          <div className="tips">Check: <b>{form.title}</b> · {categories.find((x) => x.id === form.category_id)?.name} · {money(Number(form.price) || 0, config?.currency || "INR")} · {form.city}</div>
          <div style={{ display: "flex", gap: 8 }}>
            <button className="btn" onClick={() => setStep(1)}>Back</button>
            <button className="btn btn-primary" disabled={!form.price || !!priceErr} onClick={submit}>Post now</button></div>
        </div>
      )}
    </div>
  );
}

function Account({ user, onUser, toast, ...ctx }: Ctx & { onUser: (u: User | null) => void }) {
  const [mode, setMode] = useState<"login" | "register">("login");
  const [form, setForm] = useState({ name: "", email: "{{user_email}}", password: "", city: "" });
  const [mine, setMine] = useState<Item[] | null>(null);
  const load = useCallback(() => { api<Item[]>("/my/items").then(setMine).catch(() => setMine([])); }, []);
  useEffect(() => { if (user) load(); }, [user, load]);
  if (!user) {
    const submit = async () => {
      try {
        const r = await api<{ token: string; user: User }>(mode === "login" ? "/auth/login" : "/auth/register",
          { method: "POST", body: mode === "login" ? { email: form.email, password: form.password } : form });
        setToken(r.token); onUser(r.user);
      } catch (e) { toast((e as Error).message, true); }
    };
    return (
      <div className="card panel form" style={{ margin: "24px auto", maxWidth: 420 }}>
        <div style={{ display: "flex", gap: 8 }}>
          <button className={`chip${mode === "login" ? " on" : ""}`} onClick={() => setMode("login")}>Log in</button>
          <button className={`chip${mode === "register" ? " on" : ""}`} onClick={() => setMode("register")}>Create account</button>
        </div>
        {mode === "register" && <div><label className="label">Name</label><input className="input" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></div>}
        <div><label className="label">Email</label><input className="input" type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} /></div>
        <div><label className="label">Password</label><input className="input" type="password" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} onKeyDown={(e) => e.key === "Enter" && submit()} /></div>
        <button className="btn btn-primary" onClick={submit}>{mode === "login" ? "Log in" : "Create account"}</button>
        <div className="muted" style={{ fontSize: 13 }}>Demo: {{user_email}} / {{user_password}}</div>
      </div>
    );
  }
  const markSold = async (item: Item, status: string) => {
    try { await api(`/my/items/${item.id}`, { method: "PATCH", body: { status } }); load(); toast(status === "sold" ? "Marked as sold" : "Live again"); }
    catch (e) { toast((e as Error).message, true); }
  };
  return (
    <>
      <div className="card panel" style={{ display: "flex", gap: 14, alignItems: "center", marginBottom: 18, flexWrap: "wrap" }}>
        <Initials name={user.name} size={56} />
        <div style={{ flex: 1 }}><div style={{ fontWeight: 800, fontSize: 20 }}>{user.name}</div>
          <div className="muted">{user.email} · {user.city} · member since {user.member_since}</div></div>
        <button className="btn" onClick={() => { setToken(""); onUser(null); go("/"); }}>Log out</button>
      </div>
      <div className="head"><h2>My {ctx.config?.items_label.toLowerCase() || "listings"}</h2>
        <button className="btn btn-accent" onClick={() => go("/post")}>＋ Post new</button></div>
      {mine === null ? <Skeletons /> : mine.length ? (
        <div className="grid">{mine.map((i) => (
          <div key={i.id} style={{ display: "grid", gap: 6 }}>
            <ItemCard item={i} user={user} toast={toast} {...ctx} showStatus />
            {(i.status === "active" || i.status === "sold") && (
              <button className="btn" onClick={() => markSold(i, i.status === "sold" ? "active" : "sold")}>
                {i.status === "sold" ? "Make live again" : "✓ Mark as sold"}</button>)}
          </div>))}</div>
      ) : <Empty icon="📦" title="Nothing posted yet">Your listings and their review status appear here.</Empty>}
    </>
  );
}

function Favourites(ctx: Ctx) {
  const [items, setItems] = useState<Item[] | null>(null);
  useEffect(() => { api<Item[]>("/favourites").then(setItems).catch(() => setItems([])); }, [ctx.favIds]);
  if (!ctx.user) return <Empty icon="♡" title="Log in to see favourites" />;
  return (
    <>
      <div className="head"><h2>Favourites</h2></div>
      {items === null ? <Skeletons /> : items.length
        ? <div className="grid">{items.map((i) => <ItemCard key={i.id} item={i} {...ctx} />)}</div>
        : <Empty icon="♡" title="No favourites yet">Tap the heart on any listing to keep it here.</Empty>}
    </>
  );
}
