# Catalogo regola → function hook

Ogni voce: quando si applica, evento, snippet minimo (TypeScript/JSX, `h` come factory), trappole. Gli snippet assumono `export const register: Register = (on) => { ... }` e vanno **verificati contro i tipi generati** (`.claude/types/claude-code.d.ts`): l'API è early access.

Convenzioni comuni:

```ts
const str = (v: unknown) => (typeof v === 'string' ? v : '')

// $.ui.ask restituisce l'etichetta scelta e RIFIUTA se il dialogo viene chiuso o non esiste (-p/SDK).
async function confirm($: EngineInterface, q: string, yes: string, no: string, header?: string) {
  try { return (await $.ui.ask(q, { options: [yes, no], header })) === yes } catch { return false }
}
```

---

## A. Divieto assoluto su tool → `tool.call` + `{ deny }`

**Quando**: «mai X» dove X è un tool MCP preciso o un comando/path riconoscibile da regex. Nessuna eccezione prevista.

```ts
// Tool MCP per nome (regex sul nome)
on('tool.call', { tool: /^mcp__claude_ai_Gmail__(trash_message|trash_thread|send_message|reply|forward)$/ },
  () => ({ deny: 'Regola 🔒: nessuna cancellazione o invio Gmail da Claude. Proponi la bozza e fermati.' }))

// Comando shell per pattern
const FORBIDDEN = /\brm\s+-rf\s+\/(?!tmp)|\bgit\s+push\s+--force\b|drafts\(\)\.delete\(/
on('tool.call', { tool: 'Bash' }, ($, e, next) =>
  FORBIDDEN.test(e.command) ? { deny: 'Comando vietato dalla regola 🔒 …' } : next(e))
```

**Trappole**: il testo del deny lo legge il modello → scrivi cosa fare invece, o riproverà per altra via. I managed-settings hooks girano prima e il loro deny vince. Un deny è visivamente identico a un hook standard: va bene per la sicurezza, non per una demo.

## B. Divieto con eccezione umana → `tool.call` + `$.ui.ask`

**Quando**: «chiedi conferma prima di X», «X solo se l'utente autorizza». Il giudizio resta umano, il plugin garantisce che la domanda venga fatta.

```ts
on('tool.call', { tool: 'Bash' }, async ($, e, next) => {
  if (!/\bgit\s+push\b/.test(e.command)) return next(e)
  const cwd = await $.session.cwd()
  if (!e.command.includes('apps/site') && !/\/apps\/site(\/|$)/.test(cwd)) return next(e)   // la dir che fa deploy al push
  const ok = await confirm($, 'git push su apps/site = deploy in produzione. Confermi?', 'Push e deploy', 'Annulla', 'Deploy 🔒')
  return ok ? next(e) : { deny: 'Push annullato dall’utente: raggruppare le modifiche e richiedere.' }
})
```

Memoria dell'autorizzazione per la sessione (evita di richiedere a ogni edit):

```ts
const key = `x.authorized.${await $.session.id()}`
if (await $.store.get(key)) return next(e)
// … dopo il sì:
await $.store.set(key, true)
```

**Trappole**: `$.store` è persistente tra sessioni (file JSON sotto `~/.claude/plugins/store/`): chiavi per sessione si accumulano, accettabile; per pulizia usare `$.store.keys()` in `session.start`. In `-p` il dialogo non esiste → rifiuta → deny: giusto così.

## C. Sostituzione / normalizzazione → `tool.call` con rewrite

**Quando**: «usa sempre X al posto di Y» dove la trasformazione è meccanica (interprete, package manager, flag).

```ts
const PY = '.venv/bin/python'   // l'interprete voluto dal progetto
on('tool.call', { tool: 'Bash' }, ($, e, next) => {
  const cmd = e.command.replace(/(^|&&|\|\||;|\|)\s*python3?\b/g, (_, sep) => `${sep} ${PY}`)
  return cmd === e.command ? next(e) : next({ ...e, command: cmd })
})
```

**Trappole**: `tool` e `tool_use_id` sono riservati (un rewrite viene ignorato). Riscrivi il minimo: il modello vede nel transcript il comando originale, l'utente quello riscritto solo se lo mostri (`$.ui.log`). Non riscrivere dentro stringhe quotate se il pattern può comparire in un `grep`.

