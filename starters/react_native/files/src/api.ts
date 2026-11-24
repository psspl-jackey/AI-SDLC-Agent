// API client. The backend runs on the computer that serves this app (port {{api_port}});
// Expo tells us that computer's address, so it works on a phone on the same Wi-Fi and on the emulator.
import Constants from "expo-constants";

const host = (Constants.expoConfig?.hostUri || "localhost").split(":")[0];
export const API_URL = `http://${host}:{{api_port}}`;

export type User = { id: number; name: string; email: string; role: string; city: string; member_since: number };
export type Seller = { id: number; name: string; member_since: number; phone_masked: string; verified: boolean };
export type Category = { id: number; name: string };
export type Item = {
  id: number; title: string; description: string; price: number; city: string; image_url: string;
  category_id: number; category: string; seller: Seller | null; status: string; featured: boolean;
  created_at: string | null;
};
export type AppConfig = {
  app_name: string; item_label: string; items_label: string; currency: string; cities: string[];
  tagline: string; category_icons: Record<string, string>; safety_tips: string[];
};

let token = ""; // kept in memory for the demo; use secure storage (Keychain / Keystore) in the real app
export const setToken = (t: string) => { token = t; };

export async function api<T>(path: string, options: { method?: string; body?: unknown } = {}): Promise<T> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (token) headers.Authorization = `Bearer ${token}`;
  const res = await fetch(`${API_URL}${path}`, {
    method: options.method || "GET", headers,
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error((data as { detail?: string }).detail || `Request failed (${res.status})`);
  return data as T;
}

export const money = (value: number, currency: string) => `${currency === "INR" ? "₹" : currency + " "}${Math.round(value).toLocaleString("en-IN")}`;
