"""
Turn a text file full of bank SMS into a sorted, de-duplicated list of transactions.

Pipeline:
1. Templates from ``sms_formats.txt`` are matched first (any language).
2. Everything between template matches goes to the label-based parser (``heuristic.py``).
3. Each message becomes a ``Transaction``; OTP/ad messages are set aside, duplicates removed,
   missing years filled in, the list sorted by date and checked against the running balance.
"""

import bisect
import datetime as _dt
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Optional

from . import jalali
from .categories import categorize
from .dates import DateValue, extract_datetime, parse_time, parse_with_format
from .heuristic import (Context, Vocabulary, classify_line, fragment_fields, split_messages,
                        _account_digits)
from .normalize import normalize, compact, clean_name, has_persian
from .numbers import parse_amount, find_currency
from .templates import FormatsFile, scan

BALANCE_TOLERANCE = 0.005


@dataclass
class Options:
    formats: Optional[FormatsFile] = None
    calendar: str = "auto"         # "auto" | "j" (Jalali) | "g" (Gregorian) - for ambiguous 2-digit years
    date_order: Optional[str] = None   # "dmy" | "mdy" | "ymd"
    decimal: Optional[str] = None      # "," or "."
    currency: Optional[str] = None     # currency to assume when the SMS does not say


@dataclass
class Record:
    """One SMS, before it is turned into a transaction."""
    start_line: int
    raw: str
    norm: str
    fields: dict
    types: list = field(default_factory=list)      # [(word, "in"/"out"/None)]
    texts: list = field(default_factory=list)
    is_otp: bool = False
    template: Optional[str] = None
    forced_direction: Optional[str] = None
    default_currency: Optional[str] = None


@dataclass
class Transaction:
    order: int
    line: int
    amount: float
    currency: Optional[str]
    direction: Optional[str]          # "in" / "out" / None
    direction_source: Optional[str]   # sign / keyword / template / balance
    balance: Optional[float] = None
    fee: float = 0
    date: Optional[DateValue] = None  # as written in the SMS (Jalali or Gregorian)
    gdate: Optional[_dt.date] = None  # the same day in the Gregorian calendar
    time: Optional[tuple] = None
    tracking: Optional[str] = None
    merchant: Optional[str] = None
    person: Optional[str] = None
    desc: Optional[str] = None
    bank: Optional[str] = None
    account: Optional[str] = None
    type_word: Optional[str] = None
    raw: str = ""
    norm: str = ""
    category: str = ""
    chain_ok: Optional[bool] = None
    template: Optional[str] = None
    foreign: bool = False             # different currency than the rest of the file
    account_tail: str = ""            # last digits of the account (filled in when the SMS omits it)

    @property
    def signed(self) -> float:
        """Effect on the account balance (fees included)."""
        if self.direction == "in":
            return self.amount - self.fee
        if self.direction == "out":
            return -self.amount - self.fee
        return 0

    @property
    def account_key(self) -> str:
        return f"{self.bank or ''}|{self.account_tail}|{self.currency or ''}"

    @property
    def iso(self) -> str:
        return self.gdate.isoformat() if self.gdate else ""

    @property
    def jalali_str(self) -> str:
        return jalali.fmt(jalali.from_date(self.gdate)) if self.gdate else ""

    @property
    def time_str(self) -> str:
        return f"{self.time[0]:02d}:{self.time[1]:02d}" if self.time else ""

    @property
    def sort_key(self):
        if self.gdate:
            return (0, self.gdate, self.time or (0, 0), self.order)
        return (1, _dt.date.min, (0, 0), self.order)

    @property
    def timestamp(self) -> Optional[int]:
        """Milliseconds since 1970 (time axis of the charts)."""
        if not self.gdate:
            return None
        h, m = self.time or (0, 0)
        d = _dt.datetime(self.gdate.year, self.gdate.month, self.gdate.day, h, m, tzinfo=_dt.timezone.utc)
        return int(d.timestamp() * 1000)


@dataclass
class ParseResult:
    transactions: list
    others: list            # not transactions (OTP, ads, incomplete)
    duplicates: list        # removed duplicate SMS
    total_messages: int
    chain_checked: int = 0
    chain_broken: int = 0
    inferred_years: dict = field(default_factory=dict)
    currency: Optional[str] = None
    persian: bool = False
    template_hits: dict = field(default_factory=dict)
    foreign: int = 0


