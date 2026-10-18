"""Tests for the templates file, the sample files (against their known answers), the report and the CLI."""

import datetime as dt
import json
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from sms_analyzer import Options, analyze, build_report, load_formats, parse_file, parse_formats, parse_text  # noqa
from sms_analyzer.templates import TemplateError  # noqa: E402

FORMATS = os.path.join(ROOT, "sms_formats.txt")


def opts(text):
    return Options(formats=parse_formats(text))


class TemplateTests(unittest.TestCase):
    def test_default_file_loads(self):
        fmt = load_formats(FORMATS)
        self.assertGreaterEqual(len(fmt.templates), 5)
        self.assertIn("Lohn", fmt.in_words)

    def test_german_template_with_optional_parts(self):
        o = opts("[template: de]\n@decimal: ,\n"
                 "{bank}: {type} {amount} [[bei {merchant}]] [[an {person}]] am {date:dd.mm.yyyy} um {time}. "
                 "Kontostand: {balance}")
        r = parse_text("Sparkasse: Kartenzahlung 30,41 EUR bei Aral Tankstelle am 29.04.2026 um 16:55. "
                       "Kontostand: 1.446,87 EUR\n"
                       "Sparkasse: Überweisung 75,00 EUR an Max Mustermann am 30.04.2026 um 08:00. "
                       "Kontostand: 1.371,87 EUR", o)
        a, b = r.transactions
        self.assertEqual((a.bank, a.merchant, a.amount, a.currency, a.balance, a.gdate, a.time, a.direction),
                         ("Sparkasse", "Aral Tankstelle", 30.41, "EUR", 1446.87, dt.date(2026, 4, 29), (16, 55), "out"))
        self.assertEqual((b.person, b.direction, b.chain_ok), ("Max Mustermann", "out", True))

    def test_us_template_and_options(self):
        o = opts("[template: us]\n@currency: USD\n@direction: out\n"
                 "{bank}: You sent {amount} to {person} [[with {desc}]] on {date:mm/dd/yyyy} {time}. Avail bal: {balance}")
        t = parse_text("Chase: You sent $160.90 to EMILY DAVIS with Zelle on 05/08/2026 06:15 PM. "
                       "Avail bal: $8,137.02", o).transactions[0]
        self.assertEqual((t.amount, t.person, t.desc, t.gdate, t.time, t.direction_source),
                         (160.9, "EMILY DAVIS", "Zelle", dt.date(2026, 5, 8), (18, 15), "template"))

    def test_type_word_in_literal_text(self):
        o = opts("[template: es]\n@decimal: ,\n"
                 "{bank}: Compra con tarjeta {account} por {amount} en {merchant} el {date:dd/mm/yyyy} a las {time}.")
        t = parse_text("BBVA: Compra con tarjeta *1234 por 45,90 EUR en MERCADONA el 12/03/2026 a las 18:45.",
                       o).transactions[0]
        self.assertEqual((t.direction, t.amount, t.merchant, t.category), ("out", 45.9, "MERCADONA", "groceries"))

    def test_jalali_template(self):
        o = opts("[template: fa]\n@language: fa\n{bank}\n{type} {amount} ریال\nمانده {balance}\n{date:yy/mm/dd} {time}")
        t = parse_text("بانک تجارت\nبرداشت ۱,۲۰۰,۰۰۰ ریال\nمانده ۵,۰۰۰,۰۰۰\n۰۵/۰۲/۲۲ ۱۰:۳۰", o).transactions[0]
        self.assertEqual((t.bank, t.amount, t.date.cal, t.gdate), ("بانک تجارت", 1200000, "j", dt.date(2026, 5, 12)))

    def test_trailing_lines_are_absorbed(self):
        o = opts("[template: x]\nPaid {amount} at {merchant}")
        r = parse_text("Paid 12.00 EUR at Cafe Luna\nDate: 2026-04-01 09:00\nRef: 77\n\nPaid 3.00 EUR at Kiosk", o)
        self.assertEqual(len(r.transactions), 2)
        self.assertEqual((r.transactions[0].tracking, r.transactions[0].gdate), ("77", dt.date(2026, 4, 1)))

    def test_errors_are_clear(self):
        for text, msg in [("[template: a]\nhello {nope}", "unknown placeholder"),
                          ("[template: a]\nno placeholders", "no {placeholders}"),
                          ("[template: a]\n{merchant} only", "needs an {amount}"),
                          ("[template: a]\n@colour: red\n{amount}", "unknown option"),
                          ("[template: a]\n[[{amount}", "without"),
                          ("{amount}", "outside a [section]")]:
            with self.assertRaises(TemplateError) as cm:
                parse_formats(text)
            self.assertIn(msg, str(cm.exception))


