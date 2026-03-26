#!/usr/bin/env python3
"""
Fuzzy matching utilities for TempleDB CLI

Provides consistent fuzzy search UX across all commands.
"""
import sys
from pathlib import Path
from typing import List, Dict, Optional, Callable, Any
from dataclasses import dataclass

sys.path.insert(0, str(Path(__file__).parent.parent))
from logger import get_logger

logger = get_logger(__name__)


@dataclass
class FuzzyMatch:
    """Represents a fuzzy match result"""
    value: str
    display: str
    score: float
    metadata: Dict[str, Any] = None

    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}


class FuzzyMatcher:
    """Generic fuzzy matcher for CLI arguments"""

    @staticmethod
    def simple_score(pattern: str, candidate: str) -> float:
        """
        Simple scoring algorithm for fuzzy matching.

        Returns score from 0.0 (no match) to 1.0 (perfect match).
        - Exact match: 1.0
        - Starts with pattern: 0.8
        - Contains pattern: 0.6
        - Case-insensitive variations: -0.1 penalty
        """
        pattern_lower = pattern.lower()
        candidate_lower = candidate.lower()

        # No match
        if pattern_lower not in candidate_lower:
            return 0.0

        # Exact match
        if pattern == candidate:
            return 1.0

        # Case-insensitive exact match
        if pattern_lower == candidate_lower:
            return 0.95

        # Starts with pattern
        if candidate_lower.startswith(pattern_lower):
            # Bonus for shorter candidates (more specific)
            length_ratio = len(pattern) / len(candidate)
            return 0.8 + (length_ratio * 0.15)

        # Contains pattern
        # Bonus for position (earlier is better)
        position = candidate_lower.index(pattern_lower)
        position_score = 1.0 - (position / len(candidate))

        return 0.4 + (position_score * 0.2)

    @classmethod
    def match(
        cls,
        pattern: str,
        candidates: List[str],
        display_formatter: Optional[Callable[[str], str]] = None,
        min_score: float = 0.1,
        max_results: int = 10
    ) -> List[FuzzyMatch]:
        """
        Fuzzy match pattern against candidates.

        Args:
            pattern: Search pattern
            candidates: List of candidate strings
            display_formatter: Optional function to format display strings
            min_score: Minimum score threshold (0.0-1.0)
            max_results: Maximum number of results to return

        Returns:
            List of FuzzyMatch objects, sorted by score (descending)
        """
        if display_formatter is None:
            display_formatter = lambda x: x

        matches = []
        for candidate in candidates:
            score = cls.simple_score(pattern, candidate)
            if score >= min_score:
                matches.append(FuzzyMatch(
                    value=candidate,
                    display=display_formatter(candidate),
                    score=score
                ))

        # Sort by score (highest first), then by length (shortest first)
        matches.sort(key=lambda m: (-m.score, len(m.value)))

        return matches[:max_results]

    @classmethod
    def match_one(
        cls,
        pattern: str,
        candidates: List[str],
        display_formatter: Optional[Callable[[str], str]] = None,
        entity_name: str = "item",
        show_matched: bool = True
    ) -> Optional[str]:
        """
        Fuzzy match pattern and return single result.

        Returns:
            - Matched value if exactly one match found
            - None if no matches or multiple matches (prints error)

        Args:
            pattern: Search pattern
            candidates: List of candidate strings
            display_formatter: Optional function to format display strings
            entity_name: Name of entity type for error messages (e.g., "file", "project")
            show_matched: Whether to print "Matched: X" on single match
        """
        matches = cls.match(pattern, candidates, display_formatter)

        if len(matches) == 0:
            logger.error(f"No {entity_name} matches '{pattern}'")
            return None

        if len(matches) == 1:
            if show_matched:
                logger.info(f"Matched {entity_name}: {matches[0].display}")
            return matches[0].value

        # Multiple matches
        logger.error(f"Multiple {entity_name}s match '{pattern}':")
        for match in matches:
            score_indicator = "●" if match.score > 0.8 else "○"
            logger.error(f"  {score_indicator} {match.display}")
        logger.error(f"Please specify exact {entity_name} name")
        return None


