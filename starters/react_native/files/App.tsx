// {{project_name}}: mobile app starter for Android and iOS (written by the AI SDLC Agent; tickets add features).
// Look and feel come from src/theme.ts (Stage 4 UI theme). Flows: search first, photo-first cards,
// three-step posting, trust signals at the contact bar, visible listing status.
import { StatusBar } from "expo-status-bar";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ActivityIndicator, Animated, FlatList, Platform, Pressable, RefreshControl, ScrollView, Share, StyleSheet, Text,
  TextInput, View,
} from "react-native";
import { SafeAreaProvider, SafeAreaView } from "react-native-safe-area-context";
import { api, API_URL, AppConfig, Category, Item, money, setToken, User } from "./src/api";
import { theme } from "./src/theme";

const c = theme.colors;
const R = theme.radius;
const fontFamily = (theme.font as string) === "serif" ? Platform.select({ ios: "Georgia", android: "serif" }) : undefined;
type Tab = "home" | "favourites" | "post" | "account";

function timeAgo(iso: string | null): string {
  if (!iso) return "";
  const then = new Date(iso.endsWith("Z") || iso.includes("+") ? iso : iso + "Z").getTime();
  const hours = Math.round((Date.now() - then) / 3600000);
  if (hours < 1) return "just now";
  if (hours < 24) return `${hours} h ago`;
  const days = Math.round(hours / 24);
  return days === 1 ? "yesterday" : `${days} days ago`;
}

function hue(text: string): number {
  let h = 0;
  for (const ch of text) h = (h * 31 + ch.charCodeAt(0)) % 360;
  return h;
}

export default function Root() {
  return <SafeAreaProvider><App /></SafeAreaProvider>;
}

function App() {
  const [config, setConfig] = useState<AppConfig | null>(null);
  const [user, setUser] = useState<User | null>(null);
  const [tab, setTab] = useState<Tab>("home");
  const [selected, setSelected] = useState<Item | null>(null);
  const [categories, setCategories] = useState<Category[]>([]);
  const [favIds, setFavIds] = useState<Set<number>>(new Set());
  const [offline, setOffline] = useState(false);
  const [toast, setToast] = useState("");
  const fade = useRef(new Animated.Value(0)).current;

  const say = useCallback((text: string) => {
    setToast(text);
    Animated.sequence([
      Animated.timing(fade, { toValue: 1, duration: 150, useNativeDriver: true }),
      Animated.delay(2200),
      Animated.timing(fade, { toValue: 0, duration: 250, useNativeDriver: true }),
    ]).start();
  }, [fade]);

  useEffect(() => {
    api<AppConfig>("/config").then(setConfig).catch(() => setOffline(true));
    api<Category[]>("/categories").then(setCategories).catch(() => undefined);
  }, []);
  const loadFavs = useCallback(() => {
    if (!user) return setFavIds(new Set());
    api<Item[]>("/favourites").then((f) => setFavIds(new Set(f.map((i) => i.id)))).catch(() => undefined);
  }, [user]);
  useEffect(() => { loadFavs(); }, [loadFavs]);

  const toggleFav = async (id: number) => {
    if (!user) { say("Log in to save favourites"); return setTab("account"); }
    const saved = favIds.has(id);
    await api(`/favourites/${id}`, { method: saved ? "DELETE" : "POST" });
    loadFavs();
    say(saved ? "Removed from favourites" : "Saved ♥");
  };

  const ctx = { config, user, categories, favIds, toggleFav, say, open: (i: Item) => setSelected(i),
    cur: config?.currency || "INR", icons: config?.category_icons || {} };

  return (
    <SafeAreaView style={s.safe} edges={["top"]}>
      <StatusBar style="dark" />
      {offline && <Text style={s.offline}>Cannot reach the server at {API_URL}. Start the backend on your computer and use the same Wi-Fi.</Text>}
      <View style={{ flex: 1 }}>
        {selected ? <Detail item={selected} onBack={() => setSelected(null)} {...ctx} /> : (<>
          {tab === "home" && <Home {...ctx} />}
          {tab === "favourites" && <Favourites {...ctx} />}
          {tab === "post" && <Post {...ctx} onDone={() => setTab("account")} needLogin={() => setTab("account")} />}
          {tab === "account" && <Account {...ctx} onUser={(u) => { setUser(u); if (u) say(`Welcome, ${u.name.split(" ")[0]}`); }} />}
        </>)}
      </View>
      {!selected && (
        <SafeAreaView edges={["bottom"]} style={s.tabs}>
          {([["home", "🏠", "Home"], ["favourites", "♡", "Saved"], ["post", "＋", "Sell"], ["account", "👤", user ? "Account" : "Log in"]] as const).map(([key, icon, label]) => (
            <Pressable key={key} style={s.tab} onPress={() => setTab(key)} accessibilityRole="tab" accessibilityState={{ selected: tab === key }}>
              {key === "post"
                ? <View style={s.sellBtn}><Text style={{ color: c.onAccent, fontSize: 22, fontWeight: "800" }}>{icon}</Text></View>
                : <Text style={{ fontSize: 20, opacity: tab === key ? 1 : 0.6 }}>{icon}</Text>}
              <Text style={[s.tabText, tab === key && { color: c.primary, fontWeight: "700" }]}>{label}</Text>
            </Pressable>
          ))}
        </SafeAreaView>
      )}
      <Animated.View pointerEvents="none" style={[s.toast, { opacity: fade }]}><Text style={{ color: "#fff" }}>{toast}</Text></Animated.View>
    </SafeAreaView>
  );
}

