# Temple Agent: the Emacs integration

How Claude runs *inside* Emacs as a native Org buffer rather than a terminal
pane, what each moving part is responsible for, and the workflows the design
is actually built around.

Written 2026-10-01 against `integrations/emacs/templedb-agent.el` (3080
lines) and `src/agent/`. Line numbers are indicative; the structure is the
durable part.

---

## 1. The one-sentence version

A `templedb` subprocess speaks JSON-lines over stdio to Emacs; Emacs renders
the conversation as an Org document whose sections are individually owned by
either you or the agent; and the agent can write back into that document
mid-run through MCP tools that cross a process boundary via a database
table.

The last clause is the only genuinely surprising part of the design. See §5.

---

## 2. Architecture

Four processes, not two:

```
┌─ Emacs ─────────────────────────────────────────────────────┐
│  templedb-agent.el — Org buffer, ewoc, section anchors      │
└───────────────┬─────────────────────────────────────────────┘
                │  JSON-lines over stdio (one object per line)
┌───────────────▼─────────────────────────────────────────────┐
│  templedb ai agent serve --stdio                            │
│    src/agent/protocol.py   ProtocolServer   — framing       │
│    src/agent/service.py    AgentService     — orchestration │
│    src/agent/store.py      AgentStore       — single writer │
└───────────────┬─────────────────────────────────────────────┘
                │  spawns
┌───────────────▼─────────────────────────────────────────────┐
│  claude (Claude Code CLI)   src/agent/providers/claude_code │
└───────────────┬─────────────────────────────────────────────┘
                │  MCP (stdio)
┌───────────────▼─────────────────────────────────────────────┐
│  templedb MCP server — src/mcp_server.py, 22 tools          │
└─────────────────────────────────────────────────────────────┘
```

Responsibilities:

| Layer | Owns |
|---|---|
| `templedb-agent.el` | All rendering. Holds no authoritative state — the buffer is rebuilt from the DB on `, g`. |
| `protocol.py` | Line framing, request/response ids, thread-safe writes. Methods: `session.create/open/list/close`, `message.send`, `run.cancel/resume`, `events.since`, `notes.get/set`, `provider.doctor`. |
| `service.py` | Session and run lifecycle, provider dispatch, streaming with batched writes (`FLUSH_INTERVAL = 0.25`), crash recovery. |
| `store.py` | Every agent-table mutation. Single-writer by convention, with `_retry_on_lock` exponential backoff so a GUI or CLI write lock doesn't kill a session. |
| `providers/` | Normalising provider-specific output into the event vocabulary in `events.py`. `fake.py` exists so the stack is testable without burning tokens. |

The provider abstraction is real, not aspirational: `events.py` defines a
closed vocabulary (`ALL_TYPES`) that providers must map into, so Emacs never
sees a Claude-shaped payload.

---

## 3. The Org buffer is the interface

A session renders as one Org document. Sections are not decoration — each has
a distinct owner and lifecycle.

**Yours to edit:**

| Section | Role |
|---|---|
| `Goal` | Sent to Claude with *every* message. The anti-drift mechanism. |
| `Next Prompt` | Your message. `C-c C-c` sends and clears it. |
| `Notes` | Persisted to the DB on run completion (`--save-notes-to-db`). |
| `Scratch` | Never sent. Genuinely local. |

**Agent-owned, written mid-run:**

| Section | Written by |
|---|---|
| `Findings` | `templedb_agent_note_finding` |
| `Todo` | `templedb_agent_todo_add` / `_todo_done` |
| `Open Questions` | `templedb_agent_question_add` / `_question_answered` |
| `dynamic:*` | `templedb_agent_section_write` — arbitrary named sections |

**Neither:**

| Section | Note |
|---|---|
| `Now` | Live status line. What Claude is doing *right now*. |
| `Context` | The context basket (§6). Toggled, not typed. |
| `Conversation` | Exclusively owned by an ewoc. The source warns that nothing may `insert` between that anchor and `Next Prompt` — all edits go through ewoc mutations. |

Sections are located by **text-property anchors**, not by regex. The old
`templedb-agent--section-heading-regex` is still present but explicitly
marked `DEPRECATED ... kept only for legacy callers`. If you extend this,
use the anchor API — regex matching breaks the moment a tool result contains
a line starting with `* `.

### Reading the markers

