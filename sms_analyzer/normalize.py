"""Text normalisation: Persian/Arabic digits, Arabic letter variants, invisible bidi marks, dashes."""

import re

_TRANS = {}
for _i, _ch in enumerate("۰۱۲۳۴۵۶۷۸۹"):
    _TRANS[ord(_ch)] = str(_i)
for _i, _ch in enumerate("٠١٢٣٤٥٦٧٨٩"):
    _TRANS[ord(_ch)] = str(_i)
_TRANS.update({
    ord("ي"): "ی", ord("ى"): "ی", ord("ك"): "ک", ord("ة"): "ه", ord("ۀ"): "ه",
    ord("ـ"): None,                                   # tatweel (ـ)
    ord(" "): " ", ord(" "): " ", ord(" "): " ", ord("\t"): " ",
    ord("−"): "-", ord("–"): "-", ord("—"): "-", ord("‐"): "-", ord("﹣"): "-", ord("－"): "-",
    ord("＋"): "+", ord("："): ":", ord("﹕"): ":",
    ord("٬"): ",", ord("،"): ",", ord("٫"): ".",
})
# Invisible direction marks that appear when SMS are copied from a phone
for _cp in (0x200E, 0x200F, 0x061C, 0xFEFF, 0x200B, *range(0x202A, 0x202F), *range(0x2066, 0x206A)):
    _TRANS[_cp] = None

_SPACES = re.compile(r"[ ]{2,}")
_PERSIAN = re.compile(r"[؀-ۿ]")


def normalize(text: str) -> str:
    """Normalise text for parsing. Keeps line breaks and ZWNJ (half-space)."""
    return _SPACES.sub(" ", text.translate(_TRANS))


def compact(text: str) -> str:
    """Text without spaces/ZWNJ, used to compare keywords."""
    return re.sub(r"[\s‌]+", "", text)


def clean_name(text: str) -> str:
    """Tidy a merchant/person name so the same shop is grouped together."""
    text = text.replace("‌", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip(" :-_.,;/\\|*")


def has_persian(text: str) -> bool:
    return bool(_PERSIAN.search(text))