# ---------------------------------------------------------------------------
# Template matches -> records
# ---------------------------------------------------------------------------

def _template_record(match, start_line, raw, norm, ctx: Context) -> Record:
    tpl = match.template
    opts = tpl.options
    hint = tpl.calendar_hint
    order = (opts.get("date-order") or ctx.order or "").lower() or None
    decimal = opts.get("decimal") or ctx.decimal
    fields, types = {}, []
    for name, items in match.values.items():
        for value, arg in items:
            if name in fields:
                break
            if name in ("amount", "balance", "available", "fee"):
                a = parse_amount(value, decimal)
                if a:
                    fields[name] = a
            elif name == "currency":
                fields["currency"] = find_currency(value) or value.upper()
            elif name == "date":
                dv = parse_with_format(value, arg, hint) if arg else extract_datetime(value, hint, order)[0]
                if dv:
                    fields["date"] = dv
                if not arg:
                    tm = extract_datetime(value, hint, order)[1]
                    if tm:
                        fields.setdefault("time", tm)
            elif name == "time":
                tm, _ = parse_time(re.sub(r"(\d)\s?[.hH]\s?(\d)", r":", value))
                if tm:
                    fields["time"] = tm
            elif name == "type":
                d = ctx.vocab.direction(value)
                if d is None:
                    t = ctx.vocab.first_type_word(value)
                    d = t[1] if t else None
                types.append((clean_name(value), d))
            elif name in ("account",):
                fields["account"] = _account_digits(value)
            elif name in ("tracking", "ref"):
                fields[name] = value.strip(":.,-#")
            elif name in ("merchant", "person", "desc", "bank"):
                v = clean_name(value)
                if name == "merchant":
                    v = ctx.vocab.strip_stopwords(v)
                if v:
                    fields[name] = v
    if opts.get("bank"):
        fields.setdefault("bank", opts["bank"])
    direction = (opts.get("direction") or "").lower()
    return Record(start_line, raw, norm, fields, types, [], bool(ctx.vocab.otp_re.search(norm)),
                  tpl.name, direction if direction in ("in", "out") else None, opts.get("currency"))


def _records(text: str, options: Options):
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    raw_lines = text.split("\n")
    norm_text = normalize(text)
    norm_lines = norm_text.split("\n")

    lettered = [l for l in norm_lines if re.search(r"[^\W\d_]", l)]
    persian = sum(1 for l in lettered if has_persian(l)) > len(lettered) / 2 if lettered else False
    fmt = options.formats or FormatsFile()
    extra_in = list(fmt.in_words) + [w.strip() for t in fmt.templates for w in t.options.get("in", "").split(",") if w.strip()]
    extra_out = list(fmt.out_words) + [w.strip() for t in fmt.templates for w in t.options.get("out", "").split(",") if w.strip()]
    hint = options.calendar if options.calendar in ("j", "g") else ("j" if persian else "g")
    ctx = Context(Vocabulary(extra_in, extra_out), hint, options.date_order, options.decimal)

    line_starts = [0]
    for line in norm_lines[:-1]:
        line_starts.append(line_starts[-1] + len(line) + 1)

    def line_of(pos):
        return bisect.bisect_right(line_starts, pos) - 1

    matches = scan(norm_text, fmt.templates)
    records = []

    def heuristic(a, b):
        for frag in split_messages(((i + 1, raw_lines[i]) for i in range(a, b)), ctx):
            f, types, texts = fragment_fields(frag)
            records.append(Record(frag.start_line, frag.raw_text, frag.norm_text, f, types, texts, frag.is_otp))

    pos = 0
    for k, m in enumerate(matches):
        s_line, e_line = line_of(m.start), line_of(m.end - 1)
        if s_line < pos:            # overlaps lines already absorbed by the previous match
            continue
        heuristic(pos, s_line)
        limit = line_of(matches[k + 1].start) if k + 1 < len(matches) else len(norm_lines)
        rec = _template_record(m, s_line + 1, "\n".join(raw_lines[s_line:e_line + 1]),
                               "\n".join(norm_lines[s_line:e_line + 1]), ctx)
        # absorb following lines that only add missing details (date, reference, ...)
        j = e_line + 1
        while j < limit:
            line = norm_lines[j].strip()
            if not line or re.fullmatch(r"[-=_*~.]{3,}", line):
                break
            info = classify_line(line, ctx)
            kinds = set(info)
            if not kinds or "text" in kinds or kinds & {"amount", "amount_weak", "bank", "type"} \
                    or kinds & set(rec.fields):
                break
            for key, v in info.items():
                rec.fields.setdefault(key, v)
            rec.raw += "\n" + raw_lines[j]
            rec.norm += "\n" + norm_lines[j]
            j += 1
        records.append(rec)
        pos = j
    heuristic(pos, len(raw_lines))
    records.sort(key=lambda r: r.start_line)
    return records, ctx, persian


