// {{project_name}}: mobile app starter for Android and iOS (written by the AI SDLC Agent; tickets add features).
import { StatusBar } from "expo-status-bar";
import { useCallback, useEffect, useState } from "react";
import {
  ActivityIndicator, Alert, FlatList, Image, Pressable, SafeAreaView, ScrollView, StyleSheet, Text, TextInput, View,
} from "react-native";
import { api, API_URL, AppConfig, Category, Item, money, setToken, User } from "./src/api";

type Screen = "home" | "detail" | "favourites" | "post" | "account";

export default function App() {
  const [config, setConfig] = useState<AppConfig | null>(null);
  const [error, setError] = useState("");
  const [user, setUser] = useState<User | null>(null);
  const [screen, setScreen] = useState<Screen>("home");
  const [categories, setCategories] = useState<Category[]>([]);
  const [items, setItems] = useState<Item[]>([]);
  const [favourites, setFavourites] = useState<Item[]>([]);
  const [selected, setSelected] = useState<Item | null>(null);
  const [q, setQ] = useState("");
  const [categoryId, setCategoryId] = useState<number | null>(null);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams({ q, ...(categoryId ? { category_id: String(categoryId) } : {}) });
      setItems(await api<Item[]>(`/items?${params}`));
      setError("");
    } catch (e) {
      setError(`Cannot reach the backend at ${API_URL}: ${(e as Error).message}`);
    } finally {
      setLoading(false);
    }
  }, [q, categoryId]);

  useEffect(() => {
    api<AppConfig>("/config").then(setConfig).catch(() => undefined);
    api<Category[]>("/categories").then(setCategories).catch(() => undefined);
  }, []);
  useEffect(() => { load(); }, [categoryId]); // eslint-disable-line react-hooks/exhaustive-deps

  const cur = config?.currency || "INR";
  const needLogin = () => { setScreen("account"); };

  const openFavourites = async () => {
    if (!user) return needLogin();
    setFavourites(await api<Item[]>("/favourites"));
    setScreen("favourites");
  };

  return (
    <SafeAreaView style={s.safe}>
      <StatusBar style="dark" />
      <View style={s.header}>
        <Text style={s.title}>{config?.app_name || "Loading..."}</Text>
        {user && <Text style={s.muted}>Hi, {user.name.split(" ")[0]}</Text>}
      </View>
      {!!error && <Text style={s.error}>{error}</Text>}

      <View style={{ flex: 1 }}>
        {screen === "home" && (
          <View style={{ flex: 1 }}>
            <View style={s.row}>
              <TextInput style={[s.input, { flex: 1 }]} placeholder={`Search ${config?.items_label.toLowerCase() || ""}`}
                value={q} onChangeText={setQ} onSubmitEditing={load} returnKeyType="search" />
              <Pressable style={s.primary} onPress={load}><Text style={s.primaryText}>Go</Text></Pressable>
            </View>
            <ScrollView horizontal showsHorizontalScrollIndicator={false} style={s.chips} contentContainerStyle={{ gap: 6, paddingHorizontal: 12 }}>
              <Chip label="All" active={categoryId === null} onPress={() => setCategoryId(null)} />
              {categories.map((c) => <Chip key={c.id} label={c.name} active={categoryId === c.id} onPress={() => setCategoryId(c.id)} />)}
            </ScrollView>
            {loading ? <ActivityIndicator style={{ marginTop: 24 }} /> : (
              <FlatList data={items} keyExtractor={(i) => String(i.id)} contentContainerStyle={{ padding: 12, gap: 10 }}
                onRefresh={load} refreshing={loading}
                ListEmptyComponent={<Text style={s.muted}>Nothing found.</Text>}
                renderItem={({ item }) => <ItemCard item={item} currency={cur} onPress={() => { setSelected(item); setScreen("detail"); }} />} />
            )}
          </View>
        )}

        {screen === "detail" && selected && (
          <Detail item={selected} currency={cur} user={user} onLogin={needLogin} onBack={() => setScreen("home")} />
        )}

        {screen === "favourites" && (
          <FlatList data={favourites} keyExtractor={(i) => String(i.id)} contentContainerStyle={{ padding: 12, gap: 10 }}
            ListHeaderComponent={<Text style={s.h2}>Favourites</Text>}
            ListEmptyComponent={<Text style={s.muted}>No favourites yet. Open an item and tap Save.</Text>}
            renderItem={({ item }) => <ItemCard item={item} currency={cur} onPress={() => { setSelected(item); setScreen("detail"); }} />} />
        )}

        {screen === "post" && (user
          ? <PostForm categories={categories} city={user.city} label={config?.item_label || "Item"} onDone={() => setScreen("home")} />
          : <Account user={user} onUser={setUser} />)}

        {screen === "account" && <Account user={user} onUser={(u) => { setUser(u); if (u) setScreen("home"); }} />}
      </View>

      <View style={s.tabs}>
        <Tab label="Home" active={screen === "home"} onPress={() => setScreen("home")} />
        <Tab label="Favourites" active={screen === "favourites"} onPress={openFavourites} />
        <Tab label="Post" active={screen === "post"} onPress={() => setScreen("post")} />
        <Tab label={user ? "Account" : "Log in"} active={screen === "account"} onPress={() => setScreen("account")} />
      </View>
    </SafeAreaView>
  );
}