## D. Scorciatoia utente → `prompt.submit` + `{ drop }` o rewrite

**Quando**: «quando scrivo `X: …` fai Y» con Y deterministico (append a un file, lancio di uno script, apertura di una skill). Zero turno del modello, zero token.

```ts
on('prompt.submit', async ($, e, next) => {
  if (e.origin.kind === 'plugin') return next(e)          // non intercettare i prompt dei plugin
  const m = e.text.match(/^(?:capture|cattura)(\s+personal)?:\s*(.+)$/is)
  if (!m) return next(e)
  const file = m[1] ? 'TODO-personal.md' : 'TODO.md'
  try {
    const cur = await $.fs.readFile(file)
    const n = (cur.match(/^\d+\.\s/gm) ?? []).length + 1
    await $.fs.writeFile(file, cur.replace(/\s*$/, '\n') + `${n}. ${m[2].trim()}\n`)
    $.ui.toast(`✓ Todo #${n}`)
    return { drop: `Todo #${n} → ${file}` }             // il testo del drop è mostrato all'utente
  } catch { return next(e) }                              // se qualcosa manca, decide il modello
})
```

Varianti:
- **`done: X`** → trova la riga che contiene X (case-insensitive, match unico), la rimuove o la spunta, rinumera se la lista è numerata; se il match è zero o multiplo, `next(e)` e decide il modello.
- **Alias verso una skill**: «fai commit e push», «committa» → `return next({ ...e, text: '/commit' })`: il turno resta, ma il modello parte già dentro la procedura giusta.
- **Espansione**: `next({ ...e, text: espanso })`.
- Match fuzzy → lascia passare al modello (mai indovinare).

I candidati D con frequenza misurata vengono da `scripts/scan_history.py` (prompt brevi ripetuti, prefissi `parola:`); i file bersaglio da `scripts/find_opportunities.py` (`todo-file`). Mappa completa in `opportunity-signals.md`.

**Trappole**: `$.fs` lavora solo sotto la cwd della sessione → controlla `await $.fs.exists(file)` per non intercettare prompt in altri progetti. Il prompt droppato non entra nel transcript: se serve traccia, `$.ui.log`.

## E. Post-azione obbligatoria → `tool.call` post-hoc o `turn.complete`

**Quando**: «dopo ogni X fai Y» con Y meccanico (rigenerare un file, lanciare uno script).

```ts
on('tool.call', { tool: 'Bash' }, async ($, e, next) => {
  const r = await next(e)                                  // il tool ha girato
  if (!('deny' in r) && /\bgit\s+commit\b/.test(e.command) && !r.isError) {
    void $.process.run(['python3', 'scripts/update_changelog.py'])   // no shell: argv
  }
  return r                                                 // ritorna l'oggetto ricevuto (mantiene ref)
})
```

**Trappole**: ogni dispatch ha un budget → il lavoro lungo va lanciato senza `await` o spostato in `session.start` + `$.clock`. Se Y richiede giudizio (scrivere il changelog), non è E: usa `$.prompt.submit({ text: '/commit-docs' })` a fine turno (`turn.complete`) per delegare al modello *dopo*, oppure resta in CLAUDE.md.

## F. Formato dei testi git → `attribution.text`

**Quando**: «commit/PR body con firma X», «mai la riga Co-Authored-By», footer fissi.

```ts
on('attribution.text', { kind: 'commit' }, () => ({ text: 'Co-Authored-By: …' }))
on('attribution.text', { kind: 'pr' }, () => ({ text: '🤖 Generated with …' }))
```

## G. Stato da tenere d'occhio → `ui.render` `AbovePrompt` / `session.start`

**Quando**: «ricordati di controllare X», «se il cron non ha girato avvisami», code pendenti.

```tsx
let state: { pending: number } | null = null
on('session.start', async ($, e, next) => {
  if (e.interactive && e.surface === 'terminal') {
    try { state = { pending: (await $.fs.readFile('docs/INBOX.md')).match(/^- \[ \]/gm)?.length ?? 0 } } catch {}
    $.ui.invalidate('ui.render')
  }
  return next(e)
})
on('ui.render', { component: 'AbovePrompt', surface: 'terminal' }, async ($, e, next) => {
  if (!state || e.props.hasSurvey) return next(e)
  const { Box, Text, Button } = await $.ui.resolve(e)
  return (
    <Box flexDirection="row" gap={2} paddingX={1}>
      <Text color={state.pending ? 'yellow' : 'green'}>{`Pending: ${state.pending}`}</Text>
      <Button hotkey="1" label="Smaltisci" onPress={() => void $.prompt.submit({ text: '/pending' })} />
    </Box>
  )
})
```

**Trappole**: hotkey **solo cifre**; figli di `Text` solo stringhe (niente numeri nudi); un prop fuori allowlist (`BoxProps`/`TextProps` nei tipi) invalida **tutto** l'albero e il motore disegna il suo (riga `ui.render (AbovePrompt): a hook returned a tree that does not validate` nel debug log). Il collasso della band è nativo (`ctrl+x ctrl+a`). Refresh = `$.clock.every` + `$.ui.invalidate('ui.render')`, max 10/s.

## H. Protezione file / dir → `tool.call` su Read/Edit/Write/Bash

**Quando**: «non editare a mano X, è autogenerato», «mai toccare `.env`», e i segnali `secrets`/`autogenerated` di `find_opportunities.py` anche senza regola scritta.

```ts
const PROTECTED = /(^|\/)(docs\/schema\.md|\.env)$/
on('tool.call', { tool: ['Edit', 'Write'] }, ($, e, next) =>
  PROTECTED.test(str(e.file_path)) ? { deny: 'File autogenerato/protetto: modifica la sorgente (…) e rigenera.' } : next(e))
