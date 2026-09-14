#!/usr/bin/env python3
"""Legge i transcript LOCALI di Claude Code del progetto (~/.claude/projects/<cwd>/*.jsonl)
e misura come l'utente lavora davvero: prompt brevi ripetuti, slash command,
comandi Bash ricorrenti e falliti, tool MCP usati. Da qui escono le idee di hook
con un beneficio MISURATO (turni risparmiati al mese), non presunto.

Solo stdlib, sola lettura, nulla esce dalla macchina. Nel report finiscono
conteggi e pattern normalizzati, non il testo integrale delle conversazioni.

Uso:
  python3 scan_history.py                                  # progetto = cwd, ultimi 60 giorni
  python3 scan_history.py --root ~/proj --days 90 --out tmp/hooks-audit/history.json --md
  python3 scan_history.py --project-dir ~/.claude/projects/-Users-me-proj   # path esplicito
"""
from __future__ import annotations

import argparse
import collections
import json
import re
import sys
import time
from pathlib import Path

INTERRUPT = re.compile(r"^\s*\[request interrupted", re.I)
WORDS_SHORT = 8
MIN_REPEAT = 2
ACKS = {"si", "sì", "ok", "okay", "no", "fatto", "confermo", "vai", "procedi", "yes", "go", "continua", "perfetto", "bene", "grazie", "a", "esatto", "dai"}
SLASH = re.compile(r"^(/[A-Za-z][\w:-]*)(?:\s|$)")

STOP_HEADS = {"cd", "ls", "cat", "echo", "head", "tail", "pwd", "wc", "true", "sleep", "which", "test", "[", "mkdir", "rm", "cp", "mv", "find", "grep", "sed", "awk", "sort", "open"}
GIT_SUB = re.compile(r"^git\s+(-C\s+\S+\s+)?([a-z-]+)")


def project_dir_for(root: Path) -> Path:
    return Path.home() / ".claude" / "projects" / re.sub(r"[^A-Za-z0-9]", "-", str(root))


