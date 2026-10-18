"""
Label-based parser: works without templates for SMS that use labels such as
"Amount: ...", "Balance: ...", "مبلغ: ...", "Kontostand: ..." in any supported language.

1. Each line is split into pieces at strong labels and every piece is classified
   (amount, balance, date, merchant, ...).
2. Lines are grouped into messages: a blank line, a repeated "one-per-SMS" field (a second
   amount, a second date ...) or the header of the next SMS (bank name / transaction type)
   starts a new message.
3. Pieces of one SMS that were separated by a stray blank line are glued back together.
"""

import re
from dataclasses import dataclass, field

from . import keywords as kw
from .dates import extract_datetime
from .normalize import normalize, compact, clean_name
from .numbers import CURRENCY_PATTERN, parse_amount, remove_first_amount, strip_currency_words

UNIQUE_KINDS = {"amount", "balance", "available", "fee", "date", "time", "tracking", "ref", "bank"}
HEADER_KINDS = {"bank", "type"}
VALUE_KINDS = {"balance", "available", "fee", "amount", "tracking", "ref", "date"}
TEXT_KINDS = {"merchant", "person", "desc"}
NOT_LETTER = r"(?![^\W\d_])"
NOT_AFTER_LETTER = r"(?<![^\W\d_])"


def lab(label: str) -> str:
    """Regex for a label/keyword; spaces may be spaces or ZWNJ."""
    return r"[\s‌]*".join(re.escape(p) for p in label.split())


def _alt(words):
    return "|".join(lab(w) for w in sorted(set(words), key=lambda s: -len(compact(s))))


class Vocabulary:
    """Compiled keyword regexes. Extra in/out words can come from the formats file."""

    def __init__(self, extra_in=(), extra_out=()):
        self.type_words = [(w, "in") for w in list(kw.TYPE_IN) + list(extra_in)] + \
                          [(w, "out") for w in list(kw.TYPE_OUT) + list(extra_out)]
        self.type_words.sort(key=lambda x: -len(compact(x[0])))
        self.direction_of = {}
        for w, d in self.type_words:
            self.direction_of.setdefault(compact(w).lower(), d)
        self.type_start = re.compile(rf"^[\W_]*?({_alt(w for w, _ in self.type_words)}){NOT_LETTER}", re.I)
        self.type_any = re.compile(rf"{NOT_AFTER_LETTER}({_alt(w for w, _ in self.type_words)}){NOT_LETTER}", re.I)

        self.label_kind = {}
        for kind, labels in kw.LABELS.items():
            for label in labels:
                self.label_kind.setdefault(compact(label).lower(), kind)
        self.colon_kind = {}
        for kind, labels in kw.COLON_LABELS.items():
            for label in labels:
                self.colon_kind.setdefault(compact(label).lower(), kind)
        all_labels = [l for ls in kw.LABELS.values() for l in ls]
        self.label_re = re.compile(rf"^[\W_]*?(?P<label>{_alt(all_labels)}){NOT_LETTER}\s*[:=]?\s*(?P<value>.*)$",
                                   re.I)
        colon = [l for ls in kw.COLON_LABELS.values() for l in ls]
        self.colon_label_re = re.compile(rf"^[\W_]*?(?P<label>{_alt(colon)})\s*:\s*(?P<value>.*)$", re.I)
        value_labels = [l for k in VALUE_KINDS for l in kw.LABELS[k]]
        text_labels = [l for k in TEXT_KINDS for l in kw.LABELS[k]]
        # mid-line split: value labels followed by a number, text labels only when followed by ":"
        self.split_re = re.compile(
            rf"{NOT_AFTER_LETTER}(?:(?:{_alt(value_labels)}){NOT_LETTER}"
            rf"(?=\s*[:=]?\s*[+\-]?\s*(?:{CURRENCY_PATTERN}\.?\s?)?\d)"
            rf"|(?:{_alt(text_labels)}){NOT_LETTER}(?=\s*:))", re.I)
        self.otp_re = re.compile(rf"{NOT_AFTER_LETTER}(?:{_alt(kw.OTP_WORDS)}){NOT_LETTER}", re.I)
        self.bank_re = re.compile(rf"(?:{_alt(kw.BANK_WORDS)})", re.I)
        stop = _alt(kw.STOPWORDS_EDGE)
        self.stop_edge = re.compile(rf"^(?:(?:{stop})(?:\s+|$))+|(?:\s+|^)(?:{stop})$", re.I)

    def direction(self, word: str):
        return self.direction_of.get(compact(word).lower())

    def first_type_word(self, text: str):
        m = self.type_any.search(text or "")
        return (m.group(1), self.direction(m.group(1))) if m else None

    def strip_stopwords(self, text: str) -> str:
        prev = None
        while prev != text:
            prev = text
            text = clean_name(self.stop_edge.sub("", text))
        return text


