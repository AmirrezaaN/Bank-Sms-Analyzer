"""
Statistics and insights from parsed transactions.

The output is language-neutral (ISO dates, category ids, insight ids with parameters);
the HTML report renders it in English or Persian, in the Gregorian or Jalali calendar.
"""

import datetime as _dt
from collections import defaultdict

from .normalize import compact
from .numbers import tidy


def _party(t) -> str:
    if t.merchant:
        return t.merchant
    if t.person:
        return t.person
    if t.desc:
        return t.desc
    return ""


def _party_kind(t) -> str:
    return "store" if t.merchant else "person" if t.person else "other"


def _txn(t):
    return {
        "d": t.iso, "time": t.time_str, "ts": t.timestamp, "dir": t.direction, "dirSrc": t.direction_source,
        "amount": tidy(t.amount), "fee": tidy(t.fee), "balance": None if t.balance is None else tidy(t.balance),
        "currency": t.currency, "foreign": t.foreign, "party": _party(t), "kind": _party_kind(t),
        "desc": t.desc or "", "category": t.category, "type": t.type_word or "", "tracking": t.tracking or "",
        "bank": t.bank or "", "account": t.account or "", "chainOk": t.chain_ok, "line": t.line,
        "template": t.template or "", "raw": t.raw,
    }


