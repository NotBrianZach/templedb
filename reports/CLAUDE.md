# CLAUDE.md — reports/

Convention for adding reports to `reports/` inside the templedb project.

## Filename

`reports/YYYY-MM-DD-HHMM-kebab-title.html`

Date is today. Time is 24h HHMM (local), so multiple reports the same
day sort naturally and stay visually distinguishable in the GUI list.
Title ≤ ~8 words. Prefer `templedb reports new "Your title"` — it
computes the filename (including current time), drops the standard
template, and refuses to overwrite.

Reports from before this convention landed use the shorter
`YYYY-MM-DD-kebab-title.html` form; both are still parsed correctly.
Don't rename older files just to add time — links live in commit
messages and other reports.

## Self-contained

One HTML file per report. Inline CSS in a `<style>` block in `<head>`. Do
NOT extract shared CSS or images into separate files — the invariant is
"one HTML file, one browser tab, no missing dependencies." Making reports
emailable and pastable is worth some duplication of the style block.

## Structural expectations

Every report should have:

- `<title>…</title>` — the report title, matches the `<h1>`
- `<h1>…</h1>` — visible title
- `<p class="lede">…</p>` — one-paragraph summary; `templedb reports
  reindex` picks this up for the index listing

Everything else is up to the report.

## After adding a report

```
templedb reports reindex   # regenerate index.html
templedb vcs add -p templedb reports/<new file> index.html
templedb vcs commit -p templedb -m "reports: <title>"
```

## Not for

- Ephemeral scratch — use `/tmp/`.
- Machine-readable data — this is for humans reading in a browser.
- Living wiki-style documentation — reports are snapshots. If a doc needs
  to evolve over time, it belongs in the project it documents (or in
  templedb's top-level `docs/`).
- Session recap / metacognition reports — those go here too, tagged
  `session-recap` in the title so the index makes them findable.
