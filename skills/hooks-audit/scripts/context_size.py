#!/usr/bin/env python3
"""Misura quanto contesto occupa un file di istruzioni (o una sua sezione).

Solo stdlib. Token stimati con ~4 caratteri/token (ordine di grandezza; il
tokenizer reale varia ±20%). Utile per il prima/dopo di /hooks-audit.

Uso:
  python3 context_size.py CLAUDE.md
  python3 context_size.py CLAUDE.md --section "Deploy"        # solo la sezione (heading che contiene il testo)
  python3 context_size.py CLAUDE.md --by-section              # tabella per heading di livello 2
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path


def measure(text: str) -> dict:
    b = len(text.encode("utf-8"))
    return {"bytes": b, "chars": len(text), "lines": text.count("\n") + (1 if text and not text.endswith("\n") else 0),
            "tokens_est": round(len(text) / 4)}


def sections(text: str, level: int = 2) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    title, buf = "(preambolo)", []
    pat = re.compile(rf"^#{{{level}}}\s+(.*)")
    for line in text.splitlines(keepends=True):
        m = pat.match(line)
        if m:
            out.append((title, "".join(buf)))
            title, buf = m.group(1).strip(), [line]
        else:
            buf.append(line)
    out.append((title, "".join(buf)))
    return out


def fmt(title: str, m: dict) -> str:
    return f"| {title[:50]} | {m['bytes']:>7} | {m['lines']:>5} | ~{m['tokens_est']:>6} |"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("file")
    ap.add_argument("--section", help="misura solo la sezione il cui heading contiene questo testo")
    ap.add_argument("--by-section", action="store_true", help="tabella per heading ##")
    ap.add_argument("--level", type=int, default=2)
    args = ap.parse_args()

    text = Path(args.file).read_text(encoding="utf-8")
    header = "| sezione | byte | righe | token |\n|---|---:|---:|---:|"

    if args.section:
        hits = [(t, body) for t, body in sections(text, args.level) if args.section.lower() in t.lower()]
        if not hits:
            print(f"nessuna sezione con «{args.section}»")
            return 1
        print(header)
        for t, body in hits:
            print(fmt(t, measure(body)))
        return 0

    if args.by_section:
        print(header)
        for t, body in sections(text, args.level):
            print(fmt(t, measure(body)))
        print(fmt("TOTALE", measure(text)))
        return 0

    m = measure(text)
    print(f"{args.file}: {m['bytes']} byte · {m['lines']} righe · ~{m['tokens_est']} token")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
