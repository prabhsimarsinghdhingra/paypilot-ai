"""Pure, explainable statistics over transaction dicts {id,date,status,amount,currency,payer,email,subject}.
Never sums across currencies. Forecasts are ranges, not promises."""
import math, statistics
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

OK, PENDING, DENIED, REVERSED = "S", "P", "D", "V"
SEV = {"high": 0, "medium": 1, "low": 2}


def _aware(d: datetime) -> datetime:
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _rev(rows):  # revenue = completed, positive-amount payments
    return [r for r in rows if r["status"] == OK and r["amount"] > 0]


def revenue_summary(rows: list[dict], now: datetime) -> dict:
    by_cur: dict[str, dict] = {}
    for cur in sorted({r["currency"] for r in rows}):
        cr = [r for r in rows if r["currency"] == cur]
        paid = _rev(cr)
        revenue = round(sum(r["amount"] for r in paid), 2)
        by_cur[cur] = {
            "currency": cur, "revenue": revenue, "payments": len(paid),
            "avg_payment": round(revenue / len(paid), 2) if paid else 0,
            "pending_count": sum(r["status"] == PENDING for r in cr),
            "pending_amount": round(sum(r["amount"] for r in cr if r["status"] == PENDING and r["amount"] > 0), 2),
            "failed_count": sum(r["status"] == DENIED for r in cr),
            "reversed_count": sum(r["status"] == REVERSED for r in cr),
            "transactions": len(cr),
        }
    status_counts: dict[str, int] = defaultdict(int)
    for r in rows:
        status_counts[r["status"]] += 1
    monthly: dict[tuple, float] = defaultdict(float)
    for r in _rev(rows):
        d = _aware(r["date"]); monthly[(d.strftime("%Y-%m"), r["currency"])] += r["amount"]
    return {"by_currency": list(by_cur.values()), "status_counts": dict(status_counts),
            "monthly": [{"month": m, "currency": c, "revenue": round(v, 2)} for (m, c), v in sorted(monthly.items())],
            "month_comparison": month_comparison(rows, now), "total_transactions": len(rows)}


def month_comparison(rows: list[dict], now: datetime) -> list[dict]:
    """This month-to-date vs the SAME number of days of last month (a fair comparison)."""
    now = _aware(now); start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    prev_end_month = start - timedelta(seconds=1); prev_start = prev_end_month.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    elapsed = now - start; prev_cut = prev_start + elapsed
    out = []
    for cur in sorted({r["currency"] for r in rows}):
        paid = [r for r in _rev(rows) if r["currency"] == cur]
        this = sum(r["amount"] for r in paid if _aware(r["date"]) >= start)
        last_same = sum(r["amount"] for r in paid if prev_start <= _aware(r["date"]) <= prev_cut)
        last_full = sum(r["amount"] for r in paid if prev_start <= _aware(r["date"]) < start)
        out.append({"currency": cur, "this_month_to_date": round(this, 2), "last_month_same_period": round(last_same, 2),
                    "last_month_full": round(last_full, 2),
                    "change_pct": round((this - last_same) / last_same * 100, 1) if last_same else None})
    return out


def customer_insights(rows: list[dict], limit: int = 10) -> list[dict]:
    agg: dict[tuple, dict] = {}
    for r in rows:
        key = ((r.get("email") or r.get("payer") or "unknown").lower(), r["currency"])
        a = agg.setdefault(key, {"customer": r.get("payer") or key[0], "email": r.get("email", ""), "currency": r["currency"],
                                 "revenue": 0.0, "payments": 0, "failed": 0, "last_payment": None})
        if r["status"] == OK and r["amount"] > 0:
            a["revenue"] += r["amount"]; a["payments"] += 1
            d = _aware(r["date"]).date().isoformat(); a["last_payment"] = max(a["last_payment"] or d, d)
        elif r["status"] == DENIED:
            a["failed"] += 1
    out = sorted(agg.values(), key=lambda a: -a["revenue"])[:limit]
    for a in out: a["revenue"] = round(a["revenue"], 2)
    return out


def weekly_series(rows: list[dict], currency: str, now: datetime) -> list[tuple[date, float]]:
    """Completed Monday-based weeks only (the in-progress week would look like a false drop)."""
    paid = [r for r in _rev(rows) if r["currency"] == currency]
    if not paid: return []
    today = _aware(now).date(); this_monday = today - timedelta(days=today.weekday())
    buckets: dict[date, float] = defaultdict(float)
    for r in paid:
        d = _aware(r["date"]).date(); m = d - timedelta(days=d.weekday())
        if m < this_monday: buckets[m] += r["amount"]
    if not buckets: return []
    _first, out, m = min(buckets), [], min(buckets)
    while m < this_monday:
        out.append((m, round(buckets.get(m, 0.0), 2))); m += timedelta(days=7)
    return out


