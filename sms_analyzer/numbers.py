"""Amount and currency parsing for many number styles: 1,234.56 / 1.234,56 / 400,000 / 12,50 / 1'234.50."""

import re

# Currency words/symbols -> ISO code. "IRT" (toman) is converted to rial later.
CURRENCIES = {
    "ریال": "IRR", "rial": "IRR", "rials": "IRR", "irr": "IRR",
    "تومان": "IRT", "تومن": "IRT", "toman": "IRT", "tomans": "IRT",
    "$": "USD", "us$": "USD", "usd": "USD", "dollar": "USD", "dollars": "USD",
    "€": "EUR", "eur": "EUR", "euro": "EUR", "euros": "EUR",
    "£": "GBP", "gbp": "GBP", "₺": "TRY", "tl": "TRY",
    "aed": "AED", "درهم": "AED", "₹": "INR", "inr": "INR", "rs": "INR",
    "chf": "CHF", "cad": "CAD", "aud": "AUD", "sek": "SEK", "nok": "NOK", "dkk": "DKK",
    "jpy": "JPY", "¥": "JPY", "rub": "RUB", "₽": "RUB", "руб": "RUB", "sar": "SAR", "kwd": "KWD",
    "pln": "PLN", "zł": "PLN", "czk": "CZK", "huf": "HUF", "cny": "CNY",
}
_SYMBOLS = [c for c in CURRENCIES if not c[0].isalpha()]
_WORDS = sorted((c for c in CURRENCIES if c[0].isalpha()), key=len, reverse=True)
CURRENCY_PATTERN = ("(?:" + "|".join(re.escape(s) for s in sorted(_SYMBOLS, key=len, reverse=True))
                    + "|(?<![^\\W\\d_])(?:" + "|".join(re.escape(w) for w in _WORDS) + ")(?![^\\W\\d_]))")
_CURRENCY_RE = re.compile(CURRENCY_PATTERN, re.IGNORECASE)

# 1,234,567.89 | 1.234,56 | 1'234.50 | 400000 | 12,50
NUMBER_CORE = r"\d{1,3}(?:[,.'’]\d{3})+(?:[.,]\d{1,2})?|\d+(?:[.,]\d{1,2})?"
_NUM_RE = re.compile(rf"(?<![\d*/])([+-])?\s?(?:{CURRENCY_PATTERN}\.?\s?)?({NUMBER_CORE})([+-])?(?![\d*/:%])",
                     re.IGNORECASE)


def find_currency(text: str):
    m = _CURRENCY_RE.search(text or "")
    return CURRENCIES.get(m.group(0).lower()) if m else None


def to_number(s: str, decimal: str = None) -> float:
    """Turn '1.234,56' / '1,234.56' / '400,000' into a float.

    Without a hint, the last separator is the decimal point only when 1-2 digits follow it.
    """
    seps = [(i, c) for i, c in enumerate(s) if c in ",.'’"]
    if not seps:
        return float(s)
    last_i, last_c = seps[-1]
    tail = len(s) - last_i - 1
    if decimal:
        is_decimal = last_c == decimal
    else:
        is_decimal = last_c in ",." and tail in (1, 2)
    if is_decimal:
        whole = re.sub(r"\D", "", s[:last_i]) or "0"
        return float(f"{whole}.{s[last_i + 1:]}")
    return float(re.sub(r"\D", "", s))


def parse_amount(text: str, decimal: str = None):
    """First amount in ``text`` -> (value, sign +1/-1/None, currency code or None), or None."""
    for m in _NUM_RE.finditer(text):
        lead, digits, trail = m.group(1), m.group(2), m.group(3)
        # long digit runs without separators are account/card numbers, not amounts
        if not lead and not trail and digits.isdigit() and len(digits) >= 13:
            continue
        sign_ch = lead or trail
        sign = None if sign_ch is None else (1 if sign_ch == "+" else -1)
        return to_number(digits, decimal), sign, find_currency(text)
    return None


def remove_first_amount(text: str) -> str:
    return _NUM_RE.sub(" ", text, count=1)


def strip_currency_words(text: str) -> str:
    return _CURRENCY_RE.sub(" ", text)


def tidy(value: float):
    """int when whole, otherwise rounded to 2 decimals (nicer JSON)."""
    value = round(value, 2)
    return int(value) if value == int(value) else value
