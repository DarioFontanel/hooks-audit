#!/usr/bin/env python3
"""Estrae le righe «regola» dai file di istruzioni di un workspace Claude Code.

Solo stdlib. Euristico per costruzione: trova i candidati, la classificazione
finale (tipo A-H/N, evento, priorità) la fa l'agente leggendo il contesto.

Uso:
  python3 find_rules.py                      # CLAUDE.md, AGENTS.md, settings, skill, docs/context del cwd
  python3 find_rules.py CLAUDE.md docs/x.md  # solo questi file
  python3 find_rules.py --out tmp/hooks-audit/rules.json --md
  python3 find_rules.py --skip workspace,plans   # cartelle in più da ignorare (deliverable, archivi)
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

MARKERS = [
    (r"🔒", "lock"),
    (r"\bMAI\b|\bNEVER\b|\bnever\b|\bmai\b", "never"),
    (r"\bSEMPRE\b|\bALWAYS\b|\balways\b|\bsempre\b", "always"),
    (r"\bMUST\b|\bmust\b|\bdeve\b|\bdevi\b|\bdevono\b|\bobbligatori[oa]\b", "must"),
    (r"\bDO NOT\b|\bdo not\b|\bdon't\b|\bnon\s+\w+\s+mai\b", "forbid"),
    (r"chied(?:ere|i)\s+(?:sempre\s+)?(?:conferma|prima)|\bask\s+(?:for\s+)?(?:confirmation|before)\b|\bconferma esplicita\b", "confirm"),
    (r"\bsolo\b.*\b(?:se|quando|dopo)\b|\bonly\b.*\b(?:if|when|after)\b", "only-if"),
    (r"\binvece di\b|\bal posto di\b|\binstead of\b|\bnon\s+\w+,\s*(?:ma|usa)\b", "replace"),
    (r"prima di (?:ogni|ciascun)|dopo (?:ogni|ciascun)|\bbefore (?:every|each|any)\b|\bafter (?:every|each|any)\b", "pre-post"),
    (r"`[A-Za-z][\w ]*:\s*<[^`]+>`|\bquando (?:l'utente|scrivo|dico)\b|\bwhen the user (?:says|types|writes)\b", "shortcut"),
    (r"\bnon editar[el]\b|\bnon modificare\b|\bnon toccare\b|\bnever edit\b|\bdo not edit\b|\bautogenerat[oa]\b|\bnon a mano\b", "protect-file"),
]

DEFAULT_TARGETS = [
    "CLAUDE.md", "AGENTS.md", ".claude/settings.json", ".claude/settings.local.json",
    ".cursorrules", ".github/copilot-instructions.md",
]
DEFAULT_GLOBS = ["**/CLAUDE.md", ".claude/rules/*.md", ".claude/skills/*/SKILL.md", "docs/**/*.md", "context/*.md"]
SKIP_PARTS = {"node_modules", ".git", ".venv", "venv", "dist", "build", "vendor", "tmp", "worktrees", ".worktrees", "__pycache__"}
STRONG = re.compile(r"\b(MAI|SEMPRE|NEVER|ALWAYS|MUST)\b")


def is_code_fence(line: str) -> bool:
    return line.lstrip().startswith("```")


def scan_markdown(path: Path, root: Path, strict: bool = False) -> list[dict]:
    """strict=True (SKILL.md, docs): tiene solo 🔒 e marcatori in maiuscolo, per tagliare il rumore procedurale."""
    rules: list[dict] = []
    section = ""
    in_fence = False
    in_tree = False
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return rules
    for n, line in enumerate(lines, 1):
        if "<!-- TREE:START" in line:
            in_tree = True
        if "<!-- TREE:END" in line:
            in_tree = False
            continue
        if is_code_fence(line):
            in_fence = not in_fence
            continue
        if in_fence or in_tree:
            continue
        m = re.match(r"^(#{1,6})\s+(.*)", line)
        if m:
            section = m.group(2).strip()
            continue
        text = line.strip()
        if len(text) < 12:
            continue
        hits = [tag for pat, tag in MARKERS if re.search(pat, text)]
        if not hits:
            continue
        if strict and "lock" not in hits and not STRONG.search(text):
            continue
        rules.append({
            "id": f"{path.relative_to(root)}:{n}",
            "file": str(path.relative_to(root)),
            "line": n,
            "section": section,
            "markers": sorted(set(hits)),
            "bytes": len(line.encode("utf-8")),
            "text": text[:400],
        })
    return rules


def scan_settings(path: Path, root: Path) -> list[dict]:
    """Hook `command` esistenti in settings.json = candidati a migrazione."""
    out: list[dict] = []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return out
    hooks = data.get("hooks") or {}
    for event, entries in hooks.items():
        for entry in entries or []:
            for h in entry.get("hooks", []):
                out.append({
                    "id": f"{path.relative_to(root) if path.is_relative_to(root) else path}:hooks.{event}",
                    "file": str(path),
                    "line": 0,
                    "section": f"settings hook {event}",
                    "markers": ["settings-hook"],
                    "bytes": len(json.dumps(h)),
                    "text": f"{event} → {h.get('type')}: {str(h.get('command') or h.get('prompt') or '')[:200]}"
                           + (f" (matcher: {entry.get('matcher')})" if entry.get("matcher") else ""),
                })
    return out


def collect_targets(root: Path, explicit: list[str]) -> list[Path]:
    if explicit:
        return [Path(p).resolve() for p in explicit]
    seen: dict[Path, None] = {}
    for t in DEFAULT_TARGETS:
        p = root / t
        if p.is_file():
            seen[p.resolve()] = None
    for g in DEFAULT_GLOBS:
        for p in root.glob(g):
            if p.is_file() and not (set(p.relative_to(root).parts) & SKIP_PARTS):
                seen[p.resolve()] = None
    home_settings = Path.home() / ".claude" / "settings.json"
    if home_settings.is_file():
        seen[home_settings] = None
    return list(seen)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("paths", nargs="*", help="file da analizzare (default: set standard del workspace)")
    ap.add_argument("--root", default=".", help="root del workspace (default: cwd)")
    ap.add_argument("--out", help="scrive il JSON qui (default: stdout)")
    ap.add_argument("--md", action="store_true", help="stampa anche una tabella markdown")
    ap.add_argument("--skip", default="", help="nomi di cartelle da ignorare in più, separati da virgola")
    args = ap.parse_args()
    SKIP_PARTS.update(x.strip() for x in args.skip.split(",") if x.strip())

    root = Path(args.root).resolve()
    rules: list[dict] = []
    for p in collect_targets(root, args.paths):
        if p.suffix == ".json":
            rules.extend(scan_settings(p, root))
        else:
            rel = p.relative_to(root) if p.is_relative_to(root) else p
            strict = rel.name == "SKILL.md" or rel.parts[:1] == ("docs",)
            rules.extend(scan_markdown(p, root, strict=strict))

    payload = {
        "root": str(root),
        "files_scanned": sorted({r["file"] for r in rules}),
        "count": len(rules),
        "bytes_total": sum(r["bytes"] for r in rules),
        "rules": rules,
    }
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"{len(rules)} candidati ({payload['bytes_total']} byte) → {out}", file=sys.stderr)
    else:
        print(json.dumps(payload, ensure_ascii=False, indent=2))

    if args.md:
        print("\n| id | marker | sezione | testo |\n|---|---|---|---|")
        for r in rules:
            t = r["text"].replace("|", "\\|")[:140]
            print(f"| {r['id']} | {','.join(r['markers'])} | {r['section'][:40]} | {t} |")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
