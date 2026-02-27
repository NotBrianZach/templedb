#!/usr/bin/env python3
"""
Agent Decision UI - Rich interface for inflection point prompts

Provides an enhanced UI for agent decision points with:
- Multiple choice selection
- Rich descriptions and context
- Decision tree visualization
- Impact indicators
"""

import sys
import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from logger import get_logger

logger = get_logger(__name__)


class DecisionUI:
    """
    Rich terminal UI for agent decision points.

    Displays options with descriptions, impact levels, and
    trade-offs to help users make informed decisions.
    """

    def __init__(self):
        """Initialize decision UI"""
        # Terminal colors
        self.COLORS = {
            'RESET': '\033[0m',
            'BOLD': '\033[1m',
            'DIM': '\033[2m',
            'UNDERLINE': '\033[4m',
            'RED': '\033[31m',
            'GREEN': '\033[32m',
            'YELLOW': '\033[33m',
            'BLUE': '\033[34m',
            'MAGENTA': '\033[35m',
            'CYAN': '\033[36m',
            'WHITE': '\033[37m',
            'GRAY': '\033[90m',
            'BG_RED': '\033[41m',
            'BG_GREEN': '\033[42m',
            'BG_YELLOW': '\033[43m',
            'BG_BLUE': '\033[44m',
        }

        # Impact indicators
        self.IMPACT_ICONS = {
            'low': '○',
            'medium': '◐',
            'high': '●',
            'critical': '⚠',
        }

        self.IMPACT_COLORS = {
            'low': 'GREEN',
            'medium': 'YELLOW',
            'high': 'MAGENTA',
            'critical': 'RED',
        }

    def _color(self, text: str, color: str) -> str:
        """Add color to text"""
        return f"{self.COLORS.get(color, '')}{text}{self.COLORS['RESET']}"

    def _box_top(self, width: int, title: str = "") -> str:
        """Create box top border"""
        if title:
            title_len = len(title) + 2
            left_len = 3
            right_len = width - left_len - title_len - 2
            return f"┌─{self._color(' ' + title + ' ', 'BOLD')}{'─' * right_len}┐"
        return f"┌{'─' * width}┐"

    def _box_line(self, content: str, width: int, align='left') -> str:
        """Create box content line"""
        content_len = len(content)
        # Strip ANSI codes for length calculation
        import re
        visible_len = len(re.sub(r'\033\[[0-9;]+m', '', content))
        padding = width - visible_len

        if align == 'center':
            left_pad = padding // 2
            right_pad = padding - left_pad
            return f"│{' ' * left_pad}{content}{' ' * right_pad}│"
        elif align == 'right':
            return f"│{' ' * padding}{content}│"
        else:  # left
            return f"│{content}{' ' * padding}│"

    def _box_bottom(self, width: int) -> str:
        """Create box bottom border"""
        return f"└{'─' * width}┘"

    def _box_divider(self, width: int) -> str:
        """Create box divider"""
        return f"├{'─' * width}┤"

    def prompt_decision(
        self,
        prompt: str,
        options: List[Dict],
        context: Optional[str] = None,
        show_impact: bool = True,
        show_tradeoffs: bool = True
    ) -> Tuple[int, str]:
        """
        Display decision prompt and get user choice.

        Args:
            prompt: The question to ask
            options: List of option dicts with:
                - label: Short option name
                - description: Detailed description
                - impact: 'low', 'medium', 'high', 'critical' (optional)
                - pros: List of pros (optional)
                - cons: List of cons (optional)
            context: Additional context about the decision
            show_impact: Show impact indicators
            show_tradeoffs: Show pros/cons if available

        Returns:
            Tuple of (option_index, option_label)
        """
        width = 70

        # Header
        print("\n" + self._box_top(width, "Decision Required"))

        # Context if provided
        if context:
            print(self._box_line("", width))
            for line in self._wrap_text(context, width - 2):
                print(self._box_line(f" {self._color(line, 'DIM')}", width - 2))

        # Question
        print(self._box_line("", width))
        print(self._box_divider(width))
        for line in self._wrap_text(prompt, width - 2):
            print(self._box_line(f" {self._color(line, 'BOLD')}", width - 2))

        print(self._box_divider(width))
        print(self._box_line("", width))

        # Options
        for i, option in enumerate(options, 1):
            # Option header with impact
            label = option.get('label', f'Option {i}')
            impact = option.get('impact', 'medium')

            if show_impact and 'impact' in option:
                impact_icon = self.IMPACT_ICONS.get(impact, '○')
                impact_color = self.IMPACT_COLORS.get(impact, 'GRAY')
                impact_text = f"{self._color(impact_icon, impact_color)} {impact.upper()}"
                header = f"{self._color(str(i), 'CYAN')}. {self._color(label, 'BOLD')} [{impact_text}]"
            else:
                header = f"{self._color(str(i), 'CYAN')}. {self._color(label, 'BOLD')}"

            print(self._box_line(f" {header}", width - 2))

            # Description
            desc = option.get('description', '')
            if desc:
                for line in self._wrap_text(desc, width - 6):
                    print(self._box_line(f"    {line}", width - 2))

            # Pros/Cons
            if show_tradeoffs:
                pros = option.get('pros', [])
                cons = option.get('cons', [])

                if pros:
                    print(self._box_line(f"    {self._color('Pros:', 'GREEN')}", width - 2))
                    for pro in pros:
                        print(self._box_line(f"      {self._color('✓', 'GREEN')} {pro}", width - 2))

                if cons:
                    print(self._box_line(f"    {self._color('Cons:', 'RED')}", width - 2))
                    for con in cons:
                        print(self._box_line(f"      {self._color('✗', 'RED')} {con}", width - 2))

            print(self._box_line("", width))

        print(self._box_bottom(width))

        # Get user choice
        while True:
            try:
                choice_str = input(f"\n{self._color('Your choice', 'BOLD')} [1-{len(options)}]: ").strip()

                if not choice_str:
                    continue

                choice = int(choice_str)
                if 1 <= choice <= len(options):
                    selected_option = options[choice - 1]
                    return choice - 1, selected_option.get('label', f'Option {choice}')

                print(self._color(f"Please enter a number between 1 and {len(options)}", 'YELLOW'))

            except ValueError:
                print(self._color("Please enter a valid number", 'YELLOW'))
            except (EOFError, KeyboardInterrupt):
                print(f"\n{self._color('Decision cancelled', 'YELLOW')}")
                return -1, "cancelled"

    def _wrap_text(self, text: str, width: int) -> List[str]:
        """Wrap text to width"""
        words = text.split()
        lines = []
        current_line = []
        current_length = 0

        for word in words:
            word_len = len(word)
            if current_length + word_len + len(current_line) <= width:
                current_line.append(word)
                current_length += word_len
            else:
                if current_line:
                    lines.append(' '.join(current_line))
                current_line = [word]
                current_length = word_len

        if current_line:
            lines.append(' '.join(current_line))

        return lines or ['']

    def display_decision_tree(
        self,
        root_question: str,
        tree: Dict,
        indent: int = 0
    ):
        """
        Display a decision tree visualization.

        Args:
            root_question: The root decision
            tree: Tree structure with decisions and branches
            indent: Current indentation level
        """
        prefix = "  " * indent

        if indent == 0:
            print(f"\n{self._color('Decision Tree:', 'BOLD')}")
            print(f"{self._color('═' * 60, 'CYAN')}\n")

        print(f"{prefix}{self._color('●', 'CYAN')} {root_question}")

        if 'options' in tree:
            for i, (option, subtree) in enumerate(tree['options'].items()):
                is_last = i == len(tree['options']) - 1
                connector = "└─" if is_last else "├─"
                print(f"{prefix}{connector} {self._color(option, 'YELLOW')}")

                if isinstance(subtree, dict) and 'question' in subtree:
                    self.display_decision_tree(
                        subtree['question'],
                        subtree,
                        indent + 1
                    )
                elif isinstance(subtree, str):
                    print(f"{prefix}   {self._color('→', 'GREEN')} {subtree}")


