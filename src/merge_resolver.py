#!/usr/bin/env python3
"""
Merge Resolution System

Handles three-way merge conflicts with AI assistance and human override.
Supports merging changes from external git repos or between checkouts.
"""

import difflib
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from enum import Enum

from logger import get_logger

logger = get_logger(__name__)


class ConflictType(Enum):
    """Types of merge conflicts"""
    BOTH_MODIFIED = "both_modified"  # Both sides modified same file
    MODIFY_DELETE = "modify_delete"   # One modified, other deleted
    BOTH_ADDED = "both_added"         # Both added same file path
    CONTENT_CONFLICT = "content_conflict"  # Line-level conflicts within file


@dataclass
class FileVersion:
    """Represents a version of a file"""
    content: str
    hash: str
    source: str  # 'ours', 'theirs', 'base'
    author: Optional[str] = None
    timestamp: Optional[str] = None


@dataclass
class MergeConflict:
    """Represents a merge conflict"""
    file_path: str
    conflict_type: ConflictType
    ours: Optional[FileVersion] = None
    theirs: Optional[FileVersion] = None
    base: Optional[FileVersion] = None
    conflict_markers: Optional[str] = None
    ai_suggestion: Optional[str] = None
    ai_confidence: Optional[str] = None
    ai_reasoning: Optional[str] = None


@dataclass
class MergeResult:
    """Result of a merge operation"""
    success: bool
    conflicts: List[MergeConflict]
    auto_merged: List[str]  # Files merged automatically
    error_message: Optional[str] = None


class ThreeWayMerge:
    """Performs three-way merge with conflict detection"""

    def __init__(self):
        pass

    def merge_files(
        self,
        file_path: str,
        ours: FileVersion,
        theirs: FileVersion,
        base: Optional[FileVersion] = None
    ) -> Tuple[bool, Optional[str], Optional[MergeConflict]]:
        """
        Perform three-way merge on a single file.

        Args:
            file_path: Path to file being merged
            ours: Our version
            theirs: Their version
            base: Common ancestor version (if available)

        Returns:
            Tuple of (success, merged_content, conflict)
        """
        # If no base, can't do three-way merge
        if not base:
            return self._two_way_merge(file_path, ours, theirs)

        # If either version matches base, take the other
        if ours.hash == base.hash:
            logger.debug(f"{file_path}: Taking theirs (ours unchanged)")
            return True, theirs.content, None

        if theirs.hash == base.hash:
            logger.debug(f"{file_path}: Taking ours (theirs unchanged)")
            return True, ours.content, None

        # Both changed - need to merge
        return self._merge_with_diff3(file_path, ours, theirs, base)

    def _two_way_merge(
        self,
        file_path: str,
        ours: FileVersion,
        theirs: FileVersion
    ) -> Tuple[bool, Optional[str], Optional[MergeConflict]]:
        """Two-way merge when no base is available"""

        # If identical, no conflict
        if ours.hash == theirs.hash:
            return True, ours.content, None

        # Otherwise, it's a conflict
        conflict = MergeConflict(
            file_path=file_path,
            conflict_type=ConflictType.BOTH_MODIFIED,
            ours=ours,
            theirs=theirs,
            base=None
        )

        # Generate conflict markers
        conflict.conflict_markers = self._generate_conflict_markers(
            file_path, ours.content, theirs.content, None
        )

        return False, conflict.conflict_markers, conflict

    def _merge_with_diff3(
        self,
        file_path: str,
        ours: FileVersion,
        theirs: FileVersion,
        base: FileVersion
    ) -> Tuple[bool, Optional[str], Optional[MergeConflict]]:
        """Three-way merge using diff3 algorithm"""

        # Split into lines
        ours_lines = ours.content.splitlines(keepends=True)
        theirs_lines = theirs.content.splitlines(keepends=True)
        base_lines = base.content.splitlines(keepends=True)

        # Compute diffs
        ours_diff = list(difflib.unified_diff(base_lines, ours_lines, lineterm=''))
        theirs_diff = list(difflib.unified_diff(base_lines, theirs_lines, lineterm=''))

        # Try to merge line by line
        merged_lines = []
        conflicts = []

        i_ours = 0
        i_theirs = 0
        i_base = 0

        # Simple merge strategy: check each line
        while i_base < len(base_lines):
            base_line = base_lines[i_base]
            ours_line = ours_lines[i_ours] if i_ours < len(ours_lines) else None
            theirs_line = theirs_lines[i_theirs] if i_theirs < len(theirs_lines) else None

            # If both unchanged, keep base
            if base_line == ours_line == theirs_line:
                merged_lines.append(base_line)
                i_base += 1
                i_ours += 1
                i_theirs += 1

            # If ours changed but not theirs
            elif base_line == theirs_line and ours_line != base_line:
                merged_lines.append(ours_line if ours_line else '')
                i_base += 1
                i_ours += 1
                i_theirs += 1

            # If theirs changed but not ours
            elif base_line == ours_line and theirs_line != base_line:
                merged_lines.append(theirs_line if theirs_line else '')
                i_base += 1
                i_ours += 1
                i_theirs += 1

            # Both changed differently - conflict
            else:
                # Collect conflicting region
                conflict_ours = []
                conflict_theirs = []
                conflict_base = []

                # Simple approach: mark this section as conflict
                while (i_base < len(base_lines) and
                       (i_ours >= len(ours_lines) or ours_lines[i_ours] != base_lines[i_base]) and
                       (i_theirs >= len(theirs_lines) or theirs_lines[i_theirs] != base_lines[i_base])):

                    if i_base < len(base_lines):
                        conflict_base.append(base_lines[i_base])
                        i_base += 1

                    if i_ours < len(ours_lines):
                        conflict_ours.append(ours_lines[i_ours])
                        i_ours += 1

                    if i_theirs < len(theirs_lines):
                        conflict_theirs.append(theirs_lines[i_theirs])
                        i_theirs += 1

                    # Safety: limit conflict region size
                    if len(conflict_base) > 100:
                        break

                # Add conflict markers
                merged_lines.append(f"<<<<<<< ours\n")
                merged_lines.extend(conflict_ours)
                merged_lines.append(f"=======\n")
                merged_lines.extend(conflict_theirs)
                merged_lines.append(f">>>>>>> theirs\n")

                conflicts.append({
                    'line': len(merged_lines),
                    'ours': ''.join(conflict_ours),
                    'theirs': ''.join(conflict_theirs),
                    'base': ''.join(conflict_base)
                })

        # If no conflicts, return merged content
        if not conflicts:
            return True, ''.join(merged_lines), None

        # Has conflicts
        conflict = MergeConflict(
            file_path=file_path,
            conflict_type=ConflictType.CONTENT_CONFLICT,
            ours=ours,
            theirs=theirs,
            base=base,
            conflict_markers=''.join(merged_lines)
        )

        return False, ''.join(merged_lines), conflict

    def _generate_conflict_markers(
        self,
        file_path: str,
        ours_content: str,
        theirs_content: str,
        base_content: Optional[str]
    ) -> str:
        """Generate conflict markers for manual resolution"""

        lines = [
            f"<<<<<<< ours\n",
            ours_content,
            f"\n=======\n",
            theirs_content,
            f"\n>>>>>>> theirs\n"
        ]

        if base_content:
            lines.insert(3, f"\n||||||| base\n")
            lines.insert(4, base_content)

        return ''.join(lines)


