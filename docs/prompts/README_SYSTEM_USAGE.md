# README Cross-Reference System - Usage Guide

## Overview
The README cross-reference system helps maintain interconnected documentation across TempleDB projects. It automatically tracks README files, generates index links, finds related documentation, and verifies cross-references.

## MCP Tools Available

When using Claude Code with TempleDB MCP server, these tools are available:

### 1. `templedb_readme_scan`
**Scan a project for README files**

```typescript
templedb_readme_scan({
  project: "templedb"  // Project slug
})
```

**What it does:**
- Finds all README.md, *.md files in docs/
- Extracts title from first heading
- Extracts description from first paragraph
- Identifies sections and their anchors
- Registers everything in the database

**When to use:**
- After adding new documentation
- When initializing README tracking for a project
- Periodically to catch new documentation files

---

### 2. `templedb_readme_create`
**Create a new README with proper metadata**

```typescript
templedb_readme_create({
  project: "templedb",
  file_path: "docs/DEPLOYMENT.md",
  title: "Deployment Guide",
  content: "# Deployment Guide\n\nThis guide explains...",
  category: "deployment",  // Optional: setup, api, deployment, architecture
  topics: ["nix", "nixos", "deployment"]  // Optional: topic tags
})
```

**What it does:**
- Creates the README file with content
- Registers it in the database
- Tags it with topics for discovery
- Sets up metadata for auto-indexing

**When to use:**
- Creating new documentation from scratch
- Want automatic topic tagging and categorization
- Planning to use auto-generated indexes

---

### 3. `templedb_readme_add_topic`
**Tag a README with topics**

```typescript
templedb_readme_add_topic({
  readme_id: 42,
  topic: "nix",
  relevance: 0.9  // Optional: 0.0-1.0, defaults to 1.0
})
```

**What it does:**
- Tags README with a topic for discovery
- Sets relevance score (higher = more central to topic)
- Enables finding related docs by shared topics

**When to use:**
- After scanning existing READMEs
- To improve documentation discovery
- When topics weren't set during creation

**Common topics:**
- `nix`, `nixos`, `deployment`, `vcs`, `api`
- `setup`, `architecture`, `configuration`
- `database`, `migration`, `workflow`

---

### 4. `templedb_readme_add_reference`
**Create cross-reference between READMEs**

```typescript
// Link to another README
templedb_readme_add_reference({
  source_readme_id: 42,
  target_readme_id: 43,
  link_text: "See Deployment Guide for details",
  section: "Prerequisites"  // Optional: which section
})

// Link to external URL
templedb_readme_add_reference({
  source_readme_id: 42,
  target_url: "https://nixos.org/manual/nixos/stable/",
  link_text: "NixOS Manual",
  section: "Further Reading"
})
```

**What it does:**
- Tracks references between documentation
- Enables broken link detection
- Builds documentation network graph

**When to use:**
- When one doc references another
- Tracking external documentation links
- Building explicit relationships

---

### 5. `templedb_readme_generate_index`
**Auto-generate index section**

```typescript
templedb_readme_generate_index({
  readme_id: 42,
  template: "nix-docs"  // Optional: uses category-based default
})
```

**What it does:**
- Finds related READMEs by topic/category
- Generates markdown index section
- Inserts into README with marker comments
- Updates existing auto-generated sections

**Output example:**
```markdown
<!-- AUTO-GENERATED INDEX -->
## Related Documentation

- **[Nix Setup Guide](../NIX_SETUP.md)** - Get started with Nix development
- **[Deployment Guide](../DEPLOYMENT.md)** - Deploy with NixOps4
- **[Flake Configuration](../FLAKE_SCHEMA.md)** - Understanding flake.nix
```

**When to use:**
- Maintaining "See Also" or "Related Docs" sections
- After adding new documentation
- When documentation relationships change

---

### 6. `templedb_readme_find_related`
**Find related documentation**

```typescript
templedb_readme_find_related({
  readme_id: 42,
  limit: 10  // Optional: max results, defaults to 10
})
```

**Returns:**
```json
[
  {
    "related_readme_id": 43,
    "title": "Deployment Guide",
    "file_path": "docs/DEPLOYMENT.md",
    "project_slug": "templedb",
    "shared_topics": 3,
    "relevance_score": 0.85
  }
]
```

**What it does:**
- Finds READMEs with shared topics
- Calculates relevance based on topic overlap
- Orders by relevance score

**When to use:**
- Discovering related documentation
- Building cross-references
- Understanding documentation clusters

---

### 7. `templedb_readme_verify_links`
**Verify all README links**

```typescript
templedb_readme_verify_links({
  project: "templedb"  // Optional: scope to project
})
```

