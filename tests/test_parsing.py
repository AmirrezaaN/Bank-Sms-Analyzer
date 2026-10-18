"""Unit tests for numbers, dates, the label reader and the parsing pipeline.

Run from the project root:  python -m unittest discover -s tests -v
"""

import datetime as dt
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from sms_analyzer import jalali, parse_text, analyze  # noqa: E402
from sms_analyzer.dates import DateValue, extract_datetime, parse_with_format  # noqa: E402
from sms_analyzer.heuristic import classify_line  # noqa: E402
from sms_analyzer.normalize import normalize  # noqa: E402
from sms_analyzer.numbers import parse_amount, to_number, find_currency  # noqa: E402

FA_SMS = """برداشت
مبلغ : -400000
موجودی : 65646444
شماره پیگیری : 5555555555
فروشگاه رفاه
تاریخ : 22/2/1405 22:35"""


def fa_sms(kind, amount, balance, date, merchant=None, track=None):
    sign = "+" if kind == "واریز" else "-"
    lines = [kind, f"مبلغ : {sign}{amount:,}", f"موجودی : {balance:,}"]
    if track:
        lines.append(f"شماره پیگیری : {track}")
    if merchant:
        lines.append(f"فروشگاه {merchant}")
    lines.append(f"تاریخ : {date}")
    return "\n".join(lines)


class JalaliTests(unittest.TestCase):
    def test_known_dates(self):
        self.assertEqual(jalali.jalali_to_gregorian(1405, 1, 1), (2026, 3, 21))
        self.assertEqual(jalali.jalali_to_gregorian(1403, 1, 1), (2024, 3, 20))
        self.assertEqual(jalali.gregorian_to_jalali(2026, 10, 9), (1405, 7, 17))

    def test_roundtrip(self):
        d = dt.date(2015, 1, 1)
        while d < dt.date(2035, 1, 1):
            self.assertEqual(jalali.to_date(*jalali.from_date(d)), d)
            d += dt.timedelta(days=1)

    def test_leap(self):
        self.assertTrue(jalali.is_leap_jalali(1403))
        self.assertFalse(jalali.is_valid_jalali(1404, 12, 30))


class NumberTests(unittest.TestCase):
    def test_number_styles(self):
        self.assertEqual(to_number("1,234.56"), 1234.56)
        self.assertEqual(to_number("1.234,56"), 1234.56)
        self.assertEqual(to_number("400,000"), 400000)
        self.assertEqual(to_number("4.000.000"), 4000000)
        self.assertEqual(to_number("12,50"), 12.5)
        self.assertEqual(to_number("1'234.50"), 1234.5)
        self.assertEqual(to_number("1,234", decimal=","), 1.234)

    def test_amounts(self):
        self.assertEqual(parse_amount("-400000"), (400000, -1, None))
        self.assertEqual(parse_amount("+ 1,500,000"), (1500000, 1, None))
        self.assertEqual(parse_amount("400,000-"), (400000, -1, None))
        self.assertEqual(parse_amount("25,000 تومان"), (25000, None, "IRT"))
        self.assertEqual(parse_amount("-$1,234.56"), (1234.56, -1, "USD"))
        self.assertEqual(parse_amount("23,45 EUR"), (23.45, None, "EUR"))
        self.assertEqual(parse_amount("Rs.1,250.00"), (1250.0, None, "INR"))
        self.assertIsNone(parse_amount("Get 5% off"))
        self.assertIsNone(parse_amount("6037991234567890"))        # a card number, not an amount

    def test_currency(self):
        self.assertEqual(find_currency("12 €"), "EUR")
        self.assertEqual(find_currency("مبلغ 400 ریال"), "IRR")
        self.assertIsNone(find_currency("Please try again"))


