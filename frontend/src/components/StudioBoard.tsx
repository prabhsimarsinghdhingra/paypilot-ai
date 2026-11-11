"use client";
import { useMemo } from "react";
import { AgStudio } from "ag-studio-react";
import OwesScoreboard, { PilotContext } from "./OwesScoreboard";
import { api as pilotApi, Invoice } from "@/lib/api";
import { AgStudioLicenseManager, AgStudioAiModule, AgStudioModuleRegistry, createAiHarness, createWidgets, directLlmRunner, studioTheme } from "ag-studio";
import { pilotAdapter } from "@/lib/studioAdapter";
import type { AgAiHarnessSetup, AgReportState, AgStudioApi } from "ag-studio";

// AG Studio is a commercial product: it runs locally without a licence (watermark + console warning). A 45-day trial key
// (NEXT_PUBLIC_AG_LICENSE_KEY) removes both for the hosted demo. Keys are public by design in browser apps; never commit one.
if (process.env.NEXT_PUBLIC_AG_LICENSE_KEY) AgStudioLicenseManager.setLicenseKey(process.env.NEXT_PUBLIC_AG_LICENSE_KEY);
AgStudioModuleRegistry.registerModules([AgStudioAiModule]);

const T = "transactions";
const title = (text: string) => ({ title: { enabled: true, text } });
const OWES = "owes-scoreboard";

/** Custom widget: a friendly "who still owes you" scoreboard. It reads our invoices through Studio's `context` property. */
const owesWidget = {
  id: OWES, label: "Who owes what",
  comp: OwesScoreboard,
  form: ({ createDefaults }: { createDefaults: (p: object) => unknown }) => createDefaults({}),
  defaultSize: { xSpan: 4, ySpan: 5 }, minSize: { xSpan: 3, ySpan: 3 },
};

// PayPilot theme: same ink-and-cobalt palette as the rest of the app.
const theme = studioTheme.withParams({ accentColor: "#1f4fd8", fontFamily: "ui-sans-serif, system-ui, -apple-system, 'Segoe UI', Roboto, Arial, sans-serif", textColor: "#0f1b2d", borderColor: "#dde2ea" });
const widgets = (w: { menu: unknown[] }) => createWidgets({ additionalTypes: [owesWidget], menu: [...w.menu, { label: "PayPilot", widgetIds: [OWES] }] } as never) as never;

/** The dashboard users see first. Everything after that is theirs to rearrange, add to and edit (drag and drop, cross-filtering, undo/redo). */
export const SEED = {
  selectedPageId: "overview",
  panels: { filters: { collapsed: true } },
  pages: [{
    id: "overview",
    layout: { columns: 12, rowHeight: 56, widgetPadding: 8, pagePadding: 8 },
    widgets: {
      revenue: { type: "value", dataMapping: { value: [{ id: `${T}.payment`, aggregation: "sum" }] }, format: title("Revenue") },
      payments: { type: "value", dataMapping: { value: [{ id: `${T}.payment`, aggregation: "count" }] }, format: title("Completed payments") },
      average: { type: "value", dataMapping: { value: [{ id: `${T}.payment`, aggregation: "avg" }] }, format: title("Average payment") },
      failed: { type: "value", dataMapping: { value: [{ id: `${T}.failed`, aggregation: "sum" }] }, format: title("Failed payments") },
      monthly: { type: "column-chart-grouped", dataMapping: { categoryKey: [{ id: `${T}.month` }], valueKey: [{ id: `${T}.payment`, aggregation: "sum" }] }, format: title("Revenue by month") },
      status: { type: "donut-chart", dataMapping: { categoryKey: [{ id: `${T}.status` }], valueKey: [{ id: `${T}.paypal_id`, aggregation: "count" }] }, format: title("Payment status") },
      owes: { type: OWES },
      customers: { type: "bar-chart-grouped", dataMapping: { categoryKey: [{ id: `${T}.customer` }], valueKey: [{ id: `${T}.payment`, aggregation: "sum" }] }, format: title("Revenue by customer") },
      table: { type: "grid", dataMapping: { cols: ["date", "customer", "description", "amount", "status"].map(id => ({ id: `${T}.${id}` })) }, format: title("Transactions") },
    },
    widgetLayout: {
      revenue: { xTrack: 0, yTrack: 0, xSpan: 3, ySpan: 2 }, payments: { xTrack: 3, yTrack: 0, xSpan: 3, ySpan: 2 },
      average: { xTrack: 6, yTrack: 0, xSpan: 3, ySpan: 2 }, failed: { xTrack: 9, yTrack: 0, xSpan: 3, ySpan: 2 },
      monthly: { xTrack: 0, yTrack: 2, xSpan: 5, ySpan: 5 }, status: { xTrack: 5, yTrack: 2, xSpan: 3, ySpan: 5 }, owes: { xTrack: 8, yTrack: 2, xSpan: 4, ySpan: 5 },
      customers: { xTrack: 0, yTrack: 7, xSpan: 4, ySpan: 5 }, table: { xTrack: 4, yTrack: 7, xSpan: 8, ySpan: 5 },
    },
  }],
} as unknown as AgReportState;

