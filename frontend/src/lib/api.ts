export const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api/v1";

// sessionStorage: cleared when the tab closes. (Any JS-readable token store is XSS-exposed; we avoid third-party scripts and render no raw HTML.)
export const tokenStore = {
  get: () => (typeof window === "undefined" ? null : sessionStorage.getItem("pp_token")),
  set: (t: string) => sessionStorage.setItem("pp_token", t),
  clear: () => sessionStorage.removeItem("pp_token"),
};

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message); }
}

async function req<T>(path: string, init: RequestInit = {}): Promise<T> {
  const token = tokenStore.get();
  let r: Response;
  try {
    r = await fetch(API_BASE + path, {
      ...init, cache: "no-store",
      headers: { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}), ...(init.headers || {}) },
    });
  } catch {
    throw new ApiError(0, "Cannot reach the PayPilot API. Is the backend running?");
  }
  const d = await r.json().catch(() => ({}));
  if (r.status === 401 && !path.startsWith("/auth/")) { tokenStore.clear(); if (typeof window !== "undefined") window.location.href = "/login"; }
  if (!r.ok) {
    const detail = Array.isArray(d.detail) ? d.detail.map((x: { loc: string[]; msg: string }) => `${x.loc.slice(1).join(".")}: ${x.msg}`).join("; ") : d.detail;
    throw new ApiError(r.status, detail || `Request failed (${r.status})`);
  }
  return d as T;
}
const post = <T,>(p: string, body?: unknown) => req<T>(p, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) });

export type Tx = { id: string; paypal_id: string; date: string; status: string; amount: number; fee: number; currency: string; payer_name: string; payer_email: string; subject: string };
export type CurrencySummary = { currency: string; revenue: number; payments: number; avg_payment: number; pending_count: number; pending_amount: number; failed_count: number; reversed_count: number; transactions: number };
export type Summary = { by_currency: CurrencySummary[]; status_counts: Record<string, number>; monthly: { month: string; currency: string; revenue: number }[];
  month_comparison: { currency: string; this_month_to_date: number; last_month_same_period: number; last_month_full: number; change_pct: number | null }[];
  customers: { customer: string; email: string; currency: string; revenue: number; payments: number; failed: number }[]; total_transactions: number; window_days: number };
export type Invoice = { id: string; number: string; status: string; customer: string; email: string; total: number; currency: string; due_date: string | null; days_overdue: number; last_reminded_at: string | null };
export type Action = { id: string; type: "create_invoice_draft" | "send_invoice" | "send_reminder"; title: string; payload: Record<string, any>; status: string; source: string; result: Record<string, any> | null; error: string | null; created_at: string; decided_at: string | null; executed_at: string | null };
export type SweepResult = { proposed: number; already_queued: number; recently_reminded: number; anomalies: number; transactions_fetched: number; invoices_fetched: number };
export type SweepStart = { mode: "inline" | "render"; run_id: string | null; status: string; result?: SweepResult };
export type SweepRun = { status: string; result: SweepResult | null; error: string | null };
export type Anomaly = { type: string; severity: "high" | "medium" | "low"; currency: string; title: string; why: string; evidence_transaction_ids: string[]; suggested_action: string };
export type Forecast = { currency: string; status: string; message?: string; weeks_available?: number; trend?: string; history?: { week_start: string; revenue: number }[]; projection?: { week_start: string; expected: number; low: number; high: number }[];
  next_4_weeks?: { expected: number; low: number; high: number }; method?: string; disclaimer?: string };
export type ToolCall = { name: string; kind: string; args: Record<string, unknown>; ok: boolean; error: string | null };
export type ChatOut = { conversation_id: string; reply: string; tool_calls: ToolCall[]; actions: Action[] };
export type DraftInput = { recipient_email: string; recipient_name: string; currency: string; due_in_days: number; note: string; items: { name: string; quantity: number; unit_amount: number; tax_percent: number }[] };

export const api = {
  register: (email: string, password: string, name: string) => post<{ token: string }>("/auth/register", { email, password, name }),
  login: (email: string, password: string) => post<{ token: string }>("/auth/login", { email, password }),
  me: () => req<{ email: string; name: string }>("/auth/me"),
  status: () => req<{ mode: "demo" | "sandbox"; label: string; connected_account: boolean; transactions_stored: number }>("/paypal/status"),
  connect: (client_id: string, client_secret: string) => post("/paypal/connect", { client_id, client_secret }),
  disconnect: () => req("/paypal/connect", { method: "DELETE" }),
  sync: (days = 90) => post<{ transactions: { added: number; updated: number; fetched: number }; invoices: { fetched: number }; mode: string }>(`/paypal/sync?days=${days}`),
  transactions: (qs: URLSearchParams) => req<{ total: number; rows: Tx[] }>(`/transactions?${qs}`),
  summary: (days = 90) => req<Summary>(`/dashboard/summary?days=${days}`),
  forecast: () => req<{ forecasts: Forecast[] }>("/insights/forecast"),
  anomalies: () => req<{ anomalies: Anomaly[] }>("/insights/anomalies"),
  dataset: (currency?: string) => req<{ currency: string | null; currencies: string[]; transactions: Record<string, string | number | null>[] }>(`/analytics/dataset${currency ? `?currency=${currency}` : ""}`),
  invoices: () => req<Invoice[]>("/invoices"),
  previewInvoice: (d: DraftInput) => post<{ subtotal: number; tax: number; total: number; currency: string }>("/invoices/preview", d),
  createInvoice: (d: DraftInput) => post<Action>("/invoices", d),
  requestSend: (id: string) => post<Action>(`/invoices/${id}/request-send`, {}),
  requestReminder: (id: string, subject?: string, note?: string) => post<Action>(`/invoices/${id}/request-reminder`, { subject, note }),
  chat: (message: string, conversation_id?: string) => post<ChatOut>("/ai/chat", { message, conversation_id }),
  conversations: () => req<{ id: string; title: string }[]>("/ai/conversations"),
  conversation: (id: string) => req<{ messages: { role: string; content: string; meta: { tool_calls?: ToolCall[]; action_ids?: string[] } }[] }>(`/ai/conversations/${id}`),
  startSweep: () => post<SweepStart>("/sweep"),
  sweepRun: (id: string) => req<SweepRun>(`/sweep/runs/${id}`),
  actions: (status?: string) => req<Action[]>(`/actions${status ? `?status=${status}` : ""}`),
  approve: (id: string) => post<Action>(`/actions/${id}/approve`),
  reject: (id: string) => post<Action>(`/actions/${id}/reject`),
  cancel: (id: string) => post<Action>(`/actions/${id}/cancel`),
  audit: () => req<{ id: string; action_id: string | null; event: string; detail: Record<string, any>; at: string }[]>("/audit"),
};

export const money = (v: number, cur: string) => new Intl.NumberFormat(undefined, { style: "currency", currency: cur }).format(v);
export const errMsg = (e: unknown) => (e instanceof Error ? e.message : "Something went wrong");