class ProjectFuzzyMatcher:
    """Fuzzy matcher specialized for projects"""

    def __init__(self):
        from repositories import ProjectRepository
        self.project_repo = ProjectRepository()

    def match_project(self, pattern: str, show_matched: bool = True) -> Optional[dict]:
        """
        Fuzzy match project by slug or name.

        Returns:
            Project dict if found, None otherwise
        """
        projects = self.project_repo.list_projects()

        # Try exact match first (silent - no need to announce exact matches)
        for project in projects:
            if project['slug'] == pattern:
                return project

        # Build candidate list (try both slug and name)
        candidates = {}
        for project in projects:
            candidates[project['slug']] = project
            # Also index by name if different
            if project['name'] != project['slug']:
                candidates[f"{project['name']} ({project['slug']})"] = project

        # Fuzzy match (only show "Matched:" for fuzzy matches)
        matched_key = FuzzyMatcher.match_one(
            pattern,
            list(candidates.keys()),
            entity_name="project",
            show_matched=show_matched
        )

        if matched_key:
            return candidates[matched_key]

        return None


class FileFuzzyMatcher:
    """Fuzzy matcher specialized for files within a project"""

    def __init__(self, project_id: int):
        from repositories import FileRepository
        self.file_repo = FileRepository()
        self.project_id = project_id

    def match_file(self, pattern: str, show_matched: bool = True) -> Optional[dict]:
        """
        Fuzzy match file by path.

        Returns:
            File record dict if found, None otherwise
        """
        # Try exact match first (silent - no need to announce exact matches)
        file_record = self.file_repo.get_file_by_path(self.project_id, pattern)
        if file_record:
            return file_record

        # Get all files in project
        import sqlite3
        from config import DB_PATH

        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute("""
            SELECT id, file_path
            FROM files
            WHERE project_id = ?
            ORDER BY file_path
        """, (self.project_id,))

        files = [dict(row) for row in cursor.fetchall()]
        conn.close()

        if not files:
            return None

        # Fuzzy match (only show "Matched:" for fuzzy matches)
        file_paths = [f['file_path'] for f in files]
        matched_path = FuzzyMatcher.match_one(
            pattern,
            file_paths,
            entity_name="file",
            show_matched=show_matched
        )

        if matched_path:
            # Return the file record
            for f in files:
                if f['file_path'] == matched_path:
                    return f

        return None


class SymbolFuzzyMatcher:
    """Fuzzy matcher for code symbols (functions, classes)"""

    def __init__(self, project_id: int):
        self.project_id = project_id

    def match_symbol(self, pattern: str, symbol_type: Optional[str] = None) -> Optional[dict]:
        """
        Fuzzy match code symbol.

        Args:
            pattern: Symbol name pattern
            symbol_type: Optional filter (function, class, method)

        Returns:
            Symbol record if found, None otherwise
        """
        import sqlite3
        from config import DB_PATH

        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # Get symbols
        if symbol_type:
            cursor.execute("""
                SELECT id, qualified_name, symbol_type, file_path
                FROM code_symbols cs
                JOIN files f ON cs.file_id = f.id
                WHERE f.project_id = ?
                AND cs.symbol_type = ?
                ORDER BY qualified_name
            """, (self.project_id, symbol_type))
        else:
            cursor.execute("""
                SELECT id, qualified_name, symbol_type, file_path
                FROM code_symbols cs
                JOIN files f ON cs.file_id = f.id
                WHERE f.project_id = ?
                ORDER BY qualified_name
            """, (self.project_id,))

        symbols = [dict(row) for row in cursor.fetchall()]
        conn.close()

        if not symbols:
            return None

        # Format display with type and location
        def format_symbol(name):
            symbol = next((s for s in symbols if s['qualified_name'] == name), None)
            if symbol:
                return f"{name} [{symbol['symbol_type']}] in {symbol['file_path']}"
            return name

        # Fuzzy match
        symbol_names = [s['qualified_name'] for s in symbols]
        matched_name = FuzzyMatcher.match_one(
            pattern,
            symbol_names,
            display_formatter=format_symbol,
            entity_name="symbol"
        )

        if matched_name:
            return next((s for s in symbols if s['qualified_name'] == matched_name), None)

        return None


# Convenience functions for common use cases

def fuzzy_match_project(pattern: str, show_matched: bool = True) -> Optional[dict]:
    """Convenience function to fuzzy match a project"""
    return ProjectFuzzyMatcher().match_project(pattern, show_matched)


def fuzzy_match_file(project_id: int, pattern: str, show_matched: bool = True) -> Optional[dict]:
    """Convenience function to fuzzy match a file"""
    return FileFuzzyMatcher(project_id).match_file(pattern, show_matched)


def fuzzy_match_symbol(project_id: int, pattern: str, symbol_type: Optional[str] = None) -> Optional[dict]:
    """Convenience function to fuzzy match a symbol"""
    return SymbolFuzzyMatcher(project_id).match_symbol(pattern, symbol_type)