def analyze(result, source_name: str = "", lang: str = "auto", calendar: str = "auto") -> dict:
    txns = [t for t in result.transactions if not t.foreign]
    dated = [t for t in txns if t.gdate]
    income = [t for t in txns if t.direction == "in"]
    expense = [t for t in txns if t.direction == "out"]
    unknown = [t for t in txns if t.direction is None]

    total_in = sum(t.amount for t in income)
    total_fee = sum(t.fee for t in txns)
    total_out = sum(t.amount for t in expense) + total_fee

    # ---------- daily ----------
    daily = []
    first = last = None
    if dated:
        first, last = dated[0].gdate, dated[-1].gdate
        by_day = defaultdict(lambda: {"in": 0.0, "out": 0.0, "count": 0, "inCount": 0, "outCount": 0})
        for t in dated:
            b = by_day[t.gdate]
            b["count"] += 1
            if t.direction == "in":
                b["in"] += t.amount
                b["inCount"] += 1
            elif t.direction == "out":
                b["out"] += t.amount
                b["outCount"] += 1
            b["out"] += t.fee
        day = first
        while day <= last:
            b = by_day.get(day, {"in": 0, "out": 0, "count": 0, "inCount": 0, "outCount": 0})
            daily.append({"d": day.isoformat(), "wd": day.weekday(),
                          **{k: tidy(v) if isinstance(v, float) else v for k, v in b.items()}})
            day += _dt.timedelta(days=1)
    span = len(daily)

    # ---------- merchants / income sources ----------
    def group(items):
        g = {}
        for t in items:
            name = _party(t) or ""
            key = compact(name).lower() or f"__{t.category}"
            e = g.setdefault(key, {"name": name, "kind": _party_kind(t), "category": t.category, "count": 0,
                                   "total": 0.0, "max": 0.0, "first": t.iso, "last": t.iso})
            if _party_kind(t) == "store":
                e["kind"] = "store"          # a name seen as a shop anywhere is a shop
            e["count"] += 1
            e["total"] += t.amount
            e["max"] = max(e["max"], t.amount)
            if t.iso:
                e["first"] = min(filter(None, [e["first"], t.iso]))
                e["last"] = max(e["last"] or "", t.iso)
        out = sorted(g.values(), key=lambda e: -e["total"])
        tot = sum(e["total"] for e in out) or 1
        for e in out:
            e["avg"] = tidy(e["total"] / e["count"])
            e["share"] = round(e["total"] / tot, 6)
            e["total"], e["max"] = tidy(e["total"]), tidy(e["max"])
        return out

    merchants = group(expense)
    sources = group(income)
    stores = [m for m in merchants if m["kind"] == "store"]

    def cats(items, add_fee=0):
        c = defaultdict(lambda: {"total": 0.0, "count": 0})
        for t in items:
            c[t.category]["total"] += t.amount
            c[t.category]["count"] += 1
        if add_fee:
            c["fees"]["total"] += add_fee
        return sorted(({"id": k, "total": tidy(v["total"]), "count": v["count"]} for k, v in c.items()),
                      key=lambda e: -e["total"])

    categories = cats(expense, total_fee)
    income_categories = cats(income)

    # ---------- weekday (0 = Monday) / hour ----------
    weekday = [{"wd": i, "out": 0.0, "count": 0, "days": 0} for i in range(7)]
    for d in daily:
        weekday[d["wd"]]["days"] += 1
    for t in expense:
        if t.gdate:
            weekday[t.gdate.weekday()]["out"] += t.amount
            weekday[t.gdate.weekday()]["count"] += 1
    for w in weekday:
        w["avg"] = tidy(w["out"] / w["days"]) if w["days"] else 0
        w["out"] = tidy(w["out"])
    hourly = [{"hour": h, "out": 0.0, "count": 0} for h in range(24)]
    for t in expense:
        if t.time:
            hourly[t.time[0]]["out"] += t.amount
            hourly[t.time[0]]["count"] += 1
    for h in hourly:
        h["out"] = tidy(h["out"])

    # ---------- balances per account ----------
    balances = defaultdict(list)
    for t in dated:
        if t.balance is not None:
            balances[(t.bank or "", t.account_tail)].append(
                {"ts": t.timestamp, "v": tidy(t.balance), "d": t.iso, "t": t.time_str})
    accounts = [{"bank": bank, "tail": tail, "points": pts, "start": pts[0]["v"], "end": pts[-1]["v"],
                 "min": min(p["v"] for p in pts), "max": max(p["v"] for p in pts)}
                for (bank, tail), pts in balances.items()]
    accounts.sort(key=lambda a: -len(a["points"]))

    top_days = sorted((d for d in daily if d["out"]), key=lambda d: -d["out"])[:10]
    top_expenses = sorted(expense, key=lambda t: -t.amount)[:10]
    top_incomes = sorted(income, key=lambda t: -t.amount)[:10]

    persian = result.persian
    summary = {
        "source": source_name,
        "lang": lang if lang in ("fa", "en") else ("fa" if persian else "en"),
        "calendar": calendar if calendar in ("jalali", "gregorian") else "auto",
        "currency": result.currency,
        "totalMessages": result.total_messages, "transactions": len(result.transactions),
        "otherMessages": len(result.others), "duplicates": len(result.duplicates),
        "foreign": result.foreign,
        "incomeTotal": tidy(total_in), "incomeCount": len(income),
        "expenseTotal": tidy(total_out), "expenseCount": len(expense), "feeTotal": tidy(total_fee),
        "unknownTotal": tidy(sum(t.amount for t in unknown)), "unknownCount": len(unknown),
        "net": tidy(total_in - total_out),
        "first": first.isoformat() if first else "", "last": last.isoformat() if last else "",
        "firstTs": int(_dt.datetime.combine(first, _dt.time(), tzinfo=_dt.timezone.utc).timestamp() * 1000)
        if first else None,
        "spanDays": span, "activeDays": sum(1 for d in daily if d["count"]),
        "avgDailyExpense": tidy(total_out / span) if span else 0,
        "avgDailyIncome": tidy(total_in / span) if span else 0,
        "avgExpense": tidy(sum(t.amount for t in expense) / len(expense)) if expense else 0,
        "merchantCount": len(stores),
        "noDate": sum(1 for t in txns if not t.gdate),
        "chainChecked": result.chain_checked, "chainBroken": result.chain_broken,
        "inferredYears": result.inferred_years,
        "savingsRate": round((total_in - total_out) / total_in, 6) if total_in else None,
        "templateHits": result.template_hits,
        "generatedAt": _dt.datetime.now().strftime("%Y-%m-%dT%H:%M"),
    }

    return {
        "summary": summary,
        "insights": _insights(summary, stores, categories, weekday, hourly, top_days, top_expenses, sources),
        "warnings": _warnings(result, txns),
        "daily": daily, "merchants": merchants, "sources": sources,
        "categories": categories, "incomeCategories": income_categories,
        "weekday": weekday, "hourly": hourly, "accounts": accounts, "topDays": top_days,
        "topExpenses": [_txn(t) for t in top_expenses], "topIncomes": [_txn(t) for t in top_incomes],
        "transactions": [_txn(t) for t in result.transactions],
        "others": result.others, "duplicates": result.duplicates,
    }


