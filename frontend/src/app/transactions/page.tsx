"use client";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { AgGridReact } from "ag-grid-react";
import { AllCommunityModule, ColDef, GridApi, GridReadyEvent, IDatasource, ModuleRegistry, themeQuartz } from "ag-grid-community";
import { api, errMsg, money, Tx } from "@/lib/api";
import { useToast } from "@/components/Shell";

ModuleRegistry.registerModules([AllCommunityModule]);
const PAGE = 50;
const STATUS: Record<string, string> = { S: "Completed", P: "Pending", D: "Failed", V: "Reversed" };
const theme = themeQuartz.withParams({ fontFamily: "inherit", accentColor: "#1f4fd8", headerBackgroundColor: "#f3f5f8", borderColor: "#dde2ea", wrapperBorderRadius: 0, rowHeight: 40 });
// CSV cells beginning with = + - @ can execute as spreadsheet formulas; neutralise them.
const csv = (v: unknown) => { let s = String(v ?? ""); if (/^[=+\-@\t\r]/.test(s)) s = "'" + s; return `"${s.replace(/"/g, '""')}"`; };

export default function Transactions() {
  const toast = useToast(), apiRef = useRef<GridApi<Tx> | null>(null);
  const [f, setF] = useState({ q: "", status: "", currency: "", from: "", to: "" });
  const [total, setTotal] = useState<number | null>(null), [error, setError] = useState(""), [sel, setSel] = useState<Tx | null>(null), [menu, setMenu] = useState(false);
  const [hidden, setHidden] = useState<Record<string, boolean>>({ payer_email: true, fee: true });

  const cols = useMemo<ColDef<Tx>[]>(() => [
    { field: "date", headerName: "Date", sort: "desc", width: 200, valueFormatter: p => (p.value ? new Date(p.value).toLocaleString() : "") },
    { field: "paypal_id", headerName: "Transaction ID", width: 160 },
    { field: "payer_name", headerName: "Customer", flex: 1, minWidth: 140 },
    { field: "payer_email", headerName: "Email", flex: 1, minWidth: 160, sortable: false, hide: true },
    { field: "subject", headerName: "Description", flex: 1, minWidth: 140, sortable: false },
    { field: "amount", headerName: "Amount", width: 130, type: "rightAligned", valueFormatter: p => (p.data ? money(p.data.amount, p.data.currency) : "") },
    { field: "fee", headerName: "PayPal fee", width: 120, type: "rightAligned", sortable: false, hide: true, valueFormatter: p => (p.data ? money(p.data.fee, p.data.currency) : "") },
    { field: "currency", headerName: "Cur.", width: 80 },
    { field: "status", headerName: "Status", width: 120, cellRenderer: (p: { value: string }) => <span className={`chip st-${p.value}`}>{STATUS[p.value] ?? p.value}</span> },
  ], []);

  const params = useCallback((page: number, size: number, sortBy?: string, dir?: string) => {
    const qs = new URLSearchParams({ page: String(page), page_size: String(size), sort_by: sortBy || "date", sort_dir: dir || "desc" });
    if (f.q) qs.set("q", f.q); if (f.status) qs.set("status", f.status); if (f.currency) qs.set("currency", f.currency);
    if (f.from) qs.set("date_from", new Date(f.from + "T00:00:00").toISOString()); if (f.to) qs.set("date_to", new Date(f.to + "T23:59:59").toISOString());
    return qs;
  }, [f]);

  // Infinite row model: AG Grid asks for rows [start,end) with the active sort; we translate that to server-side page/sort/filter params.
  const datasource = useMemo<IDatasource>(() => ({
    getRows: async p => {
      try {
        const s = p.sortModel[0];
        const r = await api.transactions(params(Math.floor(p.startRow / PAGE) + 1, PAGE, s?.colId, s?.sort));
        setTotal(r.total); setError(""); p.successCallback(r.rows, r.total);
      } catch (e) { setError(errMsg(e)); p.failCallback(); }
    },
  }), [params]);

  useEffect(() => { const h = (e: KeyboardEvent) => { if (e.key === "Escape") setSel(null); }; window.addEventListener("keydown", h); return () => window.removeEventListener("keydown", h); }, []);

  async function exportCsv() {
    try {
      const all: Tx[] = []; let page = 1, t = 0;
      do { const r = await api.transactions(params(page, 200)); all.push(...r.rows); t = r.total; page++; } while (all.length < t && page < 100);
      const head = ["Date", "Transaction ID", "Customer", "Email", "Description", "Amount", "Currency", "Fee", "Status"];
      const body = all.map(r => [r.date, r.paypal_id, r.payer_name, r.payer_email, r.subject, r.amount, r.currency, r.fee, STATUS[r.status] ?? r.status].map(csv).join(","));
      const url = URL.createObjectURL(new Blob([[head.map(csv).join(","), ...body].join("\n")], { type: "text/csv" }));
      Object.assign(document.createElement("a"), { href: url, download: "paypilot-transactions.csv" }).click(); URL.revokeObjectURL(url);
      toast(`Exported ${all.length} transactions`);
    } catch (e) { toast(errMsg(e), "err"); }
  }
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => setF(v => ({ ...v, [k]: e.target.value }));
  const onReady = (e: GridReadyEvent<Tx>) => { apiRef.current = e.api; };
  const toggle = (id: string) => { const h = !hidden[id]; setHidden(v => ({ ...v, [id]: h })); apiRef.current?.setColumnsVisible([id], !h); };

  return (
    <div className={sel ? "with-drawer" : undefined}>
      <header className="page-head"><div><h1>Transactions</h1><p className="sub">{total === null ? "Loading…" : `${total.toLocaleString()} matching · sorted and filtered on the server`}</p></div>
        <div className="row"><div className="menu-wrap"><button className="ghost" onClick={() => setMenu(m => !m)} aria-expanded={menu}>Columns</button>
          {menu && <div className="menu" role="group" aria-label="Visible columns">{cols.map(c => <label key={c.field}><input type="checkbox" checked={!hidden[c.field as string]} onChange={() => toggle(c.field as string)} />{c.headerName}</label>)}</div>}</div>
          <button className="ghost" onClick={exportCsv}>Export CSV</button></div></header>
      <div className="filters" role="search">
        <label>Search<input type="search" placeholder="Customer, email, ID, description" value={f.q} onChange={set("q")} /></label>
        <label>Status<select value={f.status} onChange={set("status")}><option value="">All</option>{Object.entries(STATUS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></label>
        <label>Currency<select value={f.currency} onChange={set("currency")}><option value="">All</option><option>USD</option><option>EUR</option><option>GBP</option><option>INR</option></select></label>
        <label>From<input type="date" value={f.from} onChange={set("from")} /></label>
        <label>To<input type="date" value={f.to} onChange={set("to")} /></label>
        <button className="link" onClick={() => setF({ q: "", status: "", currency: "", from: "", to: "" })}>Clear filters</button>
      </div>
      {error && <p className="err" role="alert">{error}</p>}
      <div className="grid-wrap">
        <AgGridReact<Tx> theme={theme} columnDefs={cols} rowModelType="infinite" datasource={datasource} cacheBlockSize={PAGE} maxBlocksInCache={10}
          pagination paginationPageSize={PAGE} paginationPageSizeSelector={false} onGridReady={onReady} domLayout="autoHeight"
          defaultColDef={{ resizable: true, sortable: true }} onRowClicked={e => e.data && setSel(e.data)} suppressCellFocus
          overlayNoRowsTemplate="No transactions match. Clear the filters, or sync from PayPal on the Overview page." />
      </div>
      {sel && <aside className="drawer" aria-label="Transaction details">
        <button className="link" onClick={() => setSel(null)} aria-label="Close details (Escape)">Close</button>
        <h2>{money(sel.amount, sel.currency)}</h2><span className={`chip st-${sel.status}`}>{STATUS[sel.status] ?? sel.status}</span>
        <dl><dt>Customer</dt><dd>{sel.payer_name || "—"}</dd><dt>Email</dt><dd>{sel.payer_email || "—"}</dd><dt>Description</dt><dd>{sel.subject || "—"}</dd>
          <dt>Date</dt><dd>{new Date(sel.date).toLocaleString()}</dd><dt>PayPal fee</dt><dd>{money(sel.fee, sel.currency)}</dd><dt>PayPal transaction ID</dt><dd>{sel.paypal_id}</dd></dl>
      </aside>}
    </div>
  );
}
