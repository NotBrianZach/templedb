# Blog Engine - TempleDB Example Project

A simple static site generator for blogs, demonstrating TempleDB file tracking and version control.

## Features

- Markdown to HTML conversion
- Template rendering (Jinja2)
- RSS feed generation
- Static asset management
- Multi-author support

## Project Structure

```
blog-engine/
├── src/
│   ├── generator.py      # Main generator
│   ├── markdown_parser.py
│   ├── template_engine.py
│   └── rss_builder.py
├── content/
│   ├── posts/            # Markdown posts
│   │   ├── 2026-01-15-welcome.md
│   │   └── 2026-02-20-templedb-intro.md
│   └── pages/            # Static pages
│       └── about.md
├── templates/
│   ├── base.html
│   ├── post.html
│   └── index.html
├── static/
│   ├── css/
│   └── images/
├── output/               # Generated site (gitignored)
├── requirements.txt
└── README.md
```

## Usage

```bash
# Generate site
python src/generator.py

# Watch for changes
python src/generator.py --watch

# Serve locally
python -m http.server 8000 --directory output
```

## TempleDB Workflow

```bash
# Import project
templedb project import /path/to/blog-engine

# Track file changes
templedb vcs status blog-engine

# Commit changes
templedb vcs commit -p blog-engine -m "Add new blog post" -a "Author Name"

# View version history
templedb vcs log blog-engine

# Query all markdown files
sqlite3 ~/.local/share/templedb/templedb.sqlite \
  "SELECT file_path, lines_of_code FROM files_with_types_view
   WHERE project_slug = 'blog-engine' AND type_name = 'markdown'"
```

## File Tracking

TempleDB tracks:
- **Markdown files** - Blog posts and pages
- **Python files** - Generator scripts
- **HTML templates** - Jinja2 templates
- **CSS/JS** - Static assets
- **Configuration** - YAML/JSON configs

## Version Control

All changes are tracked in TempleDB's database-native VCS:
- File versions stored once
- Commits reference versions
- No .git directory duplication
- SQL-queryable history

## Example Post

Create a new post in `content/posts/`:

```markdown
---
title: "Getting Started with TempleDB"
date: 2026-02-23
author: "Terry Davis Memorial Team"
tags: ["templedb", "database", "vcs"]
---

# Getting Started with TempleDB

TempleDB is a database-native project management system...

## Features

- Database-native version control
- File tracking and versioning
- Environment management
- Secrets handling

...
```

## Deployment

```bash
# Build production site
python src/generator.py --env production

# Deploy with TempleDB
templedb deploy blog-engine production \
  --output-dir ./output
```

## Environment Variables

- `BLOG_TITLE` - Blog title
- `BLOG_URL` - Production URL
- `AUTHOR_EMAIL` - Contact email

Configure with TempleDB:
```bash
templedb env add BLOG_TITLE "My TempleDB Blog"
templedb env add BLOG_URL "https://example.com"
```