class AIMergeAssistant:
    """Provides AI-assisted merge suggestions"""

    def __init__(self, llm_client=None):
        """
        Initialize AI merge assistant

        Args:
            llm_client: Optional LLM client (Claude, GPT, etc.)
                       If None, will attempt to use MCP or environment
        """
        self.llm_client = llm_client

    def suggest_resolution(self, conflict: MergeConflict) -> MergeConflict:
        """
        Ask AI to suggest merge resolution

        Args:
            conflict: Conflict to resolve

        Returns:
            Updated conflict with AI suggestion
        """

        if not self.llm_client:
            logger.warning("No LLM client available for AI merge assistance")
            return conflict

        # Build prompt for AI
        prompt = self._build_merge_prompt(conflict)

        try:
            # Call LLM
            response = self.llm_client.complete(prompt)

            # Parse response
            suggestion = self._parse_ai_response(response)

            # Update conflict with suggestion
            conflict.ai_suggestion = suggestion.get('merged_content')
            conflict.ai_confidence = suggestion.get('confidence')
            conflict.ai_reasoning = suggestion.get('reasoning')

            logger.info(f"AI suggestion for {conflict.file_path}: {conflict.ai_confidence} confidence")

        except Exception as e:
            logger.error(f"AI merge suggestion failed: {e}")

        return conflict

    def _build_merge_prompt(self, conflict: MergeConflict) -> str:
        """Build prompt for AI merge assistance"""

        prompt_parts = [
            "You are assisting with a merge conflict resolution.",
            f"File: {conflict.file_path}",
            "",
            "## Conflict Details",
            ""
        ]

        if conflict.base:
            prompt_parts.extend([
                "### Base Version (common ancestor):",
                "```",
                conflict.base.content,
                "```",
                ""
            ])

        if conflict.ours:
            author_info = f" (by {conflict.ours.author})" if conflict.ours.author else ""
            prompt_parts.extend([
                f"### Our Version{author_info}:",
                "```",
                conflict.ours.content,
                "```",
                ""
            ])

        if conflict.theirs:
            author_info = f" (by {conflict.theirs.author})" if conflict.theirs.author else ""
            prompt_parts.extend([
                f"### Their Version{author_info}:",
                "```",
                conflict.theirs.content,
                "```",
                ""
            ])

        prompt_parts.extend([
            "## Task",
            "",
            "Please suggest a merged version that:",
            "1. Preserves intent from both versions where possible",
            "2. Resolves conflicts by choosing the most appropriate version",
            "3. Maintains code correctness and style",
            "",
            "Respond in JSON format:",
            "```json",
            "{",
            '  "merged_content": "... merged file content ...",',
            '  "confidence": "low|medium|high",',
            '  "reasoning": "explanation of merge decisions"',
            "}",
            "```"
        ])

        return '\n'.join(prompt_parts)

    def _parse_ai_response(self, response: str) -> Dict:
        """Parse AI response into structured format"""
        import json
        import re

        # Try to extract JSON from response
        json_match = re.search(r'```json\s*(\{.*?\})\s*```', response, re.DOTALL)

        if json_match:
            try:
                return json.loads(json_match.group(1))
            except json.JSONDecodeError:
                pass

        # Fallback: return response as reasoning
        return {
            'merged_content': None,
            'confidence': 'low',
            'reasoning': response
        }