type Ctx = {
  config: AppConfig | null; user: User | null; categories: Category[]; favIds: Set<number>;
  toggleFav: (id: number) => void; say: (t: string) => void; open: (i: Item) => void; cur: string; icons: Record<string, string>;
};

function Thumb({ item, icons, height }: { item: Item; icons: Record<string, string>; height: number }) {
  const h = hue(item.category);
  return (
    <View style={{ height, backgroundColor: `hsl(${h}, 70%, 88%)`, alignItems: "center", justifyContent: "center" }}>
      <Text style={{ fontSize: height * 0.36 }}>{icons[item.category] || "🛍️"}</Text>
    </View>
  );
}

function Card({ item, ...ctx }: Ctx & { item: Item }) {
  return (
    <Pressable style={s.card} onPress={() => ctx.open(item)} accessibilityRole="button" accessibilityLabel={`${item.title}, ${money(item.price, ctx.cur)}`}>
      <Thumb item={item} icons={ctx.icons} height={110} />
      {item.featured && <Text style={s.featured}>★ Featured</Text>}
      <Pressable style={s.heart} onPress={() => ctx.toggleFav(item.id)} hitSlop={8} accessibilityLabel="Save">
        <Text style={{ fontSize: 15, color: c.danger }}>{ctx.favIds.has(item.id) ? "♥" : "♡"}</Text>
      </Pressable>
      <View style={{ padding: 10, gap: 2 }}>
        <Text style={s.price}>{money(item.price, ctx.cur)}</Text>
        <Text style={s.cardTitle} numberOfLines={2}>{item.title}</Text>
        <Text style={s.meta} numberOfLines={1}>📍 {item.city} · {timeAgo(item.created_at)}</Text>
      </View>
    </Pressable>
  );
}

