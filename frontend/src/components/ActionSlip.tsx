"use client";
import { useState } from "react";
import { Action, api, errMsg, Invoice, money } from "@/lib/api";
import { useToast } from "./Shell";

const TYPE = { create_invoice_draft: "Create invoice draft", send_invoice: "Send invoice to customer", send_reminder: "Send payment reminder" } as const;
const LABEL: Record<string, string> = { PENDING: "Waiting for you", APPROVED: "Approved", EXECUTING: "Running", COMPLETED: "Done", FAILED: "Failed", REJECTED: "Rejected", CANCELLED: "Cancelled" };

/** An action the AI (or you) proposed. Nothing happens in PayPal until you press Approve. */
export default function ActionSlip({ action, invoices, onChange }: { action: Action; invoices?: Invoice[]; onChange?: (a: Action) => void }) {
  const [a, setA] = useState(action), [busy, setBusy] = useState(false), toast = useToast();
  const p = a.payload, inv = invoices?.find(i => i.id === p.invoice_id);
  async function run(fn: (id: string) => Promise<Action>, ok: string) {
    setBusy(true);
    try { const n = await fn(a.id); setA(n); onChange?.(n); n.status === "FAILED" ? toast(`${n.error}`, "err") : toast(ok); }
    catch (e) { toast(errMsg(e), "err"); } finally { setBusy(false); }
  }
  return (
    <article className={`slip ${a.status.toLowerCase()}`} aria-label={a.title}>
      <header><strong>{TYPE[a.type]}</strong><span className="state">{LABEL[a.status] ?? a.status}</span></header>
      {a.source === "sweep" && <p className="fine" style={{ margin: "0 0 .4rem" }}>Prepared by the overnight sweep</p>}
      <dl>
        {a.type === "create_invoice_draft" && <>
          <dt>To</dt><dd>{p.recipient_name ? `${p.recipient_name} · ` : ""}{p.recipient_email}</dd>
          <dt>Items</dt><dd>{p.items?.map((i: any) => `${i.quantity} × ${i.name} @ ${money(Number(i.unit_amount), p.currency)}`).join(", ")}</dd>
          <dt>Due</dt><dd>in {p.due_in_days} days</dd></>}
        {a.type !== "create_invoice_draft" && <>
          <dt>Invoice</dt><dd>{inv ? `${inv.number} · ${inv.customer || inv.email} · ${money(inv.total, inv.currency)}${inv.days_overdue ? ` · ${inv.days_overdue} days overdue` : ""}` : p.invoice_id}</dd>
          {inv && <><dt>Sends to</dt><dd>{inv.email}</dd></>}</>}
        {a.type === "send_reminder" && <><dt>Subject</dt><dd>{p.subject}</dd><dt>Message</dt><dd className="msg">{p.note}</dd></>}
      </dl>
      {a.error && <p className="err">PayPal said: {a.error}</p>}
      {a.status === "COMPLETED" && a.result && <p className="okline">Completed {a.executed_at && new Date(a.executed_at).toLocaleTimeString()} · invoice is now {a.result.status}</p>}
      {a.status === "PENDING" && <footer>
        <button className="approve" disabled={busy} onClick={() => run(api.approve, "Approved and executed")}>{busy ? "Working…" : "Approve and run"}</button>
        <button className="ghost" disabled={busy} onClick={() => run(api.reject, "Rejected")}>Reject</button>
        {a.source === "user" && <button className="link" disabled={busy} onClick={() => run(api.cancel, "Cancelled")}>Cancel</button>}
      </footer>}
    </article>
  );
}
