"""
Date / time parsing for SMS in any language, in the Jalali (Persian) or Gregorian calendar.

A parsed date is a ``DateValue(cal, y, m, d)`` where ``cal`` is "j" (Jalali) or "g" (Gregorian).
The year may be ``None`` when the SMS omits it (filled in later from the other messages).
"""

import datetime as _dt
import re
from typing import NamedTuple, Optional

from . import jalali
from .normalize import compact


class DateValue(NamedTuple):
    cal: str
    y: Optional[int]
    m: int
    d: int

    def to_gregorian(self) -> Optional[_dt.date]:
        if self.y is None:
            return None
        try:
            if self.cal == "j":
                return jalali.to_date(self.y, self.m, self.d) if jalali.is_valid_jalali(self.y, self.m, self.d) \
                    else None
            return _dt.date(self.y, self.m, self.d)
        except ValueError:
            return None


# Month names -> (month, calendar)
_GREGORIAN_MONTHS = {
    1: "january jan januar jän jänner janvier janv enero ene gennaio gen janeiro ocak يناير",
    2: "february feb februar février févr fev febrero febbraio fevereiro şubat subat فبراير",
    3: "march mar märz mär maerz mars marzo março mart مارس",
    4: "april apr avril avr abril abr aprile nisan أبريل",
    5: "may mai mayo maggio maio mayıs mayis مايو",
    6: "june jun juni juin junio giugno junho haziran يونيو",
    7: "july jul juli juillet juil julio luglio julho temmuz يوليو",
    8: "august aug août aout agosto ago ağustos agustos أغسطس",
    9: "september sep sept septembre septiembre setiembre settembre setembro eylül eylul سبتمبر",
    10: "october oct oktober okt octobre octubre ottobre outubro out ekim أكتوبر",
    11: "november nov novembre noviembre novembro kasım kasim نوفمبر",
    12: "december dec dezember dez décembre déc decembre diciembre dic dicembre dezembro aralık aralik ديسمبر",
}
MONTH_WORDS = {}
for _m, _names in _GREGORIAN_MONTHS.items():
    for _n in _names.split():
        MONTH_WORDS[_n] = (_m, "g")
for _i, _n in enumerate(jalali.MONTH_NAMES):
    MONTH_WORDS[compact(_n)] = (_i + 1, "j")
MONTH_WORDS[compact("اردی بهشت")] = (2, "j")
MONTH_WORDS["امرداد"] = (5, "j")


def month_from_word(word: str):
    w = compact(word).lower().strip(".")
    return MONTH_WORDS.get(w)


_WORD = r"(?:اردی\s*بهشت|[^\W\d_](?:[^\W\d_]|‌){1,11}\.?)"   # a month name
DATE_NUMERIC_RE = re.compile(r"(?<![\d,])(\d{1,4})\s?[/\-.]\s?(\d{1,2})\s?[/\-.]\s?(\d{1,4})(?![\d,])")
DATE_DMY_NAME_RE = re.compile(rf"(?<!\d)(\d{{1,2}})\.?[\s\-/]*({_WORD})[\s\-/,]*(\d{{4}}|\d{{2}}(?![\d:]))?")
DATE_MDY_NAME_RE = re.compile(rf"(?<![^\W\d_])({_WORD})\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s*(\d{{4}})?")
TIME_RE = re.compile(r"(?<![\d,])([01]?\d|2[0-3])\s?:\s?([0-5]\d)(?:\s?:\s?([0-5]\d))?"
                     r"(?:\s?([ap])\.?\s?m\.?)?(?![\d,])", re.IGNORECASE)
_COMPACT_DT_RE = re.compile(r"^(\d{2})/?(\d{2})\s*[-_ ]\s*(\d{2}):?(\d{2})$")
_PARTIAL_DATE_RE = re.compile(r"(?<![\d,/])(\d{1,2})/(\d{1,2})(?![\d,/])")


def _full_year(y: str, cal_hint: str):
    """'26' + hint 'g' -> (2026, 'g'); '05' + hint 'j' -> (1405, 'j'); 4-digit years decide themselves."""
    n = int(y)
    if len(y) <= 2:
        if cal_hint == "g":
            return (2000 + n if n < 70 else 1900 + n), "g"
        return (1400 + n if n < 70 else 1300 + n), "j"
    return n, ("g" if n >= 1700 else "j")


def make_date(cal: str, y, m: int, d: int) -> Optional[DateValue]:
    if not (1 <= m <= 12 and 1 <= d <= 31):
        return None
    dv = DateValue(cal, y, m, d)
    if y is None:
        return dv
    return dv if dv.to_gregorian() else None