```

Per Bash: stesso path nel comando **e** un indicatore di scrittura (`sed -i`, `>`, `>>`, `tee`, heredoc). Per un blocco «a sezioni» (il tree dentro CLAUDE.md), controlla `old_string`/`new_string` contro i marker della sezione.

Segreti (lettura, non solo scrittura):

```ts
const SECRET = /(^|\/)(\.env(\..+)?|\.secrets\/.*|.*credentials.*\.json|.*\.pem)$/
on('tool.call', { tool: 'Read' }, ($, e, next) =>
  SECRET.test(str(e.file_path)) ? { deny: "File di segreti: leggi solo i NOMI delle variabili con `grep -o '^[A-Z_]*=' .env`." } : next(e))
on('tool.call', { tool: 'Bash' }, ($, e, next) =>
  /\b(cat|less|sed|awk|head|tail|bat)\b[^|;&]*\.env\b(?!\.example)/.test(e.command) ? { deny: 'Non stampare .env: solo i nomi delle variabili.' } : next(e))
```

Lasciare passare i `.example`; il modello deve poter verificare che una chiave esista (nome sì, valore no).

## N. Non hookabile (resta in CLAUDE.md)

- Lingua, tono, «sii diretto», «celebra i progressi»: sono istruzioni al modello, non eventi.
- Giudizi di merito («se sembra superata dillo», «proponi la soluzione più semplice»).
- Regole per runtime che non eseguono plugin: cron, script, Codex, bot headless con config isolata. Rete possibile: **test** (pytest/CI) che fallisce se il pattern vietato compare nel codice, oppure hook standard `settings.json` se il runtime li onora.
- Regole il cui trigger è ambiguo o semantico: al massimo diventano B con la domanda all'umano, mai un deny automatico.

## Mappa rapida dei nouns di `$` (dai tipi 2.1.263)

`ui{ask,toast,status,log,notice,invalidate,resolve}` · `model{complete,fork,classify}` · `prompt{submit}` · `tool{list,call,register}` · `agent{spawn,list}` · `mcp{call}` · `session{messages,cwd,model,turnCount,id,repo,surface}` · `turn{abort}` · `fs{readFile,writeFile,listDir,exists,stat,ancestors}` (solo sotto cwd) · `store{get,set,delete,keys}` (persistente) · `clock{now,sleep,after,every}` · `http{fetch}` · `process{run(argv)}` (no shell) · `audio{play,speak}`.

Eventi: `tool.call`, `tool.describe`, `prompt.submit`, `prompt.section`, `prompt.context`, `skill.prompt`, `attribution.text`, `session.start`, `turn.start|step|complete`, `engine.create`, `agent.offer`, `agent.spawn`, `ui.render`, `ui.resolve`, `ui.press`, `ui.input`, `ui.select`.
