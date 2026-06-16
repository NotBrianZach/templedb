#!/usr/bin/env python3
"""
Code Intelligence Commands

NOT REGISTERED - Functionality available via MCP tools.

This Click-based CLI is kept for reference but not integrated into main CLI.
Use MCP tools instead:
- templedb_code_search
- templedb_code_show_symbol
- templedb_code_show_clusters
- templedb_code_extract_symbols
- templedb_code_impact_analysis
- templedb_code_build_graph

Original commands (deprecated):
- Extracting symbols (Phase 1.2)
- Building dependency graph (Phase 1.3)
- Analyzing impact (Phase 1.4)
- Code clustering (Phase 1.5)
- Searching code (Phase 1.6)
"""

import click
import logging
from rich.console import Console
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn
from pathlib import Path
import sys

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from services.symbol_extraction_service import extract_symbols_for_project
from services.dependency_graph_service import build_dependency_graph_for_project
from services.impact_analysis_service import (
    analyze_symbol_impact,
    precompute_impact_for_project
)
from services.community_detection_service import (
    detect_communities_for_project,
    get_clusters_for_project
)
from services.code_search_service import (
    index_project_for_search,
    search_code
)
from db_utils import get_connection, get_project_by_slug

console = Console()
logger = logging.getLogger(__name__)


@click.group()
def code():
    """Code intelligence and analysis commands"""
    pass


# ============================================================================
# SEARCH COMMANDS (Phase 1.6)
# ============================================================================

@code.command()
@click.argument('project')
def index_search(project: str):
    """
    Index project for code search.

    Creates full-text search index (FTS5) for fast keyword search.
    Run this after extracting symbols or when symbols change.

    Example:
        templedb code index-search templedb
    """
    try:
        proj = get_project_by_slug(project)
        if not proj:
            console.print(f"[red]✗[/red] Project '{project}' not found")
            return

        project_id = proj['id']

        # Check if symbols exist
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM code_symbols WHERE project_id = ?", (project_id,))
        symbol_count = cursor.fetchone()[0]

        if symbol_count == 0:
            console.print("[yellow]⚠ No symbols found.[/yellow]")
            console.print("  Extract symbols first:")
            console.print(f"  templedb code extract-symbols {project}")
            return

        console.print(f"\n[bold]Indexing project for search:[/bold] {project}")
        console.print(f"  Symbols to index: {symbol_count}")

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console
        ) as progress:
            task = progress.add_task("Building search index...", total=None)
            stats = index_project_for_search(project_id)
            progress.update(task, completed=True)

        console.print("\n[bold green]✓ Search index built![/bold green]")
        console.print(f"  Symbols indexed: {stats['symbols_indexed']}")
        console.print(f"  Symbols updated: {stats['symbols_updated']}")

        console.print(f"\nSearch is ready! Try:")
        console.print(f"  templedb code search {project} 'database connection'")

    except Exception as e:
        console.print(f"[red]✗ Error:[/red] {e}")
        logger.exception("Search indexing failed")
        raise click.Abort()


@code.command()
@click.argument('project')
@click.argument('query')
@click.option('--limit', default=10, help='Max results to return')
@click.option('--type', 'symbol_type', help='Filter by symbol type (function, class, method)')
@click.option('--show-scores', is_flag=True, help='Show scoring breakdown')
def search(project: str, query: str, limit: int, symbol_type: str, show_scores: bool):
    """
    Search code using hybrid search (BM25 + graph ranking).

    Searches symbol names, docstrings, and signatures using:
    - BM25 full-text search (keyword relevance)
    - Graph-aware ranking (structural importance)
    - Semantic search (if embeddings available)

    Examples:
        templedb code search templedb 'database connection'
        templedb code search templedb 'deploy' --type function
        templedb code search templedb 'authentication' --limit 20
        templedb code search templedb 'query' --show-scores
    """
    try:
        proj = get_project_by_slug(project)
        if not proj:
            console.print(f"[red]✗[/red] Project '{project}' not found")
            return

        project_id = proj['id']

        # Check if search index exists
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT COUNT(*) FROM code_search_index csi
            JOIN code_symbols cs ON csi.symbol_id = cs.id
            WHERE cs.project_id = ?
        """, (project_id,))

        indexed_count = cursor.fetchone()[0]
        if indexed_count == 0:
            console.print("[yellow]⚠ Search index not found.[/yellow]")
            console.print("  Build the search index first:")
            console.print(f"  templedb code index-search {project}")
            return

        console.print(f"\n[bold]Searching:[/bold] \"{query}\" in {project}\n")

        # Perform search
        results = search_code(project_id, query, limit, symbol_type)

        if not results:
            console.print("[yellow]No results found.[/yellow]")
            console.print("\nTry:")
            console.print("  - Different keywords")
            console.print("  - Broader search terms")
            console.print("  - Check if symbols are indexed")
            return

        # Display results
        console.print(f"[bold green]Found {len(results)} results[/bold green]\n")

        for i, result in enumerate(results, 1):
            # Format score with color
            score = result.final_score
            if score >= 0.8:
                score_color = "green"
            elif score >= 0.5:
                score_color = "yellow"
            else:
                score_color = "red"

            console.print(f"[bold]{i}. {result.qualified_name}[/bold] ([{score_color}]{score:.3f}[/{score_color}])")
            console.print(f"   {result.symbol_type} in {result.file_path}:{result.start_line}")

            if result.docstring:
                # Show first 100 chars of docstring
                doc_preview = result.docstring[:100].replace('\n', ' ')
                console.print(f"   [dim]{doc_preview}...[/dim]")

            # Show scoring breakdown if requested
            if show_scores:
                console.print(f"   [dim]Scores: BM25={result.bm25_score:.3f}, "
                            f"Graph={result.graph_score:.3f}, "
                            f"Dependents={result.num_dependents}[/dim]")

            console.print()

    except Exception as e:
        console.print(f"[red]✗ Error:[/red] {e}")
        logger.exception("Search failed")
        raise click.Abort()


def register(cli):
    """Register code commands with CLI"""
    cli.add_command(code)