DEFAULT_VOCAB = Vocabulary()
_ACCOUNT_LIKE_RE = re.compile(r"^[\d*xX\-\s#.]{4,}$")


def _is_account_value(value: str) -> bool:
    v = value.strip()
    digits = sum(ch.isdigit() for ch in v)
    return bool(_ACCOUNT_LIKE_RE.match(v)) or (digits >= 6 and digits >= len(v.replace(" ", "")) * 0.6)


def _account_digits(value: str) -> str:
    return re.sub(r"[^\dA-Za-z*]", "", value)


@dataclass
class Context:
    vocab: Vocabulary = DEFAULT_VOCAB
    hint: str = "j"          # calendar for ambiguous 2-digit years: "j" (Jalali) or "g" (Gregorian)
    order: str = None        # forced date order: "dmy" / "mdy" / "ymd"
    decimal: str = None      # forced decimal separator: "," or "."


# ---------------------------------------------------------------------------
# Classifying lines
# ---------------------------------------------------------------------------

def _split_pieces(line: str, ctx: Context):
    cuts = [m.start() for m in ctx.vocab.split_re.finditer(line) if m.start() > 0]
    pieces, last = [], 0
    for c in cuts:
        before = line[last:c].strip()
        if not before:
            continue
        key = compact(before).strip(":=-").lower()
        if key in ctx.vocab.label_kind or key in ctx.vocab.colon_kind:
            continue          # the label is part of a longer label ("مانده" in "مانده حساب")
        pieces.append(line[last:c])
        last = c
    pieces.append(line[last:])
    return [p.strip(" ,|؛;") for p in pieces if p.strip(" ,|؛;")]