function Home(ctx: Ctx) {
  const { config, categories, icons } = ctx;
  const [items, setItems] = useState<Item[] | null>(null);
  const [q, setQ] = useState("");
  const [city, setCity] = useState("");
  const [categoryId, setCategoryId] = useState<number | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const load = useCallback(async () => {
    const params = new URLSearchParams({ q, city, ...(categoryId ? { category_id: String(categoryId) } : {}) });
    try { setItems(await api<Item[]>(`/items?${params}`)); } catch { setItems([]); }
  }, [q, city, categoryId]);
  useEffect(() => { load(); }, [city, categoryId]); // eslint-disable-line react-hooks/exhaustive-deps
  const cities = config?.cities || [];
  const nextCity = () => setCity(city ? (cities[cities.indexOf(city) + 1] || "") : cities[0] || "");

  const header = (
    <View style={{ gap: 12, paddingBottom: 6 }}>
      <View style={s.hero}>
        <View style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "center" }}>
          <Text style={[s.brand, { fontFamily }]}>{theme.brandName}</Text>
          <Pressable onPress={nextCity} style={s.cityChip} accessibilityLabel="Change city"><Text style={{ color: c.onPrimary, fontWeight: "600" }}>📍 {city || "All cities"} ▾</Text></Pressable>
        </View>
        {!!theme.tagline && <Text style={{ color: c.onPrimary, opacity: 0.9 }}>{theme.tagline}</Text>}
        <View style={s.searchBox}>
          <Text>🔍</Text>
          <TextInput style={{ flex: 1, paddingVertical: 10, color: c.text }} placeholder={`Search ${config?.items_label.toLowerCase() || ""}`}
            placeholderTextColor={c.muted} value={q} onChangeText={setQ} onSubmitEditing={load} returnKeyType="search" />
        </View>
      </View>
      <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: 10, paddingHorizontal: 12 }}>
        {categories.map((cat) => {
          const on = categoryId === cat.id;
          return (
            <Pressable key={cat.id} onPress={() => setCategoryId(on ? null : cat.id)} style={[s.catTile, on && s.catTileOn]}>
              <Text style={{ fontSize: 26 }}>{icons[cat.name] || "🏷️"}</Text>
              <Text style={[s.catText, on && { color: c.primary }]} numberOfLines={1}>{cat.name}</Text>
            </Pressable>
          );
        })}
      </ScrollView>
      <Text style={[s.h2, { paddingHorizontal: 12 }]}>{categoryId ? categories.find((x) => x.id === categoryId)?.name : `Fresh ${config?.items_label.toLowerCase() || "items"}`}{city ? ` in ${city}` : ""}</Text>
    </View>
  );
  if (items === null) return <View style={{ flex: 1 }}>{header}<ActivityIndicator color={c.primary} style={{ marginTop: 32 }} /></View>;
  return (
    <FlatList data={items} keyExtractor={(i) => String(i.id)} numColumns={2} ListHeaderComponent={header}
      columnWrapperStyle={{ gap: 10, paddingHorizontal: 12 }} contentContainerStyle={{ gap: 10, paddingBottom: 24 }}
      refreshControl={<RefreshControl refreshing={refreshing} tintColor={c.primary} onRefresh={async () => { setRefreshing(true); await load(); setRefreshing(false); }} />}
      ListEmptyComponent={<Empty icon="🔍" title="Nothing matches yet" text="Try another word, city or category." />}
      renderItem={({ item }) => <View style={{ flex: 1 / 2 }}><Card item={item} {...ctx} /></View>} />
  );
}