# ---------------------------------------------------------------------------
# Records -> transactions
# ---------------------------------------------------------------------------

def _to_rial(value_tuple, currency_hint):
    if not value_tuple:
        return None
    value, sign, cur = value_tuple
    if (cur or currency_hint) == "IRT":
        value *= 10
    return value


def build_transaction(rec: Record, order: int, ctx: Context) -> Optional[Transaction]:
    if rec.is_otp:
        return None
    f = rec.fields
    types = list(rec.types)
    amt = f.get("amount") or f.get("amount_weak")
    fee = f.get("fee")
    if not amt:
        if not fee:
            return None
        amt, fee = (fee[0], -1, fee[2]), None      # an SMS that only reports a fee is itself a debit
        types.insert(0, ("fee", "out"))
    value, sign, cur = amt
    if value <= 0:
        return None
    currency = cur or f.get("currency") or rec.default_currency
    if currency and len(currency) != 3:          # a symbol or word such as "€" or "toman"
        currency = find_currency(currency) or currency
    if currency:
        currency = currency.upper()
    amount = _to_rial(amt, currency)
    balance = _to_rial(f.get("balance") or f.get("available"), currency)
    fee_value = _to_rial(fee, currency) or 0
    if currency == "IRT":
        currency = "IRR"

    direction = source = None
    if rec.forced_direction:
        direction, source = rec.forced_direction, "template"
    elif sign is not None:
        direction, source = ("in" if sign > 0 else "out"), "sign"
    else:
        for word, d in types:
            if d:
                direction, source = d, "keyword"
                break
        if direction is None:
            # template SMS: any type word in the message ("Compra con tarjeta ..."); others: free text only
            hint_text = rec.norm if rec.template else " ".join(rec.texts + [f.get("desc", "")])
            t = ctx.vocab.first_type_word(hint_text)
            if t and t[1]:
                direction, source = t[1], "keyword"

    return Transaction(
        order=order, line=rec.start_line, amount=amount, currency=currency, direction=direction,
        direction_source=source, balance=balance, fee=fee_value, date=f.get("date"), time=f.get("time"),
        tracking=f.get("tracking") or f.get("ref"), merchant=f.get("merchant"), person=f.get("person"),
        desc=f.get("desc"), bank=f.get("bank"), account=f.get("account"),
        type_word=next((w for w, _ in types if w), None), raw=rec.raw, norm=rec.norm, template=rec.template,
    )


def parse_text(text: str, options: Options = None) -> ParseResult:
    options = options or Options()
    records, ctx, persian = _records(text, options)
    txns, others, dups = [], [], []
    seen_text, seen_track = set(), set()
    hits = Counter()
    for i, rec in enumerate(records):
        t = build_transaction(rec, i, ctx)
        if t is None:
            others.append({"line": rec.start_line, "text": rec.raw, "reason": "otp" if rec.is_otp else "no_amount"})
            continue
        key_text = compact(t.norm).lower()
        key_track = (t.tracking, t.amount, t.date) if t.tracking else None
        if key_text in seen_text or (key_track and key_track in seen_track):
            dups.append({"line": rec.start_line, "text": rec.raw})
            continue
        seen_text.add(key_text)
        if key_track:
            seen_track.add(key_track)
        hits[t.template or ""] += 1
        txns.append(t)

    for t in txns:
        t.category = categorize(t)
    inferred = _fill_missing_years(txns)
    currency = _assign_currency(txns, options, persian)
    _fill_account_tails(txns)
    txns.sort(key=lambda t: t.sort_key)
    _reorder_ties(txns)
    checked, broken = _balance_chain(txns)
    return ParseResult(txns, others, dups, len(records), checked, broken, inferred, currency, persian,
                       dict(hits), sum(1 for t in txns if t.foreign))


