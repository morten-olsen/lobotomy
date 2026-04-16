"""MCP server exposing wiki search and management tools.

Designed to run as a stdio-based MCP server. All library logging is
suppressed on stdout to avoid corrupting the JSON-RPC stream.
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

# Route ALL logging to stderr before importing anything else
logging.basicConfig(
    stream=sys.stderr,
    level=logging.WARNING,
    format="%(name)s: %(message)s",
)
# Suppress noisy libraries
for _name in ("sentence_transformers", "transformers", "torch", "huggingface_hub", "httpx"):
    logging.getLogger(_name).setLevel(logging.WARNING)

from mcp.server.fastmcp import FastMCP

from .config import load_config
from .index import WikiIndex
from .search import WikiSearch
from .templates import create_note, stamp_document, list_templates, generate_zettel_id

server = FastMCP("lobotomy", log_level="WARNING")

# Lazy singletons — initialized on first tool call
_index: WikiIndex | None = None
_search: WikiSearch | None = None


def _get_index() -> WikiIndex:
    global _index
    if _index is None:
        config = load_config()
        _index = WikiIndex(config)
    return _index


def _get_search() -> WikiSearch:
    global _search
    if _search is None:
        _search = WikiSearch(_get_index())
    return _search


def _format_results(results) -> str:
    if not results:
        return "No results found."

    idx = _get_index()
    lines = []
    for i, r in enumerate(results, 1):
        title = r.title or Path(r.path).stem
        zid = f" [{r.zettel_id}]" if r.zettel_id else ""
        lines.append(f"{i}. {title}{zid} (score: {r.score:.3f})")
        lines.append(f"   Path: {r.path}")

        # Fetch tags and dates for this document
        doc = idx.conn.execute(
            "SELECT id, created_date, modified_date FROM documents WHERE path = ?",
            (r.path,),
        ).fetchone()
        if doc:
            tag_rows = idx.conn.execute(
                "SELECT tag FROM tags WHERE doc_id = ?", (doc["id"],)
            ).fetchall()
            if tag_rows:
                lines.append(f"   Tags: {', '.join('#' + t['tag'] for t in tag_rows)}")
            dates = []
            if doc["created_date"]:
                dates.append(f"created: {doc['created_date']}")
            if doc["modified_date"]:
                dates.append(f"modified: {doc['modified_date']}")
            if dates:
                lines.append(f"   {', '.join(dates)}")

        if r.heading_path:
            lines.append(f"   Section: {r.heading_path}")
        lines.append(f"   {r.snippet[:500]}")
        lines.append("")
    return "\n".join(lines)


@server.tool()
def wiki_search(
    query: str | None = None,
    tags: list[str] | None = None,
    after: str | None = None,
    before: str | None = None,
    date_field: str = "created",
    mode: str = "hybrid",
    limit: int = 10,
) -> str:
    """Search the wiki. All parameters are optional — combine for precision.

    Args:
        query: Search terms (semantic + full-text). Omit to browse by filters only.
        tags: Filter to documents with ALL of these tags (AND logic). e.g. ["devops", "kubernetes"]
        after: ISO date (inclusive), e.g. "2026-01-01". Omit for no lower bound.
        before: ISO date (inclusive), e.g. "2026-12-31". Omit for no upper bound.
        date_field: Which date to filter on — "created" (default) or "modified".
        mode: Search mode — "hybrid" (default), "semantic", or "fulltext". Only applies when query is provided.
        limit: Maximum number of results.

    Examples:
        - wiki_search(query="deployment strategies") — broad search
        - wiki_search(tags=["devops"]) — all devops-tagged docs
        - wiki_search(query="kubernetes", tags=["devops"], after="2026-01-01") — precise filtered search
        - wiki_search(after="2026-04-01") — everything created this month
    """
    ws = _get_search()
    if mode in ("semantic", "fulltext") and query:
        if mode == "semantic":
            results = ws.semantic(query, limit=limit)
        else:
            results = ws.fulltext(query, limit=limit)
    else:
        results = ws.hybrid(
            query=query, tags=tags, after=after, before=before,
            date_field=date_field, limit=limit,
        )
    return _format_results(results)


@server.tool()
def wiki_list_tags() -> str:
    """List all tags in the wiki with their document counts."""
    tag_list = _get_search().list_tags()
    if not tag_list:
        return "No tags found."
    return "\n".join(f"#{t} ({count})" for t, count in tag_list)


@server.tool()
def wiki_stats() -> str:
    """Get a bird's-eye view of the wiki's health and structure.

    Returns document counts, tag distribution, link density, orphan count,
    hub notes (most linked-to), and stale notes (not modified in 90+ days).
    Useful for understanding the wiki's shape and finding maintenance opportunities.
    """
    s = _get_search().stats()
    lines = [
        f"Documents: {s['documents']}",
        f"  with tags: {s['documents_with_tags']}",
        f"  with outgoing links: {s['documents_with_links']}",
        f"  orphans (no links): {s['orphan_count']}",
        f"  stale (>90 days): {s['stale_count']}",
        f"Unique tags: {s['unique_tags']}",
        f"Total links: {s['total_links']}",
    ]
    if s["top_tags"]:
        lines.append("")
        lines.append("Top tags:")
        for tag, count in s["top_tags"]:
            lines.append(f"  #{tag} ({count})")
    if s["most_linked"]:
        lines.append("")
        lines.append("Most linked-to (hubs):")
        for target, count in s["most_linked"]:
            lines.append(f"  {target} ({count} incoming)")
    return "\n".join(lines)


@server.tool()
def wiki_graph(identifier: str, depth: int = 1) -> str:
    """Explore the link graph around a document.

    Returns the document's neighbors (backlinks + outgoing links) resolved to
    actual documents, traversable up to `depth` hops. Use this to understand
    how a topic connects to the rest of the wiki.

    Args:
        identifier: Path, title, or Zettelkasten ID of the starting document.
        depth: How many hops to traverse (1 = direct, 2 = neighbors of neighbors). Max 3.
    """
    depth = min(depth, 3)
    result = _get_search().graph_neighbors(identifier, depth=depth)
    if "error" in result:
        return result["error"]

    center = result["center"]
    lines = [f"Graph around: {center.get('title') or center['path']}"]
    lines.append(f"Nodes: {len(result['nodes'])}, Edges: {len(result['edges'])}")
    lines.append("")

    for node in sorted(result["nodes"], key=lambda n: n["depth"]):
        title = node.get("title") or Path(node["path"]).stem
        zid = f" [{node.get('zettel_id')}]" if node.get("zettel_id") else ""
        marker = " (center)" if node["depth"] == 0 else f" (depth {node['depth']})"
        lines.append(f"  {title}{zid}{marker}")
        lines.append(f"    {node['path']}")

    if result["edges"]:
        lines.append("")
        lines.append("Connections:")
        id_to_title = {n["id"]: n.get("title") or Path(n["path"]).stem for n in result["nodes"]}
        for edge in result["edges"]:
            src = id_to_title.get(edge["source"], "?")
            tgt = id_to_title.get(edge["target"], "?")
            lines.append(f"  {src} -> {tgt}")

    return "\n".join(lines)


@server.tool()
def wiki_orphans() -> str:
    """Find documents with no incoming or outgoing links.

    Useful for wiki maintenance — orphans are notes that aren't connected to
    anything and may need linking or cleanup.
    """
    results = _get_search().orphans()
    if not results:
        return "No orphans found. Every note is connected."
    lines = [f"Found {len(results)} orphaned document(s):", ""]
    for r in results:
        title = r.title or Path(r.path).stem
        zid = f" [{r.zettel_id}]" if r.zettel_id else ""
        lines.append(f"  {title}{zid}")
        lines.append(f"    {r.path}")
    return "\n".join(lines)


@server.tool()
def wiki_resolve_id(zettel_id: str) -> str:
    """Resolve a Zettelkasten ID to a file path.

    Args:
        zettel_id: The Zettelkasten timestamp ID (e.g. 202604161430).
    """
    idx = _get_index()
    idx.sync()
    path = idx.resolve_id(zettel_id)
    return path or f"No document found with ID: {zettel_id}"


@server.tool()
def wiki_index(force: bool = False) -> str:
    """Synchronize the search index with the filesystem.

    Call this after syncing files, or if search results seem stale.

    Args:
        force: If true, re-index all documents regardless of changes.
    """
    idx = _get_index()
    stats = idx.sync(force=force)
    return f"Indexed: {stats['indexed']}, Removed: {stats['removed']}, Unchanged: {stats['unchanged']}"


@server.tool()
def wiki_create_note(title: str, template: str = "default", folder: str | None = None) -> str:
    """Create a new wiki note from a template.

    Args:
        title: Title for the new note.
        template: Template name (default: "default").
        folder: Optional subfolder to create the note in.
    """
    config = load_config()
    path = create_note(config, title=title, template_name=template, subfolder=folder)
    return f"Created: {path}"


@server.tool()
def wiki_stamp(path: str, zettel_id: str | None = None) -> str:
    """Add or update a Zettelkasten ID in a document's frontmatter.

    If the document has a created date, the ID is derived from it.

    Args:
        path: Path to the document.
        zettel_id: Optional explicit ID to assign.
    """
    zid = stamp_document(Path(path), zettel_id=zettel_id)
    return f"Stamped with ID: {zid}"


@server.tool()
def wiki_stamp_all(directory: str | None = None) -> str:
    """Stamp all markdown files in a directory with Zettelkasten IDs.

    Skips files that already have an ID. Useful for onboarding existing notes
    into the wiki.

    Args:
        directory: Directory to scan. Defaults to the wiki root.
    """
    from .templates import batch_stamp

    config = load_config()
    target = Path(directory) if directory else config.root
    files = sorted(target.rglob("*.md"))
    if not files:
        return "No markdown files found."
    results = batch_stamp(files)
    lines = [f"Stamped {len(results)} file(s):"]
    for path, zid in results:
        lines.append(f"  {path} -> {zid}")
    return "\n".join(lines)


@server.tool()
def wiki_list_templates() -> str:
    """List available note templates."""
    config = load_config()
    templates = list_templates(config)
    if not templates:
        return "No templates found."
    return "\n".join(f"- {t.stem}" for t in templates)


@server.tool()
def wiki_generate_id() -> str:
    """Generate a new Zettelkasten timestamp ID for the current time."""
    return generate_zettel_id()


def main() -> None:
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
