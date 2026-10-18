"""
Automatic categories from the merchant / description text (multilingual, easy to extend).

Category ids are language-neutral; the report shows them in English or Persian.
Latin keywords match whole words, Persian keywords match anywhere inside the name.
"""

import re

from .normalize import compact

# Order matters: more specific rules first ("snapp food" before "snapp").
EXPENSE_RULES = [
    ("dining", ["اسنپ فود", "اسنپفود", "رستوران", "کافه", "کافی شاپ", "فست فود", "پیتزا", "برگر", "کبابی",
                "ساندویچ", "چلوکباب", "سفره خانه", "قنادی", "شیرینی", "بستنی", "آبمیوه",
                "restaurant", "cafe", "café", "coffee", "starbucks", "mcdonald's", "mcdonalds", "burger", "pizza",
                "kebab", "bistro", "diner", "bakery cafe", "uber eats", "doordash", "deliveroo", "lieferando",
                "just eat", "grubhub", "kfc", "subway", "dunkin", "costa", "gastronomie", "imbiss", "bäckerei cafe"]),
    ("transport", ["اسنپ", "تپسی", "مکسیم", "بنزین", "پمپ", "جایگاه سوخت", "سوخت", "مترو", "تاکسی", "پارکینگ",
                   "عوارض", "اتوبوس", "بلیط", "قطار", "رجا", "هواپیمایی", "علی بابا", "کارواش",
                   "uber", "lyft", "bolt", "taxi", "fuel", "gas station", "petrol", "shell", "aral", "esso", "chevron",
                   "exxon", "parking", "metro", "subway fare", "train", "deutsche bahn", "db bahn", "bvg", "mvg",
                   "airline", "ryanair", "lufthansa", "easyjet", "tankstelle", "car wash"]),
    ("online", ["دیجی کالا", "دیجیکالا", "ترب", "باسلام", "دیوار", "شیپور", "تخفیفان", "فروشگاه اینترنتی", "اینترنتی",
                "amazon", "amzn", "ebay", "aliexpress", "temu", "shein", "zalando", "etsy", "otto"]),
    ("groceries", ["سوپر", "هایپر", "افق کوروش", "کوروش", "رفاه", "شهروند", "جانبو", "اتکا", "میوه", "تره بار",
                   "نانوایی", "قصابی", "لبنیات", "پروتئین", "مرغ", "خواربار", "بقالی", "اسنپ مارکت",
                   "supermarket", "grocery", "groceries", "market", "aldi", "lidl", "rewe", "edeka", "penny", "netto",
                   "kaufland", "tesco", "sainsbury", "walmart", "costco", "kroger", "carrefour", "whole foods",
                   "trader joe's", "mercadona", "migros", "a101", "bim", "dia", "coop", "spar", "auchan", "leclerc",
                   "monoprix", "intermarché", "albert heijn", "jumbo", "big bazaar", "dmart", "bakery", "bäckerei", "metzgerei", "butcher", "supermarkt", "lebensmittel"]),
    ("bills", ["شارژ", "قبض", "ایرانسل", "همراه اول", "رایتل", "آبفا", "برق", "گاز", "مخابرات", "اینترنت", "شاتل",
               "های وب", "مبین نت", "بسته",
               "electricity", "electric", "water bill", "utility", "utilities", "internet", "mobile", "phone bill",
               "vodafone", "telekom", "o2", "verizon", "at&t", "t-mobile", "comcast", "stadtwerke", "strom",
               "rundfunkbeitrag", "insurance premium"]),
    ("health", ["داروخانه", "دارو", "پزشک", "دکتر", "کلینیک", "بیمارستان", "آزمایشگاه", "دندان", "درمانگاه", "عینک",
                "بیمه", "pharmacy", "apotheke", "drugstore", "cvs", "walgreens", "doctor", "arzt", "clinic",
                "hospital", "dentist", "zahnarzt", "optician", "health"]),
    ("shopping", ["پوشاک", "لباس", "کفش", "مانتو", "کیف", "آرایشی", "بهداشتی", "آرایشگاه", "سالن زیبایی", "عطر",
                  "ادکلن", "h&m", "zara", "primark", "uniqlo", "nike", "adidas", "clothing", "fashion", "shoes",
                  "douglas", "sephora", "hairdresser", "friseur", "boutique", "mall"]),
    ("entertainment", ["سینما", "فیلیمو", "نماوا", "تئاتر", "بازی", "گیم", "استخر", "باشگاه", "پارک", "شهربازی",
                       "کتاب", "اسپاتیفای", "cinema", "kino", "netflix", "spotify", "disney", "steam", "playstation",
                       "xbox", "gym", "fitness", "theatre", "theater", "concert", "bookstore", "books", "youtube"]),
    ("home", ["لوازم خانگی", "مبلمان", "ابزار", "الکتریکی", "ساختمانی", "شوینده", "ایکیا", "دکوراسیون",
              "ikea", "home depot", "hornbach", "obi", "bauhaus", "leroy merlin", "furniture", "hardware"]),
    ("education", ["آموزش", "دانشگاه", "مدرسه", "شهریه", "کلاس", "آموزشگاه", "دوره", "school", "university",
                   "tuition", "course", "udemy", "coursera", "schule", "universität"]),
    ("loans", ["قسط", "وام", "تسهیلات", "اقساط", "loan", "installment", "mortgage", "kredit", "emi"]),
    ("fees", ["کارمزد", "fee", "fees", "charges", "gebühr", "entgelt", "frais", "commission"]),
    ("transfer", ["کارت به کارت", "انتقال", "پایا", "ساتنا", "حواله", "transfer", "überweisung", "virement",
                  "transferencia", "sepa", "wire", "zelle", "venmo", "paypal"]),
    ("cash", ["خودپرداز", "عابر بانک", "برداشت نقدی", "atm", "cash withdrawal", "geldautomat", "bargeld",
              "abhebung", "retrait"]),
]

