"""Command line interface: ``python analyze.py sms.txt`` or ``python -m sms_analyzer sms.txt``."""

import argparse
import json
import os
import sys
import time
import webbrowser

from .analysis import analyze
from .parser import Options, parse_text, decode_bytes
from .report import build_report
from .templates import TemplateError, find_formats_file, load_formats


def _setup_console():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass


def _pick_files():
    try:
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        paths = filedialog.askopenfilenames(title="Select the SMS text file(s)",
                                            filetypes=[("Text files", "*.txt"), ("All files", "*.*")])
        root.destroy()
        return list(paths)
    except Exception:
        p = input("Path of the .txt file: ").strip().strip('"')
        return [p] if p else []


def _money(v, cur):
    s = f"{v:,.2f}".rstrip("0").rstrip(".") if isinstance(v, float) else f"{v:,}"
    return f"{s} {cur or ''}".strip()


WARNINGS = {
    "duplicates": "{n} duplicate SMS were counted only once",
    "no_date": "{n} transactions have no recognisable date",
    "unknown_direction": "{n} transactions could not be classified as income or expense",
    "inferred_year": "some SMS have no year; {y} was assumed",
    "chain_broken": "for {n} of {t} transactions the balance doesn't follow from the previous SMS",
    "foreign_currency": "{n} transactions in other currencies are excluded from the {c} totals",
}


def build_parser():
    ap = argparse.ArgumentParser(
        prog="sms-analyzer",
        description="Analyse bank SMS messages from a text file and build an interactive HTML report.")
    ap.add_argument("files", nargs="*", help="text file(s) with the copied SMS messages")
    ap.add_argument("-o", "--output", help="path of the HTML report (default: <input>_report.html)")
    ap.add_argument("-f", "--formats", help="SMS templates file (default: ./sms_formats.txt)")
    ap.add_argument("--no-formats", action="store_true", help="ignore the templates file")
    ap.add_argument("--lang", choices=["auto", "en", "fa"], default="auto", help="initial report language")
    ap.add_argument("--calendar", choices=["auto", "jalali", "gregorian"], default="auto",
                    help="calendar for 2-digit years and the report's initial calendar")
    ap.add_argument("--date-order", choices=["dmy", "mdy", "ymd"], help="order of ambiguous numeric dates")
    ap.add_argument("--decimal", choices=[",", "."], help="decimal separator of amounts")
    ap.add_argument("--currency", help="currency to assume when the SMS do not mention one (e.g. EUR, IRR)")
    ap.add_argument("--json", help="also save the analysis as JSON")
    ap.add_argument("--no-open", action="store_true", help="do not open the report in the browser")
    return ap


def main(argv=None):
    _setup_console()
    args = build_parser().parse_args(argv)

    files = args.files or _pick_files()
    if not files:
        print("No file selected.")
        return 1
    texts = []
    for f in files:
        if not os.path.isfile(f):
            print(f"File not found: {f}")
            return 1
        with open(f, "rb") as fh:
            texts.append(decode_bytes(fh.read()))

    formats = None
    formats_path = None if args.no_formats else find_formats_file(args.formats)
    if formats_path:
        try:
            formats = load_formats(formats_path)
        except (OSError, TemplateError) as e:
            print(f"Error in templates file: {e}")
            return 2
    elif args.formats:
        print(f"Templates file not found: {args.formats}")
        return 2

    cal = {"jalali": "j", "gregorian": "g"}.get(args.calendar, "auto")
    options = Options(formats=formats, calendar=cal, date_order=args.date_order, decimal=args.decimal,
                      currency=args.currency)
    t0 = time.perf_counter()
    result = parse_text("\n\n".join(texts), options)
    data = analyze(result, ", ".join(os.path.basename(f) for f in files), args.lang, args.calendar)
    out = args.output or os.path.splitext(os.path.abspath(files[0]))[0] + "_report.html"
    build_report(data, out)
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=1)
    elapsed = time.perf_counter() - t0

    s, cur = data["summary"], data["summary"]["currency"]
    print("=" * 60)
    print(f" Messages: {s['totalMessages']}  |  transactions: {s['transactions']}  |  "
          f"other: {s['otherMessages']}  |  duplicates: {s['duplicates']}")
    if formats:
        used = {k: v for k, v in s["templateHits"].items() if k}
        print(f" Templates: {len(formats.templates)} loaded from {os.path.basename(formats_path)}"
              + (f", matched: " + ", ".join(f"{k} ({v})" for k, v in used.items()) if used else ", none matched"))
    if s["first"]:
        print(f" Period: {s['first']} .. {s['last']}  ({s['spanDays']} days)")
    print(f" Income:  {_money(s['incomeTotal'], cur)}  in {s['incomeCount']} credits")
    print(f" Expense: {_money(s['expenseTotal'], cur)}  in {s['expenseCount']} debits")
    print(f" Net:     {_money(s['net'], cur)}")
    stores = [m for m in data["merchants"] if m["kind"] == "store"]
    if stores:
        print(f" Top merchant: {stores[0]['name']}  ({_money(stores[0]['total'], cur)}, {stores[0]['count']}x)")
    if data["topDays"]:
        print(f" Most expensive day: {data['topDays'][0]['d']}  ({_money(data['topDays'][0]['out'], cur)})")
    for w in data["warnings"]:
        print(" ! " + WARNINGS.get(w["id"], w["id"]).format(**w["p"]))
    print("=" * 60)
    print(f" Report written in {elapsed:.2f}s:\n {out}")
    if not args.no_open:
        webbrowser.open("file:///" + out.replace("\\", "/"))
    return 0