def parse_file(path: str, options: Options = None) -> ParseResult:
    with open(path, "rb") as fh:
        return parse_text(decode_bytes(fh.read()), options)


def decode_bytes(data: bytes) -> str:
    """UTF-8, UTF-16 (Windows Notepad) or Windows-1256 (old Persian Windows)."""
    if data[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return data.decode("utf-16")
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        pass
    try:
        return data.decode("cp1256")
    except UnicodeDecodeError:
        return data.decode("utf-8", errors="replace")


def _fill_missing_years(txns):
    inferred = {}
    for cal in ("j", "g"):
        years = Counter(t.date.y for t in txns if t.date and t.date.cal == cal and t.date.y)
        missing = [t for t in txns if t.date and t.date.cal == cal and t.date.y is None]
        if missing:
            if years:
                year = years.most_common(1)[0][0]
            else:
                today = _dt.date.today()
                year = jalali.from_date(today)[0] if cal == "j" else today.year
            inferred[cal] = year
            for t in missing:
                t.date = t.date._replace(y=year)
    for t in txns:
        t.gdate = t.date.to_gregorian() if t.date else None
    return inferred


def _assign_currency(txns, options: Options, persian: bool):
    counts = Counter(t.currency for t in txns if t.currency)
    if counts:
        primary = counts.most_common(1)[0][0]
    else:
        primary = (options.currency or ("IRR" if persian else None))
    primary = primary.upper() if primary else None
    for t in txns:
        if t.currency is None:
            t.currency = primary
        elif t.currency != primary:
            t.foreign = True
    return primary


def _fill_account_tails(txns):
    """If a bank only ever shows one account, its SMS without an account number belong to it."""
    tails = {}
    for t in txns:
        t.account_tail = re.sub(r"\D", "", t.account or "")[-4:]
        if t.account_tail:
            tails.setdefault((t.bank, t.currency), set()).add(t.account_tail)
    for t in txns:
        if not t.account_tail and t.bank and len(tails.get((t.bank, t.currency), ())) == 1:
            t.account_tail = next(iter(tails[(t.bank, t.currency)]))


def _close(a, b):
    return abs(a - b) < BALANCE_TOLERANCE


def _reorder_ties(txns):
    """Transactions of one account in the same minute: order them so the balance chain holds."""
    last_bal = {}
    i, n = 0, len(txns)
    while i < n:
        j = i
        while j + 1 < n and txns[i].sort_key[0] == 0 and txns[j + 1].sort_key[:3] == txns[i].sort_key[:3]:
            j += 1
        block = txns[i:j + 1]
        if len(block) > 1:
            by_acc = {}
            for p, t in enumerate(block):
                by_acc.setdefault(t.account_key, []).append(p)
            for acc, positions in by_acc.items():
                if len(positions) < 2:
                    continue
                items = [block[p] for p in positions]
                prev, ordered, rest = last_bal.get(acc), [], items[:]
                while rest and prev is not None:
                    nxt = next((t for t in rest if t.balance is not None and (
                        _close(prev + t.signed, t.balance) if t.direction else
                        any(_close(abs(t.balance - prev), x) for x in (t.amount - t.fee, t.amount + t.fee)))), None)
                    if nxt is None:
                        break
                    ordered.append(nxt)
                    rest.remove(nxt)
                    prev = nxt.balance
                for p, t in zip(positions, ordered + rest):
                    block[p] = t
            txns[i:j + 1] = block
        for t in block:
            if t.balance is not None:
                last_bal[t.account_key] = t.balance
        i = j + 1


def _balance_chain(txns):
    """Use the balance to guess unknown directions and to check that no SMS is missing."""
    prev = {}
    checked = broken = 0
    for t in txns:
        acc = t.account_key
        p = prev.get(acc)
        if t.balance is not None and p is not None:
            diff = t.balance - p
            if t.direction is None:
                if _close(diff, t.amount - t.fee):
                    t.direction, t.direction_source = "in", "balance"
                elif _close(diff, -t.amount - t.fee):
                    t.direction, t.direction_source = "out", "balance"
            if t.direction:
                checked += 1
                t.chain_ok = _close(p + t.signed, t.balance)
                if not t.chain_ok:
                    broken += 1
        if t.balance is not None:
            prev[acc] = t.balance
    return checked, broken
