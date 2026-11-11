"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { Area, CartesianGrid, ComposedChart, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Anomaly, api, errMsg, Forecast, money } from "@/lib/api";

export default function Insights() {
  const [fc, setFc] = useState<Forecast[] | null>(null), [an, setAn] = useState<Anomaly[]>([]), [err, setErr] = useState("");
  useEffect(() => { Promise.all([api.forecast(), api.anomalies()]).then(([f, a]) => { setFc(f.forecasts); setAn(a.anomalies); }).catch(e => setErr(errMsg(e))); }, []);
  if (err) return <p className="err" role="alert">{err}</p>;
  if (!fc) return <div className="skeleton" aria-busy="true"><div /><div /></div>;
  return (
    <>
      <header className="page-head"><div><h1>Forecast & alerts</h1><p className="sub">Statistical estimates from your past payments. They are ranges, not promises.</p></div></header>
      {fc.length === 0 && <p className="sub">No payment history yet. Sync from PayPal on the Overview page.</p>}
      {fc.map(f => <section key={f.currency} className="forecast"><h2>{f.currency} revenue, next 4 weeks</h2>
        {f.status !== "ok" ? <p className="sub">{f.message} ({f.weeks_available} week{f.weeks_available === 1 ? "" : "s"} so far)</p> : <>
          <p>Expected <strong>{money(f.next_4_weeks!.expected, f.currency)}</strong>, plausible range {money(f.next_4_weeks!.low, f.currency)} to {money(f.next_4_weeks!.high, f.currency)}. Trend: {f.trend}.</p>
          <div className="chart" role="img" aria-label={`${f.currency} weekly revenue history and four-week projection`}><ResponsiveContainer width="100%" height={260}>
            <ComposedChart data={[...f.history!.map(h => ({ w: h.week_start, actual: h.revenue })), ...f.projection!.map(p => ({ w: p.week_start, expected: p.expected, range: [p.low, p.high] }))]}>
              <CartesianGrid vertical={false} stroke="#e6e9ef" /><XAxis dataKey="w" tickFormatter={w => w.slice(5)} tickLine={false} axisLine={false} /><YAxis tickLine={false} axisLine={false} width={56} />
              <Tooltip /><Area dataKey="range" stroke="none" fill="#1f4fd8" fillOpacity={0.14} name="Plausible range" />
              <Line dataKey="actual" stroke="#16233b" strokeWidth={2} dot={false} name="Actual" /><Line dataKey="expected" stroke="#1f4fd8" strokeWidth={2} strokeDasharray="5 4" dot={false} name="Projected" /></ComposedChart></ResponsiveContainer></div>
          <p className="fine">{f.method}. {f.disclaimer}</p></>}</section>)}
      <h2>Alerts</h2>
      {an.length === 0 ? <p className="sub">No unusual activity detected in your synced data.</p> : <ul className="alerts">{an.map((a, i) => <li key={i}><header><span className={`sev ${a.severity}`}>{a.severity}</span><strong>{a.title}</strong></header>
        <p>{a.why}</p>{a.evidence_transaction_ids.length > 0 && <p className="fine">Based on {a.evidence_transaction_ids.length} transaction{a.evidence_transaction_ids.length > 1 ? "s" : ""}: {a.evidence_transaction_ids.slice(0, 4).join(", ")}{a.evidence_transaction_ids.length > 4 ? "…" : ""}</p>}
        <p><Link href={`/assistant?prompt=${encodeURIComponent(`Explain this alert and suggest next steps: ${a.title}`)}`}>{a.suggested_action}</Link></p></li>)}</ul>}
    </>
  );
}
