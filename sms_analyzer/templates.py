"""
User-defined SMS templates (``sms_formats.txt``).

A template is an example SMS where the changing parts are replaced by placeholders::

    [template: My bank]
    @currency: EUR
    {bank}: {type} {amount} bei {merchant} am {date:dd.mm.yyyy} um {time}. Kontostand: {balance}

Matching is forgiving: spaces and line breaks are flexible, letter case is ignored and
Persian/Arabic digits are normalised. ``[[ ... ]]`` marks an optional part.
See ``sms_formats.txt`` for the full syntax.
"""

import os
import re
from dataclasses import dataclass, field
from typing import Optional

from .dates import format_to_regex, _WORD
from .normalize import normalize
from .numbers import CURRENCY_PATTERN, NUMBER_CORE

AMOUNT_RE = (rf"[+\-]?\s?(?:{CURRENCY_PATTERN}\.?\s?)?[+\-]?\s?(?:{NUMBER_CORE})[+\-]?"
             rf"(?:\s?{CURRENCY_PATTERN})?")
DATE_ANY_RE = (r"\d{1,4}\s?[/\-.]\s?\d{1,2}\s?[/\-.]\s?\d{1,4}"
               rf"|\d{{1,2}}\.?[\s\-/]*{_WORD}[\s\-/,]*(?:\d{{4}}|\d{{2}}(?![\d:]))?"
               rf"|{_WORD}\s+\d{{1,2}}(?:st|nd|rd|th)?,?\s*(?:\d{{4}})?"
               r"|\d{2}/?\d{2}(?=\s*[-_ ]\s*\d{2}:?\d{2})")
TIME_RE = r"\d{1,2}\s?[:.h]\s?\d{2}(?:[:.]\d{2})?(?:\s?[AaPp]\.?\s?[Mm]\.?)?"

FIELD_PATTERNS = {
    "amount": AMOUNT_RE, "balance": AMOUNT_RE, "available": AMOUNT_RE, "fee": AMOUNT_RE,
    "currency": rf"{CURRENCY_PATTERN}|[A-Z]{{3}}",
    "date": None,                       # built per placeholder (optional format)
    "time": TIME_RE,
    "type": r"[^\W\d_][^\n\d:]*?",
    "merchant": r"[^\n]+?", "person": r"[^\n]+?", "desc": r"[^\n]+?", "bank": r"[^\n]+?",
    "account": r"[^\s,;]+", "tracking": r"[^\s,;]+", "ref": r"[^\s,;]+",
    "skip": r"[^\n]*?", "*": r"[\s\S]*?",
}
FIELD_ALIASES = {"_": "skip", "ignore": "skip", "store": "merchant", "shop": "merchant", "payee": "person",
                 "card": "account", "description": "desc", "reference": "ref"}
OPTION_KEYS = {"language", "currency", "calendar", "date-order", "decimal", "direction", "bank", "in", "out"}

SEP = r"[\s‌]*"


class TemplateError(ValueError):
    pass


@dataclass
class Template:
    name: str
    body: str
    options: dict = field(default_factory=dict)
    regex: Optional[re.Pattern] = None
    groups: dict = field(default_factory=dict)      # group name -> (field, arg)
    line: int = 0                                    # line in the formats file (for error messages)

    @property
    def calendar_hint(self):
        cal = (self.options.get("calendar") or "").lower()
        if cal in ("j", "jalali", "persian", "shamsi", "شمسی"):
            return "j"
        if cal in ("g", "gregorian", "miladi", "میلادی"):
            return "g"
        return "j" if (self.options.get("language") or "").lower() == "fa" else "g"


@dataclass
class FormatsFile:
    templates: list = field(default_factory=list)
    in_words: list = field(default_factory=list)
    out_words: list = field(default_factory=list)
    path: str = ""


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

_HEADER_RE = re.compile(r"^\[(?!\[)\s*(?:template\s*:\s*)?(?P<name>[^\]]+?)\s*\]\s*$", re.I)
_OPTION_RE = re.compile(r"^@\s*(?P<key>[\w\-]+)\s*[:=]\s*(?P<value>.*)$")


def load_formats(path: str) -> FormatsFile:
    with open(path, encoding="utf-8-sig") as fh:
        return parse_formats(fh.read(), path)