def norm_prompt(t: str) -> str:
    t = t.strip().lower()
    t = re.sub(r"https?://\S+", "<url>", t)
    t = re.sub(r"\d+([.,]\d+)?", "#", t)
    t = re.sub(r"[^\w\s#<>:/-]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def cmd_head(cmd: str) -> str:
    """Primo comando della pipeline/catena, ridotto a 1-3 token significativi."""
    first = re.split(r"\s*(?:&&|\|\||;|\|)\s*", cmd.strip(), maxsplit=1)[0]
    first = re.sub(r"^(?:cd\s+\S+\s*(?:&&|;)\s*)+", "", first)
    first = re.sub(r"^\s*(?:[A-Z_]+=\S+\s+)+", "", first)  # env var prefix
    toks = first.split()
    if not toks:
        return ""
    if toks[0] == "git":
        m = GIT_SUB.match(first)
        return f"git {m.group(2)}" if m else "git"
    if toks[0] in {"python", "python3", "node", "npx", "pnpm", "npm", "yarn", "bun", "uv", "poetry", "conda"} or toks[0].endswith(("/python", "/python3")):
        interp = "python" if "python" in toks[0] else toks[0]
        target = next((t for t in toks[1:] if not t.startswith(("-", "<", "'", '"', "$"))), "")
        target = Path(target).name if "/" in target else target
        return f"{interp} {target}".strip()
    sub = toks[1] if len(toks) > 1 and re.fullmatch(r"[a-z][a-z-]*", toks[1]) else ""
    return f"{toks[0]} {sub}".strip()


def user_text(msg: dict) -> str | None:
    ct = msg.get("content")
    if isinstance(ct, str):
        return ct
    if isinstance(ct, list):
        parts = [x.get("text", "") for x in ct if isinstance(x, dict) and x.get("type") == "text"]
        return " ".join(parts) if parts else None
    return None


def scan(project_dir: Path, since: float) -> dict:
    sessions = 0
    prompts = collections.Counter()
    prefixes = collections.Counter()
    slash = collections.Counter()
    bash_heads = collections.Counter()
    bash_errors = collections.Counter()
    tools = collections.Counter()
    mcp_tools = collections.Counter()
    edits_by_ext = collections.Counter()
    after_commit = collections.Counter()
    n_prompts = 0
    interrupts = 0
    pending: dict[str, tuple[str, str]] = {}  # tool_use_id → (tool, head)

    for f in sorted(project_dir.glob("*.jsonl")):
        try:
            if f.stat().st_mtime < since:
                continue
        except OSError:
            continue
        sessions += 1
        last_commit_seen = 0
        with f.open(encoding="utf-8", errors="replace") as fh:
            for line in fh:
                try:
                    d = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if d.get("isSidechain"):
                    continue
                t = d.get("type")
                if t == "system" and d.get("subtype") == "local_command":
                    m = re.search(r"<command-name>(/[\w:-]+)</command-name>", d.get("content", ""))
                    if m:
                        slash[m.group(1)] += 1
                    continue
                msg = d.get("message") or {}
                if t == "user":
                    ct = msg.get("content")
                    if isinstance(ct, list):
                        for x in ct:
                            if isinstance(x, dict) and x.get("type") == "tool_result" and x.get("is_error"):
                                tool, h = pending.get(x.get("tool_use_id", ""), ("", ""))
                                if tool == "Bash" and h and h.split()[0] not in STOP_HEADS:
                                    bash_errors[h] += 1
                    txt = user_text(msg)
                    if not txt or txt.startswith("<"):
                        continue
                    if INTERRUPT.match(txt):
                        interrupts += 1
                        continue
                    if txt.lstrip().lower().startswith("[image"):
                        continue
                    n_prompts += 1
                    sm = SLASH.match(txt)
                    if sm:
                        slash[sm.group(1)] += 1
                        continue
                    words = txt.split()
                    npn = norm_prompt(txt)
                    if 2 <= len(words) <= WORDS_SHORT and npn not in ACKS:
                        prompts[npn] += 1
                    m = re.match(r"^\s*([A-Za-zÀ-ÿ][\w-]{1,20}):\s+\S", txt)
                    if m and not txt.startswith(("http", "/")):
                        prefixes[m.group(1).lower() + ":"] += 1
                elif t == "assistant":
                    ct = msg.get("content")
                    if not isinstance(ct, list):
                        continue
                    for x in ct:
                        if not (isinstance(x, dict) and x.get("type") == "tool_use"):
                            continue
                        name = x.get("name", "")
                        inp = x.get("input") or {}
                        tools[name] += 1
                        if name.startswith("mcp__"):
                            mcp_tools[name] += 1
                        if name == "Bash":
                            h = cmd_head(str(inp.get("command", "")))
                            pending[x.get("id", "")] = (name, h)
                            if h and h.split()[0] not in STOP_HEADS:
                                bash_heads[h] += 1
                            if h == "git commit":
                                last_commit_seen = 3
                            elif last_commit_seen > 0 and h:
                                after_commit[h] += 1
                                last_commit_seen -= 1
                        elif name in {"Edit", "Write", "MultiEdit"}:
                            fp = str(inp.get("file_path", ""))
                            edits_by_ext[Path(fp).suffix or "(none)"] += 1

    days = max(1, round((time.time() - since) / 86400))
    repeated = [(p, c) for p, c in prompts.most_common(40) if c >= MIN_REPEAT and p]
    ideas = []
    for p, c in repeated[:15]:
        ideas.append({"kind": "D", "pattern": p, "count": c, "per_month": round(c * 30 / days, 1),
                      "idea": "prompt ripetuto → alias `prompt.submit` (rewrite verso una skill) o `{ drop }` se l'azione è deterministica"})
    for p, c in prefixes.most_common(10):
        if c >= MIN_REPEAT:
            ideas.append({"kind": "D", "pattern": p + " …", "count": c, "per_month": round(c * 30 / days, 1),
                          "idea": "prefisso `parola:` usato come comando → hook `prompt.submit` che agisce senza modello"})
    for s, c in slash.most_common(10):
        if c >= 3:
            ideas.append({"kind": "G", "pattern": s, "count": c, "per_month": round(c * 30 / days, 1),
                          "idea": "slash command frequente → `Button` con hotkey nella band AbovePrompt (o alias `prompt.submit`)"})
    for h, c in bash_errors.most_common(10):
        if c >= MIN_REPEAT:
            ideas.append({"kind": "C", "pattern": h, "count": c, "per_month": round(c * 30 / days, 1),
                          "idea": "comando che fallisce ripetutamente → rewrite `tool.call` (interprete/gestore giusto) o deny con istruzione"})
    for h, c in after_commit.most_common(5):
        if c >= 3 and h not in {"git push", "git status", "git log", "git diff", "git add", "git commit", "git stash"}:
            ideas.append({"kind": "E", "pattern": f"git commit → {h}", "count": c, "per_month": round(c * 30 / days, 1),
                          "idea": "passo fisso dopo il commit → post-hook `tool.call` che lo lancia senza turno"})
    for n, c in mcp_tools.most_common(30):
        if re.search(r"(delete|trash|remove|destroy|purge|send|publish|deploy|pay|revoke)", n, re.I):
            ideas.append({"kind": "A/B", "pattern": n, "count": c, "per_month": round(c * 30 / days, 1),
                          "idea": "tool MCP distruttivo/outbound già usato → deny o `$.ui.ask` sul nome esatto"})

    return {
        "project_dir": str(project_dir), "days": days, "sessions": sessions, "prompts": n_prompts,
        "interrupts": interrupts,
        "prompts_per_month": round(n_prompts * 30 / days, 1),
        "repeated_short_prompts": repeated[:25],
        "prefixes": prefixes.most_common(10),
        "slash_commands": slash.most_common(15),
        "bash_heads": bash_heads.most_common(25),
        "bash_errors": bash_errors.most_common(15),
        "after_commit": after_commit.most_common(8),
        "tools": tools.most_common(20),
        "mcp_tools": mcp_tools.most_common(30),
        "edits_by_ext": edits_by_ext.most_common(10),
        "ideas": ideas,
    }


def to_markdown(r: dict) -> str:
    out = [f"**Storico**: {r['sessions']} sessioni · {r['prompts']} prompt in {r['days']} giorni (~{r['prompts_per_month']}/mese) · {r['interrupts']} interruzioni",
           "", "| tipo | pattern | volte | /mese | idea |", "|---|---|---:|---:|---|"]
    for i in r["ideas"]:
        out.append(f"| {i['kind']} | `{i['pattern'][:60]}` | {i['count']} | {i['per_month']} | {i['idea']} |")
    if r["bash_errors"]:
        out += ["", "Comandi Bash falliti più spesso: " + ", ".join(f"`{h}` ×{c}" for h, c in r["bash_errors"][:8])]
    if r["slash_commands"]:
        out += ["", "Slash command: " + ", ".join(f"`{s}` ×{c}" for s, c in r["slash_commands"][:10])]
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default=".", help="root del progetto (default: cwd)")
    ap.add_argument("--project-dir", help="cartella transcript esplicita (default: derivata da --root)")
    ap.add_argument("--days", type=int, default=60, help="finestra temporale (default 60)")
    ap.add_argument("--out", help="scrive il JSON qui (default: stdout)")
    ap.add_argument("--md", action="store_true", help="stampa anche il riassunto markdown")
    args = ap.parse_args()

    root = Path(args.root).resolve()
    pdir = Path(args.project_dir).expanduser() if args.project_dir else project_dir_for(root)
    if not pdir.is_dir():
        print(f"nessun transcript in {pdir} — l'analisi dello storico viene saltata (le altre fasi non ne dipendono)", file=sys.stderr)
        return 2
    r = scan(pdir, time.time() - args.days * 86400)
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(r, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"{r['sessions']} sessioni, {r['prompts']} prompt, {len(r['ideas'])} idee → {out}", file=sys.stderr)
    else:
        print(json.dumps(r, ensure_ascii=False, indent=2))
    if args.md:
        print("\n" + to_markdown(r))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