function Chip({ label, active, onPress }: { label: string; active: boolean; onPress: () => void }) {
  return (
    <Pressable onPress={onPress} style={[s.chip, active && s.chipActive]}>
      <Text style={active ? s.primaryText : undefined}>{label}</Text>
    </Pressable>
  );
}

function Tab({ label, active, onPress }: { label: string; active: boolean; onPress: () => void }) {
  return (
    <Pressable onPress={onPress} style={s.tab}>
      <Text style={[s.tabText, active && { color: "#2563eb", fontWeight: "700" }]}>{label}</Text>
    </Pressable>
  );
}

function ItemCard({ item, currency, onPress }: { item: Item; currency: string; onPress: () => void }) {
  return (
    <Pressable style={s.card} onPress={onPress}>
      {!!item.image_url && <Image source={{ uri: item.image_url }} style={s.thumb} />}
      <View style={{ flex: 1 }}>
        {item.featured && <Text style={s.badge}>Featured</Text>}
        <Text style={s.itemTitle} numberOfLines={2}>{item.title}</Text>
        <Text style={s.price}>{money(item.price, currency)}</Text>
        <Text style={s.muted}>{item.category} · {item.city}</Text>
      </View>
    </Pressable>
  );
}

function Detail({ item, currency, user, onLogin, onBack }:
  { item: Item; currency: string; user: User | null; onLogin: () => void; onBack: () => void }) {
  const save = async () => {
    if (!user) return onLogin();
    await api(`/favourites/${item.id}`, { method: "POST" });
    Alert.alert("Saved", "Added to your favourites");
  };
  const pay = async () => {
    if (!user) return onLogin();
    const r = await api<{ status: string; reference: string | null; message: string }>(
      "/payments/dummy", { method: "POST", body: { amount: 99, purpose: `Feature item ${item.id}` } });
    Alert.alert(r.status === "success" ? "Payment done" : "Payment failed", `${r.message}${r.reference ? `\nRef: ${r.reference}` : ""}`);
  };
  return (
    <ScrollView contentContainerStyle={{ padding: 12, gap: 8 }}>
      <Pressable onPress={onBack}><Text style={s.link}>‹ Back</Text></Pressable>
      {!!item.image_url && <Image source={{ uri: item.image_url }} style={s.hero} />}
      <Text style={s.h2}>{item.title}</Text>
      <Text style={[s.price, { fontSize: 22 }]}>{money(item.price, currency)}</Text>
      <Text style={s.muted}>{item.category} · {item.city} · Seller: {item.seller?.name}</Text>
      <Text>{item.description}</Text>
      <View style={s.row}>
        <Pressable style={s.secondary} onPress={save}><Text>Save</Text></Pressable>
        <Pressable style={s.primary} onPress={pay}><Text style={s.primaryText}>Feature for {money(99, currency)} (dummy pay)</Text></Pressable>
      </View>
    </ScrollView>
  );
}

function PostForm({ categories, city, label, onDone }: { categories: Category[]; city: string; label: string; onDone: () => void }) {
  const [title, setTitle] = useState("");
  const [price, setPrice] = useState("");
  const [description, setDescription] = useState("");
  const [categoryId, setCategoryId] = useState<number | null>(null);
  const submit = async () => {
    try {
      await api("/items", { method: "POST", body: { title, price: Number(price) || 0, description, category_id: categoryId, city } });
      Alert.alert("Posted", "It goes live after an admin approves it in the admin panel.");
      onDone();
    } catch (e) { Alert.alert("Could not post", (e as Error).message); }
  };
  return (
    <ScrollView contentContainerStyle={{ padding: 12, gap: 10 }}>
      <Text style={s.h2}>Post {label.toLowerCase()}</Text>
      <TextInput style={s.input} placeholder="Title" value={title} onChangeText={setTitle} />
      <TextInput style={s.input} placeholder="Price" keyboardType="numeric" value={price} onChangeText={setPrice} />
      <TextInput style={[s.input, { height: 90 }]} placeholder="Description" multiline value={description} onChangeText={setDescription} />
      <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 6 }}>
        {categories.map((c) => <Chip key={c.id} label={c.name} active={categoryId === c.id} onPress={() => setCategoryId(c.id)} />)}
      </View>
      <Pressable style={[s.primary, (!title || !categoryId) && { opacity: 0.5 }]} disabled={!title || !categoryId} onPress={submit}>
        <Text style={s.primaryText}>Post</Text>
      </Pressable>
    </ScrollView>
  );
}