| Marker | Where | Meaning |
|---|---|---|
| `- [ ]` / `- [X]` | Todo | Open vs done |
| `~low~` `~medium~` `~high~` | Todo | Priority |
| `[?]` / `[✓]` | Open Questions | Answered entries show `→ <answer>` inline |
| `[3t · 2.4s]` | Conversation heading | Tools used · duration. Gains a fail slot: `[3t/1f · 2.4s]` |
| `[F:n T:n Q:n D:n]` | modeline | Open counts; empty categories elided |
| brief highlight | any agent entry | Fresh-write fade on newly appended entries |

The modeline counter is the quiet win: you can see the agent has logged
three findings without unfolding anything.

---

## 4. The event model

Events flow provider → service → Emacs, where `--handle-event` dispatches on
a `pcase`. The vocabulary:

- **Run:** `run.started` / `.completed` / `.failed` / `.interrupted`
- **Assistant:** `assistant.started` / `.delta` / `.completed` — `.delta`
  drives incremental rendering
- **Tool:** `tool.started` / `.completed` / `.failed` — rendered as
  collapsible rich blocks that mutate in place from `RUNNING` to
  `DONE`/`FAILED`
- **Provider:** `provider.rate_limited`, `provider.login_required` — the
  latter surfaces `Run: claude auth login` rather than a stack trace
- **Agent-to-user:** `agent.ask.question`, `agent.message`,
  `agent.section.*`, `agent.exchange.suggestions.write`

Streaming is batched at 250ms rather than per-token, which is why the buffer
stays responsive during long outputs.

---

## 5. The MCP bridge — the non-obvious part

When Claude calls `templedb_agent_note_finding`, that tool executes in the
**MCP server process**, which is a child of the `claude` subprocess — not in
`AgentService`. It therefore has no access to the event callback that would
push a line to Emacs.

The solution is a database-backed queue:

```
MCP tool handler  ──writes row──▶  agent_pending_events   (migration 084)
                                   agent_pending_asks     (migration 080)
                                            │
AgentService._ask_poll_loop  ──polls 300ms──┘
                                            │
                                     re-emits as events
                                            │
                                            ▼
                                          Emacs
```

`_ask_poll_loop` (`service.py:546`) handles both transports in one thread
rather than two per session, and marks rows dispatched so they fire once.

The two tables differ in direction:

- `agent_pending_events` — **one-way**. Fire and forget (findings, todos).
- `agent_pending_asks` — **round-trip**. `templedb_ask_user` blocks until the
  human answers in Emacs; the answer travels back by `ask_id`.

This is why the agent can populate `Findings` *while still working*, instead
of dumping everything in a final message. It is also why a stale
`ai agent serve` process is harmful: two pollers will race the same rows.

---

## 6. The context basket

Rather than re-pasting files, `Context` is a declarative set assembled per
message by `--build-context-payload`. Toggleable items (`context.py`):

| Item | Default |
|---|---|
| Project prompt (rules, workflow, MCP tools) | on |
| Recent commits | on |
| Full file tree | off |
| Language breakdown | off |
| Environment | off |
| Selected files (contents) | off |

Add to it with `, x a` (project), `, x f` (file picker), `, x b` (current
buffer), `, x v` (region). Toggle with `, x t`.

`_resolve_cwd` sets the provider subprocess's working directory to the first
project in the basket, so the right `CLAUDE.md` autoloads. The basket is
therefore not only *what Claude is told* but *where Claude stands*.

---

## 7. Keybindings

**Anywhere:**

| Key | Action |
|---|---|
| `SPC a T A n` | New session |
| `SPC a T A o` | Open session by id |
| `SPC a T A l` | List sessions |
| `SPC a T A ?` | Ask about symbol at point |
| `SPC a T A L` | Work log |
| `SPC a T A d` | Doctor (provider health) |

**In the agent buffer** — `C-c` chords and `,` major-mode leader:

| Key | Action |
|---|---|
| `C-c C-c` | Send |
| `C-c C-k` | Cancel run |
| `C-c C-r` | Resume interrupted run |
| `C-c C-q` | Close session |
| `C-c C-s` | Save user-owned sections |
| `C-c C-l` | Reload from checkout |
| `C-c u` | Remove agent entry at point |
| `, i` | Send guidance *while Claude works* |
| `, g` | Refresh buffer from DB |
| `, x a/r/t/l/f/b/v` | Context: add/remove project, toggle, list, add file/buffer/region |
| `, s n/s/l/f/q` | Session: new/switch/list/fork/close |
| `, /` | Slash command (`/compact`, `/review`, `/cost`) |
| `, P` | Plan mode (read-only) |
| `, M` | Model (sonnet/opus/haiku) |
| `, p` | Permission mode |
| `, ?` | Debug: process, stderr, pending |
| `, K` | Kill stuck process |

