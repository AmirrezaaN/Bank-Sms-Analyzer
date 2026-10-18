"""
Generate sample SMS files (with the correct answers) for trying out and testing the analyzer.

    python generate_samples.py

Writes to ./samples:
  1_fa_simple.txt          10 Persian SMS in one simple format
  2_fa_messy.txt           6 Iranian bank formats, unsorted, Persian digits, missing blank lines,
                           duplicates, OTP codes, ads, toman amounts, one-line SMS
  3_fa_large_2months.txt   ~50 SMS per day for 62 days, newest first and shuffled (3,100+ SMS)
  4_en_usd.txt             US-style alerts (templates) + labelled multi-line SMS, USD with cents
  5_de_eur.txt             German push messages (templates) + labelled SMS, 1.234,56 EUR style
  *.expected.json          the correct totals, used by the automated tests
"""

import datetime as dt
import json
import os
import random

from sms_analyzer import jalali

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "samples")
FA_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")
NOISE_WORDS = ("رمز", "کد تایید", "جشنواره", "مشتری گرامی", "قبض گاز", "verification code", "verify",
               "cashback this weekend", "TAN", "Apple Pay")


def is_noise(msg: str) -> bool:
    return any(w in msg for w in NOISE_WORDS)


def join_messages(rng, messages, no_blank_ratio=0.0):
    """Join SMS with varied separators. Some transactions don't even get a blank line."""
    out = []
    for i, msg in enumerate(messages):
        out.append(msg)
        if i == len(messages) - 1:
            break
        r = rng.random()
        if r < no_blank_ratio and not (is_noise(msg) or is_noise(messages[i + 1])):
            out.append("\n")
        elif r < no_blank_ratio + 0.08:
            out.append("\n\n\n")
        elif r < no_blank_ratio + 0.10:
            out.append("\n\n--------------------\n\n")
        else:
            out.append("\n\n")
    return "".join(out) + "\n"


def write(name, text, expected):
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(os.path.join(OUT_DIR, name + ".txt"), "w", encoding="utf-8") as fh:
        fh.write(text)
    with open(os.path.join(OUT_DIR, name + ".expected.json"), "w", encoding="utf-8") as fh:
        json.dump(expected, fh, ensure_ascii=False, indent=2)
    print(f"  {name}.txt  ({expected['transactions']} transactions)")


def expected_of(txns, dups, others, scale=1):
    """Correct answers. ``scale`` converts integer cents back to currency units."""
    inc = [t for t in txns if t["dir"] == "in"]
    out = [t for t in txns if t["dir"] == "out"]
    merch, days = {}, {}
    for t in out:
        if t.get("merchant") and not t.get("hidden_merchant"):
            name = t["merchant"].replace("فروشگاه ", "")
            merch[name] = merch.get(name, 0) + t["amount"]
        days[t["gdate"]] = days.get(t["gdate"], 0) + t["amount"]
    dates = sorted(t["gdate"] for t in txns)
    top_day = max(days.items(), key=lambda x: x[1]) if days else None
    top_m = max(merch.items(), key=lambda x: x[1]) if merch else (None, 0)
    names = {t["merchant"].replace("فروشگاه ", "") for t in txns if t.get("merchant")}
    names |= {t["party"] for t in txns if t.get("party")}
    return {
        "transactions": len(txns),
        "incomeCount": len(inc), "incomeTotal": round(sum(t["amount"] for t in inc) / scale, 2),
        "expenseCount": len(out), "expenseTotal": round(sum(t["amount"] for t in out) / scale, 2),
        "duplicates": dups, "otherMessages": others,
        "first": dates[0].isoformat(), "last": dates[-1].isoformat(),
        "topMerchant": top_m[0], "topMerchantTotal": round(top_m[1] / scale, 2),
        "names": sorted(names),         # every merchant / person name that appears in the file
        "topDay": top_day[0].isoformat() if top_day else None,
        "topDayTotal": round(top_day[1] / scale, 2) if top_day else 0,
    }


class Account:
    def __init__(self, name, balance, fmt):
        self.name, self.balance, self.fmt = name, balance, fmt


