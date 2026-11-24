"use client";
// Shared UI kit for the website and the admin panel. Every colour, radius and font comes from theme.ts.
import { useCallback, useState, type ReactNode } from "react";
import { theme } from "./theme";

const c = theme.colors;
const r = theme.radius;
const sp = theme.space;

export const baseCss = `
*{box-sizing:border-box}
html,body{margin:0;background:${c.background};color:${c.text};font-family:${theme.fontFamily};-webkit-font-smoothing:antialiased}
body{zoom:${theme.textScale}}
a{color:${c.primary}}
button,input,select,textarea{font:inherit;color:inherit}
:focus-visible{outline:3px solid ${c.accent};outline-offset:2px}
.btn{display:inline-flex;align-items:center;justify-content:center;gap:6px;padding:${sp * 0.75}px ${sp * 1.25}px;border-radius:${r.control}px;border:1px solid ${c.border};background:${c.surface};cursor:pointer;font-weight:600;white-space:nowrap}
.btn:hover{border-color:${c.muted}}
.btn:disabled{opacity:.5;cursor:not-allowed}
.btn-primary{background:${c.primary};color:${c.onPrimary};border-color:${c.primary}}
.btn-primary:hover{filter:brightness(1.08);border-color:${c.primary}}
.btn-accent{background:${c.accent};color:${c.onAccent};border-color:${c.accent}}
.btn-danger{color:${c.danger};border-color:${c.danger}}
.btn-ghost{background:transparent;border-color:transparent}
.input{width:100%;color:${c.text};padding:${sp * 0.8}px ${sp}px;border-radius:${r.control}px;border:1px solid ${c.border};background:${c.surface}}
.input:focus{border-color:${c.primary};outline:none;box-shadow:0 0 0 3px ${c.primary}33}
.label{display:block;font-size:13px;font-weight:600;color:${c.muted};margin:0 0 4px}
.card{background:${c.surface};border:1px solid ${c.border};border-radius:${r.card}px}
.muted{color:${c.muted}}
.badge{display:inline-flex;align-items:center;gap:4px;font-size:12px;font-weight:700;padding:2px 8px;border-radius:${r.pill}px;background:${c.background};border:1px solid ${c.border}}
.badge-featured{background:${c.accent};color:${c.onAccent};border-color:${c.accent}}
.badge-active{color:${c.success};border-color:${c.success}55}
.badge-pending{color:${c.warning};border-color:${c.warning}55}
.badge-sold{color:${c.muted}}
.badge-removed{color:${c.danger};border-color:${c.danger}55}
.chip{display:inline-flex;align-items:center;gap:6px;padding:6px 12px;border-radius:${r.pill}px;border:1px solid ${c.border};background:${c.surface};cursor:pointer}
.chip.on{background:${c.primary};color:${c.onPrimary};border-color:${c.primary}}
.price{font-weight:800;font-size:20px;letter-spacing:-.01em}
.toasts{position:fixed;right:16px;bottom:16px;display:grid;gap:8px;z-index:50;max-width:min(380px,calc(100vw - 32px))}
.toast{padding:12px 14px;border-radius:${r.control}px;background:${c.text};color:#fff;box-shadow:0 8px 24px #0003}
.toast.error{background:${c.danger}}
.skeleton{background:linear-gradient(90deg,${c.border} 25%,${c.background} 50%,${c.border} 75%);background-size:200% 100%;animation:sk 1.2s infinite;border-radius:${r.card}px}
@keyframes sk{to{background-position:-200% 0}}
.empty{text-align:center;padding:48px 16px;color:${c.muted}}
.empty .icon{font-size:44px;margin-bottom:8px}
`;

export function Styles({ css = "" }: { css?: string }) {
  return <style dangerouslySetInnerHTML={{ __html: baseCss + css }} />;
}

// Soft colour per category so cards look different without real photos.
function hue(text: string): number {
  let h = 0;
  for (const ch of text) h = (h * 31 + ch.charCodeAt(0)) % 360;
  return h;
}

export function Thumb({ category, icon, imageUrl, height = 160, rounded = true }:
  { category: string; icon?: string; imageUrl?: string; height?: number; rounded?: boolean }) {
  const h = hue(category);
  const style = {
    height, borderRadius: rounded ? `${r.card}px ${r.card}px 0 0` : r.card, display: "grid", placeItems: "center",
    background: `linear-gradient(135deg, hsl(${h} 70% 92%), hsl(${(h + 40) % 360} 65% 82%))`, fontSize: height * 0.32,
    overflow: "hidden",
  } as const;
  return imageUrl
    ? <img src={imageUrl} alt="" style={{ ...style, width: "100%", objectFit: "cover" }} />
    : <div style={style} aria-hidden>{icon || "🛍️"}</div>;
}

export function timeAgo(iso: string | null): string {
  if (!iso) return "";
  const then = new Date(iso.endsWith("Z") || iso.includes("+") ? iso : iso + "Z").getTime();
  const mins = Math.max(1, Math.round((Date.now() - then) / 60000));
  if (mins < 60) return `${mins} min ago`;
  const hours = Math.round(mins / 60);
  if (hours < 24) return `${hours} h ago`;
  const days = Math.round(hours / 24);
  return days === 1 ? "yesterday" : `${days} days ago`;
}

const STATUS_LABEL: Record<string, string> = { active: "Live", pending: "Under review", sold: "Sold", removed: "Removed" };

export function StatusBadge({ status }: { status: string }) {
  return <span className={`badge badge-${status}`}>{STATUS_LABEL[status] || status}</span>;
}

export type Toast = { id: number; text: string; error?: boolean };

export function useToasts() {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const push = useCallback((text: string, error = false) => {
    const id = Date.now() + Math.random();
    setToasts((t) => [...t, { id, text, error }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 3500);
  }, []);
  const view = (
    <div className="toasts" role="status" aria-live="polite">
      {toasts.map((t) => <div key={t.id} className={`toast${t.error ? " error" : ""}`}>{t.text}</div>)}
    </div>
  );
  return { push, view };
}

export function Empty({ icon, title, children }: { icon: string; title: string; children?: ReactNode }) {
  return (
    <div className="empty">
      <div className="icon" aria-hidden>{icon}</div>
      <div style={{ fontWeight: 700, color: c.text, marginBottom: 4 }}>{title}</div>
      {children}
    </div>
  );
}

export function Initials({ name, size = 40 }: { name: string; size?: number }) {
  const letters = name.split(" ").map((p) => p[0]).join("").slice(0, 2).toUpperCase();
  return (
    <div aria-hidden style={{ width: size, height: size, borderRadius: r.pill, background: c.primary, color: c.onPrimary,
      display: "grid", placeItems: "center", fontWeight: 800, fontSize: size * 0.38, flex: "none" }}>{letters}</div>
  );
}

export function BrandMark({ size = 36 }: { size?: number }) {
  return (
    <div aria-hidden style={{ width: size, height: size, borderRadius: r.control, background: c.primary, color: c.onPrimary,
      display: "grid", placeItems: "center", fontWeight: 900, fontSize: size * 0.5 }}>{theme.brandName[0]}</div>
  );
}
