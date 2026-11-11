"use client";
import { Suspense, useEffect, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import ActionSlip from "@/components/ActionSlip";
import { Action, api, errMsg, Invoice, ToolCall } from "@/lib/api";

type Msg = { role: "user" | "assistant"; text: string; tools?: ToolCall[]; actions?: Action[] };
const SUGGESTED = ["Find overdue invoices and prepare reminders", "How does this month compare with last month?", "Which payments failed and who should I follow up with?",
  "Who are my top customers?", "What's my revenue outlook for the next 4 weeks?", "Anything unusual in my payment activity?"];
const TOOL_LABEL: Record<string, string> = { get_transactions: "Read transactions", get_revenue_summary: "Calculated revenue", get_failed_payments: "Checked failed payments", get_pending_payments: "Checked pending payments",
  get_customer_insights: "Analysed customers", get_overdue_invoices: "Looked up overdue invoices", list_invoices: "Listed invoices", get_cashflow_forecast: "Ran cash-flow forecast",
  detect_transaction_anomalies: "Scanned for anomalies", propose_invoice_draft: "Proposed an invoice draft", propose_send_invoice: "Proposed sending an invoice", propose_payment_reminder: "Drafted a reminder" };

function Chat() {
  const qp = useSearchParams().get("prompt");
  const [msgs, setMsgs] = useState<Msg[]>([]), [input, setInput] = useState(""), [busy, setBusy] = useState(false), [cid, setCid] = useState<string>();
  const [hist, setHist] = useState<{ id: string; title: string }[]>([]), [invoices, setInvoices] = useState<Invoice[]>([]);
  const end = useRef<HTMLDivElement>(null), sent = useRef(false);
  useEffect(() => { api.conversations().then(setHist).catch(() => {}); api.invoices().then(setInvoices).catch(() => {}); }, []);
  useEffect(() => { end.current?.scrollIntoView({ behavior: "smooth", block: "end" }); }, [msgs, busy]);
  async function send(text: string) {
    if (!text.trim() || busy) return;
    setMsgs(m => [...m, { role: "user", text }]); setInput(""); setBusy(true);
    try { const r = await api.chat(text, cid); setCid(r.conversation_id); setMsgs(m => [...m, { role: "assistant", text: r.reply, tools: r.tool_calls, actions: r.actions }]); api.conversations().then(setHist).catch(() => {}); }
    catch (e) { setMsgs(m => [...m, { role: "assistant", text: errMsg(e) }]); } finally { setBusy(false); }
  }
  useEffect(() => { if (qp && !sent.current) { sent.current = true; send(qp); } /* eslint-disable-next-line */ }, [qp]);
  async function open(id: string) {
    const c = await api.conversation(id); setCid(id);
    const all = await api.actions().catch(() => [] as Action[]);
    setMsgs(c.messages.map(m => ({ role: m.role as "user" | "assistant", text: m.content, tools: m.meta?.tool_calls, actions: all.filter(a => m.meta?.action_ids?.includes(a.id)) })));
  }
  return (
    <div className="chat-layout">
      <aside className="history" aria-label="Past conversations"><button className="ghost" onClick={() => { setMsgs([]); setCid(undefined); }}>New chat</button>
        <ul>{hist.map(h => <li key={h.id}><button className={`link ${h.id === cid ? "on" : ""}`} onClick={() => open(h.id)}>{h.title}</button></li>)}</ul></aside>
      <section className="chat">
        <div className="thread" aria-live="polite">
          {msgs.length === 0 && <div className="empty"><h1>Ask about your PayPal activity</h1><p>The assistant reads your synced data with fixed tools. It can draft invoices and reminders, but nothing is sent until you approve it.</p>
            <ul className="suggest">{SUGGESTED.map(s => <li key={s}><button className="ghost" onClick={() => send(s)}>{s}</button></li>)}</ul></div>}
          {msgs.map((m, i) => <div key={i} className={`msg ${m.role}`}>
            {m.tools && m.tools.length > 0 && <ul className="tools" aria-label="Tools used">{m.tools.map((t, j) => <li key={j} className={t.ok ? t.kind : "bad"}>{t.ok ? "✓" : "✕"} {TOOL_LABEL[t.name] ?? t.name}{t.kind === "action" ? " (needs approval)" : ""}</li>)}</ul>}
            <p>{m.text}</p>
            {m.actions?.map(a => <ActionSlip key={a.id} action={a} invoices={invoices} />)}</div>)}
          {busy && <div className="msg assistant"><p className="thinking">Reading your data…</p></div>}
          <div ref={end} />
        </div>
        <form className="composer" onSubmit={e => { e.preventDefault(); send(input); }}>
          <input aria-label="Message" value={input} onChange={e => setInput(e.target.value)} placeholder="Ask about revenue, customers, overdue invoices…" maxLength={2000} />
          <button className="approve" disabled={busy || input.trim().length < 2}>Send</button></form>
      </section>
    </div>
  );
}
export default function Assistant() { return <Suspense fallback={null}><Chat /></Suspense>; }
