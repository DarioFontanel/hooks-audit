# hooks-audit

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](./LICENSE)
[![Claude Code](https://img.shields.io/badge/Claude_Code-skill-d97757)](https://docs.anthropic.com/en/docs/claude-code)
[![Function hooks](https://img.shields.io/badge/Function_hooks-%E2%89%A5_2.1.263-3178c6)](https://docs.anthropic.com/en/docs/claude-code/plugins)

**hooks-audit** è una skill per Claude Code che ti permette di scoprire cosa, nel tuo workspace, può diventare una **function hook** — codice TypeScript eseguito dal motore di Claude Code prima che il modello veda la richiesta — e di implementarla, verificarla e liberare il contesto corrispondente nel `CLAUDE.md`. Le idee arrivano da tre sorgenti — le regole scritte, la struttura del workspace e lo storico d'uso locale — e ognuna viene proposta con il beneficio misurato: turni risparmiati, rischi evitati, rework eliminato.

---

## Il problema che risolve

```
regole scritte (CLAUDE.md)                       plugin di function hooks
"MAI cancellare email"                ──▶   tool.call su trash_* → { deny }
"chiedi prima di un deploy"           ──▶   tool.call su git push → $.ui.ask → deny | next
"rispondi in italiano"                ──▶   resta nel CLAUDE.md (non è un evento)

struttura del workspace (nessuna regola scritta)
TODO.md con 40 voci                   ──▶   prompt.submit "todo: X" → scrive il file → { drop }
.env presente                         ──▶   tool.call su Read/cat .env → { deny }
netlify.toml in un submodule          ──▶   tool.call su git push → $.ui.ask

storico d'uso (transcript locali)
"fai commit e push" × 9 in 60 giorni  ──▶   prompt.submit → rewrite verso /commit
`python x.py` fallito × 11            ──▶   tool.call su Bash → interprete del progetto
```

Una regola scritta viene letta, pesata e a volte ignorata dal modello, e occupa contesto a ogni turno. Un'abitudine ripetuta costa un turno intero ogni volta. Una function hook intercetta l'evento e decide da sola: nega il tool, chiede conferma a te, riscrive il comando, agisce senza avviare un turno. Le regole che richiedono giudizio — tono, lingua, decisioni di merito — restano dove sono: la skill le classifica come non trasformabili e lo dice.

---

## Le cinque fasi

**0. 🔎 Prerequisiti** — versione di Claude Code, flag di attivazione dei function hooks, tipi TypeScript generati dalla build corrente, presenza di un plugin già esistente e di altri agenti (Codex, bot headless) che leggono lo stesso `CLAUDE.md` ma non eseguono plugin.

**1. 📋 Raccolta da tre sorgenti** — `find_rules.py` estrae le righe-regola da `CLAUDE.md`, `AGENTS.md`, hook già presenti in `settings.json`, skill e documentazione, riconoscendo marcatori come 🔒, MAI, SEMPRE, «chiedi conferma prima di», «usa X invece di Y». `find_opportunities.py` legge la struttura del workspace e segnala ciò che suggerisce un hook anche senza regola scritta: file todo, segreti, file autogenerati, changelog e script di rigenerazione, deploy legati al push, lockfile e interprete Python, database locali, marker di cron, server MCP con tool distruttivi. `scan_history.py` legge i transcript locali del progetto e misura come lavori davvero: prompt brevi ripetuti, prefissi usati come comandi, comandi che falliscono più volte, passi fissi dopo un commit, tool MCP distruttivi già invocati. Nulla esce dalla macchina: nel report entrano conteggi e pattern, non le conversazioni.

**2. 🗂️ Classificazione e gate di utilità** — ogni candidato riceve un tipo (divieto assoluto, divieto con eccezione umana, sostituzione, scorciatoia utente, post-azione, formato dei testi git, stato da monitorare, protezione di file, non trasformabile) e l'evento del motore. Entra nella lista solo se supera almeno uno di tre criteri: evita un'azione a costo alto con un trigger deterministico, elimina turni del modello con una frequenza osservata nello storico, oppure elimina un errore ricorrente o un passo dimenticabile. Il resto finisce in appendice con il motivo dello scarto. Il report ordina le idee per priorità, con il beneficio in numeri dove lo storico lo consente e la stima del contesto liberabile.

**3. ✅ Scelta** — la lista viene proposta in una sola domanda a scelta multipla; per le idee scelte la skill chiede i dettagli necessari (formulazione della domanda di conferma, prefissi accettati, bersaglio della riscrittura). Nulla viene scritto nel plugin senza una scelta esplicita, perché il plugin è codice che gira a ogni sessione.

**4. 🔧 Implementazione e verifica** — per ogni hook scelto la skill legge i tipi dell'evento, scrive l'hook a partire dal catalogo di snippet, poi esegue `claude plugin validate`, il type-check TypeScript e una prova a runtime in sessione headless leggendo il debug log del motore. Dove l'azione vietata può arrivare anche da fuori Claude Code (cron, altri agenti), aggiunge un test alla suite del progetto.

**5. ✂️ Rimozione** — solo per le regole con hook verificato: il blocco nel `CLAUDE.md` diventa una riga che rimanda al plugin, la differenza viene mostrata prima del salvataggio e lo script `context_size.py` misura byte e token liberati. Se altri agenti leggono il file, resta una riga con il «cosa» e sparisce il «come».

---

## Contenuto della skill

**SKILL.md** — il flusso in cinque fasi, il gate di utilità e le regole per non rimuovere mai una regola prima che il suo hook sia verificato.

**references/opportunity-signals.md** — la mappa segnale → tipo → idea → beneficio, condivisa tra gli script di scansione e l'agente, con le trappole di ogni caso.

**references/rule-to-hook-catalog.md** — la tassonomia regola → evento → capacità del motore, con uno snippet pronto per ogni tipo e le trappole note (un hook che lancia un'eccezione viene saltato, `$.ui.ask` rifiuta quando il dialogo non esiste, le hotkey accettano solo cifre).

**references/plugin-setup.md** — layout del plugin, flag di attivazione, comandi di verifica e comportamento del motore che non si deduce dai tipi.

**scripts/find_rules.py** — estrattore delle regole candidate dai file di istruzioni, output JSON o tabella markdown.

**scripts/find_opportunities.py** — scansione strutturale del workspace in sola lettura: produce i segnali con evidenza (path), tipo di hook, idea e beneficio atteso.

**scripts/scan_history.py** — analisi dei transcript locali del progetto: occorrenze al mese di prompt ripetuti, comandi falliti, slash command e tool MCP, da cui derivano le idee con beneficio misurato. Se il progetto non ha ancora transcript la fase viene saltata.

**scripts/context_size.py** — misura byte, righe e token stimati di un file di istruzioni o di una sua sezione.

---

## Installazione

1. Clona la repo — `git clone https://github.com/DarioFontanel/hooks-audit.git`
2. Copia la skill nella cartella delle skill utente di Claude Code:

```bash
# macOS / Linux
cp -r hooks-audit/skills/* ~/.claude/skills/

# Windows (PowerShell)
Copy-Item -Recurse hooks-audit\skills\* $env:USERPROFILE\.claude\skills\
```

Verifica: in Claude Code digita `/hooks-audit` — la skill compare tra quelle disponibili. Funziona anche in linguaggio naturale: "quali regole del mio CLAUDE.md possono diventare hook", "libera contesto dal CLAUDE.md".

Per aggiornare: `git pull` e ri-copia.

---

## Prerequisiti

**Claude Code ≥ 2.1.263** — la prima build con i function hooks. L'API è in accesso anticipato e può cambiare tra una release e l'altra: per questo la skill genera i tipi dalla build in uso con `/plugin-types` e li tratta come unica fonte di verità.

**Flag di attivazione** — se nelle impostazioni globali hai disattivato la telemetria (`DISABLE_TELEMETRY=1` o `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1`), il rollout dei function hooks risulta spento e i plugin non vengono caricati, senza messaggi a schermo. La skill lo rileva dal debug log e ti indica di aggiungere `CLAUDE_CODE_ENABLE_FUNCTION_HOOKS=1` alla sezione `env` di `~/.claude/settings.json`.

**Node.js** — opzionale, serve al type-check con `tsc`. Senza Node la skill si affida a `claude plugin validate` e alla prova a runtime.

---

## Limiti

Un hook protegge solo le sessioni di Claude Code. Codex, cron, script e bot con configurazione isolata non eseguono plugin: per loro la skill propone un test nella suite del progetto e lascia la regola nel file di istruzioni, in forma breve. Le regole il cui trigger richiede un giudizio non diventano mai un blocco automatico: al massimo una domanda a te, con `$.ui.ask`.

---

Designed by **[Dario Fontanel, PhD](https://dariofontanel.com/)**

*Aiuto PMI italiane ad integrare l'intelligenza artificiale per automatizzare i lavori ripetitivi, abbattere i costi e guadagnare tempo per crescere.*

[![Sito](https://img.shields.io/badge/Sito-dariofontanel.com-4285F4?style=flat&logo=googlechrome&logoColor=white)](https://dariofontanel.com/)
[![YouTube](https://img.shields.io/badge/YouTube-FF0000?style=flat&logo=youtube&logoColor=white)](https://www.youtube.com/@dariofontanel)
[![Instagram](https://img.shields.io/badge/Instagram-E4405F?style=flat&logo=instagram&logoColor=white)](https://www.instagram.com/dariofontanel.ai/)
[![LinkedIn](https://img.shields.io/badge/LinkedIn-0A66C2?style=flat&logo=data%3Aimage%2Fsvg%2Bxml%3Bbase64%2CPHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHZpZXdCb3g9IjAgMCAyNCAyNCI%2BPHBhdGggZmlsbD0id2hpdGUiIGQ9Ik0yMC40NDcgMjAuNDUyaC0zLjU1NHYtNS41NjljMC0xLjMyOC0uMDI3LTMuMDM3LTEuODUyLTMuMDM3LTEuODUzIDAtMi4xMzYgMS40NDUtMi4xMzYgMi45Mzl2NS42NjdIOS4zNTFWOWgzLjQxNHYxLjU2MWguMDQ2Yy40NzctLjkgMS42MzctMS44NSAzLjM3LTEuODUgMy42MDEgMCA0LjI2NyAyLjM3IDQuMjY3IDUuNDU1djYuMjg2ek01LjMzNyA3LjQzM2MtMS4xNDQgMC0yLjA2My0uOTI2LTIuMDYzLTIuMDY1IDAtMS4xMzguOTItMi4wNjMgMi4wNjMtMi4wNjMgMS4xNCAwIDIuMDY0LjkyNSAyLjA2NCAyLjA2MyAwIDEuMTM5LS45MjUgMi4wNjUtMi4wNjQgMi4wNjV6bTEuNzgyIDEzLjAxOUgzLjU1NVY5aDMuNTY0djExLjQ1MnpNMjIuMjI1IDBIMS43NzFDLjc5MiAwIDAgLjc3NCAwIDEuNzI5djIwLjU0MkMwIDIzLjIyNy43OTIgMjQgMS43NzEgMjRoMjAuNDUxQzIzLjIgMjQgMjQgMjMuMjI3IDI0IDIyLjI3MVYxLjcyOUMyNCAuNzc0IDIzLjIgMCAyMi4yMjUgMHoiLz48L3N2Zz4%3D)](https://www.linkedin.com/in/dario-fontanel/)
[![TikTok](https://img.shields.io/badge/TikTok-000000?style=flat&logo=tiktok&logoColor=white)](https://www.tiktok.com/@dario.fontanel)
[![AI Academy](https://img.shields.io/badge/AI_Academy-E7514F?style=flat&logo=data%3Aimage%2Fsvg%2Bxml%3Bbase64%2CPHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHZpZXdCb3g9IjAgMCAyNCAyNCI%2BPHBhdGggZmlsbD0id2hpdGUiIGQ9Ik0xMiAzIDEgOWwxMSA2IDktNC45MVYxN2gyVjlMMTIgM3pNNSAxMy4xOFYxN2MwIDEuNjYgMy4xMyAzIDcgM3M3LTEuMzQgNy0zdi0zLjgybC03IDMuODItNy0zLjgyeiIvPjwvc3ZnPg%3D%3D)](https://www.skool.com/ai-academy-2306)

Licenza [MIT](./LICENSE).