def classify_piece(piece: str, ctx: Context) -> dict:
    info = {}
    text = piece.strip()
    if not text:
        return info
    vocab = ctx.vocab

    if compact(text).startswith("کارتبهکارت"):          # before the "کارت" (card) label
        t = _type_of(text, ctx)
        if t:
            return _classify_type(t, info, ctx)

    kind = value = None
    m = vocab.label_re.match(text)
    if m:
        kind = vocab.label_kind.get(compact(m.group("label")).lower())
        value = m.group("value").strip()
    else:
        m = vocab.colon_label_re.match(text)
        if m:
            kind = vocab.colon_kind.get(compact(m.group("label")).lower())
            value = m.group("value").strip()

    if kind:
        if kind in ("tracking", "ref"):
            v = re.sub(r"\s", "", value).strip(":.-#")
            if v:
                info[kind] = v
            return info
        date, time, rest = extract_datetime(value, ctx.hint, ctx.order)
        if date:
            info["date"] = date
        if time:
            info["time"] = time
        if kind == "date":
            return info
        if kind in ("amount", "balance", "available", "fee"):
            a = parse_amount(rest, ctx.decimal)
            if a:
                info[kind] = a
            return info
        if kind == "account":
            info["account"] = _account_digits(value) or value
            return info
        if kind == "party":
            if _is_account_value(value):
                info["account"] = _account_digits(value)
            elif value:
                info["person"] = clean_name(value)
            return info
        if kind == "type":
            t = vocab.first_type_word(value)
            info["type"] = (t[0], t[1]) if t else (clean_name(value), vocab.direction(value))
            return info
        if kind in ("merchant", "desc", "person"):
            v = vocab.strip_stopwords(rest) if kind == "merchant" else clean_name(rest)
            if v:
                info[kind] = v
            return info

    # No label ------------------------------------------------------------
    if vocab.bank_re.search(text):
        words = text.split()
        looks_like_name = (len(text) <= 40 and not re.search(r"[\d،,.!?؟:]", text) and not vocab.type_any.search(text)
                           and (len(words) <= 3 or vocab.bank_re.search(" ".join(words[:2]))))
        if looks_like_name:
            info["bank"] = clean_name(text)
            return info
        m = vocab.type_any.search(text)       # "بانک پاسارگاد خرید 250,000 ..." bank + rest on one line
        if m and m.start() > 0 and vocab.bank_re.search(text[:m.start()]):
            info["bank"] = clean_name(text[:m.start()])
            for k, v in classify_piece(text[m.start():], ctx).items():
                info.setdefault(k, v)
            return info

    t = _type_of(text, ctx)
    if t:
        return _classify_type(t, info, ctx)

    date, time, rest = extract_datetime(text, ctx.hint, ctx.order)
    if date or time:
        if date:
            info["date"] = date
        if time:
            info["time"] = time
        text = rest.strip()
        if not text:
            return info

    s = text.strip(" :")
    if re.fullmatch(r"[+-]\s*\D{0,4}[\d,.'’]+\s*\D{0,8}|\D{0,4}[\d,.'’]+[+-]\s*\D{0,8}", s):
        a = parse_amount(s, ctx.decimal)
        if a and not re.search(r"[^\W\d_]{9,}", s):
            info["amount"] = a
            return info
    a = parse_amount(s, ctx.decimal)
    if a and (a[2] or re.fullmatch(r"\d{1,3}(,\d{3})+", s)) and \
            len(strip_currency_words(remove_first_amount(s)).strip(" .")) == 0:
        info["amount_weak"] = a            # "400,000 ریال" / "12,50 €" alone on a line
        return info
    # free text such as "Rs 2,000 credited to A/c XX4521": a type word plus an amount with a currency
    tw = vocab.first_type_word(s)
    if tw and tw[1] and a and (a[2] or re.search(r"\d[,.]\d", s)):
        info["type"] = tw
        info["amount"] = a
        return info
    if s:
        info["text"] = s
    return info


def _type_of(text: str, ctx: Context):
    m = ctx.vocab.type_start.match(text)
    if m:
        return m.group(1), ctx.vocab.direction(m.group(1)), text[m.end():]
    return None


def _classify_type(t, info, ctx: Context):
    word, direction, rest = t
    info["type"] = (word, direction)
    rest = rest.strip(" :")
    if not rest:
        return info
    date, time, rest = extract_datetime(rest, ctx.hint, ctx.order)
    if date:
        info["date"] = date
    if time:
        info["time"] = time
    a = parse_amount(rest, ctx.decimal)
    if a:
        info["amount"] = a
        rest = remove_first_amount(rest)
    rest = clean_name(strip_currency_words(rest))
    if not rest:
        return info
    if re.search(r"(حساب|کارت|سپرده|account|a/c|card)", rest, re.I) or _is_account_value(rest):
        acc = _account_digits(rest)
        if acc:
            info["account"] = acc
        return info
    from_to = bool(re.match(r"^(از|به|from|to|von|an)\s", rest, re.I))
    rest = ctx.vocab.strip_stopwords(rest)
    if rest and re.search(r"[^\W\d_]", rest):
        # "واریز از علی" / "transfer to John" is a person; "خرید از X" / "purchase at X" is a shop
        is_purchase = ctx.vocab.direction(word) == "out" and compact(word).lower() not in (
            "انتقال", "کارتبهکارت", "transfer", "sent", "überweisung", "virement", "transferencia")
        info["person" if from_to and not is_purchase else "merchant"] = rest
    return info


def classify_line(line: str, ctx: Context = None) -> dict:
    """All fields found on one line (a one-line SMS can contain many fields)."""
    ctx = ctx or Context()
    info = {}
    line = normalize(line).strip()
    for piece in _split_pieces(line, ctx):
        for k, v in classify_piece(piece, ctx).items():
            if k == "text" and "text" in info:
                info["text"] += " " + v
            elif k == "type" and "type" in info:
                info.setdefault("type2", v)
            else:
                info.setdefault(k, v)
    return info