def forecast(rows: list[dict], now: datetime, horizon: int = 4) -> list[dict]:
    """Linear trend on weekly revenue with an approximate 95% prediction interval. Needs >=6 completed weeks."""
    res = []
    for cur in sorted({r["currency"] for r in rows}):
        s = weekly_series(rows, cur, now)
        if len(s) < 6 or sum(v > 0 for _, v in s) < 4:
            res.append({"currency": cur, "status": "insufficient_data", "weeks_available": len(s),
                        "message": "Need at least 6 completed weeks, 4 of them with revenue, to forecast."}); continue
        n, ys = len(s), [v for _, v in s]; xs = list(range(n)); xb, yb = sum(xs) / n, sum(ys) / n
        sxx = sum((x - xb) ** 2 for x in xs); slope = sum((x - xb) * (y - yb) for x, y in zip(xs, ys)) / sxx
        icpt = yb - slope * xb
        sd = math.sqrt(sum((y - (icpt + slope * x)) ** 2 for x, y in zip(xs, ys)) / (n - 2)) if n > 2 else 0
        proj = []
        for h in range(1, horizon + 1):
            x = n - 1 + h; yh = icpt + slope * x
            m = 1.96 * sd * math.sqrt(1 + 1 / n + (x - xb) ** 2 / sxx)
            proj.append({"week_start": (s[-1][0] + timedelta(days=7 * h)).isoformat(), "expected": round(max(0, yh), 2),
                         "low": round(max(0, yh - m), 2), "high": round(max(0, yh + m), 2)})
        change = slope * (n - 1) / yb if yb else 0
        res.append({"currency": cur, "status": "ok", "method": "Linear trend on weekly revenue; ~95% prediction interval from residuals",
                    "trend": "up" if change > .15 else "down" if change < -.15 else "flat",
                    "history": [{"week_start": d.isoformat(), "revenue": v} for d, v in s], "projection": proj,
                    "next_4_weeks": {"expected": round(sum(p["expected"] for p in proj), 2), "low": round(sum(p["low"] for p in proj), 2),
                                     "high": round(sum(p["high"] for p in proj), 2)},
                    "disclaimer": "Statistical estimate from past payments, not guaranteed income."})
    return res


def anomalies(rows: list[dict], now: datetime) -> list[dict]:
    out, now = [], _aware(now)
    for cur in sorted({r["currency"] for r in rows}):
        s = weekly_series(rows, cur, now)
        if len(s) >= 5:  # 1) revenue drop vs trailing baseline
            last_w, last = s[-1]; base = [v for _, v in s[:-1]][-8:]; mean = statistics.median(base); statistics.pstdev(base)
            if mean > 0 and last <= mean * 0.6:  # median baseline: one big payment must not hide a real drop
                ids = [r["id"] for r in _rev(rows) if r["currency"] == cur and last_w <= _aware(r["date"]).date() < last_w + timedelta(days=7)]
                out.append({"type": "revenue_drop", "severity": "high" if last <= mean * 0.4 else "medium", "currency": cur,
                            "title": f"{cur} revenue dropped {round((1 - last / mean) * 100)}% vs recent weeks",
                            "why": f"Week of {last_w} brought {last:,.2f} {cur}; the median of the prior {len(base)} weeks was {mean:,.2f}.",
                            "evidence_transaction_ids": ids[:20],
                            "suggested_action": "Review unpaid invoices and ask me to prepare payment reminders."})
        amts = [r["amount"] for r in _rev(rows) if r["currency"] == cur]  # 2) unusually large payments (robust z-score)
        if len(amts) >= 10:
            med = statistics.median(amts); mad = statistics.median(abs(a - med) for a in amts)
            if mad > 0:
                for r in _rev(rows):
                    if r["currency"] == cur and 0.6745 * (r["amount"] - med) / mad > 3.5 and r["amount"] > 2 * med:
                        out.append({"type": "large_payment", "severity": "low", "currency": cur,
                                    "title": f"Unusually large payment: {r['amount']:,.2f} {cur}",
                                    "why": f"Typical payment is about {med:,.2f} {cur}; this one is {r['amount'] / med:.1f}x larger (robust z-score > 3.5). Large is not the same as suspicious.",
                                    "evidence_transaction_ids": [r["id"]],
                                    "suggested_action": "Confirm it matches an expected customer/invoice."})
        rec_cut, base_cut = now - timedelta(days=14), now - timedelta(days=56)  # 3) failure-rate spike
        cr = [r for r in rows if r["currency"] == cur]
        rec = [r for r in cr if _aware(r["date"]) >= rec_cut]; base = [r for r in cr if base_cut <= _aware(r["date"]) < rec_cut]
        rf = [r for r in rec if r["status"] == DENIED]
        if len(rf) >= 3 and rec and base:
            rr, br = len(rf) / len(rec), sum(r["status"] == DENIED for r in base) / len(base)
            if rr >= 2 * br + 0.05:
                out.append({"type": "failure_spike", "severity": "high" if rr > .3 else "medium", "currency": cur,
                            "title": f"Failed {cur} payments up: {rr:.0%} of the last 14 days (baseline {br:.0%})",
                            "why": f"{len(rf)} of {len(rec)} recent transactions were denied versus a {br:.0%} baseline over the prior 6 weeks.",
                            "evidence_transaction_ids": [r["id"] for r in rf][:20],
                            "suggested_action": "Check whether the same customers are failing and follow up with them."})
    return sorted(out, key=lambda a: SEV[a["severity"]])
