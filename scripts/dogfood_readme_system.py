#!/usr/bin/env python3
"""
Dogfood the README cross-reference system by indexing TempleDB's own documentation.

This script:
1. Scans all markdown files in docs/
2. Extracts metadata (title, description, sections)
3. Infers topics from content and file paths
4. Detects cross-references between docs
5. Populates the README database tables
"""

import sys
import re
import sqlite3
from pathlib import Path
from typing import List, Dict, Tuple, Optional

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from config import DB_PATH, PROJECT_ROOT

# Topic inference patterns
TOPIC_PATTERNS = {
    'nix': r'\b(nix|nixos|nixpkgs|flake|derivation)\b',
    'deployment': r'\b(deploy|deployment|nixops|infrastructure)\b',
    'vcs': r'\b(vcs|version control|commit|branch|staging)\b',
    'api': r'\b(api|endpoint|interface|rest|http)\b',
    'database': r'\b(database|sql|sqlite|schema|migration)\b',
    'security': r'\b(security|secret|yubikey|encryption|key)\b',
    'workflow': r'\b(workflow|orchestration|task|execution)\b',
    'architecture': r'\b(architecture|design|pattern|component)\b',
    'configuration': r'\b(config|configuration|environment|settings)\b',
    'migration': r'\b(migration|upgrade|version)\b',
    'mcp': r'\b(mcp|model context protocol|claude code)\b',
    'cathedral': r'\b(cathedral|package|export|import)\b',
}

# Category inference from path/content
CATEGORY_PATTERNS = {
    'setup': r'(setup|installation|getting started|quickstart)',
    'api': r'(api|reference|interface)',
    'deployment': r'(deploy|deployment|operations)',
    'architecture': r'(architecture|design|technical)',
}