INCOME_RULES = [
    ("salary", ["حقوق", "دستمزد", "مزایا", "پاداش", "عیدی", "کارانه", "اضافه کار", "salary", "payroll", "wages",
                "gehalt", "lohn", "salaire", "nómina", "bonus"]),
    ("interest", ["سود", "interest", "zinsen", "dividend", "intérêts"]),
    ("refund", ["عودت", "برگشت", "استرداد", "بازگشت", "refund", "reversal", "erstattung", "rückbuchung",
                "remboursement", "reembolso", "cashback"]),
    ("loan_in", ["وام", "تسهیلات", "loan", "kredit"]),
    ("transfer_in", ["کارت به کارت", "انتقال", "پایا", "ساتنا", "حواله", "واریز", "transfer", "deposit",
                     "überweisung", "gutschrift", "virement", "zelle", "venmo", "paypal"]),
]


def _compile(rules):
    out = []
    for cat, words in rules:
        latin, persian = [], []
        for w in words:
            (latin if re.search(r"[a-zA-Zäöüéèàçñß]", w) else persian).append(w)
        latin_re = re.compile(r"(?<![\w&])(?:" + "|".join(re.escape(w) for w in latin) + r")(?![\w&])", re.I) \
            if latin else None
        out.append((cat, latin_re, [compact(w) for w in persian]))
    return out


_EXP, _INC = _compile(EXPENSE_RULES), _compile(INCOME_RULES)


def categorize(t) -> str:
    text = " ".join(filter(None, [t.merchant, t.person, t.desc, t.type_word]))
    ctext = compact(text)
    for cat, latin_re, persian in (_INC if t.direction == "in" else _EXP):
        if (latin_re and latin_re.search(text)) or any(w in ctext for w in persian):
            return cat
    if t.direction == "out" and t.person and not t.merchant:
        return "transfer"
    if t.direction == "in":
        return "other_income"
    if t.merchant or (t.type_word or "").lower() in ("خرید", "پرداخت", "purchase", "payment", "kartenzahlung"):
        return "other_purchase"
    return "other"