def _insights(s, stores, cats, weekday, hourly, top_days, top_exp, sources):
    """Each insight is {id, kind, p}; the report holds the sentence for every language."""
    out = []
    if not s["transactions"]:
        return out
    if s["incomeTotal"] or s["expenseTotal"]:
        out.append({"id": "net_pos" if s["net"] >= 0 else "net_neg", "kind": "good" if s["net"] >= 0 else "bad",
                    "p": {"m": abs(s["net"])}})
    if s["savingsRate"] is not None and s["savingsRate"] > 0:
        out.append({"id": "savings", "kind": "info", "p": {"p": s["savingsRate"]}})
    if top_days:
        d = top_days[0]
        out.append({"id": "top_day", "kind": "info", "p": {"d": d["d"], "w": d["wd"], "m": d["out"], "n": d["outCount"]}})
    if stores:
        m = stores[0]
        out.append({"id": "top_store", "kind": "info", "p": {"s": m["name"], "m": m["total"], "n": m["count"],
                                                              "p": m["share"]}})
        freq = max(stores, key=lambda e: e["count"])
        if freq is not m:
            out.append({"id": "frequent_store", "kind": "info", "p": {"s": freq["name"], "n": freq["count"]}})
    if cats and s["expenseTotal"]:
        c = cats[0]
        out.append({"id": "top_category", "kind": "info", "p": {"c": c["id"], "p": c["total"] / s["expenseTotal"]}})
    wk = [w for w in weekday if w["days"]]
    if wk:
        w = max(wk, key=lambda w: w["avg"])
        out.append({"id": "top_weekday", "kind": "info", "p": {"w": w["wd"], "m": w["avg"]}})
    hrs = [h for h in hourly if h["count"]]
    if hrs:
        h = max(hrs, key=lambda h: h["count"])
        out.append({"id": "top_hour", "kind": "info", "p": {"h": h["hour"], "n": h["count"]}})
    if top_exp:
        t = top_exp[0]
        out.append({"id": "biggest_transfer" if (t.person and not t.merchant) else "biggest_expense", "kind": "info",
                    "p": {"m": tidy(t.amount), "d": t.iso, "s": _party(t) or t.type_word or ""}})
    if sources:
        src = sources[0]
        out.append({"id": "top_source", "kind": "info", "p": {"s": src["name"], "m": src["total"], "n": src["count"]}})
    if s["feeTotal"]:
        out.append({"id": "fees", "kind": "info", "p": {"m": s["feeTotal"]}})
    return out


def _warnings(result, txns):
    w = []
    if result.duplicates:
        w.append({"id": "duplicates", "p": {"n": len(result.duplicates)}})
    nd = sum(1 for t in txns if not t.gdate)
    if nd:
        w.append({"id": "no_date", "p": {"n": nd}})
    unk = sum(1 for t in txns if t.direction is None)
    if unk:
        w.append({"id": "unknown_direction", "p": {"n": unk}})
    for cal, year in result.inferred_years.items():
        w.append({"id": "inferred_year", "p": {"y": year, "c": cal}})
    if result.chain_broken:
        w.append({"id": "chain_broken", "p": {"n": result.chain_broken, "t": result.chain_checked}})
    if result.foreign:
        w.append({"id": "foreign_currency", "p": {"n": result.foreign, "c": result.currency or ""}})
    return w