class SampleFileTests(unittest.TestCase):
    """Every sample must give exactly the answers stored in its .expected.json file."""

    def check(self, name, formats=True):
        path = os.path.join(ROOT, "samples", name + ".txt")
        if not os.path.exists(path):
            self.skipTest("run `python generate_samples.py` first")
        with open(os.path.join(ROOT, "samples", name + ".expected.json"), encoding="utf-8") as fh:
            exp = json.load(fh)
        o = Options(formats=load_formats(FORMATS) if formats else None)
        data = analyze(parse_file(path, o))
        s = data["summary"]
        for k in ("transactions", "incomeCount", "incomeTotal", "expenseCount", "expenseTotal",
                  "duplicates", "otherMessages", "first", "last"):
            self.assertEqual(s[k], exp[k], k)
        stores = [m for m in data["merchants"] if m["kind"] == "store"]
        self.assertEqual((stores[0]["name"], stores[0]["total"]), (exp["topMerchant"], exp["topMerchantTotal"]))
        self.assertEqual((data["topDays"][0]["d"], data["topDays"][0]["out"]), (exp["topDay"], exp["topDayTotal"]))
        names = {m["name"] for m in data["merchants"] + data["sources"] if m["name"]}
        self.assertEqual(names - set(exp["names"]), set(), "names that are not in the file")
        self.assertEqual((s["chainBroken"], s["unknownCount"], s["noDate"]), (0, 0, 0))

    def test_fa_simple(self):
        self.check("1_fa_simple")

    def test_fa_messy(self):
        self.check("2_fa_messy")

    def test_fa_large(self):
        self.check("3_fa_large_2months")

    def test_fa_without_templates(self):
        self.check("2_fa_messy", formats=False)

    def test_en_usd(self):
        self.check("4_en_usd")

    def test_de_eur(self):
        self.check("5_de_eur")


class ReportTests(unittest.TestCase):
    SMS = "Purchase: 12.50 EUR\nMerchant: </script><b>x\nDate: 2026-04-01 10:00"

    def test_html_is_built_and_safe(self):
        data = analyze(parse_text(self.SMS), "test.txt")
        with tempfile.TemporaryDirectory() as d:
            out = build_report(data, os.path.join(d, "r.html"))
            with open(out, encoding="utf-8") as fh:
                html = fh.read()
        self.assertNotIn("/*__DATA__*/", html)
        self.assertEqual(html.count("</script>"), 2)        # only the template's own tags
        self.assertIn('"expenseTotal":12.5', html)

    def test_empty_input(self):
        data = analyze(parse_text("hello\n\nnot a bank message"))
        self.assertEqual((data["summary"]["transactions"], data["summary"]["otherMessages"]), (0, 2))
        with tempfile.TemporaryDirectory() as d:
            build_report(data, os.path.join(d, "r.html"))

    def test_cli(self):
        with tempfile.TemporaryDirectory() as d:
            src = os.path.join(d, "in.txt")
            with open(src, "w", encoding="utf-16") as fh:       # Windows Notepad "Unicode"
                fh.write(self.SMS)
            out, js = os.path.join(d, "out.html"), os.path.join(d, "out.json")
            res = subprocess.run([sys.executable, os.path.join(ROOT, "analyze.py"), src, "-o", out, "--json", js,
                                  "--no-open", "--lang", "fa"], capture_output=True, text=True, encoding="utf-8",
                                 cwd=ROOT)
            self.assertEqual(res.returncode, 0, res.stderr)
            self.assertIn("12.5 EUR", res.stdout)
            with open(js, encoding="utf-8") as fh:
                self.assertEqual(json.load(fh)["summary"]["lang"], "fa")
            self.assertTrue(os.path.exists(out))

    def test_cli_reports_template_errors(self):
        with tempfile.TemporaryDirectory() as d:
            bad, src = os.path.join(d, "f.txt"), os.path.join(d, "in.txt")
            with open(bad, "w", encoding="utf-8") as fh:
                fh.write("[template: x]\n{oops}")
            with open(src, "w", encoding="utf-8") as fh:
                fh.write(self.SMS)
            res = subprocess.run([sys.executable, os.path.join(ROOT, "analyze.py"), src, "-f", bad, "--no-open"],
                                 capture_output=True, text=True, encoding="utf-8", cwd=ROOT)
            self.assertEqual(res.returncode, 2)
            self.assertIn("unknown placeholder", res.stdout)


if __name__ == "__main__":
    unittest.main()
