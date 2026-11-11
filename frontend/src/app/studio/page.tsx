"use client";
import dynamic from "next/dynamic";
import { useEffect, useState } from "react";
import { api, errMsg, Invoice } from "@/lib/api";

const StudioBoard = dynamic(() => import("@/components/StudioBoard"), { ssr: false, loading: () => <div className="skeleton"><div /></div> });

export default function StudioPage() {
  const [d, setD] = useState<Awaited<ReturnType<typeof api.dataset>> | null>(null), [cur, setCur] = useState<string>(), [mode, setMode] = useState<"edit" | "view">("view"), [err, setErr] = useState(""), [invoices, setInvoices] = useState<Invoice[]>([]);
  useEffect(() => { api.invoices().then(setInvoices).catch(() => {}); }, []);
  useEffect(() => { setD(null); api.dataset(cur).then(setD).catch(e => setErr(errMsg(e))); }, [cur]);
  if (err) return <p className="err" role="alert">{err}</p>;
  return (
    <div className="studio-page">
      <header className="page-head"><div><h1>Analytics Studio</h1>
        <p className="sub">Build your own dashboard from your PayPal data: drag widgets, add charts, click a bar to cross-filter. Powered by AG Studio.</p></div>
        <div className="row">
          {d && d.currencies.length > 1 && <div className="tabs" role="tablist" aria-label="Currency">{d.currencies.map(c => <button key={c} role="tab" aria-selected={c === d.currency} onClick={() => setCur(c)}>{c}</button>)}</div>}
          <button className="ghost" onClick={() => setMode(m => (m === "edit" ? "view" : "edit"))}>{mode === "edit" ? "Preview" : "Edit dashboard"}</button></div></header>
      {!d ? <div className="skeleton" aria-busy="true"><div /><div /></div> : d.transactions.length === 0 ?
        <section className="empty"><h2>No data yet</h2><p>Sync from PayPal on the Overview page, then come back.</p></section> :
        <div className="studio-frame"><StudioBoard key={d.currency} rows={d.transactions} mode={mode} invoices={invoices} currency={d.currency} /></div>}
      <p className="fine">One currency at a time, so charts never add euros to dollars.</p>
    </div>
  );
}
