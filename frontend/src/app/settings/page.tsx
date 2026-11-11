"use client";
import { useCallback, useEffect, useState } from "react";
import { api, errMsg } from "@/lib/api";
import { useToast } from "@/components/Shell";

export default function Settings() {
  const toast = useToast();
  const [st, setSt] = useState<Awaited<ReturnType<typeof api.status>> | null>(null), [id, setId] = useState(""), [secret, setSecret] = useState(""), [busy, setBusy] = useState(false);
  const load = useCallback(() => { api.status().then(setSt).catch(e => toast(errMsg(e), "err")); }, [toast]);
  useEffect(load, [load]);
  async function connect(e: React.FormEvent) {
    e.preventDefault(); setBusy(true);
    try { await api.connect(id.trim(), secret.trim()); setSecret(""); setId(""); toast("PayPal Sandbox connected"); load(); } catch (er) { toast(errMsg(er), "err"); } finally { setBusy(false); }
  }
  return (
    <>
      <header className="page-head"><div><h1>Settings</h1><p className="sub">Connect your PayPal Sandbox app. Your secret is encrypted on the server and never shown again.</p></div></header>
      {st && <p>Data source: <strong>{st.label}</strong>{st.mode === "demo" && " — sample data from a built-in simulator. Connect Sandbox credentials below to use real PayPal Sandbox data."} · {st.transactions_stored} transactions stored</p>}
      <form className="stack narrow" onSubmit={connect}>
        <label>Sandbox Client ID<input required value={id} onChange={e => setId(e.target.value)} autoComplete="off" /></label>
        <label>Sandbox Client Secret<input required type="password" value={secret} onChange={e => setSecret(e.target.value)} autoComplete="off" /></label>
        <small>Find both at developer.paypal.com under Apps & Credentials, with the Sandbox toggle on. We check them with PayPal before saving.</small>
        <div className="row"><button className="approve" disabled={busy}>{busy ? "Checking with PayPal…" : "Connect Sandbox"}</button>
          {st?.connected_account && <button type="button" className="ghost" onClick={async () => { await api.disconnect(); toast("Disconnected"); load(); }}>Disconnect</button>}</div>
      </form>
      <h2>Webhooks</h2>
      <p className="sub">To track invoice payments automatically, add a webhook in your PayPal app pointing to <code>/api/v1/webhooks/paypal</code> on your backend URL (HTTPS), subscribe to Invoicing events, and set <code>PAYPAL_WEBHOOK_ID</code> on the server. Unsigned or forged events are rejected.</p>
    </>
  );
}