class MergeResolver:
    """High-level merge resolver with AI assistance"""

    def __init__(self, llm_client=None):
        """
        Initialize merge resolver

        Args:
            llm_client: Optional LLM client for AI assistance
        """
        self.three_way = ThreeWayMerge()
        self.ai_assistant = AIMergeAssistant(llm_client)

    def resolve_conflicts(
        self,
        conflicts: List[MergeConflict],
        strategy: str = 'ai-assisted'
    ) -> List[MergeConflict]:
        """
        Resolve conflicts using specified strategy

        Args:
            conflicts: List of conflicts to resolve
            strategy: Resolution strategy:
                     - 'ai-assisted': AI suggests, human reviews
                     - 'ours': Always take our version
                     - 'theirs': Always take their version
                     - 'manual': No automatic resolution

        Returns:
            List of conflicts with resolutions
        """

        resolved = []

        for conflict in conflicts:
            if strategy == 'ai-assisted':
                conflict = self.ai_assistant.suggest_resolution(conflict)
            elif strategy == 'ours':
                if conflict.ours:
                    conflict.ai_suggestion = conflict.ours.content
                    conflict.ai_confidence = 'high'
                    conflict.ai_reasoning = 'Using our version (strategy: ours)'
            elif strategy == 'theirs':
                if conflict.theirs:
                    conflict.ai_suggestion = conflict.theirs.content
                    conflict.ai_confidence = 'high'
                    conflict.ai_reasoning = 'Using their version (strategy: theirs)'

            resolved.append(conflict)

        return resolved

    def merge_file_versions(
        self,
        file_path: str,
        ours_content: str,
        ours_hash: str,
        theirs_content: str,
        theirs_hash: str,
        base_content: Optional[str] = None,
        base_hash: Optional[str] = None,
        metadata: Optional[Dict] = None
    ) -> Tuple[bool, Optional[str], Optional[MergeConflict]]:
        """
        Merge two versions of a file

        Args:
            file_path: Path to file
            ours_content: Our version content
            ours_hash: Our version hash
            theirs_content: Their version content
            theirs_hash: Their version hash
            base_content: Base version content (optional)
            base_hash: Base version hash (optional)
            metadata: Additional metadata (authors, timestamps, etc.)

        Returns:
            Tuple of (success, merged_content, conflict)
        """

        metadata = metadata or {}

        ours = FileVersion(
            content=ours_content,
            hash=ours_hash,
            source='ours',
            author=metadata.get('ours_author'),
            timestamp=metadata.get('ours_timestamp')
        )

        theirs = FileVersion(
            content=theirs_content,
            hash=theirs_hash,
            source='theirs',
            author=metadata.get('theirs_author'),
            timestamp=metadata.get('theirs_timestamp')
        )

        base = None
        if base_content and base_hash:
            base = FileVersion(
                content=base_content,
                hash=base_hash,
                source='base',
                author=metadata.get('base_author'),
                timestamp=metadata.get('base_timestamp')
            )

        return self.three_way.merge_files(file_path, ours, theirs, base)
