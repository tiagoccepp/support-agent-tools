#!/usr/bin/env python3
"""Inline self-hosted woff2 fonts into the demo UI (single-file, offline-safe).

Reads src/static/ui.src.html, replaces the /*__FONT_FACE__*/ token with
@font-face rules (base64 data URIs from src/static/fonts/*.woff2),
writes src/static/ui.html. Run after editing ui.src.html:

    python scripts/inline_fonts.py
"""
import base64
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FONTS = [
    ("Sora", "700", "Sora-700.woff2"),
    ("Sora", "800", "Sora-800.woff2"),
    ("PublicSans", "400", "PublicSans-400.woff2"),
    ("PublicSans", "600", "PublicSans-600.woff2"),
    ("JetBrainsMono", "400", "JetBrainsMono-400.woff2"),
    ("JetBrainsMono", "600", "JetBrainsMono-600.woff2"),
]
TOKEN = "/*__FONT_FACE__*/"
FIXTURES_TOKEN = "/*__FIXTURES__*/"


def main() -> None:
    rules = []
    for family, weight, fname in FONTS:
        data = (ROOT / "src" / "static" / "fonts" / fname).read_bytes()
        b64 = base64.b64encode(data).decode()
        rules.append(
            f"@font-face{{font-family:'{family}';font-weight:{weight};"
            f"font-style:normal;font-display:swap;src:url(data:font/woff2;base64,{b64}) format('woff2');}}"
        )
    src = (ROOT / "src" / "static" / "ui.src.html").read_text()
    assert TOKEN in src, "font token missing in ui.src.html"
    out = src.replace(TOKEN, "\n".join(rules))
    assert FIXTURES_TOKEN in out, "fixtures token missing in ui.src.html"
    fixtures: dict = {}
    fdir = ROOT / "demo" / "fixtures"
    if fdir.is_dir():
        for p in sorted(fdir.glob("*.json")):
            fixtures[p.stem] = json.loads(p.read_text())
    out = out.replace(FIXTURES_TOKEN, "const FIXTURES=" + json.dumps(fixtures, separators=(",", ":")) + ";")
    (ROOT / "src" / "static" / "ui.html").write_text(out)
    print(f"wrote ui.html ({len(out) // 1024} KB, {len(fixtures)} fixtures)")


if __name__ == "__main__":
    main()