function Detail({ item, onBack, ...ctx }: Ctx & { item: Item; onBack: () => void }) {
  const { user, cur, icons, config, favIds, toggleFav, say } = ctx;
  const [phone, setPhone] = useState("");
  const showPhone = async () => {
    if (!user) return say("Log in to see the number");
    try { setPhone((await api<{ phone: string }>(`/items/${item.id}/contact`)).phone); } catch (e) { say((e as Error).message); }
  };
  return (
    <View style={{ flex: 1 }}>
      <ScrollView contentContainerStyle={{ paddingBottom: 110 }}>
        <View>
          <Thumb item={item} icons={icons} height={260} />
          <Pressable onPress={onBack} style={s.backBtn} accessibilityLabel="Back"><Text style={{ fontSize: 18 }}>‹</Text></Pressable>
          <Pressable onPress={() => Share.share({ message: `${item.title} · ${money(item.price, cur)} on ${theme.brandName}` })} style={s.shareBtn} accessibilityLabel="Share"><Text>↗</Text></Pressable>
        </View>
        <View style={{ padding: 16, gap: 8 }}>
          <Text style={[s.price, { fontSize: 26, color: c.primary }]}>{money(item.price, cur)}</Text>
          <Text style={[s.h1, { fontFamily }]}>{item.title}</Text>
          <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 6 }}>
            {item.featured && <Text style={[s.pill, { backgroundColor: c.accent, color: c.onAccent, borderColor: c.accent }]}>★ Featured</Text>}
            <Text style={s.pill}>{icons[item.category]} {item.category}</Text>
            <Text style={s.pill}>📍 {item.city}</Text>
            <Text style={s.pill}>🕒 {timeAgo(item.created_at)}</Text>
          </View>
          <Text style={s.section}>Description</Text>
          <Text style={{ color: c.text, lineHeight: 21 }}>{item.description || "No description."}</Text>
          {item.seller && (
            <View style={s.sellerCard}>
              <View style={s.avatar}><Text style={{ color: c.onPrimary, fontWeight: "800" }}>{item.seller.name.split(" ").map((p) => p[0]).join("").slice(0, 2)}</Text></View>
              <View style={{ flex: 1 }}>
                <Text style={{ fontWeight: "700", color: c.text }}>{item.seller.name}</Text>
                <Text style={s.meta}>Member since {item.seller.member_since}{item.seller.verified ? "  ·  ✓ Phone verified" : ""}</Text>
              </View>
            </View>
          )}
          {!!config?.safety_tips.length && (
            <View style={s.tips}>
              <Text style={{ fontWeight: "700", color: c.text, marginBottom: 4 }}>🛡️ Stay safe</Text>
              {config.safety_tips.map((t) => <Text key={t} style={{ color: c.text, marginVertical: 2 }}>• {t}</Text>)}
            </View>
          )}
        </View>
      </ScrollView>
      <SafeAreaView edges={["bottom"]} style={s.ctaBar}>
        <Pressable style={s.iconBtn} onPress={() => toggleFav(item.id)} accessibilityLabel="Save"><Text style={{ fontSize: 20, color: c.danger }}>{favIds.has(item.id) ? "♥" : "♡"}</Text></Pressable>
        <Pressable style={[s.btn, { flex: 1 }]} onPress={() => say("Chat comes in a later release")}><Text style={s.btnText}>💬 Chat</Text></Pressable>
        <Pressable style={[s.btnPrimary, { flex: 1.4 }]} onPress={showPhone}><Text style={s.btnPrimaryText} numberOfLines={1}>📞 {phone || item.seller?.phone_masked || "Call"}</Text></Pressable>
      </SafeAreaView>
    </View>
  );
}

