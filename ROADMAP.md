# TempleDB Roadmap

The roadmap is not in this file. It lives in two places that sit next to
the code which has to agree with them:

- **[`CLAUDE.md`](CLAUDE.md) → "Where the plan landed"** — the current
  stance, the landed tranches, and what is deferred.
- **[`README.md`](README.md) → "Roadmap / upcoming"** — the ordered list
  of what comes next.

Design work for a tranche goes in a dated report under
[`reports/`](reports/) and is linked from CLAUDE.md when it starts
shipping. Those reports carry their own phase numbering and their own
rollout tables; they are the real plan documents.

Ground truth for what is *done* is the database, not prose:

```bash
templedb summary          # ingest freshness, invariants, reconcile, hygiene
templedb doctor entities  # the 23 invariants, and which are red right now
templedb vcs log templedb # what has actually been shipping
```

## Why this file is a stub

It described a 0.6.0 cycle whose Priority 1 was "staging area
operations" — `templedb vcs add`, `vcs reset`, `vcs diff --staged` —
with branch merging held back for 0.7.0 and FTS5 search listed as
future work. All of that shipped months ago. The 1.0 checklist carried
completion marks against items that were never started, and the contact
block still said `github.com/user/templeDB`.

So the file's failure mode was not being incomplete, it was being
confidently wrong: an agent reading it cold was told that shipped
features were the top priority. A stub that points at the live plan is
strictly more useful than a detailed plan that disagrees with the
build.

The original content is in VCS history if you want it.