def parse_formats(text: str, path: str = "<formats>") -> FormatsFile:
    result = FormatsFile(path=path)
    section, body, opts, start = None, [], {}, 0

    def close():
        if section is None:
            return
        if section.lower() == "keywords":
            return
        content = "\n".join(body).strip("\n")
        if not content.strip():
            raise TemplateError(f"{path}:{start}: template '{section}' is empty")
        tpl = Template(section, content, dict(opts), line=start)
        compile_template(tpl)
        result.templates.append(tpl)

    for no, line in enumerate(text.replace("\r\n", "\n").split("\n"), 1):
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        h = _HEADER_RE.match(stripped)
        if h:
            close()
            section, body, opts, start = h.group("name"), [], {}, no
            continue
        if section is None:
            if stripped:
                raise TemplateError(f"{path}:{no}: text outside a [section]: {stripped[:40]}")
            continue
        o = _OPTION_RE.match(stripped)
        if section.lower() == "keywords":
            k = re.match(r"^(in|out)\s*[:=]\s*(.*)$", stripped, re.I)
            if k:
                words = [w.strip() for w in k.group(2).split(",") if w.strip()]
                (result.in_words if k.group(1).lower() == "in" else result.out_words).extend(words)
            elif stripped:
                raise TemplateError(f"{path}:{no}: expected 'in: ...' or 'out: ...' in [keywords]")
            continue
        if o and not body:
            key = o.group("key").lower()
            if key not in OPTION_KEYS:
                raise TemplateError(f"{path}:{no}: unknown option @{key} (known: {', '.join(sorted(OPTION_KEYS))})")
            opts[key] = o.group("value").strip()
            continue
        body.append(line.replace("\\#", "#"))
    close()
    return result


def find_formats_file(explicit: str = None):
    """--formats path, else ./sms_formats.txt, else the one next to the project root."""
    if explicit:
        return explicit
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for p in (os.path.join(os.getcwd(), "sms_formats.txt"), os.path.join(here, "sms_formats.txt")):
        if os.path.isfile(p):
            return p
    return None


# ---------------------------------------------------------------------------
# Compiling a template into a regex
# ---------------------------------------------------------------------------

_TOKEN_RE = re.compile(r"\{\{|\}\}|\[\[|\]\]|\{[^{}]*\}|[\s‌]+|\w+|.", re.S)


def compile_template(tpl: Template):
    body = normalize(tpl.body)
    stack = [[]]
    gi = 0
    for tok in _TOKEN_RE.findall(body):
        if tok == "[[":
            stack.append([])
        elif tok == "]]":
            if len(stack) == 1:
                raise TemplateError(f"line {tpl.line}: ']]' without '[[' in template '{tpl.name}'")
            inner = stack.pop()
            stack[-1].append("(?:" + SEP.join(inner) + ")?")
        elif tok in ("{{", "}}"):
            stack[-1].append(re.escape(tok[0]))
        elif tok.startswith("{") and tok.endswith("}") and len(tok) > 2:
            name, _, arg = tok[1:-1].partition(":")
            name = FIELD_ALIASES.get(name.strip().lower(), name.strip().lower())
            if name not in FIELD_PATTERNS:
                raise TemplateError(f"line {tpl.line}: unknown placeholder {tok} in template '{tpl.name}'. "
                                    f"Known: {', '.join(sorted(k for k in FIELD_PATTERNS if k != '*'))}")
            arg = arg.strip()
            if name == "date":
                # the format's named groups become non-capturing; the text is re-parsed later
                pattern = re.sub(r"\(\?P<\w+>", "(?:", format_to_regex(arg)) if arg else DATE_ANY_RE
            else:
                pattern = FIELD_PATTERNS[name]
            group = f"f{gi}"
            gi += 1
            tpl.groups[group] = (name, arg)
            stack[-1].append(f"(?P<{group}>{pattern})")
        elif tok.isspace() or tok == "‌" or not tok.strip("‌ \t\n"):
            continue
        elif re.match(r"\w", tok):
            # a literal word must not match inside another word ("an" in "Tankstelle")
            stack[-1].append(r"(?<![^\W\d_])" + re.escape(tok) + r"(?![^\W\d_])")
        else:
            stack[-1].append(re.escape(tok))
    if len(stack) != 1:
        raise TemplateError(f"line {tpl.line}: '[[' without ']]' in template '{tpl.name}'")
    if not tpl.groups:
        raise TemplateError(f"line {tpl.line}: template '{tpl.name}' has no {{placeholders}}")
    if not any(f in ("amount", "fee") for f, _ in tpl.groups.values()):
        raise TemplateError(f"line {tpl.line}: template '{tpl.name}' needs an {{amount}} placeholder")
    pattern = r"^[ \t]*" + SEP.join(stack[0]) + r"(?=[ \t.!]*(?:\n|$))"
    try:
        tpl.regex = re.compile(pattern, re.I | re.M)
    except re.error as e:
        raise TemplateError(f"line {tpl.line}: template '{tpl.name}' could not be compiled: {e}")
    return tpl


@dataclass
class TemplateMatch:
    start: int
    end: int
    template: Template
    values: dict          # field -> list of (raw text, arg)


def scan(text: str, templates):
    """All non-overlapping template matches in ``text`` (already normalised), in order."""
    found = []
    for tpl in templates:
        for m in tpl.regex.finditer(text):
            if m.end() == m.start():
                continue
            values = {}
            for g, (name, arg) in tpl.groups.items():
                v = m.group(g)
                if v is not None and v.strip():
                    values.setdefault(name, []).append((v.strip(), arg))
            found.append(TemplateMatch(m.start(), m.end(), tpl, values))
    found.sort(key=lambda x: (x.start, -(x.end - x.start)))
    chosen, last_end = [], -1
    for f in found:
        if f.start >= last_end:
            chosen.append(f)
            last_end = f.end
    return chosen