class READMEIndexer:
    """Index TempleDB documentation into README system"""

    def __init__(self, db_path: str, project_root: Path):
        self.db_path = db_path
        self.project_root = project_root
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self.cursor = self.conn.cursor()

        # Get or create templedb project
        self.project_id = self._get_project_id()

        # Track readme_id by file_path for cross-references
        self.readme_ids = {}

    def _get_project_id(self) -> int:
        """Get TempleDB project ID"""
        self.cursor.execute("SELECT id FROM projects WHERE slug = 'templedb'")
        row = self.cursor.fetchone()
        if row:
            return row[0]
        raise Exception("TempleDB project not found. Run: templedb project import .")

    def scan_markdown_files(self) -> List[Path]:
        """Find all markdown files in docs/"""
        docs_dir = self.project_root / "docs"
        md_files = list(docs_dir.rglob("*.md"))
        print(f"📁 Found {len(md_files)} markdown files")
        return md_files

    def extract_metadata(self, file_path: Path) -> Dict:
        """Extract title, description, and sections from markdown"""
        content = file_path.read_text()

        # Extract title (first # heading)
        title_match = re.search(r'^#\s+(.+)$', content, re.MULTILINE)
        title = title_match.group(1) if title_match else file_path.stem

        # Extract description (first paragraph after title)
        desc_match = re.search(r'^#.+?\n\n(.+?)(\n\n|\n#)', content, re.MULTILINE | re.DOTALL)
        description = desc_match.group(1).strip()[:500] if desc_match else ""

        # Extract sections
        sections = []
        for match in re.finditer(r'^(#{1,6})\s+(.+)$', content, re.MULTILINE):
            level = len(match.group(1))
            heading = match.group(2)
            anchor = heading.lower().replace(' ', '-').replace('/', '').replace("'", '')
            sections.append({
                'level': level,
                'heading': heading,
                'anchor': anchor,
                'line_number': content[:match.start()].count('\n') + 1
            })

        # Count words
        word_count = len(re.findall(r'\b\w+\b', content))

        # Check for TOC
        has_toc = bool(re.search(r'(table of contents|## contents)', content, re.IGNORECASE))

        return {
            'title': title,
            'description': description,
            'sections': sections,
            'word_count': word_count,
            'section_count': len(sections),
            'has_toc': has_toc,
            'content': content  # For topic inference
        }

    def infer_topics(self, file_path: Path, metadata: Dict) -> List[Tuple[str, float]]:
        """Infer topics from file path and content"""
        topics = []
        content_lower = (metadata['title'] + ' ' + metadata['description'] + ' ' +
                        metadata['content']).lower()

        # Check each topic pattern
        for topic, pattern in TOPIC_PATTERNS.items():
            if re.search(pattern, content_lower, re.IGNORECASE):
                # Calculate relevance based on frequency
                matches = len(re.findall(pattern, content_lower, re.IGNORECASE))
                relevance = min(1.0, 0.5 + (matches * 0.1))
                topics.append((topic, relevance))

        # Boost relevance for path-based topics
        path_str = str(file_path).lower()
        for topic in ['nix', 'deployment', 'vcs', 'api', 'security']:
            if topic in path_str:
                # Find and boost if exists, or add
                found = False
                for i, (t, r) in enumerate(topics):
                    if t == topic:
                        topics[i] = (t, min(1.0, r + 0.3))
                        found = True
                        break
                if not found:
                    topics.append((topic, 0.8))

        return topics

    def infer_category(self, file_path: Path, metadata: Dict) -> Optional[str]:
        """Infer category from path and content"""
        content_lower = (metadata['title'] + ' ' + metadata['description']).lower()
        path_str = str(file_path).lower()

        # Check patterns
        for category, pattern in CATEGORY_PATTERNS.items():
            if re.search(pattern, content_lower, re.IGNORECASE):
                return category
            if category in path_str:
                return category

        # Default categories based on path
        if 'advanced' in path_str:
            return 'architecture'
        if 'phases' in path_str:
            return 'architecture'
        if 'prompts' in path_str:
            return 'api'
        if 'fixes' in path_str:
            return 'architecture'

        return None

    def extract_references(self, content: str, source_path: Path) -> List[Dict]:
        """Extract markdown links from content"""
        references = []

        # Find markdown links: [text](url)
        for match in re.finditer(r'\[([^\]]+)\]\(([^\)]+)\)', content):
            link_text = match.group(1)
            target = match.group(2)

            # Find which section this is in
            lines_before = content[:match.start()].count('\n')
            section_match = None
            for sec_match in re.finditer(r'^#+\s+(.+)$', content[:match.start()], re.MULTILINE):
                section_match = sec_match.group(1)

            references.append({
                'link_text': link_text,
                'target': target,
                'section': section_match,
                'is_external': target.startswith('http')
            })

        return references

    def index_readme(self, file_path: Path) -> int:
        """Index a single README file"""
        rel_path = file_path.relative_to(self.project_root)

        print(f"  📄 {rel_path}")

        # Extract metadata
        metadata = self.extract_metadata(file_path)

        # Infer topics and category
        topics = self.infer_topics(file_path, metadata)
        category = self.infer_category(file_path, metadata)

        # Insert readme_file
        self.cursor.execute("""
            INSERT OR REPLACE INTO readme_files
            (project_id, file_path, title, description, category, scope,
             word_count, section_count, has_toc, auto_index, index_priority)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            self.project_id,
            str(rel_path),
            metadata['title'],
            metadata['description'],
            category,
            'project',
            metadata['word_count'],
            metadata['section_count'],
            metadata['has_toc'],
            1,  # auto_index enabled
            10 if category == 'setup' else 5  # Higher priority for setup docs
        ))

        readme_id = self.cursor.lastrowid
        self.readme_ids[str(rel_path)] = readme_id

        # Insert topics
        for topic, relevance in topics:
            self.cursor.execute("""
                INSERT OR REPLACE INTO readme_topics (readme_id, topic, relevance, source)
                VALUES (?, ?, ?, 'extracted')
            """, (readme_id, topic, relevance))

        # Insert sections
        for section in metadata['sections']:
            self.cursor.execute("""
                INSERT INTO readme_sections
                (readme_id, heading, level, anchor, line_number, is_indexable)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                readme_id,
                section['heading'],
                section['level'],
                section['anchor'],
                section['line_number'],
                section['level'] <= 3  # Only index h1-h3
            ))

        # Extract and store references (will link them in second pass)
        references = self.extract_references(metadata['content'], file_path)
        for ref in references:
            # Store for second pass
            if not hasattr(self, '_pending_refs'):
                self._pending_refs = []
            self._pending_refs.append({
                'source_id': readme_id,
                'source_path': rel_path,
                **ref
            })

        return readme_id

    def link_references(self):
        """Second pass: create cross-references between READMEs"""
        print(f"\n🔗 Linking references...")

        if not hasattr(self, '_pending_refs'):
            return

        linked = 0
        external = 0

        for ref in self._pending_refs:
            if ref['is_external']:
                # External URL
                self.cursor.execute("""
                    INSERT INTO readme_references
                    (source_readme_id, target_external_url, link_text, section, is_auto_generated)
                    VALUES (?, ?, ?, ?, 0)
                """, (ref['source_id'], ref['target'], ref['link_text'], ref['section']))
                external += 1
            else:
                # Internal link - resolve relative path
                target = ref['target']
                if target.startswith('#'):
                    continue  # Section link within same doc

                # Resolve relative path
                source_dir = Path(ref['source_path']).parent
                try:
                    target_path = (source_dir / target).resolve()
                    target_rel = target_path.relative_to(self.project_root)
                    target_id = self.readme_ids.get(str(target_rel))

                    if target_id:
                        self.cursor.execute("""
                            INSERT INTO readme_references
                            (source_readme_id, target_readme_id, link_text, section, is_auto_generated)
                            VALUES (?, ?, ?, ?, 0)
                        """, (ref['source_id'], target_id, ref['link_text'], ref['section']))
                        linked += 1
                except Exception as e:
                    # Link to file outside docs or broken
                    pass

        print(f"  ✓ {linked} internal references")
        print(f"  ✓ {external} external references")

    def run(self):
        """Run the complete indexing process"""
        print("🏛️  TempleDB Documentation Indexer\n")

        # Scan files
        md_files = self.scan_markdown_files()

        # Index each file
        print(f"\n📊 Indexing files...\n")
        for file_path in md_files:
            try:
                self.index_readme(file_path)
            except Exception as e:
                print(f"  ❌ Error indexing {file_path}: {e}")

        # Link references
        self.link_references()

        # Commit
        self.conn.commit()

        # Stats
        print(f"\n✨ Indexing complete!\n")
        self.print_stats()

    def print_stats(self):
        """Print indexing statistics"""
        # Total READMEs
        self.cursor.execute("SELECT COUNT(*) FROM readme_files WHERE project_id = ?", (self.project_id,))
        readme_count = self.cursor.fetchone()[0]

        # Total topics
        self.cursor.execute("""
            SELECT COUNT(DISTINCT topic)
            FROM readme_topics rt
            JOIN readme_files rf ON rt.readme_id = rf.id
            WHERE rf.project_id = ?
        """, (self.project_id,))
        topic_count = self.cursor.fetchone()[0]

        # Total references
        self.cursor.execute("""
            SELECT COUNT(*)
            FROM readme_references rr
            JOIN readme_files rf ON rr.source_readme_id = rf.id
            WHERE rf.project_id = ?
        """, (self.project_id,))
        ref_count = self.cursor.fetchone()[0]

        # Categories
        self.cursor.execute("""
            SELECT category, COUNT(*) as count
            FROM readme_files
            WHERE project_id = ? AND category IS NOT NULL
            GROUP BY category
            ORDER BY count DESC
        """, (self.project_id,))
        categories = self.cursor.fetchall()

        # Top topics
        self.cursor.execute("""
            SELECT rt.topic, COUNT(*) as count, AVG(rt.relevance) as avg_relevance
            FROM readme_topics rt
            JOIN readme_files rf ON rt.readme_id = rf.id
            WHERE rf.project_id = ?
            GROUP BY rt.topic
            ORDER BY count DESC
            LIMIT 10
        """, (self.project_id,))
        topics = self.cursor.fetchall()

        print(f"📈 Statistics:")
        print(f"  • {readme_count} README files indexed")
        print(f"  • {topic_count} unique topics")
        print(f"  • {ref_count} cross-references")

        if categories:
            print(f"\n📂 Categories:")
            for cat in categories:
                print(f"  • {cat[0]}: {cat[1]} files")

        if topics:
            print(f"\n🏷️  Top Topics:")
            for topic in topics:
                print(f"  • {topic[0]}: {topic[1]} files (avg relevance: {topic[2]:.2f})")


def main():
    """Main entry point"""
    indexer = READMEIndexer(DB_PATH, PROJECT_ROOT)
    indexer.run()


if __name__ == "__main__":
    main()
