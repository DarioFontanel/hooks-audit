---
name: hooks-audit
description: Audit di un workspace Claude Code per trovare cosa può diventare una function hook di un plugin — codice che gira nel motore prima del modello. Tre sorgenti: le regole scritte (CLAUDE.md, AGENTS.md, settings, skill), la struttura del workspace (file todo, segreti, file autogenerati, deploy, DB, MCP) e lo storico d'uso locale (prompt ripetuti, comandi falliti). Produce una lista di idee con beneficio misurato (turni/token risparmiati, rischi evitati), poi implementa, verifica e libera contesto dal CLAUDE.md. Triggers on /hooks-audit — o naturale come "quali regole del mio CLAUDE.md possono diventare hook", "che function hook mi convengono", "libera contesto dal CLAUDE.md", "audit degli hook", "porta questa regola nel plugin".
---

# /hooks-audit — dalle regole (e dalle abitudini) al codice nel motore

Una regola in CLAUDE.md è una **speranza**: il modello la legge, la pesa, a volte la dimentica, e intanto occupa contesto a ogni turno. Un'abitudine («capture: …», «fai commit e push», il `python` sbagliato che fallisce e riparte) è un **turno intero** speso ogni volta. Una **function hook** è codice TypeScript che gira dentro Claude Code *prima* del modello: intercetta l'evento (`tool.call`, `prompt.submit`, `ui.render`, …), può negare, chiedere all'utente, riscrivere l'input, agire senza turno. Questa skill trova ciò che merita il passaggio, lo presenta come lista di idee con beneficio misurato, implementa quelle scelte, le verifica e solo allora toglie le regole dal CLAUDE.md.

Argomenti: `$ARGUMENTS` — vuoto = audit completo del workspace corrente; `--ideas` (o `--dry-run`) = solo la lista di idee, nessuna implementazione; un path = audita solo quel file; `"<testo regola>"` = valuta e implementa una regola singola.

Reference locali (leggerle quando indicato, non tutte subito):
- `references/opportunity-signals.md` — segnale del workspace / dello storico → tipo → idea → come si misura il beneficio.
- `references/rule-to-hook-catalog.md` — tassonomia regola → evento → capacità `$`, con snippet pronti.
- `references/plugin-setup.md` — prerequisiti, layout plugin, flag, verifica, gotcha del motore.

## Fase 0 — Prerequisiti (2 minuti, bloccanti solo per implementare)

1. **Versione e flag.** `claude --version` (serve ≥ 2.1.263). Poi un run di prova headless: `claude --debug -p "ok"`, e nel debug log più recente (`~/.claude/debug/`) cerca `hooks modules`. Se compare `rollout flag (tengu_plugin_hooks_modules) is off`, aggiungi `CLAUDE_CODE_ENABLE_FUNCTION_HOOKS=1` a `env` in `~/.claude/settings.json` (succede sempre con `DISABLE_TELEMETRY=1`). Senza questo passo nessun hook girerà, in silenzio.
2. **Tipi.** Se `.claude/types/claude-code.d.ts` manca o è di una build diversa da quella corrente (prima riga del file), rigenerali con `/plugin-types .claude/types`. Se `/plugin-types` non compare nel catalogo, il flag del punto 1 non è attivo. I tipi sono **l'autorità** sull'API: non scrivere un hook a memoria.
3. **Plugin esistente?** Cerca `plugins/*/hooks/hooks.json` con chiave `modules` nel workspace e symlink in `~/.claude/skills/` che puntano a un plugin. Se esiste, i nuovi hook si aggiungono lì; altrimenti se ne crea uno (Fase 3).
4. **Altri agenti.** Se esistono `AGENTS.md`, `.agents/`, `.cursorrules`, `.github/copilot-instructions.md` o simili, il workspace è condiviso con agenti che **non eseguono plugin Claude Code**. Segnalo subito: le regole che valgono anche per loro non si possono rimuovere del tutto, solo accorciare (Fase 5).

Con `--ideas` i punti 1-2 si possono rimandare: la lista si produce comunque, e si dice all'utente cosa manca per implementare.