def demo():
    """Demo the decision UI"""
    ui = DecisionUI()

    # Example 1: Simple decision
    print("\n" + "=" * 80)
    print("EXAMPLE 1: Simple Decision")
    print("=" * 80)

    options = [
        {
            'label': 'Polling (Simple)',
            'description': 'Use database polling with 2-second intervals. Easy to implement.',
            'impact': 'low',
            'pros': ['Simple implementation', 'No extra dependencies', 'Works everywhere'],
            'cons': ['2-second latency', 'Extra database load', 'Not real-time']
        },
        {
            'label': 'WebSocket (Real-time)',
            'description': 'Use WebSocket server for instant updates. Complex but responsive.',
            'impact': 'high',
            'pros': ['Instant updates', 'True real-time', 'Efficient'],
            'cons': ['Complex setup', 'Requires server', 'More failure modes']
        },
        {
            'label': 'File Watching (Fast)',
            'description': 'Use inotify to watch database file for changes. Good middle ground.',
            'impact': 'medium',
            'pros': ['Fast updates', 'No server needed', 'Low overhead'],
            'cons': ['Linux-only', 'Requires inotify', 'File system dependent']
        }
    ]

    choice_idx, choice_label = ui.prompt_decision(
        prompt="How should we implement live session updates?",
        options=options,
        context="We need to show users real-time agent activity. The choice affects responsiveness and complexity.",
        show_impact=True,
        show_tradeoffs=True
    )

    print(f"\n{ui._color('✓ You selected:', 'GREEN')} {choice_label}")

    # Example 2: Decision tree
    print("\n" + "=" * 80)
    print("EXAMPLE 2: Decision Tree Visualization")
    print("=" * 80)

    tree = {
        'question': 'Add error handling?',
        'options': {
            'Yes': {
                'question': 'What level?',
                'options': {
                    'Basic (try/catch)': 'Simple error catching',
                    'Advanced (retry logic)': {
                        'question': 'Retry strategy?',
                        'options': {
                            'Exponential backoff': 'Best for network errors',
                            'Fixed interval': 'Simpler, predictable'
                        }
                    }
                }
            },
            'No': 'Rely on default handling'
        }
    }

    ui.display_decision_tree('Add error handling?', tree)


if __name__ == "__main__":
    demo()