function Post({ user, categories, icons, config, say, onDone, needLogin }: Ctx & { onDone: () => void; needLogin: () => void }) {
  const [step, setStep] = useState(0);
  const [form, setForm] = useState({ category_id: 0, title: "", description: "", price: "", city: user?.city || config?.cities[0] || "" });
  if (!user) return <Empty icon="🔐" title="Log in to sell" text="Posting takes less than a minute." action={["Log in", needLogin]} />;
  const submit = async () => {
    try {
      await api("/items", { method: "POST", body: { ...form, price: Number(form.price) || 0 } });
      say("Posted! It goes live after review");
      setStep(0); setForm({ ...form, title: "", description: "", price: "" });
      onDone();
    } catch (e) { say((e as Error).message); }
  };
  const label = config?.item_label.toLowerCase() || "item";
  return (
    <ScrollView contentContainerStyle={{ padding: 16, gap: 14 }} keyboardShouldPersistTaps="handled">
      <Text style={[s.h1, { fontFamily }]}>Sell your {label}</Text>
      <View style={{ flexDirection: "row", gap: 6 }}>{[0, 1, 2].map((i) => <View key={i} style={[s.step, i <= step && { backgroundColor: c.primary }]} />)}</View>
      {step === 0 && (<>
        <Text style={s.meta}>Step 1 of 3 · Choose a category</Text>
        <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 10 }}>
          {categories.map((cat) => (
            <Pressable key={cat.id} style={[s.catTile, { width: "30%" }]} onPress={() => { setForm({ ...form, category_id: cat.id }); setStep(1); }}>
              <Text style={{ fontSize: 28 }}>{icons[cat.name] || "🏷️"}</Text><Text style={s.catText}>{cat.name}</Text>
            </Pressable>))}
        </View>
      </>)}
      {step === 1 && (<>
        <Text style={s.meta}>Step 2 of 3 · Describe it</Text>
        <Field label="Title" value={form.title} onChange={(v) => setForm({ ...form, title: v })} placeholder="e.g. iPhone 13, 128 GB, with bill"
          error={form.title && form.title.trim().length < 5 ? "Use at least 5 characters" : ""} />
        <Field label="Description" value={form.description} onChange={(v) => setForm({ ...form, description: v })} placeholder="Condition, age, what is included" multiline />
        <Buttons back={() => setStep(0)} next={() => setStep(2)} disabled={form.title.trim().length < 5} />
      </>)}
      {step === 2 && (<>
        <Text style={s.meta}>Step 3 of 3 · Price and place</Text>
        <Field label={`Price (${config?.currency || "INR"})`} value={form.price} onChange={(v) => setForm({ ...form, price: v.replace(/[^0-9]/g, "") })} keyboard="numeric" />
        <Text style={s.label}>City</Text>
        <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 6 }}>
          {(config?.cities || []).map((x) => (
            <Pressable key={x} onPress={() => setForm({ ...form, city: x })} style={[s.chip, form.city === x && s.chipOn]}>
              <Text style={{ color: form.city === x ? c.onPrimary : c.text }}>{x}</Text></Pressable>))}
        </View>
        <Buttons back={() => setStep(1)} next={submit} nextLabel="Post now" disabled={!form.price} />
      </>)}
    </ScrollView>
  );
}

function Field({ label, value, onChange, placeholder, error, multiline, keyboard }:
  { label: string; value: string; onChange: (v: string) => void; placeholder?: string; error?: string; multiline?: boolean; keyboard?: "numeric" }) {
  return (
    <View style={{ gap: 4 }}>
      <Text style={s.label}>{label}</Text>
      <TextInput style={[s.input, multiline && { height: 110, textAlignVertical: "top" }]} value={value} onChangeText={onChange}
        placeholder={placeholder} placeholderTextColor={c.muted} multiline={multiline} keyboardType={keyboard} accessibilityLabel={label} />
      {!!error && <Text style={{ color: c.danger, fontSize: 13 }}>{error}</Text>}
    </View>
  );
}

function Buttons({ back, next, nextLabel = "Next", disabled }: { back: () => void; next: () => void; nextLabel?: string; disabled?: boolean }) {
  return (
    <View style={{ flexDirection: "row", gap: 10 }}>
      <Pressable style={[s.btn, { flex: 1 }]} onPress={back}><Text style={s.btnText}>Back</Text></Pressable>
      <Pressable style={[s.btnPrimary, { flex: 2 }, disabled && { opacity: 0.45 }]} disabled={disabled} onPress={next}><Text style={s.btnPrimaryText}>{nextLabel}</Text></Pressable>
    </View>
  );
}

function Favourites(ctx: Ctx) {
  const [items, setItems] = useState<Item[] | null>(null);
  useEffect(() => { if (ctx.user) api<Item[]>("/favourites").then(setItems).catch(() => setItems([])); }, [ctx.user, ctx.favIds]);
  if (!ctx.user) return <Empty icon="♡" title="Log in to see saved items" />;
  if (items === null) return <ActivityIndicator color={c.primary} style={{ marginTop: 32 }} />;
  return (
    <FlatList data={items} keyExtractor={(i) => String(i.id)} numColumns={2}
      ListHeaderComponent={<Text style={[s.h1, { padding: 12, fontFamily }]}>Saved</Text>}
      columnWrapperStyle={{ gap: 10, paddingHorizontal: 12 }} contentContainerStyle={{ gap: 10, paddingBottom: 24 }}
      ListEmptyComponent={<Empty icon="♡" title="No saved items yet" text="Tap the heart on any listing to keep it here." />}
      renderItem={({ item }) => <View style={{ flex: 1 / 2 }}><Card item={item} {...ctx} /></View>} />
  );
}