## Fase 1 — Raccolta da tre sorgenti

`<skill-dir>` è la cartella della skill (annunciata come «Base directory» all'invocazione); `tmp/` va tenuto fuori dal versionamento. I tre script sono stdlib, sola lettura, nulla esce dalla macchina.

**1a. Regole scritte.**
```
python3 <skill-dir>/scripts/find_rules.py --out tmp/hooks-audit/rules.json [--skip cartella1,cartella2]
```
Cerca in `CLAUDE.md` (anche annidati), `AGENTS.md`, `.claude/settings*.json` (hook `command` esistenti = candidati a migrazione), `~/.claude/settings.json`, `.claude/skills/*/SKILL.md` (solo regole trasversali), `docs/`, `context/`. Marcatori: 🔒, MAI/SEMPRE/NEVER/ALWAYS/MUST, «chiedere conferma prima di», «solo …», «usa X invece di Y», «quando l'utente scrive X → Y», «prima/dopo ogni …». Con `--skip` si escludono cartelle di deliverable o archivi che gonfierebbero il rumore.

**1b. Struttura del workspace** (idee anche senza regole scritte).
```
python3 <skill-dir>/scripts/find_opportunities.py --out tmp/hooks-audit/opportunities.json --md
```
Segnali: file todo, segreti, file autogenerati, changelog + script di rigenerazione, deploy legati al push, lockfile e interprete Python, database locali, marker di cron e code pendenti, formatter, convenzioni git, server MCP con tool distruttivi, altri agenti, peso del CLAUDE.md. Ogni segnale ha già tipo, evento, idea di partenza e beneficio atteso: la mappa è in `references/opportunity-signals.md`.

**1c. Storico d'uso** (il beneficio misurato, non presunto).
```
python3 <skill-dir>/scripts/scan_history.py --days 60 --out tmp/hooks-audit/history.json --md
```
Legge i transcript locali del progetto: prompt brevi ripetuti e prefissi `parola:` (→ D), slash command frequenti (→ G), comandi Bash che falliscono più volte con la stessa testa (→ C), passo fisso dopo `git commit` (→ E), tool MCP distruttivi già invocati (→ A/B). Riporta le occorrenze al mese. Se la cartella dei transcript non esiste, la fase si salta senza conseguenze.

**1d. Completamento a mano.** Leggi il CLAUDE.md per intero una volta: una regex non vede «il file X lo rigenera lo script Y», né le regole scritte in prosa. Aggiungi a mano ciò che manca, con la stessa scheda: `id`, `fonte:linea` (o `segnale`/`storico`), testo breve, **tipo**, **evento**, **verificabilità** (trigger deterministico? sì/no/parziale), **costo violazione** (alto: soldi, dati, invii esterni, deploy; medio: rework; basso: stile), **chi altro la legge**, **byte** in CLAUDE.md.

## Fase 2 — Classificazione, gate di utilità, lista di idee

Tassonomia (dettagli e snippet in `references/rule-to-hook-catalog.md`):

| Tipo | Esempio | Evento | Come |
|---|---|---|---|
| A. Divieto assoluto su tool | «mai cancellare email», «mai `rm -rf`», «mai `git push --force`» | `tool.call` | `{ deny }` su nome tool MCP o pattern del comando/path |
| B. Divieto con eccezione umana | «prima di un deploy chiedi», «lo script di invio si modifica solo con autorizzazione» | `tool.call` | `$.ui.ask` → deny o `next(e)`; memoria in `$.store` |
| C. Sostituzione/normalizzazione | «usa il python del venv», «pnpm non npm», «mai `--no-verify`» | `tool.call` | rewrite: `next({ ...e, command })` |
| D. Scorciatoia utente | «`Capture: X` → append al todo», «`Done: X`», «fai commit e push» → `/commit` | `prompt.submit` | `{ drop }` dopo aver agito con `$.fs`, oppure rewrite `text` |
| E. Post-azione obbligatoria | «dopo ogni commit aggiorna il changelog», «dopo Edit formatta» | `tool.call` (post: `await next(e)` poi agisci) / `turn.complete` | `$.process.run`, `$.prompt.submit` |
| F. Formato testo generato | «commit message con firma X», «PR body con footer» | `attribution.text` | `{ text }` |
| G. Stato da tenere d'occhio | «controlla il marker del cron», «coda pending», slash command frequente | `ui.render` `AbovePrompt`, `session.start` | barra sopra il prompt, `Button` con hotkey, `$.ui.notice` |
| H. Protezione file/dir | «non editare `schema.md`, è autogenerato», «mai leggere `.env`» | `tool.call` su Read/Edit/Write/Bash | deny o ask per path |
| N. Non hookabile | lingua, tono, «sii diretto», giudizi di merito, regole per runtime esterni (cron, Codex, bot headless) | — | resta in CLAUDE.md; per i runtime esterni proporre un **test** (pytest/CI) |

**Gate di utilità** — un'idea entra nella lista solo se passa almeno uno di questi tre; altrimenti va in appendice «scartate» con il motivo in una riga:
1. **Rischio**: evita un'azione a costo alto (soldi, dati, invio esterno, deploy, segreti) **e** il trigger è deterministico (nome tool, regex su comando/path). Se il trigger richiede giudizio, al massimo diventa B con `$.ui.ask`, mai un deny.
2. **Token**: elimina turni del modello con frequenza **osservata** nello storico (≥ 2 volte/mese) o dichiarata dall'utente. Beneficio = volte/mese × costo di un turno (`context_size.py CLAUDE.md` + istruzioni caricate).
3. **Rework**: elimina un errore ricorrente osservato (comando che fallisce e riparte, edit su file poi rigenerato) o un passo fisso dimenticabile (changelog, formatter).

Regole per decidere:
- **Hookabile** = trigger riconoscibile da un pattern **e** azione deterministica. «Quando sembra un duplicato» non lo è.
- **Priorità** = beneficio (rischio alto 3, token/rework misurati 2, presunti 1) × verificabilità (sì 1, parziale 0.5). Prima le A/B ad alto costo, poi le C/D con frequenza misurata, poi G/E. F e H se avanzano.
- **Contesto liberato** = byte della regola che si può togliere. Una regola letta anche da Codex libera solo la parte «come».
- Un hook **non sostituisce** la regola quando l'azione vietata può arrivare da fuori Claude Code (cron, script, altri agenti): lì la rete è un test, e la regola resta.
- Niente idee «tanto per fare»: se un segnale c'è ma non ha né rischio né frequenza né rework (es. un formatter in un repo dove il modello non tocca sorgenti), si scarta e si dice perché.

**Report** in `tmp/hooks-audit/report-YYYY-MM-DD.md` (o `plans/` se il workspace lo usa):
1. Riga di contesto: sessioni e prompt al mese analizzati, peso del CLAUDE.md in token per turno.
2. **Lista idee** ordinata per priorità, massimo 10 in evidenza, ognuna con: `#`, idea in una riga, trigger → evento, **beneficio** (numero se dallo storico: «9 volte in 60 gg ≈ 4,5 turni/mese ≈ N token»; altrimenti il rischio evitato), sforzo S/M/L, fonte (`regola CLAUDE.md:123` / `segnale todo-file` / `storico`).
3. Regole N con il motivo (una riga ciascuna).
4. Appendice: idee scartate dal gate con il motivo; il resto dei candidati oltre i 10.
5. Stima di contesto liberabile totale (`<skill-dir>/scripts/context_size.py CLAUDE.md --by-section`).

Con `--ideas`/`--dry-run` la skill finisce qui, presentando la lista in chat.

## Fase 3 — Scelta con l'utente

Presenta la lista e chiedi con **una sola domanda a scelta multipla** (AskUserQuestion o equivalente) quali idee implementare ora; poi, solo per le scelte, i dettagli: per le B la formulazione della domanda e delle due opzioni; per le D i pattern di frase accettati (prefissi, lingua); per le C il bersaglio della riscrittura (interprete, gestore). Non implementare nulla che non sia stato scelto esplicitamente: il plugin è codice che gira a ogni sessione dell'utente.

Se non esiste un plugin, proponi nome e posizione: `plugins/<nome>/` nel workspace + symlink `~/.claude/skills/<nome>` per il caricamento automatico (layout in `references/plugin-setup.md`).

## Fase 4 — Implementazione e verifica (per ogni hook scelto)

1. **Leggi i tipi** dell'evento e delle capacità `$` che userai in `.claude/types/claude-code.d.ts` (input, risultato, props). Un prop fuori allowlist invalida l'albero UI; una hotkey che non è una cifra è rifiutata; `$.ui.ask` restituisce l'etichetta scelta e rifiuta se il dialogo viene chiuso; `$.fs` non esce dalla cwd.
2. **Scrivi l'hook** nel modulo del plugin seguendo lo snippet del catalogo. Regole d'oro: ogni chiamata che può fallire in try/catch (un hook che lancia viene **saltato** = protezione zero); un dialogo chiuso vale «no»; matcher il più stretto possibile (`{ tool: 'Bash' }`, `{ component: 'AbovePrompt', surface: 'terminal' }`); pattern condiviso con eventuali test in una sola costante commentata; gli hook D controllano `$.fs.exists(file)` per non scattare in altri progetti.
3. **Verifica statica**: `claude plugin validate plugins/<nome>` (deve elencare l'hook e le chiamate `$`), poi `npx -y -p typescript@5 tsc -p plugins/<nome>/tsconfig.json` (zero output = ok).
4. **Verifica a runtime, headless**: `claude --plugin-dir ./plugins/<nome> --debug -p "<prompt che provoca l'evento>"`, poi nel debug log più recente cerca `hooks module <nome> loaded`, `<evento> settled` e assenza di `threw`/`does not validate`. In `-p` i dialoghi non esistono: `$.ui.ask` rifiuta e la B nega, che è il comportamento voluto. Per provare un deny senza rischi, usa un path o comando **innocuo che matcha il pattern**, mai il bersaglio reale. Gli hook `ui.render` si verificano solo in sessione interattiva: dillo all'utente e indicagli la riga di debug da cercare.
5. **Test di rete** dove l'azione vietata può arrivare da fuori Claude Code: aggiungi un test nella suite del progetto che fallisce se il pattern compare nel codice.

Un hook non verificato **non** autorizza la Fase 5 per la sua regola.

## Fase 5 — Rimozione dal CLAUDE.md e misura

Solo per le regole con hook verificato (le idee nate da segnali o storico non hanno nulla da rimuovere: si documentano e basta):
1. Commit di checkpoint prima di toccare CLAUDE.md, e misura: `python3 <skill-dir>/scripts/context_size.py CLAUDE.md`.
2. Sostituisci il blocco della regola con **una riga** che rimanda al plugin («🔒 … → applicata da `plugins/<nome>` (hook `tool.call`), doc in …»). Se il workspace ha altri agenti (Fase 0.4) o runtime headless che leggono CLAUDE.md, lascia il «cosa» in una riga e togli solo il «come» e le ripetizioni.
3. Mostra il diff all'utente **prima** di salvare; misura di nuovo e riporta i byte/token liberati.
4. Aggiorna la doc del plugin (tabella degli hook: evento, comportamento, regola o segnale di origine) e l'indice docs se esiste.
5. Se il workspace ha una skill di commit dedicata, usala; altrimenti suggerisci il commit.

## Output finale in chat

- Contesto analizzato: file di regole, segnali del workspace, sessioni/prompt dello storico (o «storico assente»).
- Lista idee: trovate / entrate nel gate / scartate (con motivo in una riga) / implementate / rimandate / non hookabili.
- Per ogni hook implementato: evento, cosa fa, beneficio atteso con il numero, come è stato verificato.
- Contesto liberato: prima → dopo (byte e token stimati).
- Cosa resta da vedere in sessione interattiva (barre, card) e come.
- Mai dichiarare «protetto» ciò che è solo scritto: se un hook non è stato verificato a runtime, dirlo.