def make_txn(rng, acc, gdate, minute, tracking, merchants, people, kind=None, round_to=1000,
             transfer=(5e6, 60e6), deposit=(5e6, 120e6), salary=None, min_balance=5_000_000):
    """Amounts are integers: rials for Iran, cents for USD/EUR."""
    weights = [w for *_, w in merchants]
    kind = kind or rng.choices(["buy", "transfer_out", "transfer_in"], [80, 6, 14])[0]
    t = {"gdate": gdate, "time": (minute // 60, minute % 60), "tracking": str(tracking), "account": acc.name}

    def amount(lo, hi):
        return int(round(rng.uniform(lo, hi) / round_to)) * round_to

    if kind == "buy":
        name, lo, hi, _ = rng.choices(merchants, weights)[0]
        t.update(dir="out", merchant=name, amount=amount(lo, hi))
    elif kind == "transfer_out":
        t.update(dir="out", party=rng.choice(people), amount=amount(*transfer))
    elif kind == "transfer_in":
        t.update(dir="in", party=rng.choice(people), amount=amount(*deposit))
    elif kind == "salary":
        t.update(dir="in", party=salary[0], amount=salary[1], salary=True)
    if t["dir"] == "out" and acc.balance - t["amount"] < min_balance:
        t.update(dir="in", party=rng.choice(people), merchant=None)      # not enough money: a deposit instead
    acc.balance += t["amount"] if t["dir"] == "in" else -t["amount"]
    t["balance"] = acc.balance
    return t


# =============================================================================
# Persian (Iran, rial, Jalali calendar)
# =============================================================================

FA_MERCHANTS = [
    ("فروشگاه افق کوروش", 1_500_000, 15_000_000, 8), ("هایپراستار", 5_000_000, 40_000_000, 2),
    ("سوپرمارکت محله", 300_000, 5_000_000, 10), ("نانوایی بربری", 100_000, 400_000, 8),
    ("کافه لمیز", 1_000_000, 4_000_000, 6), ("رستوران شاندیز", 8_000_000, 30_000_000, 2),
    ("اسنپ", 600_000, 4_000_000, 10), ("اسنپ فود", 2_000_000, 10_000_000, 5),
    ("دیجی کالا", 3_000_000, 80_000_000, 2), ("پمپ بنزین آزادی", 300_000, 1_500_000, 3),
    ("داروخانه دکتر رازی", 500_000, 8_000_000, 2), ("شارژ ایرانسل", 200_000, 2_000_000, 3),
    ("پوشاک هاکوپیان", 10_000_000, 60_000_000, 1), ("سینما آزادی", 1_500_000, 5_000_000, 1),
    ("تپسی", 500_000, 3_000_000, 4), ("میوه فروشی گلستان", 1_000_000, 6_000_000, 4),
    ("قصابی برادران", 3_000_000, 20_000_000, 2), ("شهر کتاب", 1_000_000, 6_000_000, 1),
]
FA_PEOPLE = ["علی محمدی", "سارا احمدی", "رضا کریمی", "مریم حسینی", "حسین رضایی", "زهرا موسوی",
             "شرکت پارس تجارت", "فروشگاه آنلاین نیک", "محمد جعفری", "نرگس صادقی"]
FA_OTPS = ["رمز دوم پویا: {code}\nمهلت استفاده: 2 دقیقه\nبانک ملت",
           "کد تایید ورود به همراه بانک: {code}\nاین کد را در اختیار دیگران قرار ندهید",
           "رمز پویا خرید از اسنپ به مبلغ {amount} ریال: {code}"]
FA_ADS = ["مشتری گرامی، با فعال‌سازی همراه بانک از خدمات بیشتری بهره‌مند شوید.\nبانک ملت",
          "جشنواره تابستانه دیجی کالا! تا ۷۰٪ تخفیف",
          "قبض گاز شما صادر شد. شناسه قبض: 1234567890123"]


def jd(t):
    return jalali.from_date(t["gdate"])


def rial(v):
    return f"{v:,}"


def fa_user(t):
    y, m, d = jd(t)
    h, mi = t["time"]
    lines = ["واریز" if t["dir"] == "in" else "برداشت",
             f"مبلغ : {'+' if t['dir'] == 'in' else '-'}{rial(t['amount'])}",
             f"موجودی : {rial(t['balance'])}", f"شماره پیگیری : {t['tracking']}"]
    if t.get("merchant") and t["dir"] == "out":
        lines.append(t["merchant"] if t["merchant"].startswith("فروشگاه") else f"فروشگاه {t['merchant']}")
    elif t.get("party"):
        lines.append(f"{'واریز کننده' if t['dir'] == 'in' else 'گیرنده'} : {t['party']}")
    lines.append(f"تاریخ : {d}/{m}/{y} {h:02d}:{mi:02d}")
    return "\n".join(lines)


def fa_mellat(t):
    y, m, d = jd(t)
    h, mi = t["time"]
    kind = "واریز" if t["dir"] == "in" else ("خرید" if t.get("merchant") else "انتقال")
    lines = ["بانک ملت", kind, "حساب 3344", f"مبلغ: {rial(t['amount'])}", f"مانده: {rial(t['balance'])}"]
    if t.get("merchant"):
        lines.append(f"پذیرنده: {t['merchant']}")
    elif t.get("party"):
        lines.append(f"{'از' if t['dir'] == 'in' else 'به'}: {t['party']}")
    lines.append(f"{y % 100:02d}/{m:02d}/{d:02d}-{h:02d}:{mi:02d}")
    return "\n".join(lines)


def fa_saderat(t):
    """No bank name and no type word, only the sign. Persian digits."""
    y, m, d = jd(t)
    h, mi = t["time"]
    lines = [f"{'+' if t['dir'] == 'in' else '-'}{rial(t['amount'])}", "حساب 0215",
             f"مانده {rial(t['balance'])}", f"{m:02d}{d:02d}-{h:02d}{mi:02d}"]
    if t.get("merchant"):
        lines.insert(1, t["merchant"] if t["merchant"].startswith("فروشگاه") else f"فروشگاه {t['merchant']}")
    return "\n".join(lines).translate(FA_DIGITS)


def fa_melli(t):
    y, m, d = jd(t)
    h, mi = t["time"]
    kind = "واریز" if t["dir"] == "in" else ("خرید" if t.get("merchant") else "انتقال")
    t["hidden_merchant"] = True         # Bank Melli's SMS doesn't show the shop
    return "\n".join(["بانک ملی ایران", f"{kind}:{'+' if t['dir'] == 'in' else '-'}{rial(t['amount'])}",
                      "از:0108****5566", f"مانده:{rial(t['balance'])}", f"{m:02d}{d:02d}-{h:02d}:{mi:02d}"])


def fa_oneline(t):
    y, m, d = jd(t)
    h, mi = t["time"]
    if t["dir"] == "in":
        body = f"واریز {rial(t['amount'])} ریال از {t['party']}"
    elif t.get("merchant"):
        body = f"خرید {rial(t['amount'])} ریال از فروشگاه {t['merchant']}"
    else:
        body = f"انتقال {rial(t['amount'])} ریال به {t['party']}"
    return f"بانک پاسارگاد {body} مانده {rial(t['balance'])} تاریخ {y}/{m:02d}/{d:02d} ساعت {h:02d}:{mi:02d}"


def fa_toman(t):
    y, m, d = jd(t)
    h, mi = t["time"]
    toman = t["amount"] // 10
    if t["dir"] == "in":
        return f"افزایش اعتبار\nواریز {rial(toman)} تومان\nتاریخ: {y}/{m}/{d} - {h}:{mi:02d}"
    return f"پرداخت موفق\nخرید {rial(toman)} تومان از {t.get('merchant')}\nتاریخ: {y}/{m}/{d} - {h}:{mi:02d}"


def fa_txn(rng, acc, gdate, minute, track, kind=None):
    return make_txn(rng, acc, gdate, minute, track, FA_MERCHANTS, FA_PEOPLE, kind,
                    salary=("شرکت پارس تجارت (حقوق)", 950_000_000))


def sample_fa_simple():
    rng = random.Random(1)
    acc = Account("A", 65_000_000, fa_user)
    txns, track = [], 5555550000
    for day in range(1, 6):
        for k in range(2):
            track += 1
            kind = "transfer_in" if (day, k) in ((1, 0), (4, 0)) else "buy"
            txns.append(fa_txn(rng, acc, jalali.to_date(1405, 2, 20 + day), 9 * 60 + k * 300 + day * 7, track, kind))
    write("1_fa_simple", join_messages(rng, [acc.fmt(t) for t in txns]), expected_of(txns, 0, 0))


def sample_fa_messy():
    rng = random.Random(2)
    accs = [Account("user", 120_000_000, fa_user), Account("mellat", 80_000_000, fa_mellat),
            Account("saderat", 40_000_000, fa_saderat), Account("melli", 60_000_000, fa_melli),
            Account("pasargad", 30_000_000, fa_oneline), Account("wallet", 20_000_000, fa_toman)]
    txns, msgs, track = [], [], 7_100_000_000
    for i in range(48):
        acc = accs[i % len(accs)]
        track += rng.randint(1, 50)
        t = fa_txn(rng, acc, jalali.to_date(1405, 1, 1 + i // 3), 8 * 60 + (i * 97) % (14 * 60), track,
                   "buy" if acc.name == "wallet" and rng.random() < .8 else None)
        if acc.name == "wallet" and t["dir"] == "out" and not t.get("merchant"):
            t["merchant"] = "اسنپ"
        txns.append(t)
        msgs.append(acc.fmt(t))
    rng.shuffle(msgs)
    dup_msgs = [msgs[3], msgs[10], msgs[20]]
    for m in dup_msgs:
        msgs.insert(rng.randint(0, len(msgs)), m)
    noise = [FA_OTPS[0].format(code=48213), FA_OTPS[2].format(code=99812, amount="1,250,000"), FA_ADS[0], FA_ADS[1]]
    for m in noise:
        msgs.insert(rng.randint(0, len(msgs)), m)
    for k in rng.sample(range(len(msgs)), 6):
        msgs[k] = msgs[k].translate(FA_DIGITS)
    target = next(i for i, m in enumerate(msgs) if m.startswith("بانک ملت\n") and "مانده" in m)
    lines = msgs[target].split("\n")
    msgs[target] = "\n".join(lines[:2]) + "\n\n" + "\n".join(lines[2:])       # blank line inside one SMS
    msgs[1] = "‏" + msgs[1].replace("\n", "‏\n")                   # invisible RTL marks
    write("2_fa_messy", join_messages(rng, msgs, 0.15), expected_of(txns, len(dup_msgs), len(noise)))


def sample_fa_large():
    rng = random.Random(3)
    accs = [Account("user", 900_000_000, fa_user), Account("mellat", 300_000_000, fa_mellat),
            Account("saderat", 80_000_000, fa_saderat)]
    txns, days, others, track = [], [], 0, 8_200_000_000
    day, end = jalali.to_date(1405, 2, 1), jalali.to_date(1405, 3, 31)
    while day <= end:
        plan = [(accs[0], "salary")] if jalali.from_date(day)[2] == 1 else []
        plan += [(rng.choices(accs, [60, 30, 10])[0], None) for _ in range(rng.randint(40, 52) - len(plan))]
        minutes = sorted(rng.sample(range(7 * 60, 24 * 60), len(plan)))
        day_msgs = []
        for (acc, kind), minute in zip(plan, minutes):
            track += rng.randint(1, 900)
            t = fa_txn(rng, acc, day, minute, track, kind)
            txns.append(t)
            day_msgs.append(acc.fmt(t))
        for _ in range(rng.randint(2, 5)):
            day_msgs.insert(rng.randint(0, len(day_msgs)), rng.choice(FA_OTPS).format(
                code=rng.randint(10000, 99999), amount=rial(int(rng.uniform(1e6, 9e6)) // 1000 * 1000)))
            others += 1
        if rng.random() < 0.3:
            day_msgs.insert(rng.randint(0, len(day_msgs)), rng.choice(FA_ADS))
            others += 1
        days.append(day_msgs)
        day += dt.timedelta(days=1)
    flat = shuffle_like_a_phone(rng, days)
    dups = add_duplicates(rng, flat, 12)
    write("3_fa_large_2months", join_messages(rng, flat, 0.05), expected_of(txns, dups, others))
    print(f"     {len(flat)} SMS in total, {len(flat) / 62:.1f} per day")


def shuffle_like_a_phone(rng, days):
    """Newest first (like copying from a phone), some days swapped, small swaps inside days."""
    days = days[::-1]
    for _ in range(max(1, len(days) // 8)):
        a, b = rng.randrange(len(days)), rng.randrange(len(days))
        days[a], days[b] = days[b], days[a]
    flat = []
    for msgs in days:
        msgs = msgs[::-1]
        for _ in range(len(msgs) // 4):
            i = rng.randrange(max(1, len(msgs) - 1))
            if i + 1 < len(msgs):
                msgs[i], msgs[i + 1] = msgs[i + 1], msgs[i]
        flat.extend(msgs)
    return flat


def add_duplicates(rng, flat, n):
    dups = 0
    for _ in range(n):
        i = rng.randrange(len(flat))
        if is_noise(flat[i]):
            continue
        flat.insert(i + rng.randint(1, 30), flat[i])
        dups += 1
    return dups


# =============================================================================
# English (USD, cents)
# =============================================================================

EN_MERCHANTS = [
    ("STARBUCKS #1234", 450, 1200, 8), ("WHOLE FOODS MARKET", 2500, 18000, 6), ("SHELL OIL 5544", 3000, 7000, 3),
    ("AMAZON MKTPLACE", 1200, 15000, 5), ("UBER TRIP", 900, 4500, 5), ("NETFLIX.COM", 1549, 1549, 1),
    ("CVS PHARMACY", 600, 5000, 2), ("TARGET", 1500, 12000, 3), ("CHIPOTLE", 1100, 2600, 4),
    ("COMCAST", 8999, 8999, 1), ("H&M", 2000, 9000, 1), ("IKEA", 3000, 40000, 1),
]
EN_PEOPLE = ["JOHN SMITH", "EMILY DAVIS", "MICHAEL BROWN", "SARAH WILSON"]


def usd(cents):
    return f"${cents / 100:,.2f}"


def en_date(t):
    return f"{t['gdate']:%m/%d/%Y} " + dt.time(*t["time"]).strftime("%I:%M %p")


def en_chase(t):
    if t["dir"] == "out" and t.get("merchant"):
        return (f"Chase: Your card ending 4821 was charged {usd(t['amount'])} at {t['merchant']} on {en_date(t)}. "
                f"Avail bal: {usd(t['balance'])}")
    if t["dir"] == "out":
        return (f"Chase: You sent {usd(t['amount'])} to {t['party']} with Zelle on {en_date(t)}. "
                f"Avail bal: {usd(t['balance'])}")
    return (f"Chase: A deposit of {usd(t['amount'])} from {t['party']} was credited to your account ending 4821 "
            f"on {en_date(t)}. Avail bal: {usd(t['balance'])}")


def en_wells(t):
    kind = "Deposit" if t["dir"] == "in" else ("Purchase" if t.get("merchant") else "Transfer")
    who = f"Merchant: {t['merchant']}" if t.get("merchant") else f"{'From' if t['dir'] == 'in' else 'To'}: {t['party']}"
    return "\n".join(["Wells Fargo Bank", f"{kind}: USD {t['amount'] / 100:,.2f}", who, "Card: x7731",
                      f"Balance: USD {t['balance'] / 100:,.2f}", f"Date: {t['gdate']:%Y-%m-%d} {t['time'][0]:02d}:"
                      f"{t['time'][1]:02d}", f"Ref: {t['tracking']}"])


def sample_en():
    rng = random.Random(4)
    accs = [Account("chase", 320_000, en_chase), Account("wells", 150_000, en_wells)]
    txns, days, others, track = [], [], 0, 99_800_000
    day = dt.date(2026, 4, 1)
    while day <= dt.date(2026, 5, 15):
        plan = [(accs[0], "salary")] if day.day in (1, 15) else []
        plan += [(rng.choices(accs, [65, 35])[0], None) for _ in range(rng.randint(5, 12))]
        minutes = sorted(rng.sample(range(7 * 60, 23 * 60), len(plan)))
        msgs = []
        for (acc, kind), minute in zip(plan, minutes):
            track += rng.randint(1, 500)
            t = make_txn(rng, acc, day, minute, track, EN_MERCHANTS, EN_PEOPLE, kind, round_to=1,
                         transfer=(2000, 30000), deposit=(2000, 40000), salary=("ACME CORP PAYROLL", 285000),
                         min_balance=10_000)
            txns.append(t)
            msgs.append(acc.fmt(t))
        if rng.random() < 0.3:
            msgs.insert(rng.randint(0, len(msgs)), f"Your Chase verification code is {rng.randint(100000, 999999)}. "
                                                    "Don't share it with anyone.")
            others += 1
        if rng.random() < 0.1:
            msgs.insert(rng.randint(0, len(msgs)), "Chase: Get 5% cashback this weekend! Reply STOP to opt out.")
            others += 1
        days.append(msgs)
        day += dt.timedelta(days=1)
    flat = shuffle_like_a_phone(rng, days)
    dups = add_duplicates(rng, flat, 4)
    write("4_en_usd", join_messages(rng, flat, 0.05), expected_of(txns, dups, others, scale=100))


# =============================================================================
# German (EUR, cents, 1.234,56 style)
# =============================================================================

DE_MERCHANTS = [
    ("REWE Markt", 800, 9000, 8), ("ALDI SÜD", 600, 6000, 6), ("Lidl", 500, 5000, 5),
    ("Bäckerei Schmidt", 250, 1200, 6), ("Deutsche Bahn", 1990, 12990, 2), ("Aral Tankstelle", 3000, 8000, 2),
    ("Amazon EU", 1000, 15000, 3), ("Lieferando", 1500, 4500, 3), ("Apotheke am Markt", 500, 4000, 2),
    ("IKEA", 2000, 30000, 1), ("Kino Cinemaxx", 1100, 3000, 1),
]
DE_PEOPLE = ["Max Mustermann", "Anna Schmidt", "Lukas Weber", "Telekom Deutschland GmbH"]


def eur(cents):
    s = f"{cents / 100:,.2f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".") + " EUR"


def de_push(t):
    when = f"am {t['gdate']:%d.%m.%Y} um {t['time'][0]:02d}:{t['time'][1]:02d}"
    if t["dir"] == "out" and t.get("merchant"):
        body = f"Kartenzahlung {eur(t['amount'])} bei {t['merchant']}"
    elif t["dir"] == "out":
        body = f"Überweisung {eur(t['amount'])} an {t['party']}"
    else:
        body = f"Gutschrift {eur(t['amount'])} von {t['party']}"
    return f"Sparkasse: {body} {when}. Kontostand: {eur(t['balance'])}"


def de_labelled(t):
    if t["dir"] == "out":
        kind, who = "Lastschrift", f"Empfänger: {t.get('merchant') or t['party']}"
    else:
        kind, who = "Gutschrift", f"Auftraggeber: {t['party']}"
    sign = "+" if t["dir"] == "in" else "-"
    return "\n".join(["Commerzbank", f"{kind}: {sign}{eur(t['amount'])}", who, f"Saldo: {eur(t['balance'])}",
                      f"Datum: {t['gdate']:%d.%m.%Y} {t['time'][0]:02d}:{t['time'][1]:02d}"])


def sample_de():
    rng = random.Random(5)
    accs = [Account("sparkasse", 250_000, de_push), Account("commerz", 120_000, de_labelled)]
    txns, days, others, track = [], [], 0, 1
    day = dt.date(2026, 4, 1)
    while day <= dt.date(2026, 4, 30):
        plan = [(accs[0], "salary")] if day.day == 1 else []
        plan += [(rng.choices(accs, [70, 30])[0], None) for _ in range(rng.randint(4, 9))]
        minutes = sorted(rng.sample(range(7 * 60, 23 * 60), len(plan)))
        msgs = []
        for (acc, kind), minute in zip(plan, minutes):
            t = make_txn(rng, acc, day, minute, track, DE_MERCHANTS, DE_PEOPLE, kind, round_to=1,
                         transfer=(1500, 25000), deposit=(1500, 30000), salary=("Muster GmbH (Gehalt)", 285000),
                         min_balance=10_000)
            txns.append(t)
            msgs.append(acc.fmt(t))
        if rng.random() < 0.3:
            msgs.insert(rng.randint(0, len(msgs)), f"Ihre TAN für die Überweisung lautet {rng.randint(100000, 999999)}.")
            others += 1
        if rng.random() < 0.1:
            msgs.insert(rng.randint(0, len(msgs)), "Sparkasse: Jetzt neu - Apple Pay für Ihre Karte!")
            others += 1
        days.append(msgs)
        day += dt.timedelta(days=1)
    flat = shuffle_like_a_phone(rng, days)
    dups = add_duplicates(rng, flat, 3)
    write("5_de_eur", join_messages(rng, flat, 0.05), expected_of(txns, dups, others, scale=100))


if __name__ == "__main__":
    print("Writing samples to", OUT_DIR)
    sample_fa_simple()
    sample_fa_messy()
    sample_fa_large()
    sample_en()
    sample_de()
