"use client";
import { useState } from "react";
import { api, errMsg, Invoice, money } from "@/lib/api";

export type PilotContext = { invoices: Invoice[]; currency: string | null };

const mood = (d: number) => (d >= 21 ? { label: "long overdue", c: "#b4400f" } : d >= 7 ? { label: "a bit late", c: "#8a6100" } : { label: "just late", c: "#46536a" });

/** A friendly scoreboard of who still owes you money. "Draft a nudge" only QUEUES a reminder for your approval; nothing is sent from here. */
export default function OwesScoreboard({ context }: { context?: PilotContext }) {
  const [state, setState] = useState<Record<string, "busy" | "queued" | string>>({});
  const cur = context?.currency ?? null;
  const rows = (context?.invoices ?? []).filter(i => i.days_overdue > 0 && (!cur || i.currency === cur)).sort((a, b) => b.days_overdue - a.days_overdue);
  const total = rows.reduce((s, i) => s + i.total, 0);
  async function nudge(i: Invoice) {
    setState(s => ({ ...s, [i.id]: "busy" }));
    try { await api.requestReminder(i.id); setState(s => ({ ...s, [i.id]: "queued" })); }
    catch (e) { setState(s => ({ ...s, [i.id]: errMsg(e) })); }
  }
  return (
    <div style={{ height: "100%", overflow: "auto", padding: 12, fontFamily: "inherit", color: "#0f1b2d" }} data-testid="owes-scoreboard">
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: 8 }}>
        <strong style={{ fontSize: 16 }}>Who still owes you{cur ? ` (${cur})` : ""}</strong>
        {rows.length > 0 && cur && <span style={{ fontSize: 13 }}>{rows.length} late · <b>{money(total, cur)}</b></span>}
      </div>
      {rows.length === 0 && <p style={{ margin: 0, color: "#0e7a54" }}>Everyone is paid up. Nice work.</p>}
      <ol style={{ listStyle: "none", margin: 0, padding: 0, display: "flex", flexDirection: "column", gap: 6 }}>
        {rows.map((i, n) => {
          const m = mood(i.days_overdue), st = state[i.id];
          return (
            <li key={i.id} style={{ display: "grid", gridTemplateColumns: "26px 1fr auto", gap: 8, alignItems: "center", padding: "6px 8px", border: "1px solid #dde2ea", borderLeft: `4px solid ${m.c}`, background: "#fff" }}>
              <span style={{ fontWeight: 700, color: "#46536a" }}>{n + 1}</span>
              <span style={{ minWidth: 0 }}>
                <div style={{ fontWeight: 600, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{i.customer || i.email}</div>
                <div style={{ fontSize: 12, color: m.c }}>{money(i.total, i.currency)} · {i.days_overdue} days late ({m.label})</div>
              </span>
              {st === "queued" ? <span style={{ fontSize: 12, color: "#0e7a54" }}>Queued. Approve it in Approvals</span>
                : <button onClick={() => nudge(i)} disabled={st === "busy"} title="Creates a reminder for your approval. Nothing is sent yet."
                    style={{ font: "inherit", fontSize: 12, padding: "4px 8px", border: "1px solid #1f4fd8", color: "#1f4fd8", background: "#fff", cursor: "pointer" }}>{st === "busy" ? "Queuing…" : "Draft a nudge"}</button>}
              {st && st !== "busy" && st !== "queued" && <span style={{ gridColumn: "2 / 4", fontSize: 12, color: "#b4400f" }}>{st}</span>}
            </li>
          );
        })}
      </ol>
    </div>
  );
}
