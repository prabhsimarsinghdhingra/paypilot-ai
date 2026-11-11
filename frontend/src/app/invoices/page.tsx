"use client";
import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { api, DraftInput, errMsg, Invoice, money } from "@/lib/api";
import { useToast } from "@/components/Shell";

const blank = (): DraftInput => ({ recipient_email: "", recipient_name: "", currency: "USD", due_in_days: 14, note: "Thank you for your business.", items: [{ name: "", quantity: 1, unit_amount: 0, tax_percent: 0 }] });

export default function Invoices() {
  const toast = useToast();
  const [list, setList] = useState<Invoice[] | null>(null), [d, setD] = useState<DraftInput>(blank()), [pv, setPv] = useState<{ subtotal: number; tax: number; total: number } | null>(null), [busy, setBusy] = useState(false);
  const load = useCallback(() => { api.invoices().then(setList).catch(e => toast(errMsg(e), "err")); }, [toast]);
  useEffect(load, [load]);
  const valid = d.recipient_email.includes("@") && d.items.every(i => i.name && i.unit_amount > 0 && i.quantity > 0);
  useEffect(() => { if (!valid) { setPv(null); return; } const t = setTimeout(() => api.previewInvoice(d).then(setPv).catch(() => setPv(null)), 250); return () => clearTimeout(t); }, [d, valid]);
  const setItem = (n: number, k: string, v: string) => setD(x => ({ ...x, items: x.items.map((it, i) => i === n ? { ...it, [k]: k === "name" ? v : Number(v) } : it) }));
  async function create() {
    setBusy(true);
    try { const a = await api.createInvoice(d); a.status === "FAILED" ? toast(a.error || "PayPal rejected the draft", "err") : toast("Draft created in PayPal. It has not been sent."); setD(blank()); load(); }
    catch (e) { toast(errMsg(e), "err"); } finally { setBusy(false); }
  }
  async function request(i: Invoice, kind: "send" | "remind") {
    try { await (kind === "send" ? api.requestSend(i.id) : api.requestReminder(i.id)); toast("Queued for your approval"); } catch (e) { toast(errMsg(e), "err"); }
  }
  return (
    <>
      <header className="page-head"><div><h1>Invoices</h1><p className="sub">Creating a draft never emails your customer. Sending and reminders go through <Link href="/approvals">Approvals</Link>.</p></div></header>
      <div className="two wide-left">
        <section>
          <h2>All invoices</h2>
          {!list ? <div className="skeleton"><div /></div> : list.length === 0 ? <p className="sub">No invoices yet. Create one, or sync from PayPal on the Overview page.</p> :
            <table className="plain"><thead><tr><th>No.</th><th>Customer</th><th className="num">Total</th><th>Due</th><th>Status</th><th /></tr></thead>
              <tbody>{list.map(i => <tr key={i.id}><td>{i.number}</td><td>{i.customer || i.email}</td><td className="num">{money(i.total, i.currency)}</td>
                <td>{i.due_date ?? "—"}{i.days_overdue > 0 && <span className="sev high"> {i.days_overdue}d late</span>}</td><td><span className="chip">{i.status}</span></td>
                <td>{i.status === "DRAFT" && <button className="link" onClick={() => request(i, "send")}>Request send</button>}
                  {i.days_overdue > 0 && <button className="link" onClick={() => request(i, "remind")}>Request reminder</button>}</td></tr>)}</tbody></table>}
        </section>
        <section>
          <h2>New invoice</h2>
          <form className="stack" onSubmit={e => { e.preventDefault(); create(); }}>
            <label>Customer email<input type="email" required value={d.recipient_email} onChange={e => setD({ ...d, recipient_email: e.target.value })} /></label>
            <label>Customer name<input value={d.recipient_name} onChange={e => setD({ ...d, recipient_name: e.target.value })} /></label>
            <div className="row"><label>Currency<select value={d.currency} onChange={e => setD({ ...d, currency: e.target.value })}><option>USD</option><option>EUR</option><option>GBP</option></select></label>
              <label>Due in (days)<input type="number" min={0} max={365} value={d.due_in_days} onChange={e => setD({ ...d, due_in_days: Number(e.target.value) })} /></label></div>
            {d.items.map((it, n) => <fieldset key={n}><legend>Item {n + 1}</legend>
              <label>Description<input value={it.name} onChange={e => setItem(n, "name", e.target.value)} /></label>
              <div className="row"><label>Qty<input type="number" min={1} value={it.quantity} onChange={e => setItem(n, "quantity", e.target.value)} /></label>
                <label>Unit price<input type="number" min={0} step="0.01" value={it.unit_amount} onChange={e => setItem(n, "unit_amount", e.target.value)} /></label>
                <label>Tax %<input type="number" min={0} max={100} value={it.tax_percent} onChange={e => setItem(n, "tax_percent", e.target.value)} /></label></div></fieldset>)}
            <button type="button" className="link" onClick={() => setD(x => ({ ...x, items: [...x.items, { name: "", quantity: 1, unit_amount: 0, tax_percent: 0 }] }))}>Add another item</button>
            <aside className="preview" aria-label="Invoice preview"><h3>Preview</h3>
              {pv ? <dl><dt>Subtotal</dt><dd>{money(pv.subtotal, d.currency)}</dd><dt>Tax</dt><dd>{money(pv.tax, d.currency)}</dd><dt>Total</dt><dd><strong>{money(pv.total, d.currency)}</strong></dd></dl> : <p className="sub">Fill in the customer and items to see totals.</p>}</aside>
            <button className="approve" disabled={!valid || busy}>{busy ? "Creating…" : "Save as draft"}</button>
          </form>
        </section>
      </div>
    </>
  );
}