`, i` is worth internalising — mid-run steering without cancelling is the
main ergonomic advantage over a terminal.

---

## 8. Workflows

### Code review with durable output
`SPC a T A n` → add project (`, x a`) → set `Goal` to the review criteria →
ask for the review. Findings accumulate in `Findings` as they're discovered
rather than arriving as one wall of text. The modeline shows `[F:7]`. Each
finding survives buffer refresh because it is DB-backed.

### "What is this?" from a code buffer
Point at a symbol, `SPC a T A ?`. The symbol and surrounding context go to a
session without leaving the file.

### Long investigation with handoff
Work the problem; the agent files `Findings` and `Open Questions` as it goes.
`Notes` persists your own commentary to the DB. Later, `, s s` back into the
session: the buffer rebuilds from stored events, and the open-question count
tells you where you stopped.

### Branching an approach
`, s f` forks the session — explore a risky refactor without losing the
conversation that got you there.

### Read-only reconnaissance
`, P` (plan mode) before pointing the agent at something you do not want
edited. Permission mode defaults to `bypassPermissions`, so this is a
deliberate narrowing, not a default.

### Cost and context control
`, /` → `/compact` when the conversation grows; `/cost` to check spend.

---

## 9. Operational notes

### Never `kill` an `ai agent serve` PID
Use `templedb ai agent stop-stale [--dry-run]`. The source documents why
(`agent.py:297`): an agent asked "is the DB locked?" once identified three
concurrent agent servers and killed two — including its own parent. The
command excludes the current process's ancestor chain via
`TEMPLEDB_AGENT_SERVER_PID`.

### Session identity
Agent work spanning multiple shells needs a stable session, or `vcs add` in
one call and `vcs commit` in the next land in different sessions. Export
`TEMPLEDB_SESSION=<name>`. `vcs commit` detects the scattered case and prints
this advice.

### When it hangs
`, ?` first — it reports the process state, stderr tail, and pending items.
`, K` only after.

### ⚠ The layer is a composite, and one of its inputs is a stale fork

`~/.emacs.d/private/local-layers/templedb` symlinks to a nix-store
`templedb-spacemacs-layer` assembled from **both** projects. Verified
file-by-file 2026-10-01:

| Layer file | Sourced from | Status |
|---|---|---|
| `packages.el` | `system_config` | identical — this is where leader keys live |
| `local/templedb/templedb.el` | `system_config` | identical |
| `local/templedb-agent/templedb-agent.el` | **`templedb`** (3080 lines) | identical to `integrations/emacs/` |

So `system_config` supplies the layer scaffolding, but the agent client
itself comes from the templedb flake.

That matters because `system_config` *also* contains a copy of the agent
client, at
`emacs.d/layers/templedb/local/templedb-agent/templedb-agent.el` — 1781
lines, shadowed, **not loaded**. It predates agent-writable sections
entirely: zero `agent.section.*` cases in its `pcase` (the live copy has
21), and its section regex lists only
`Guide|Now|Goal|Context|Conversation|Next Prompt|Pinned|Notes|Scratch`. It
still has a `Pinned` section and a `, .` pin command, both of which the live
copy has dropped (`grep -c Pinned` → 0).

Reading it to understand current behaviour will mislead you — it is the
reason this document exists in `templedb/docs/` rather than alongside it.
Deleting it is a separate change, since the surrounding layer directory *is*
still used.

---

## 10. Where to look

| Question | File |
|---|---|
| Protocol methods | `src/agent/protocol.py` |
| Session/run lifecycle, recovery, the poll loop | `src/agent/service.py` |
| Any DB write | `src/agent/store.py` |
| Event vocabulary | `src/agent/events.py` |
| Context basket items | `src/agent/context.py` |
| Adding a provider | `src/agent/providers/base.py` |
| MCP tools | `src/mcp_server.py` |
| Buffer rendering, keymaps | `integrations/emacs/templedb-agent.el` |
| Leader keys | `system_config/emacs.d/layers/templedb/packages.el` |
| Web views of the same data | `src/gui_pages/agent_{sections,sessions,work_log}.py` |