class DateTests(unittest.TestCase):
    def test_numeric(self):
        self.assertEqual(extract_datetime("22/2/1405 22:35")[:2], (DateValue("j", 1405, 2, 22), (22, 35)))
        self.assertEqual(extract_datetime("05/02/22-22:35", "j")[:2], (DateValue("j", 1405, 2, 22), (22, 35)))
        self.assertEqual(extract_datetime("21.04.2026 18:32")[:2], (DateValue("g", 2026, 4, 21), (18, 32)))
        self.assertEqual(extract_datetime("2026-04-21 2:05 PM")[:2], (DateValue("g", 2026, 4, 21), (14, 5)))
        self.assertEqual(extract_datetime("04/21/2026")[0], DateValue("g", 2026, 4, 21))        # 21 > 12 -> m/d/y
        self.assertEqual(extract_datetime("05/04/2026", order="mdy")[0], DateValue("g", 2026, 5, 4))
        self.assertEqual(extract_datetime("0222-2235", "j")[:2], (DateValue("j", None, 2, 22), (22, 35)))
        self.assertIsNone(extract_datetime("1404/12/30")[0])         # 1404 is not a leap year

    def test_month_names(self):
        self.assertEqual(extract_datetime("22 اردیبهشت 1405")[0], DateValue("j", 1405, 2, 22))
        self.assertEqual(extract_datetime("on 06-Apr-26")[0], DateValue("g", 2026, 4, 6))
        self.assertEqual(extract_datetime("May 5, 2026")[0], DateValue("g", 2026, 5, 5))
        self.assertEqual(extract_datetime("3. März 2026")[0], DateValue("g", 2026, 3, 3))

    def test_formats(self):
        self.assertEqual(parse_with_format("21.04.2026", "dd.mm.yyyy"), DateValue("g", 2026, 4, 21))
        self.assertEqual(parse_with_format("05/02/22", "yy/mm/dd", "j"), DateValue("j", 1405, 2, 22))
        self.assertEqual(parse_with_format("7 Apr 2026", "d mmm yyyy"), DateValue("g", 2026, 4, 7))


class LabelReaderTests(unittest.TestCase):
    def test_normalize(self):
        self.assertEqual(normalize("‏۱۲۳٬۴۵۶ ريال"), "123,456 ریال")

    def test_persian_lines(self):
        self.assertEqual(classify_line("انتقال:-1,000,000"), {"type": ("انتقال", "out"), "amount": (1000000, -1, None)})
        info = classify_line("خرید 250,000 ریال از فروشگاه رفاه")
        self.assertEqual((info["amount"][0], info["merchant"]), (250000, "رفاه"))
        info = classify_line("بانک پاسارگاد واریز 5,000,000 ریال از علی محمدی مانده 30,000,000 تاریخ 1405/01/03 ساعت 09:05")
        self.assertEqual((info["bank"], info["person"], info["balance"][0]), ("بانک پاسارگاد", "علی محمدی", 30000000))
        self.assertEqual((info["date"], info["time"]), (DateValue("j", 1405, 1, 3), (9, 5)))
        self.assertEqual(classify_line("گیرنده : فروشگاه آنلاین نیک"), {"person": "فروشگاه آنلاین نیک"})
        self.assertIn("available", classify_line("مانده قابل برداشت: 1000"))
        self.assertEqual(classify_line("خریدار"), {"text": "خریدار"})

    def test_other_languages(self):
        self.assertEqual(classify_line("Merchant: Coffee Shop"), {"merchant": "Coffee Shop"})
        self.assertEqual(classify_line("Balance: USD 1,234.56")["balance"], (1234.56, None, "USD"))
        info = classify_line("Lastschrift: -59,99 EUR")
        self.assertEqual((info["type"], info["amount"]), (("Lastschrift", "out"), (59.99, -1, "EUR")))
        self.assertEqual(classify_line("Saldo: 1.120,40 EUR")["balance"][0], 1120.40)
        self.assertEqual(classify_line("Empfänger: Telekom Deutschland GmbH"), {"person": "Telekom Deutschland GmbH"})
        info = classify_line("Rs 2,000 credited to A/c XX4521 on 06-Apr-26. Avl Bal Rs 20,430.55")
        self.assertEqual((info["type"][1], info["amount"][0], info["available"][0]), ("in", 2000, 20430.55))
        self.assertNotIn("amount", classify_line("Get 5% cashback this weekend!"))


