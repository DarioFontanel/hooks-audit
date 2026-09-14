# Setup di un plugin di function hooks

Verificato su Claude Code 2.1.263 (2026-09-14). L'API è early access: i tipi generati vincono su questo documento.

## Prerequisiti

| Check | Comando | Se manca |
|---|---|---|
| Versione ≥ 2.1.263 | `claude --version` | aggiornare Claude Code |
| Flag rollout | `claude --debug -p "ok"` poi `grep "hooks modules" ~/.claude/debug/$(ls -t ~/.claude/debug \| head -1)` | se dice `rollout flag … is off`: aggiungere `"CLAUDE_CODE_ENABLE_FUNCTION_HOOKS": "1"` in `~/.claude/settings.json` → `env` (sempre necessario con `DISABLE_TELEMETRY=1` o `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1`, che spengono GrowthBook) |
| Tipi | `.claude/types/claude-code.d.ts` con `Written by Claude Code <versione corrente>` in testa | `/plugin-types .claude/types` (la skill compare solo col flag attivo) |
| Node per il type-check | `node --version` | opzionale: senza, si salta `tsc` e ci si affida a `claude plugin validate` + test runtime |

## Layout

```
plugins/<nome>/
├── .claude-plugin/plugin.json   # { "name": "<nome>", "version": "0.1.0", "description": "…" }  — niente chiave "skills"
├── hooks/hooks.json             # { "modules": ["./hooks.tsx"] }   ← function hooks; NON "hooks": {SessionStart: …} (quelli sono command hook)
├── hooks/hooks.tsx              # export const register: Register = (on) => { … }   (.tsx per usare JSX con h)
└── tsconfig.json                # dal header di claude-code.d.ts, include ["../../.claude/types", "hooks"]
```

`claude plugin init <nome> --with hooks` scaffolda in `~/.claude/skills/<nome>/` un **command hook** (bun + stdin), non una function hook: va riscritto come sopra. Conviene spostare la cartella nel workspace (`plugins/<nome>/`) per versionarla e lasciare in `~/.claude/skills/<nome>` un **symlink** verso di essa: così il plugin si carica in ogni sessione (come `<nome>@skills-dir`) senza `--plugin-dir`.

tsconfig minimo:

```json
{
  "compilerOptions": {
    "target": "es2023", "lib": ["es2023"], "types": [],
    "module": "esnext", "moduleResolution": "bundler",
    "strict": true, "noEmit": true, "skipLibCheck": true,
    "jsx": "react", "jsxFactory": "h", "jsxFragmentFactory": "Fragment"
  },
  "include": ["../../.claude/types", "hooks"]
}
```

Scheletro del modulo:

```tsx
import type { Register, EngineInterface } from 'claude-code'   // a runtime l'import è vuoto

export const register: Register = (on) => {
  on('tool.call', { tool: 'Bash' }, async ($, e, next) => { /* … */ return next(e) })
}
```

## Verifica

1. `claude plugin validate plugins/<nome>` → deve elencare `hooks: <evento>{matcher}` e `calls: $.…` per ogni hook. Se un hook manca dall'elenco, il motore non lo vede.
2. `npx -y -p typescript@5 tsc -p plugins/<nome>/tsconfig.json` → nessun output = ok.
3. Runtime headless: `claude --plugin-dir ./plugins/<nome> --debug -p "<prompt>"`. Nel debug log più recente (`ls -t ~/.claude/debug/*.txt | head -1`) cercare:
   - `hooks module <nome> loaded (worker, environment 1); events: …` → caricato;
   - `hooks module <nome> <evento> settled in N ms` → l'hook ha girato;
   - `[<nome>] $.ui.log: …` → le tue righe di log;
   - `threw`, `overran`, `does not validate` → problemi.
   In `-p` non c'è surface: `session.start` arriva con `interactive: false`, `$.ui.ask` rifiuta (→ i gate negano), `ui.render` non viene mai chiamato.
4. Interattivo: `claude --plugin-dir ./plugins/<nome> --debug` (hot reload al salvataggio; se il symlink in `~/.claude/skills` è già attivo il plugin si carica due volte: per il dev loop usare uno dei due). Per gli hook `ui.render` è l'unico test possibile.
5. Per provare un deny senza rischi: bersaglio **finto che matcha il pattern** (es. `/tmp/x/scripts/mailer/probe.py` per un pattern su `scripts/mailer/`), mai quello vero. Nota che il modello può rifiutarsi da solo di violare la regola prima di chiamare il tool: in quel caso l'hook non è stato esercitato, va detto.

## Gotcha del motore

- Un hook che **lancia** viene saltato e la catena continua: nessuna protezione. Try/catch su tutto ciò che può fallire; un dialogo chiuso vale «no».
- Hook che ritorna senza `next(e)` risponde da solo; `next({ ...e, campo })` riscrive per chi sta sotto; `tool` e `tool_use_id` sono riservati.
- I managed-settings hooks girano prima: il loro deny vince.
- Budget per dispatch, `next.signal` abortisce: lavoro lungo in `session.start` + `$.clock.every/after` (i timer cadono al reload del modulo).
- `$.fs` solo sotto la cwd della sessione (più lettura in `/tmp`); `$.process.run` è argv, niente shell; `$.store` è JSON persistente sotto `~/.claude/plugins/store/`.
- `$.ui.ask(question, { options: [a, b], header })` → restituisce l'etichetta; 2-4 opzioni; header ≤ 12 caratteri.
- UI: elementi terminal `Box, Text, Button, Link, Input, Select, div, span, b`; props solo dall'allowlist nei tipi; hotkey dei `Button` **solo cifre**, armate solo nella band `AbovePrompt` a composer vuoto; `Link.href` solo `https:` ASCII; figli di `Text` = stringhe.
- `prompt.submit`: `e.origin.kind` distingue composer / bridge / sdk / plugin / …; il testo di `{ drop }` viene mostrato all'utente; il prompt droppato non entra nel transcript.
- `ui.render` gira una volta per valore di input (props + larghezza) e a ogni `$.ui.invalidate('ui.render')` (max 10/s).
- Codex, bot headless con `CLAUDE_CONFIG_DIR` isolata e cron **non** eseguono plugin: per loro valgono CLAUDE.md, gli hook standard e i test.
- Dopo un update di Claude Code: rigenerare i tipi, rilanciare validate + tsc.