**What it does:**
- Checks all README references
- Marks broken links (target doesn't exist)
- Reports verification results
- Updates `is_broken` status

**When to use:**
- After refactoring documentation
- Periodic maintenance (weekly/monthly)
- Before releases
- CI/CD documentation validation

---

### 8. `templedb_readme_list`
**List READMEs with filters**

```typescript
templedb_readme_list({
  project: "templedb",  // Optional
  category: "deployment",  // Optional
  topic: "nix"  // Optional
})
```

**Returns:**
```json
[
  {
    "id": 42,
    "project_slug": "templedb",
    "file_path": "docs/DEPLOYMENT.md",
    "title": "Deployment Guide",
    "description": "This guide explains deployment with NixOps4",
    "category": "deployment",
    "topics": "nix, nixos, deployment",
    "auto_index": 1,
    "index_priority": 10
  }
]
```

**When to use:**
- Discovering documentation
- Auditing README coverage
- Finding docs by category/topic

---

## Common Workflows

### Workflow 1: Initialize README Tracking for Existing Project

```typescript
// 1. Scan for README files
templedb_readme_scan({ project: "myproject" })

// 2. List discovered READMEs
const readmes = templedb_readme_list({ project: "myproject" })

// 3. Add topics to each README
readmes.forEach(readme => {
  templedb_readme_add_topic({
    readme_id: readme.id,
    topic: "deployment",  // Based on content
    relevance: 0.9
  })
})

// 4. Verify links
templedb_readme_verify_links({ project: "myproject" })
```

---

### Workflow 2: Create New Documentation with Auto-Index

```typescript
// 1. Create README with topics
const content = `# Deployment Guide

This guide explains how to deploy TempleDB services with NixOps4.

## Prerequisites
...
`

templedb_readme_create({
  project: "templedb",
  file_path: "docs/DEPLOYMENT.md",
  title: "Deployment Guide",
  content: content,
  category: "deployment",
  topics: ["nix", "nixos", "deployment", "nixops4"]
})

// 2. Get the README ID from the response
const readme_id = 42  // From create response

// 3. Generate index of related docs
templedb_readme_generate_index({
  readme_id: readme_id,
  template: "deployment-docs"
})
```

---

### Workflow 3: Build Documentation Network

```typescript
// 1. Find related docs
const related = templedb_readme_find_related({
  readme_id: 42,
  limit: 5
})

// 2. Create explicit references
related.forEach(doc => {
  templedb_readme_add_reference({
    source_readme_id: 42,
    target_readme_id: doc.related_readme_id,
    link_text: `See ${doc.title}`,
    section: "Related Documentation"
  })
})

// 3. Generate updated index
templedb_readme_generate_index({ readme_id: 42 })
```

---

### Workflow 4: Documentation Maintenance

```typescript
// Weekly maintenance script

// 1. Scan for new/updated READMEs
templedb_readme_scan({ project: "templedb" })

// 2. Verify all links
const broken_links = templedb_readme_verify_links()

// 3. Regenerate indexes for affected READMEs
// (Automated based on broken link report)

// 4. Report stats
const all_readmes = templedb_readme_list()
console.log(`Total READMEs: ${all_readmes.length}`)
console.log(`Broken links: ${broken_links.length}`)
```

---

## Index Templates

Pre-configured templates for auto-generated indexes:

### `project-docs-index`
General documentation index for project root README

### `setup-guides`
Installation and configuration documentation

### `api-docs`
API and interface documentation

### `architecture-docs`
Architecture, design, and technical documentation

### Custom Templates
Create custom templates in database:

```sql
INSERT INTO readme_index_templates (
  template_name,
  heading,
  filter_category,
  filter_topic,
  format,
  max_items,
  sort_by
) VALUES (
  'nix-docs',
  'Nix Documentation',
  NULL,
  'nix',
  'bullet',
  20,
  'priority'
);
```

---

## Best Practices

### 1. **Consistent Topics**
Use standardized topic tags across all documentation:
- Core: `nix`, `deployment`, `vcs`, `api`, `database`
- Features: `workflow`, `secrets`, `environment`, `configuration`
- Tools: `nixops4`, `cathedral`, `mcp`

### 2. **Hierarchical Categories**
- `setup` - Getting started, installation
- `api` - API references, interfaces
- `deployment` - Deployment, operations
- `architecture` - Design, technical docs

### 3. **Regular Scanning**
Scan projects after:
- Adding new documentation
- Major refactoring
- Release preparation

### 4. **Link Verification**
Run verification:
- Before every release
- After documentation refactoring
- Weekly in CI/CD

### 5. **Auto-Index Sections**
Place auto-generated indexes:
- At the end of READMEs (most common)
- After specific sections using `insert_after_heading`
- Use marker comments to enable updates

---

## Troubleshooting

### "README not found"
```typescript
// Solution: Scan the project first
templedb_readme_scan({ project: "myproject" })
```

### "No related documentation found"
```typescript
// Solution: Add topics to READMEs
templedb_readme_add_topic({
  readme_id: 42,
  topic: "nix",
  relevance: 1.0
})
```

### "Index not generating"
```typescript
// Solution: Check if READMEs have shared topics
const related = templedb_readme_find_related({ readme_id: 42 })
// If empty, add topics to create relationships
```

### "Broken links not detected"
```typescript
// Solution: Run verification
templedb_readme_verify_links()
// Then check broken_readme_links view
```

---

## Database Views for Analysis

### Find broken links
```sql
SELECT * FROM broken_readme_links;
```

### Documentation network analysis
```sql
SELECT * FROM readme_reference_graph
ORDER BY total_refs DESC;
```

### Topic coverage
```sql
SELECT topic, COUNT(*) as readme_count
FROM readme_topics
GROUP BY topic
ORDER BY readme_count DESC;
```

### Most referenced documentation
```sql
SELECT * FROM readme_reference_graph
WHERE incoming_refs > 0
ORDER BY incoming_refs DESC
LIMIT 10;
```

---

## Integration with Claude Code

These tools are automatically available when using Claude Code with TempleDB MCP server enabled. Claude can:

1. **Scan projects** when adding new documentation
2. **Create READMEs** with proper structure and topics
3. **Generate indexes** to keep related docs linked
4. **Verify links** before commits
5. **Find related docs** when working on features

The system maintains documentation relationships automatically, making it easy to navigate and discover relevant documentation across your codebase.
