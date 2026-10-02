-- Migration 121: drop the README cross-reference index.
--
-- readme_files / readme_topics / readme_sections and the
-- readme_files_with_topics view were a derived index over markdown in
-- project_files. Nothing writes them and, as of the commits that made
-- /docs and the project Docs tab parse content_blobs directly, nothing
-- reads them either.
--
-- They are dropped rather than left dormant because a derived table
-- with no refresh path does not sit still -- it lies. The only writer
-- was scripts/dogfood_readme_system.py, a one-off with no CLI command
-- wired to it. It ran once on 2026-04-05 and never again, so every one
-- of the 117 rows still carried that last_scanned_at while docs/ had
-- grown to 132 files in templedb alone. The /docs page confidently
-- listed a six-month-old subset, which is worse than listing nothing,
-- because nothing looks broken.
--
-- Re-running the scanner was not a fix either: it opens
-- sqlite3.connect() without PRAGMA foreign_keys=ON, so its
-- INSERT OR REPLACE on readme_files never fires the ON DELETE CASCADE
-- that would clear readme_sections. A second run would have left 7282
-- orphaned section rows and added a duplicate set. The index was clean
-- only because it had run exactly once.
--
-- Note the script also writes readme_references, which migration 074
-- already dropped as unused -- so it has been partly broken since then.
-- It is left in the tree as history; it has no remaining caller.
--
-- Nothing of value is lost. Title, description, headings, word count
-- and TOC flag are now derived from the committed bytes at request
-- time in gui_helpers._parse_markdown, which cannot go stale. The one
-- thing not carried over is the inferred `topic` and `category`
-- regexes; category is now the directory the file lives in, which is
-- both cheaper and something a reader can act on.
--
-- Views first: dropping a table out from under a view leaves the view
-- defined but unresolvable, and SQLite will not complain until someone
-- queries it.

DROP VIEW  IF EXISTS readme_files_with_topics;

DROP TABLE IF EXISTS readme_sections;
DROP TABLE IF EXISTS readme_topics;
DROP TABLE IF EXISTS readme_files;
