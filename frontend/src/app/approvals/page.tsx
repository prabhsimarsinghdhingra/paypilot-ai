"use client";
import { useCallback, useEffect, useState } from "react";
import ActionSlip from "@/components/ActionSlip";
import { Action, api, errMsg, Invoice, SweepResult } from "@/lib/api";

export default function Approvals() {
  const [actions, setActions] = useState<Action[] | null>(null), [inv, setInv] = useState<Invoice[]>([]), [audit, setAudit] = useState<Awaited<ReturnType<typeof api.audit>>>([]), [err, setErr] = useState("");
  const load = useCallback(() => { Promise.all([api.actions(), api.invoices(), api.audit()]).then(([a, i, l]) => { setActions(a); setInv(i); setAudit(l); }).catch(e => setErr(errMsg(e))); }, []);
  useEffect(load, [load]);
  const [sweep, setSweep] = useState<{ busy: boolean; msg: string; where: string }>({ busy: false, msg: "", where: "" });
  const summary = (r: SweepResult) => `Queued ${r.proposed} reminder${r.proposed === 1 ? "" : "s"} for your approval · ${r.already_queued} already waiting · ${r.recently_reminded} reminded this week · ${r.anomalies} alert${r.anomalies === 1 ? "" : "s"} found`;
  async function runSweep() {
    setSweep({ busy: true, msg: "Syncing PayPal and checking invoices…", where: "" });
    try {
      const r = await api.startSweep();
      if (r.mode === "inline") { setSweep({ busy: false, msg: summary(r.result!), where: "Ran inline on the API server" }); load(); return; }
      setSweep({ busy: true, msg: "Running on Render Workflows…", where: `Render Workflows run ${r.run_id}` });
      for (let i = 0; i < 60; i++) {
        await new Promise(res => setTimeout(res, 2000));
        const s = await api.sweepRun(r.run_id!);
        if (s.status === "completed" && s.result) { setSweep({ busy: false, msg: summary(s.result), where: `Ran on Render Workflows (${r.run_id})` }); load(); return; }
        if (s.status === "failed" || s.status === "canceled") throw new Error(s.error || `The workflow run ${s.status}`);
      }
      throw new Error("The workflow is taking longer than expected. Check the Render dashboard.");
    } catch (e) { setSweep({ busy: false, msg: errMsg(e), where: "" }); }
  }
  if (err) return <p className="err" role="alert">{err}</p>;
  if (!actions) return <div className="skeleton" aria-busy="true"><div /><div /></div>;
  const pending = actions.filter(a => a.status === "PENDING"), done = actions.filter(a => a.status !== "PENDING");
  return (
    <>
      <header className="page-head"><div><h1>Approvals</h1><p className="sub">Nothing reaches PayPal until you approve it here.</p></div></header>
      <section className="sweep" aria-label="Overnight sweep">
        <div><strong>Overnight sweep</strong><p className="sub" style={{ margin: ".2rem 0" }}>Syncs PayPal, scans for anomalies and prepares a friendly reminder for each overdue invoice. It only prepares them. You approve each one below.</p></div>
        <div><button className="ghost" onClick={runSweep} disabled={sweep.busy}>{sweep.busy ? "Sweeping…" : "Run sweep now"}</button></div>
        {sweep.msg && <p role="status" style={{ gridColumn: "1 / -1", margin: 0 }}>{sweep.msg}{sweep.where && <span className="fine"> · {sweep.where}</span>}</p>}
      </section>
      <h2>Waiting for you ({pending.length})</h2>
      {pending.length === 0 ? <p className="sub">Nothing to review. Ask the assistant to find overdue invoices and it will draft reminders for you to approve.</p>
        : <div className="slips">{pending.map(a => <ActionSlip key={a.id} action={a} invoices={inv} onChange={load} />)}</div>}
      <h2>History</h2>
      {done.length === 0 ? <p className="sub">No decisions yet.</p> : <div className="slips">{done.map(a => <ActionSlip key={a.id} action={a} invoices={inv} />)}</div>}
      <h2>Audit log</h2>
      <table className="plain"><thead><tr><th>When</th><th>Event</th><th>Action</th><th>Detail</th></tr></thead>
        <tbody>{audit.map(l => <tr key={l.id}><td>{new Date(l.at).toLocaleString()}</td><td>{l.event}</td><td>{l.action_id?.slice(0, 8)}</td>
          <td>{l.detail?.error ?? l.detail?.result?.status ?? l.detail?.type ?? ""}</td></tr>)}</tbody></table>
    </>
  );
}
