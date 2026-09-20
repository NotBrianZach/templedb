# reports/

Self-contained HTML overview documents produced by agents while working on
templedb-tracked projects. See `../CLAUDE.md` for project-level context; the
report-adding conventions live in `CLAUDE.md` next to this file.

Managed via the `templedb reports` CLI:

```
templedb reports list         -- newest-first listing
templedb reports view [q]     -- extract + open in browser
templedb reports new <title>  -- scaffold a new report
templedb reports reindex      -- regenerate index.html
```

Reports render as standalone HTML in any browser. `index.html` is a landing
page linking all reports newest-first, kept in sync by `templedb reports
reindex` (safe to run whenever).