function Account({ user, onUser }: { user: User | null; onUser: (u: User | null) => void }) {
  const [email, setEmail] = useState("{{user_email}}");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  if (user) {
    return (
      <View style={{ padding: 12, gap: 8 }}>
        <Text style={s.h2}>{user.name}</Text>
        <Text style={s.muted}>{user.email} · {user.city}</Text>
        <Pressable style={s.secondary} onPress={() => { setToken(""); onUser(null); }}><Text>Log out</Text></Pressable>
      </View>
    );
  }
  const login = async () => {
    try {
      const r = await api<{ token: string; user: User }>("/auth/login", { method: "POST", body: { email, password } });
      setToken(r.token);
      onUser(r.user);
    } catch (e) { setError((e as Error).message); }
  };
  return (
    <View style={{ padding: 12, gap: 10 }}>
      <Text style={s.h2}>Log in</Text>
      <TextInput style={s.input} autoCapitalize="none" keyboardType="email-address" value={email} onChangeText={setEmail} />
      <TextInput style={s.input} secureTextEntry placeholder="Password" value={password} onChangeText={setPassword} />
      <Pressable style={s.primary} onPress={login}><Text style={s.primaryText}>Log in</Text></Pressable>
      {!!error && <Text style={s.error}>{error}</Text>}
      <Text style={s.muted}>Demo user: {{user_email}} / {{user_password}}</Text>
    </View>
  );
}

const s = StyleSheet.create({
  safe: { flex: 1, backgroundColor: "#f5f7fa" },
  header: { paddingHorizontal: 12, paddingTop: 12, paddingBottom: 6, flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
  title: { fontSize: 20, fontWeight: "700" },
  h2: { fontSize: 20, fontWeight: "700", marginBottom: 4 },
  muted: { color: "#616e7c" },
  error: { color: "#b91c1c", paddingHorizontal: 12 },
  link: { color: "#2563eb", fontSize: 16 },
  row: { flexDirection: "row", gap: 6, paddingHorizontal: 12, alignItems: "center" },
  input: { backgroundColor: "#fff", borderWidth: 1, borderColor: "#cbd2d9", borderRadius: 8, padding: 10 },
  primary: { backgroundColor: "#2563eb", paddingVertical: 10, paddingHorizontal: 14, borderRadius: 8, alignItems: "center" },
  primaryText: { color: "#fff", fontWeight: "600" },
  secondary: { borderWidth: 1, borderColor: "#9aa5b1", paddingVertical: 10, paddingHorizontal: 14, borderRadius: 8 },
  chips: { flexGrow: 0, marginVertical: 8 },
  chip: { borderWidth: 1, borderColor: "#cbd2d9", borderRadius: 16, paddingVertical: 6, paddingHorizontal: 12, backgroundColor: "#fff" },
  chipActive: { backgroundColor: "#2563eb", borderColor: "#2563eb" },
  card: { backgroundColor: "#fff", borderRadius: 10, padding: 10, flexDirection: "row", gap: 10, borderWidth: 1, borderColor: "#e4e7eb" },
  thumb: { width: 88, height: 88, borderRadius: 8, backgroundColor: "#e4e7eb" },
  hero: { width: "100%", height: 220, borderRadius: 10, backgroundColor: "#e4e7eb" },
  badge: { alignSelf: "flex-start", backgroundColor: "#fde68a", paddingHorizontal: 6, borderRadius: 4, fontSize: 12, marginBottom: 2 },
  itemTitle: { fontSize: 16, fontWeight: "600" },
  price: { fontWeight: "700", marginTop: 2 },
  tabs: { flexDirection: "row", borderTopWidth: 1, borderColor: "#e4e7eb", backgroundColor: "#fff" },
  tab: { flex: 1, paddingVertical: 12, alignItems: "center" },
  tabText: { color: "#3e4c59" },
});
