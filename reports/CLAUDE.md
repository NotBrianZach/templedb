# CLAUDE.md — reports/

Reports are **rows in the `reports` table**, not files in this directory.
This file is the only thing left in it.

## Creating one

```bash
templedb reports new "Your title"                 # markdown, templedb
templedb reports new "Your title" --project bza   # any project
templedb reports new "Your title" --html          # self-contained HTML
templedb reports edit <project>/<slug>            # $EDITOR, writes back
```

`new` prints the slug and the GUI path. There is no filename to compute
and no `reindex` step — the listing at `/reports` is a SELECT.

## The shape of a row

| Column | Notes |
|---|---|
| `slug` | stable id, unique per project. No date, no extension. |
| `title` | a column, not a `<title>` tag to be parsed |
| `lede` | one-paragraph summary for the index. Re-derived on `edit`. |
| `body` | the document, as authored |
| `format` | `markdown` or `html`. Decides rendering. |
| `created_at` | a real timestamp |
| `supersedes_id` | when a report replaces an earlier one |
| `legacy_path` | the file it was migrated from. A forwarding address, not an id. |

## Markdown or HTML

**Markdown is the default and is usually right.** The GUI renders it with
a small stdlib renderer in `gui_pages/reports.py` — headings, paragraphs,
fenced code, tables, blockquotes, lists, inline emphasis and links. The
page chrome supplies the `<h1>` and the lede, so do not repeat the title
as a heading in the body.

**`--html` is for a document that needs its own layout.** It is served
exactly as authored, so it must be self-contained: inline the CSS in a
`<style>` block, no external files, no images fetched from elsewhere. The
invariant is "one document, one browser tab, no missing dependencies" —
that is a property of the document and it survives the move to rows.

## Why this changed

Reports were HTML files found by the glob
`reports/[0-9][0-9][0-9][0-9]-*.html`. The bytes were always in SQLite —
a report is a tracked project file — but the *model* was the filesystem,
and every awkwardness came from that:

- a markdown report was invisible, because the glob ends in `.html`. Two
  bza reports existed for weeks while `/reports?project=bza` rendered
  "No reports";
- the date lived in the filename, so the convention grew an `HHMM` to
  order same-day reports, and this file used to say *"don't rename older
  files just to add time"* — because the filename was the primary key;
- the title and lede were regexes over the document's own markup, so a
  report that styled its opening differently had no index summary, and
  one with no `<title>` listed as "(untitled)";
- `reports new` hardcoded `REPORT_PROJECT = "templedb"`, so a report
  about any other project had to be hand-written with `file set`;
- `reindex` existed at all because `index.html` was a generated artifact
  that could disagree with the directory it described.

Migration 143 moved them. See `migrations/143_reports.sql`.

## Old links still work

The 72 migrated reports keep their `legacy_path`, and `/reports/<old
dated filename>.html` still resolves — in both the bare and
`<project>/<filename>` forms, since the old index emitted the second one.
Those URLs are in published commit messages and inside other reports.

`report_implementations.report_path` is also still populated, alongside a
new `report_id`, so `templedb provenance report <path>` keeps working.