const STATUS: Record<string, [string, string]> = { active: ["Live", c.success], pending: ["Under review", c.warning], sold: ["Sold", c.muted], removed: ["Removed", c.danger] };

function Account({ user, onUser, say, ...ctx }: Ctx & { onUser: (u: User | null) => void }) {
  const [email, setEmail] = useState("{{user_email}}");
  const [password, setPassword] = useState("");
  const [mine, setMine] = useState<Item[] | null>(null);
  const load = useCallback(() => { api<Item[]>("/my/items").then(setMine).catch(() => setMine([])); }, []);
  useEffect(() => { if (user) load(); }, [user, load]);
  const counts = useMemo(() => (mine || []).reduce<Record<string, number>>((a, i) => ({ ...a, [i.status]: (a[i.status] || 0) + 1 }), {}), [mine]);
  if (!user) {
    const login = async () => {
      try {
        const r = await api<{ token: string; user: User }>("/auth/login", { method: "POST", body: { email, password } });
        setToken(r.token); onUser(r.user);
      } catch (e) { say((e as Error).message); }
    };
    return (
      <ScrollView contentContainerStyle={{ padding: 20, gap: 14 }} keyboardShouldPersistTaps="handled">
        <View style={[s.avatar, { width: 64, height: 64, borderRadius: 32 }]}><Text style={{ color: c.onPrimary, fontSize: 28, fontWeight: "900" }}>{theme.brandName[0]}</Text></View>
        <Text style={[s.h1, { fontFamily }]}>Welcome to {theme.brandName}</Text>
        <Field label="Email" value={email} onChange={setEmail} />
        <View style={{ gap: 4 }}><Text style={s.label}>Password</Text>
          <TextInput style={s.input} secureTextEntry value={password} onChangeText={setPassword} onSubmitEditing={login} accessibilityLabel="Password" /></View>
        <Pressable style={s.btnPrimary} onPress={login}><Text style={s.btnPrimaryText}>Log in</Text></Pressable>
        <Text style={s.meta}>Demo: {{user_email}} / {{user_password}}</Text>
      </ScrollView>
    );
  }
  const setStatus = async (i: Item, status: string) => {
    try { await api(`/my/items/${i.id}`, { method: "PATCH", body: { status } }); load(); say(status === "sold" ? "Marked as sold" : "Live again"); }
    catch (e) { say((e as Error).message); }
  };
  return (
    <ScrollView contentContainerStyle={{ padding: 16, gap: 12 }}>
      <View style={s.sellerCard}>
        <View style={[s.avatar, { width: 52, height: 52, borderRadius: 26 }]}><Text style={{ color: c.onPrimary, fontWeight: "800", fontSize: 18 }}>{user.name.split(" ").map((p) => p[0]).join("").slice(0, 2)}</Text></View>
        <View style={{ flex: 1 }}><Text style={[s.h2, { fontFamily }]}>{user.name}</Text><Text style={s.meta}>{user.city} · member since {user.member_since}</Text></View>
        <Pressable onPress={() => { setToken(""); onUser(null); }} style={s.btn}><Text style={s.btnText}>Log out</Text></Pressable>
      </View>
      <View style={{ flexDirection: "row", gap: 8 }}>
        {(["active", "pending", "sold"] as const).map((k) => (
          <View key={k} style={[s.stat]}><Text style={{ fontSize: 22, fontWeight: "800", color: STATUS[k][1] }}>{counts[k] || 0}</Text><Text style={s.meta}>{STATUS[k][0]}</Text></View>))}
      </View>
      <Text style={s.h2}>My {ctx.config?.items_label.toLowerCase() || "listings"}</Text>
      {mine === null ? <ActivityIndicator color={c.primary} /> : mine.length ? mine.map((i) => (
        <View key={i.id} style={s.row}>
          <Text style={{ fontSize: 26 }}>{ctx.icons[i.category] || "🏷️"}</Text>
          <View style={{ flex: 1 }}>
            <Text style={{ fontWeight: "600", color: c.text }} numberOfLines={1}>{i.title}</Text>
            <Text style={s.meta}>{money(i.price, ctx.cur)} · <Text style={{ color: STATUS[i.status]?.[1], fontWeight: "700" }}>{STATUS[i.status]?.[0] || i.status}</Text></Text>
          </View>
          {(i.status === "active" || i.status === "sold") && (
            <Pressable style={s.btnSmall} onPress={() => setStatus(i, i.status === "sold" ? "active" : "sold")}>
              <Text style={s.btnText}>{i.status === "sold" ? "Relist" : "Sold ✓"}</Text></Pressable>)}
        </View>
      )) : <Empty icon="📦" title="Nothing posted yet" text="Your listings and their review status appear here." />}
    </ScrollView>
  );
}