# ---------------------------------------------------------------------------
# Grouping lines into messages
# ---------------------------------------------------------------------------

@dataclass
class Fragment:
    lines: list = field(default_factory=list)   # [(line_no, raw, normalised, info)]
    otp_re: object = None

    @property
    def start_line(self):
        return self.lines[0][0] if self.lines else 0

    @property
    def kinds(self):
        k = set()
        for *_, info in self.lines:
            k.update(info.keys())
        k.discard("text")
        return k

    @property
    def norm_text(self):
        return "\n".join(n for _, _, n, _ in self.lines)

    @property
    def raw_text(self):
        return "\n".join(r for _, r, _, _ in self.lines)

    @property
    def is_otp(self):
        return bool(self.otp_re.search(self.norm_text))

    @property
    def has_text(self):
        return any("text" in info for *_, info in self.lines)

    def has_amount(self):
        return bool(self.kinds & {"amount", "amount_weak"})


def _header_first(frag: Fragment) -> bool:
    for *_, info in frag.lines:
        if "amount" in info or "amount_weak" in info:
            return False
        if set(info) & HEADER_KINDS:
            return True
    return False


def split_messages(numbered_lines, ctx: Context = None):
    """``numbered_lines``: iterable of (line_no, raw_line). Returns a list of Fragments."""
    ctx = ctx or Context()
    frags = []
    cur = Fragment(otp_re=ctx.vocab.otp_re)

    def flush():
        nonlocal cur
        if cur.lines:
            frags.append(cur)
        cur = Fragment(otp_re=ctx.vocab.otp_re)

    for lineno, raw in numbered_lines:
        norm = normalize(raw).strip()
        if not norm or re.fullmatch(r"[-=_*~.]{3,}", norm):
            flush()
            continue
        info = classify_line(norm, ctx)
        kinds = set(info) - {"text"}
        if cur.lines:
            ck = cur.kinds
            dup = kinds & UNIQUE_KINDS & ck
            if "amount_weak" in kinds and ck & {"amount", "amount_weak"}:
                dup = dup | {"amount"}
            header_new = (kinds & HEADER_KINDS) and (ck & {"amount", "amount_weak"}) and (ck & {"date", "time"})
            if dup or header_new:
                moved = []
                if dup and _header_first(cur):
                    # header lines (bank / type) at the end of the previous SMS belong to the new one
                    while cur.lines and set(cur.lines[-1][3]) - {"text"} and \
                            set(cur.lines[-1][3]) - {"text"} <= HEADER_KINDS:
                        moved.insert(0, cur.lines.pop())
                flush()
                cur.lines.extend(moved)
        cur.lines.append((lineno, raw.rstrip(), norm, info))
    flush()
    return _merge_fragments(frags)


def _conflict(a: Fragment, b: Fragment) -> bool:
    ka, kb = a.kinds, b.kinds
    if (ka & kb) & (UNIQUE_KINDS | {"type"}):
        return True
    return bool(ka & {"amount", "amount_weak"} and kb & {"amount", "amount_weak"})


def _can_merge(a: Fragment, b: Fragment) -> bool:
    ka, kb = a.kinds, b.kinds
    if not ka or not kb or a.is_otp or b.is_otp or _conflict(a, b):
        return False
    if a.has_amount():
        # trailing piece: only closing fields (date, balance, ...) - not the start of a new SMS
        return not (kb & HEADER_KINDS) and not b.has_text and not b.has_amount()
    # leading piece ("Bank X / Purchase") whose remainder came after a blank line
    return b.has_amount() and not a.has_text and ka <= HEADER_KINDS | {"account"}


def _merge_fragments(frags):
    out = []
    for f in frags:
        if out and _can_merge(out[-1], f):
            out[-1].lines.extend(f.lines)
        else:
            out.append(f)
    return out


def fragment_fields(frag: Fragment):
    """Flatten a fragment into (fields, type_words, free_texts)."""
    fields, types, texts = {}, [], []
    for *_, info in frag.lines:
        for k, v in info.items():
            if k in ("type", "type2"):
                types.append(v)
            elif k == "text":
                texts.append(v)
            else:
                fields.setdefault(k, v)
    return fields, types, texts
