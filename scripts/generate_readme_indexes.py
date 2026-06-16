#!/usr/bin/env python3
"""
Generate auto-index sections for key TempleDB documentation files.

Inserts "Related Documentation" sections into markdown files based on
topic similarity and cross-references.
"""

import sys
import sqlite3
from pathlib import Path
from typing import List, Dict, Tuple

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from config import DB_PATH, PROJECT_ROOT


class IndexGenerator:
    """Generate and insert documentation indexes"""

    def __init__(self, db_path: str, project_root: Path):
        self.db_path = db_path
        self.project_root = project_root
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self.cursor = self.conn.cursor()

        # Marker for auto-generated sections
        self.marker_start = "<!-- AUTO-GENERATED-INDEX:START -->"
        self.marker_end = "<!-- AUTO-GENERATED-INDEX:END -->"

    def get_related_docs(self, readme_id: int, limit: int = 10) -> List[Dict]:
        """Get related documentation for a README"""
        self.cursor.execute("""
            SELECT
                rf2.id,
                rf2.title,
                rf2.file_path,
                rf2.description,
                rf2.category,
                rr.shared_topics,
                rr.relevance_score
            FROM related_readmes rr
            JOIN readme_files rf2 ON rr.related_readme_id = rf2.id
            WHERE rr.readme_id = ?
            ORDER BY rr.relevance_score DESC
            LIMIT ?
        """, (readme_id, limit))

        return [dict(row) for row in self.cursor.fetchall()]

    def get_readme_by_path(self, file_path: str) -> Dict:
        """Get README metadata by file path"""
        self.cursor.execute("""
            SELECT * FROM readme_files
            WHERE file_path = ?
        """, (file_path,))

        row = self.cursor.fetchone()
        return dict(row) if row else None

    def generate_index_markdown(self, related_docs: List[Dict], source_path: str) -> str:
        """Generate markdown for related documentation section"""
        if not related_docs:
            return ""

        lines = [
            "",
            self.marker_start,
            "## Related Documentation",
            ""
        ]

        # Group by category if we have multiple
        by_category = {}
        for doc in related_docs:
            category = doc['category'] or 'Other'
            if category not in by_category:
                by_category[category] = []
            by_category[category].append(doc)

        # If only one category or ungrouped, show flat list
        if len(by_category) <= 2:
            for doc in related_docs:
                # Calculate relative path from source
                source_dir = Path(source_path).parent
                target_path = Path(doc['file_path'])
                try:
                    rel_path = Path('../' * len(source_dir.parts)) / target_path
                except:
                    rel_path = target_path

                # Create bullet with description
                desc = doc['description'][:80] + "..." if len(doc['description']) > 80 else doc['description']
                lines.append(f"- **[{doc['title']}]({rel_path})**")
                if desc:
                    lines.append(f"  {desc}")
                lines.append("")
        else:
            # Group by category
            for category, docs in sorted(by_category.items()):
                lines.append(f"### {category.title()}")
                lines.append("")

                for doc in docs:
                    source_dir = Path(source_path).parent
                    target_path = Path(doc['file_path'])
                    try:
                        rel_path = Path('../' * len(source_dir.parts)) / target_path
                    except:
                        rel_path = target_path

                    lines.append(f"- **[{doc['title']}]({rel_path})**")
                lines.append("")

        lines.append(self.marker_end)
        lines.append("")

        return "\n".join(lines)

    def insert_or_update_index(self, file_path: Path, index_markdown: str) -> bool:
        """Insert or update index section in markdown file"""
        if not file_path.exists():
            print(f"  ⚠️  File not found: {file_path}")
            return False

        content = file_path.read_text()

        # Check if index already exists
        if self.marker_start in content:
            # Replace existing index
            import re
            pattern = f"{re.escape(self.marker_start)}.*?{re.escape(self.marker_end)}"
            new_content = re.sub(
                pattern,
                index_markdown.strip(),
                content,
                flags=re.DOTALL
            )
            action = "Updated"
        else:
            # Append to end
            new_content = content.rstrip() + "\n\n" + index_markdown
            action = "Added"

        # Write back
        file_path.write_text(new_content)
        print(f"  ✓ {action} index")
        return True

    def generate_for_file(self, file_path: str, max_related: int = 8):
        """Generate index for a specific file"""
        print(f"\n📄 {file_path}")

        # Get README metadata
        readme = self.get_readme_by_path(file_path)
        if not readme:
            print(f"  ⚠️  Not indexed yet")
            return

        # Get related docs
        related = self.get_related_docs(readme['id'], max_related)

        if not related:
            print(f"  ℹ️  No related documentation found")
            return

        print(f"  Found {len(related)} related docs")

        # Generate markdown
        index_md = self.generate_index_markdown(related, file_path)

        # Insert into file
        full_path = self.project_root / file_path
        self.insert_or_update_index(full_path, index_md)

    def generate_all_priority(self):
        """Generate indexes for all high-priority documentation"""
        print("🏛️  Generating Documentation Indexes\n")

        # Get high-priority files (most referenced + category priority)
        self.cursor.execute("""
            SELECT DISTINCT
                rf.file_path,
                rf.title,
                rf.category,
                COALESCE(rg.incoming_refs, 0) as refs,
                rf.index_priority
            FROM readme_files rf
            LEFT JOIN readme_reference_graph rg ON rf.id = rg.readme_id
            WHERE rf.auto_index = 1
            AND (
                COALESCE(rg.incoming_refs, 0) >= 3
                OR rf.category IN ('setup', 'api')
                OR rf.file_path IN ('docs/README.md', 'README.md')
                OR rf.index_priority >= 8
            )
            ORDER BY refs DESC, rf.index_priority DESC
            LIMIT 15
        """)

        priority_files = [row[0] for row in self.cursor.fetchall()]

        print(f"Generating indexes for {len(priority_files)} high-priority files:\n")

        for file_path in priority_files:
            self.generate_for_file(file_path, max_related=8)

        print(f"\n✨ Complete! Generated {len(priority_files)} indexes")


def main():
    """Main entry point"""
    generator = IndexGenerator(DB_PATH, PROJECT_ROOT)

    if len(sys.argv) > 1:
        # Generate for specific file
        file_path = sys.argv[1]
        generator.generate_for_file(file_path)
    else:
        # Generate for all priority files
        generator.generate_all_priority()


if __name__ == "__main__":
    main()
