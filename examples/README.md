# TempleDB Example Projects

This directory contains example projects demonstrating TempleDB's capabilities.

## Examples Overview

### 1. Todo API (`todo-api/`)
**Type**: REST API
**Language**: JavaScript (Node.js/Express)
**Demonstrates**:
- File tracking (JavaScript, JSON)
- Environment variable management
- Secret handling (API keys)
- Deployment configuration

**Quick Start**:
```bash
templedb project import examples/todo-api
templedb env detect todo-api
templedb env new todo-api dev
templedb env enter todo-api dev
```

---

### 2. Blog Engine (`blog-engine/`)
**Type**: Static Site Generator
**Language**: Python
**Demonstrates**:
- File tracking (Python, Markdown, HTML templates)
- Version control (commit posts, track changes)
- SQL queries (find all markdown files)
- File history tracking

**Quick Start**:
```bash
templedb project import examples/blog-engine
templedb vcs status blog-engine
python examples/blog-engine/src/generator.py
```

---

### 3. Data Pipeline (`data-pipeline/`)
**Type**: ETL Pipeline
**Language**: Python
**Demonstrates**:
- File tracking (Python, SQL)
- Environment isolation
- Secret management (API keys, connection strings)
- SQL query tracking
- Deployment automation

**Quick Start**:
```bash
templedb project import examples/data-pipeline
templedb env detect data-pipeline
./prompt_missing_vars.sh data-pipeline dev
python examples/data-pipeline/src/pipeline.py
```

---

## Using Example Projects

### Initialize Database with Examples

```bash
# Run the initialization script
./init_example_database.sh

# This will:
# 1. Create a fresh TempleDB database
# 2. Import all example projects
# 3. Setup file tracking
```

### Explore with TempleDB

```bash
# List all projects
templedb project list

# View project files
templedb tui

# Query with SQL
sqlite3 ~/.local/share/templedb/templedb.sqlite \
  "SELECT project_slug, type_name, COUNT(*) as file_count
   FROM files_with_types_view
   GROUP BY project_slug, type_name
   ORDER BY project_slug, file_count DESC"
```

### Version Control

```bash
# Check status
templedb vcs status todo-api

# Make changes to files
echo "// New feature" >> examples/todo-api/src/server.js

# Commit changes
templedb project sync todo-api
templedb vcs commit -p todo-api \
  -m "Add new feature" \
  -a "Your Name"

# View history
templedb vcs log todo-api -n 10
```

### Environment Management

```bash
# Auto-detect dependencies
templedb env detect blog-engine

# Create environment
templedb env new blog-engine dev

# Enter isolated environment
templedb env enter blog-engine dev

# Inside environment:
pip install -r requirements.txt
python src/generator.py
```

### Secrets Management

```bash
# Initialize secrets
templedb secret init data-pipeline --age-recipient <your-age-key>

# Interactive variable prompting
./prompt_missing_vars.sh data-pipeline dev

# Export secrets to environment
eval "$(templedb secret export data-pipeline --format shell)"
```

---

## Learning Path

### Beginner: Todo API
Start here to learn:
- Basic project import
- File tracking
- Environment variables
- Running projects in TempleDB

### Intermediate: Blog Engine
Next, explore:
- Version control
- File history tracking
- SQL queries
- Content management

### Advanced: Data Pipeline
Finally, master:
- Complex environments
- Secret management
- Multi-stage workflows
- Deployment automation

---

## Common Workflows

### 1. Import and Explore

```bash
# Import
templedb project import examples/todo-api

# Explore files
sqlite3 ~/.local/share/templedb/templedb.sqlite \
  "SELECT file_path, type_name, lines_of_code
   FROM files_with_types_view
   WHERE project_slug = 'todo-api'"
```

### 2. Make Changes and Commit

```bash
# Edit a file
vim examples/todo-api/src/server.js

# Sync changes
templedb project sync todo-api

# Commit
templedb vcs commit -p todo-api -m "Update API" -a "Developer"
```

### 3. Setup Environment

```bash
# Detect dependencies
templedb env detect blog-engine

# Create environment
templedb env new blog-engine dev

# Enter and work
templedb env enter blog-engine dev
pip install -r requirements.txt
python src/generator.py
exit
```

### 4. Query Everything

```bash
# All JavaScript files
sqlite3 ~/.local/share/templedb/templedb.sqlite \
  "SELECT * FROM files_with_types_view
   WHERE type_name = 'javascript'"

# Project statistics
sqlite3 ~/.local/share/templedb/templedb.sqlite \
  "SELECT
     project_slug,
     COUNT(*) as files,
     SUM(lines_of_code) as total_lines
   FROM files_with_types_view
   GROUP BY project_slug"

# Commit history
sqlite3 ~/.local/share/templedb/templedb.sqlite \
  "SELECT * FROM vcs_commit_history_view
   WHERE project_slug = 'todo-api'
   ORDER BY created_at DESC"
```

---

## Modifying Examples

Feel free to modify these examples:

1. **Add new features** to todo-api
2. **Write new blog posts** in blog-engine
3. **Add pipeline stages** to data-pipeline

All changes will be tracked by TempleDB!

---

## Creating Your Own Project

Use these examples as templates:

```bash
# Copy an example
cp -r examples/todo-api ~/my-new-api

# Customize it
cd ~/my-new-api
# ... make your changes ...

# Import to TempleDB
templedb project import ~/my-new-api
```

---

## Troubleshooting

### Project not found
```bash
# Re-import
templedb project import examples/todo-api todo-api
```

### Environment issues
```bash
# Regenerate environment
templedb env detect todo-api
templedb env generate todo-api dev
```

### Database reset
```bash
# Start fresh
./init_example_database.sh
```

---

## Documentation

Each example has its own README with detailed documentation:
- `todo-api/README.md`
- `blog-engine/README.md`
- `data-pipeline/README.md`

See also:
- [TempleDB README](../README.md)
- [Quickstart Guide](../QUICKSTART.md)
- [Workflow Guide](../WORKFLOW.md)

---

**Happy coding with TempleDB!**

*"God's temple is everything."* - Terry A. Davis
