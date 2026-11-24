// API client for the starter backend. The backend runs on the same machine, port {{api_port}}.
export const API_URL =
  typeof window === "undefined" ? "http://localhost:{{api_port}}" : `http://${window.location.hostname}:{{api_port}}`;

export type User = { id: number; name: string; email: string; role: string; city: string; active: boolean; member_since: number };
export type Seller = { id: number; name: string; member_since: number; phone_masked: string; verified: boolean };
export type Category = { id: number; name: string };
export type Item = {
  id: number; title: string; description: string; price: number; city: string; image_url: string;
  category_id: number; category: string; seller: Seller | null;
  status: string; featured: boolean; created_at: string | null;
};
export type AppConfig = {
  app_name: string; item_label: string; items_label: string; currency: string; cities: string[];
  tagline: string; category_icons: Record<string, string>; safety_tips: string[];
};

const TOKEN_KEY = "{{app_slug}}-{{surface}}-token";

export function getToken(): string {
  try { return localStorage.getItem(TOKEN_KEY) || ""; } catch { return ""; }
}

export function setToken(token: string): void {
  try { token ? localStorage.setItem(TOKEN_KEY, token) : localStorage.removeItem(TOKEN_KEY); } catch { /* private mode */ }
}

export async function api<T>(path: string, options: { method?: string; body?: unknown } = {}): Promise<T> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  const token = getToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  const res = await fetch(`${API_URL}${path}`, {
    method: options.method || "GET", headers,
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error((data && (data as { detail?: string }).detail) || `Request failed (${res.status})`);
  return data as T;
}

export function money(value: number, currency: string): string {
  try {
    return new Intl.NumberFormat("en-IN", { style: "currency", currency, maximumFractionDigits: 0 }).format(value);
  } catch {
    return `${currency} ${value}`;
  }
}