function Empty({ icon, title, text, action }: { icon: string; title: string; text?: string; action?: [string, () => void] }) {
  return (
    <View style={{ alignItems: "center", padding: 40, gap: 6 }}>
      <Text style={{ fontSize: 44 }}>{icon}</Text>
      <Text style={[s.h2, { textAlign: "center" }]}>{title}</Text>
      {!!text && <Text style={[s.meta, { textAlign: "center" }]}>{text}</Text>}
      {action && <Pressable style={[s.btnPrimary, { marginTop: 10, paddingHorizontal: 24 }]} onPress={action[1]}><Text style={s.btnPrimaryText}>{action[0]}</Text></Pressable>}
    </View>
  );
}

// Larger text when the theme asks for it (e.g. for older users); the phone's own font size still applies.
function scaled<T extends object>(styles: T): T {
  const scale = theme.textScale as number;
  if (scale === 1) return styles;
  const out: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(styles) as [string, { fontSize?: number }][]) {
    out[k] = v.fontSize ? { ...v, fontSize: Math.round(v.fontSize * scale) } : v;
  }
  return out as T;
}

const s = scaled(StyleSheet.create({
  safe: { flex: 1, backgroundColor: c.background },
  offline: { backgroundColor: c.danger, color: "#fff", padding: 10, fontSize: 13 },
  hero: { backgroundColor: c.primary, padding: 16, gap: 10, borderBottomLeftRadius: R.card, borderBottomRightRadius: R.card },
  brand: { color: c.onPrimary, fontSize: 22, fontWeight: "800" },
  cityChip: { backgroundColor: "rgba(255,255,255,0.18)", paddingVertical: 6, paddingHorizontal: 12, borderRadius: R.pill },
  searchBox: { flexDirection: "row", alignItems: "center", gap: 8, backgroundColor: c.surface, borderRadius: R.control, paddingHorizontal: 12 },
  catTile: { alignItems: "center", gap: 4, backgroundColor: c.surface, borderRadius: R.card, borderWidth: 1, borderColor: c.border, paddingVertical: 10, paddingHorizontal: 8, minWidth: 84 },
  catTileOn: { borderColor: c.primary, borderWidth: 2 },
  catText: { fontSize: 13, fontWeight: "600", color: c.text },
  h1: { fontSize: 24, fontWeight: "800", color: c.text },
  h2: { fontSize: 18, fontWeight: "700", color: c.text },
  section: { fontSize: 16, fontWeight: "700", color: c.text, marginTop: 8 },
  meta: { color: c.muted, fontSize: 13 },
  label: { color: c.muted, fontSize: 13, fontWeight: "600" },
  price: { fontWeight: "800", fontSize: 17, color: c.text },
  card: { backgroundColor: c.surface, borderRadius: R.card, borderWidth: 1, borderColor: c.border, overflow: "hidden" },
  cardTitle: { color: c.text, fontSize: 14, lineHeight: 18 },
  featured: { position: "absolute", top: 8, left: 8, backgroundColor: c.accent, color: c.onAccent, fontSize: 11, fontWeight: "800", paddingHorizontal: 6, paddingVertical: 2, borderRadius: R.pill, overflow: "hidden" },
  heart: { position: "absolute", top: 6, right: 6, backgroundColor: c.surface, width: 30, height: 30, borderRadius: 15, alignItems: "center", justifyContent: "center" },
  pill: { borderWidth: 1, borderColor: c.border, borderRadius: R.pill, paddingHorizontal: 10, paddingVertical: 4, fontSize: 13, color: c.text, overflow: "hidden" },
  sellerCard: { flexDirection: "row", alignItems: "center", gap: 12, backgroundColor: c.surface, borderRadius: R.card, borderWidth: 1, borderColor: c.border, padding: 12, marginTop: 8 },
  avatar: { width: 44, height: 44, borderRadius: 22, backgroundColor: c.primary, alignItems: "center", justifyContent: "center" },
  tips: { backgroundColor: c.surface, borderRadius: R.card, borderWidth: 1, borderColor: c.border, padding: 12, marginTop: 4 },
  backBtn: { position: "absolute", top: 12, left: 12, width: 38, height: 38, borderRadius: 19, backgroundColor: c.surface, alignItems: "center", justifyContent: "center" },
  shareBtn: { position: "absolute", top: 12, right: 12, width: 38, height: 38, borderRadius: 19, backgroundColor: c.surface, alignItems: "center", justifyContent: "center" },
  ctaBar: { position: "absolute", left: 0, right: 0, bottom: 0, flexDirection: "row", gap: 8, padding: 12, backgroundColor: c.surface, borderTopWidth: 1, borderColor: c.border },
  iconBtn: { width: 48, alignItems: "center", justifyContent: "center", borderRadius: R.control, borderWidth: 1, borderColor: c.border },
  btn: { borderWidth: 1, borderColor: c.border, backgroundColor: c.surface, borderRadius: R.control, paddingVertical: 12, paddingHorizontal: 14, alignItems: "center" },
  btnSmall: { borderWidth: 1, borderColor: c.border, borderRadius: R.control, paddingVertical: 6, paddingHorizontal: 10 },
  btnText: { color: c.text, fontWeight: "600" },
  btnPrimary: { backgroundColor: c.primary, borderRadius: R.control, paddingVertical: 13, paddingHorizontal: 14, alignItems: "center" },
  btnPrimaryText: { color: c.onPrimary, fontWeight: "700", fontSize: 15 },
  input: { backgroundColor: c.surface, borderWidth: 1, borderColor: c.border, borderRadius: R.control, padding: 12, color: c.text },
  chip: { borderWidth: 1, borderColor: c.border, borderRadius: R.pill, paddingVertical: 6, paddingHorizontal: 12, backgroundColor: c.surface },
  chipOn: { backgroundColor: c.primary, borderColor: c.primary },
  step: { flex: 1, height: 6, borderRadius: 3, backgroundColor: c.border },
  stat: { flex: 1, backgroundColor: c.surface, borderRadius: R.card, borderWidth: 1, borderColor: c.border, padding: 10, alignItems: "center" },
  row: { flexDirection: "row", alignItems: "center", gap: 10, backgroundColor: c.surface, borderRadius: R.control, borderWidth: 1, borderColor: c.border, padding: 10 },
  tabs: { flexDirection: "row", borderTopWidth: 1, borderColor: c.border, backgroundColor: c.surface },
  tab: { flex: 1, paddingTop: 8, paddingBottom: 6, alignItems: "center", gap: 2 },
  tabText: { color: c.muted, fontSize: 11 },
  sellBtn: { backgroundColor: c.accent, width: 40, height: 30, borderRadius: R.pill, alignItems: "center", justifyContent: "center" },
  toast: { position: "absolute", bottom: 90, alignSelf: "center", backgroundColor: c.text, paddingVertical: 10, paddingHorizontal: 16, borderRadius: R.control },
}));