class PipelineTests(unittest.TestCase):
    def test_persian_user_format(self):
        t = parse_text(FA_SMS).transactions[0]
        self.assertEqual((t.amount, t.direction, t.balance, t.tracking, t.merchant, t.currency),
                         (400000, "out", 65646444, "5555555555", "رفاه", "IRR"))
        self.assertEqual((t.gdate, t.time), (dt.date(2026, 5, 12), (22, 35)))

    def test_no_blank_lines_and_unsorted(self):
        a = fa_sms("برداشت", 100000, 900000, "2/2/1405 10:00", "کافه", 1)
        b = fa_sms("واریز", 500000, 1400000, "3/2/1405 09:00", None, 2)
        c = fa_sms("برداشت", 400000, 1000000, "1/2/1405 08:00", "رفاه", 3)
        r = parse_text("\n".join([b, a, c]))
        self.assertEqual([t.amount for t in r.transactions], [400000, 100000, 500000])
        self.assertEqual((r.chain_checked, r.chain_broken), (2, 0))

    def test_separators_and_blank_line_inside_sms(self):
        a = fa_sms("برداشت", 100000, 900000, "2/2/1405 10:00", "کافه", 1)
        mellat = "بانک ملت\nخرید\n\nحساب 3344\nمبلغ: 400,000\nمانده: 1,000,000\n05/02/22-22:35"
        r = parse_text(f"\n\n\n{a}\n\n\n-------------\n\n{mellat}\n\n")
        self.assertEqual(len(r.transactions), 2)
        t = [t for t in r.transactions if t.bank][0]
        self.assertEqual((t.bank, t.direction, t.amount, t.balance), ("بانک ملت", "out", 400000, 1000000))

    def test_otp_ads_duplicates(self):
        text = "\n\n".join([FA_SMS, "رمز پویا خرید از اسنپ به مبلغ 1,250,000 ریال: 99812",
                            "مشتری گرامی، با فعال‌سازی همراه بانک ...\nبانک ملت", FA_SMS,
                            "Your verification code is 482913", "Ihre TAN lautet 123456"])
        r = parse_text(text)
        self.assertEqual((len(r.transactions), len(r.others), len(r.duplicates)), (1, 4, 1))

    def test_toman_and_fee(self):
        t = parse_text("پرداخت موفق\nخرید 25,000 تومان از اسنپ\nتاریخ: 1405/1/12 - 8:35").transactions[0]
        self.assertEqual((t.amount, t.currency, t.merchant), (250000, "IRR", "اسنپ"))
        r = parse_text("انتقال:-1,000,000\nکارمزد: 5,000\nمانده:8,995,000\n1405/01/02 10:00\n\n"
                       "واریز:+1,000\nمانده:10,000,000\n1405/01/01 10:00")
        self.assertEqual((r.transactions[1].fee, r.transactions[1].chain_ok), (5000, True))
        self.assertEqual(analyze(r)["summary"]["expenseTotal"], 1005000)

    def test_direction_from_balance_and_same_minute(self):
        r = parse_text("Amount: 1,000\nBalance: 10,000\n2026-01-01 10:00\n\nAmount: 3,000\nBalance: 7,000\n"
                       "2026-01-01 11:00\n\nAmount: 5,000\nBalance: 12,000\n2026-01-01 12:00")
        self.assertEqual([t.direction for t in r.transactions], [None, "out", "in"])
        a = fa_sms("برداشت", 100, 900, "1/1/1405 10:00", "x", 1)
        b = fa_sms("برداشت", 200, 700, "1/1/1405 10:00", "y", 2)
        c = fa_sms("برداشت", 50, 1000, "1/1/1405 09:00", "z", 3)
        r = parse_text("\n\n".join([b, a, c]))
        self.assertEqual(([t.amount for t in r.transactions], r.chain_broken), ([50, 100, 200], 0))

    def test_missing_year(self):
        r = parse_text(FA_SMS + "\n\n-۲۵۴,۰۰۰\nحساب ۰۲۱۵\nمانده ۲۹,۷۴۸,۰۰۰\n۰۲۲۳-۲۰۵۶")
        self.assertEqual(r.transactions[-1].date, DateValue("j", 1405, 2, 23))
        self.assertEqual(r.inferred_years, {"j": 1405})

    def test_english_multiline(self):
        text = ("Wells Fargo Bank\nPurchase: USD 64.99\nMerchant: AMAZON MKTPLACE\nCard: x7731\n"
                "Balance: USD 1,234.56\nDate: 2026-04-21 14:32\nRef: 99812345")
        t = parse_text(text).transactions[0]
        self.assertEqual((t.bank, t.direction, t.amount, t.currency, t.merchant, t.balance, t.tracking, t.category),
                         ("Wells Fargo Bank", "out", 64.99, "USD", "AMAZON MKTPLACE", 1234.56, "99812345", "online"))

    def test_foreign_currency_excluded(self):
        text = "\n\n".join(["Purchase: 10.00 EUR\nDate: 2026-04-01", "Purchase: 20.00 EUR\nDate: 2026-04-02",
                            "Purchase: 5.00 USD\nDate: 2026-04-03"])
        r = parse_text(text)
        self.assertEqual((r.currency, r.foreign), ("EUR", 1))
        self.assertEqual(analyze(r)["summary"]["expenseTotal"], 30)


if __name__ == "__main__":
    unittest.main()
