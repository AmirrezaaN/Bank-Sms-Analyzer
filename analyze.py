"""
Analyse bank SMS messages and build an HTML report.

    python analyze.py sms.txt                 report next to the input, opened in the browser
    python analyze.py sms.txt -o report.html  custom output path
    python analyze.py a.txt b.txt             several files together
    python analyze.py                         opens a file picker

Run ``python analyze.py --help`` for all options.
"""

import sys

from sms_analyzer.cli import main

if __name__ == "__main__":
    sys.exit(main())
