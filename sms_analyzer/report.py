"""Write the single-file HTML report (works offline, no external resources)."""

import json
import os

_TEMPLATE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "report_template.html")


def build_report(data: dict, out_path: str) -> str:
    with open(_TEMPLATE, encoding="utf-8") as fh:
        html = fh.read()
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    # SMS text must never be able to close the <script> tag
    payload = payload.replace("</", "<\\/").replace("<!--", "<\\!--")
    html = html.replace("/*__DATA__*/null", payload, 1)
    folder = os.path.dirname(os.path.abspath(out_path))
    os.makedirs(folder, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(html)
    return out_path
