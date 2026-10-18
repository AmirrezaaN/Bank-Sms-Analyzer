"""Bank SMS analyzer: parse copied bank SMS (any language) and build a bilingual HTML report."""

from .parser import Options, parse_text, parse_file
from .analysis import analyze
from .report import build_report
from .templates import load_formats, parse_formats

__all__ = ["Options", "parse_text", "parse_file", "analyze", "build_report", "load_formats", "parse_formats"]
__version__ = "1.0.0"
