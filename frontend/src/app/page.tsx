"use client";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Anomaly, api, errMsg, Invoice, money, Summary } from "@/lib/api";
import { useToast } from "@/components/Shell";

const STATUS: Record<string, string> = { S: "Completed", P: "Pending", D: "Failed", V: "Reversed" };

export default function Overview() {
  const toast = useToast();
  const [s, setS] = useState<Summary | null>(null), [alerts, setAlerts] = useState<Anomaly[]>([]), [inv, setInv] = useState<Invoice[]>([]);
  const [cur, setCur] = useState(""), [loading, setLoading] = useState(true), [syncing, setSyncing] = useState(false), [err, setErr] = useState("");
  const load = useCallback(async () => {
    setLoading(true); setErr("");
    try {
      const [sum, an, iv] = await Promise.all([api.summary(90), api.anomalies(), api.invoices()]);
      setS(sum); setAlerts(an.anomalies); setInv(iv); setCur(c => c || [...sum.by_currency].sort((a, b) => b.revenue - a.revenue)[0]?.currency || "");
    } catch (e) { setErr(errMsg(e)); } finally { setLoading(false); }
  }, []);
  useEffect(() => { load(); }, [load]);
  async function sync() {
    setSyncing(true);
    try { const r = await api.sync(90); toast(`Synced ${r.transactions.fetched} transactions and ${r.invoices.fetched} invoices`); await load(); }
    catch (e) { toast(errMsg(e), "err"); } finally { setSyncing(false); }
  }
  if (loading) return <div className="skeleton" aria-busy="true"><div /><div /><div /></div>;
  if (err) return <p className="err" role="alert">{err}</p>;
  if (!s || s.total_transactions === 0) return (
    <section className="empty"><h1>No payments yet</h1><p>Pull your PayPal sandbox activity to see revenue, trends and what needs follow-up.</p>
      <button className="approve" onClick={sync} disabled={syncing}>{syncing ? "Syncing…" : "Sync from PayPal"}</button></section>);
  const c = s.by_currency.find(x => x.currency === cur) ?? s.by_currency[0];
  const mc = s.month_comparison.find(x => x.currency === c.currency);
  const monthly = s.monthly.filter(m => m.currency === c.currency);
  const overdue = inv.filter(i => i.days_overdue > 0);
  const maxStatus = Math.max(...Object.values(s.status_counts));
  return (
    <>
      <header className="page-head"><div><h1>Overview</h1><p className="sub">Last {s.window_days} days · amounts are never added across currencies</p></div>
        <button className="ghost" onClick={sync} disabled={syncing}>{syncing ? "Syncing…" : "Sync from PayPal"}</button></header>
      {s.by_currency.length > 1 && <div className="tabs" role="tablist">{s.by_currency.map(x =>
        <button key={x.currency} role="tab" aria-selected={x.currency === c.currency} onClick={() => setCur(x.currency)}>{x.currency}</button>)}</div>}
      <section className="figures" aria-label={`${c.currency} figures`}>
        <div><span>Revenue</span><strong>{money(c.revenue, c.currency)}</strong>
          {mc?.change_pct != null && <em className={mc.change_pct < 0 ? "down" : "up"}>{mc.change_pct > 0 ? "+" : ""}{mc.change_pct}% vs same days last month</em>}</div>
        <div><span>Completed payments</span><strong>{c.payments}</strong><em>avg {money(c.avg_payment, c.currency)}</em></div>
        <div><span>Pending</span><strong>{c.pending_count}</strong><em>{money(c.pending_amount, c.currency)} on hold</em></div>
        <div><span>Failed</span><strong className={c.failed_count ? "warn" : ""}>{c.failed_count}</strong><em>{c.transactions} transactions total</em></div>
      </section>
      <section className="attention">
        <h2>Needs your attention</h2>
        {overdue.length === 0 && alerts.length === 0 && <p className="sub">Nothing flagged. You're clear.</p>}
        {overdue.length > 0 && <p><strong>{overdue.length} overdue invoice{overdue.length > 1 ? "s" : ""}</strong> totalling {Object.entries(overdue.reduce<Record<string, number>>((a, i) => ({ ...a, [i.currency]: (a[i.currency] || 0) + i.total }), {})).map(([k, v]) => money(v, k)).join(" and ")}.{" "}
          <Link href={`/assistant?prompt=${encodeURIComponent("Find overdue invoices and prepare reminders")}`}>Have the assistant draft reminders</Link></p>}
        {alerts.slice(0, 3).map((a, i) => <p key={i}><span className={`sev ${a.severity}`}>{a.severity}</span> {a.title}</p>)}
        {alerts.length > 3 && <p><Link href="/insights">See all {alerts.length} alerts</Link></p>}
      </section>
      <div className="two">
        <section><h2>Monthly revenue ({c.currency})</h2>
          <div className="chart" role="img" aria-label={`Monthly ${c.currency} revenue`}>
            <ResponsiveContainer width="100%" height={240}><BarChart data={monthly}><CartesianGrid vertical={false} stroke="#e6e9ef" />
              <XAxis dataKey="month" tickLine={false} axisLine={false} /><YAxis tickLine={false} axisLine={false} width={56} />
              <Tooltip formatter={(v: number) => money(v, c.currency)} /><Bar dataKey="revenue" fill="#16233b" radius={[2, 2, 0, 0]} /></BarChart></ResponsiveContainer></div></section>
        <section><h2>Payment status (all currencies)</h2>
          <ul className="bars">{Object.entries(s.status_counts).map(([k, v]) => <li key={k}><span>{STATUS[k] ?? k}</span>
            <i style={{ width: `${(v / maxStatus) * 100}%` }} className={`st-${k}`} /><b>{v}</b></li>)}</ul>
          <h2>Top customers ({c.currency})</h2>
          <table className="plain"><tbody>{s.customers.filter(x => x.currency === c.currency).map(x => <tr key={x.email || x.customer}>
            <td>{x.customer}</td><td className="num">{money(x.revenue, x.currency)}</td></tr>)}</tbody></table></section>
      </div>
    </>
  );
}