def _from_numeric(a: str, b: str, c: str, hint: str, order: str = None) -> Optional[DateValue]:
    ia, ib, ic = int(a), int(b), int(c)

    def ymd():
        y, cal = _full_year(a, hint)
        return make_date(cal, y, ib, ic)

    def dmy():
        y, cal = _full_year(c, hint)
        return make_date(cal, y, ib, ia)

    def mdy():
        y, cal = _full_year(c, hint)
        return make_date(cal, y, ia, ib)

    if len(a) >= 3 or ia > 31:
        return ymd()
    if order == "ymd":
        tries = (ymd, dmy, mdy)
    elif order == "mdy":
        tries = (mdy, dmy, ymd)
    elif order == "dmy":
        tries = (dmy, mdy, ymd)
    elif len(c) >= 3 or ic > 31:
        tries = (mdy, dmy) if ia <= 12 < ib else (dmy, mdy)
    else:  # all two-digit: Iranian banks use yy/mm/dd, most others dd/mm/yy
        tries = (ymd, dmy, mdy) if hint == "j" else (dmy, mdy, ymd)
    for f in tries:
        dv = f()
        if dv:
            return dv
    return None


def _from_names(text: str, hint: str):
    for rx, order in ((DATE_DMY_NAME_RE, "dmy"), (DATE_MDY_NAME_RE, "mdy")):
        for m in rx.finditer(text):
            if order == "dmy":
                day, word, year = m.group(1), m.group(2), m.group(3)
            else:
                word, day, year = m.group(1), m.group(2), m.group(3)
            mw = month_from_word(word)
            if not mw:
                continue
            month, cal = mw
            y = None
            if year:
                y, ycal = _full_year(year, cal)
            dv = make_date(cal, y, month, int(day))
            if dv:
                return dv, m.group(0)
    return None, None


def parse_time(text: str):
    m = TIME_RE.search(text)
    if not m:
        return None, None
    h, mi = int(m.group(1)), int(m.group(2))
    ap = (m.group(4) or "").lower()
    if ap == "p" and h < 12:
        h += 12
    elif ap == "a" and h == 12:
        h = 0
    return (h, mi), m.group(0)


def extract_datetime(text: str, hint: str = "j", order: str = None):
    """Find a date and a time anywhere in ``text``. Returns (DateValue|None, (h, m)|None, rest_of_text)."""
    date = time = None
    rest = text
    m = _COMPACT_DT_RE.match(text.strip())          # "0222-2235" (MMDD-HHMM, used by some Iranian banks)
    if m:
        mo, d, h, mi = map(int, m.groups())
        if 1 <= mo <= 12 and 1 <= d <= 31 and h < 24 and mi < 60:
            return DateValue(hint, None, mo, d), (h, mi), ""
    for m in DATE_NUMERIC_RE.finditer(text):
        dv = _from_numeric(*m.groups(), hint=hint, order=order)
        if dv:
            date = dv
            rest = rest.replace(m.group(0), " ", 1)
            break
    if date is None:
        dv, matched = _from_names(text, hint)
        if dv:
            date = dv
            rest = rest.replace(matched, " ", 1)
    time, matched = parse_time(rest)
    if matched:
        rest = rest.replace(matched, " ", 1)
    if date is None and time is not None:
        m = _PARTIAL_DATE_RE.search(rest)
        if m:
            a, b = int(m.group(1)), int(m.group(2))
            dv = make_date(hint, None, b, a) if a > 12 or order == "dmy" else make_date(hint, None, a, b)
            if dv:
                date = dv
                rest = rest.replace(m.group(0), " ", 1)
    return date, time, rest


# ---------------------------------------------------------------------------
# Explicit formats used in templates, e.g. {date:dd.mm.yyyy} or {date:d MMM yyyy}
# ---------------------------------------------------------------------------

_FMT_TOKEN = re.compile(r"yyyy|yy|mmmm|mmm|mm|m|dd|d|\s+|.", re.IGNORECASE)


def format_to_regex(fmt: str) -> str:
    """'dd.mm.yyyy' -> regex with named groups d/m/y (or mon for a month name)."""
    out = []
    for tok in _FMT_TOKEN.findall(fmt):
        low = tok.lower()
        if low == "yyyy":
            out.append(r"(?P<y>\d{4})")
        elif low == "yy":
            out.append(r"(?P<y>\d{2})")
        elif low in ("mmmm", "mmm"):
            out.append(rf"(?P<mon>{_WORD})")
        elif low in ("mm", "m"):
            out.append(r"(?P<m>\d{1,2})")
        elif low in ("dd", "d"):
            out.append(r"(?P<d>\d{1,2})")
        elif tok.isspace():
            out.append(r"\s*")
        else:
            out.append(r"\s*" + re.escape(tok) + r"\s*" if tok in "/-.," else re.escape(tok))
    return "".join(out)


def parse_with_format(text: str, fmt: str, hint: str = "g") -> Optional[DateValue]:
    m = re.search(format_to_regex(fmt), text, re.IGNORECASE)
    if not m:
        return None
    g = m.groupdict()
    cal = hint
    if g.get("mon"):
        mw = month_from_word(g["mon"])
        if not mw:
            return None
        month, cal = mw
    else:
        month = int(g["m"])
    y = None
    if g.get("y"):
        y, ycal = _full_year(g["y"], cal)
        if not g.get("mon"):
            cal = ycal
    return make_date(cal, y, month, int(g["d"]))