const PROMPTS = [
  { label: "Nudge late payers", prompt: "Find overdue invoices and queue a friendly reminder for each one." },
  { label: "Revenue trend", prompt: "Add a line chart of revenue by month." },
  { label: "Who fails to pay?", prompt: "Add a bar chart of failed payments by customer." },
];

const DOMAIN = `You are the analyst inside PayPilot, a PayPal dashboard for a small business owner.
- The dataset is ONE currency. "payment" is completed revenue (empty for non-completed rows); "failed" is 1 for a failed payment. Never add amounts across currencies.
- Use list_overdue_invoices to see who owes money, and queue_payment_reminder to propose a reminder. queue_payment_reminder only QUEUES it for the owner's approval in the Approvals page. Never say a reminder was sent.
- Write reminders warm, short and specific (customer name, invoice number, amount, days late). Never threaten.`;

// Studio's built-in agents running on Gemini through our backend, plus two PayPilot tools on the lead agent.
const adapter = pilotAdapter();
const ai: AgAiHarnessSetup = ({ api }) => createAiHarness(api as unknown as Parameters<typeof createAiHarness>[0], ({ builtIn }) => {
  const full = api as unknown as AgStudioApi;
  const listOverdue = full.defineAiTool({
    name: "list_overdue_invoices", description: "List invoices that are past due and unpaid, with ids, customers, amounts and days overdue.",
    params: (s: any) => s.object({}),
    execute: async (_args: unknown, ctx: any) => {
      const rows = (await pilotApi.invoices()).filter(i => i.days_overdue > 0);
      return ctx.success(rows.length ? `${rows.length} overdue invoice(s).` : "No overdue invoices.", rows.map(i => ({ invoice_id: i.id, number: i.number, customer: i.customer || i.email, total: i.total, currency: i.currency, days_overdue: i.days_overdue })));
    },
  } as never);
  const queueReminder = full.defineAiTool({
    name: "queue_payment_reminder", description: "Queue a payment reminder for ONE overdue invoice. It is NOT sent: the owner must approve it in the Approvals page.",
    params: (s: any) => s.object({ invoice_id: s.string(), subject: s.string(), note: s.string() }),
    execute: async (args: { invoice_id: string; subject: string; note: string }, ctx: any) => {
      try { const a = await pilotApi.requestReminder(args.invoice_id, args.subject, args.note); return ctx.success("Queued for the owner's approval. Nothing has been sent.", { action_id: a.id, status: a.status }); }
      catch (e) { return ctx.error(e instanceof Error ? e.message : "Could not queue the reminder"); }
    },
  } as never);
  return {
    agents: Object.values(builtIn).map((d: any) => directLlmRunner({
      ...d, adapter,
      ...(d.id === "lead" ? { instructions: (c: unknown, p: unknown) => `${d.instructions?.(c, p) ?? ""}\n\n${DOMAIN}`, tools: (c: unknown, p: unknown) => [...(d.tools?.(c, p) ?? []), listOverdue, queueReminder] } : {}),
    })),
    primary: "lead", promptStarters: PROMPTS,
  } as never;
});

export default function StudioBoard({ rows, mode, invoices, currency }: { rows: Record<string, string | number | null>[]; mode: "edit" | "view"; invoices: Invoice[]; currency: string | null }) {
  const data = useMemo(() => ({ sources: [{ id: T, name: "Transactions", data: rows }] }), [rows]);
  const context = useMemo<PilotContext>(() => ({ invoices, currency }), [invoices, currency]);
  return <div style={{ height: "100%", width: "100%" }}><AgStudio studioId="paypilot-studio" data={data} mode={mode} initialState={SEED} ai={ai} widgets={widgets as never} theme={theme} context={context} /></div>;
}
