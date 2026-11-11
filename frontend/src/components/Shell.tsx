"use client";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { api, tokenStore } from "@/lib/api";

const ToastCtx = createContext<(msg: string, kind?: "ok" | "err") => void>(() => {});
export const useToast = () => useContext(ToastCtx);

const NAV = [["/", "Overview"], ["/transactions", "Transactions"], ["/invoices", "Invoices"], ["/studio", "Analytics Studio"], ["/assistant", "Assistant"],
  ["/approvals", "Approvals"], ["/insights", "Forecast & alerts"], ["/settings", "Settings"]] as const;

export default function Shell({ children }: { children: React.ReactNode }) {
  const path = usePathname(), router = useRouter();
  const [ready, setReady] = useState(false), [mode, setMode] = useState<string>(""), [pending, setPending] = useState(0);
  const [toasts, setToasts] = useState<{ id: number; msg: string; kind: string }[]>([]);
  const toast = useCallback((msg: string, kind: "ok" | "err" = "ok") => {
    const id = Date.now() + Math.random(); setToasts(t => [...t, { id, msg, kind }]); setTimeout(() => setToasts(t => t.filter(x => x.id !== id)), 5000);
  }, []);
  const isLogin = path === "/login";
  useEffect(() => {
    if (isLogin) { setReady(true); return; }
    if (!tokenStore.get()) { router.replace("/login"); return; }
    setReady(true);
    api.status().then(s => setMode(s.label)).catch(() => {});
    api.actions("PENDING").then(a => setPending(a.length)).catch(() => {});
  }, [isLogin, router, path]);
  if (!ready) return null;
  if (isLogin) return <ToastCtx.Provider value={toast}>{children}<Toasts toasts={toasts} /></ToastCtx.Provider>;
  return (
    <ToastCtx.Provider value={toast}>
      <div className="app">
        <nav className="rail" aria-label="Main">
          <div className="brand">PayPilot</div>
          <ul>{NAV.map(([href, label]) => (
            <li key={href}><Link href={href} aria-current={path === href ? "page" : undefined}>{label}
              {href === "/approvals" && pending > 0 && <span className="count" aria-label={`${pending} waiting`}>{pending}</span>}</Link></li>))}
          </ul>
          <div className="rail-foot">
            <span className={`mode ${mode.startsWith("DEMO") ? "demo" : ""}`}>{mode || "…"}</span>
            <button className="link" onClick={() => { tokenStore.clear(); router.replace("/login"); }}>Sign out</button>
          </div>
        </nav>
        <main className="main">{children}</main>
      </div>
      <Toasts toasts={toasts} />
    </ToastCtx.Provider>
  );
}

function Toasts({ toasts }: { toasts: { id: number; msg: string; kind: string }[] }) {
  return <div className="toasts" role="status" aria-live="polite">{toasts.map(t => <div key={t.id} className={`toast ${t.kind}`}>{t.msg}</div>)}</div>;
}
