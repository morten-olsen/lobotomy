"""CLI interface for Lobotomy."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click

from .config import load_config


@click.group()
@click.option("--config", "config_path", type=click.Path(exists=True, path_type=Path), default=None, help="Path to wiki.toml")
@click.pass_context
def cli(ctx: click.Context, config_path: Path | None) -> None:
    """Lobotomy — you don't need to remember, it does."""
    ctx.ensure_object(dict)
    ctx.obj["config_path"] = config_path


def _get_config(ctx: click.Context):
    return load_config(ctx.obj.get("config_path"))


@cli.command()
@click.option("--force", is_flag=True, help="Re-index all documents, ignoring cache")
@click.pass_context
def index(ctx: click.Context, force: bool) -> None:
    """Synchronize the search index with the filesystem."""
    from .index import WikiIndex

    config = _get_config(ctx)
    idx = WikiIndex(config)
    try:
        stats = idx.sync(force=force)
        click.echo(f"Indexed: {stats['indexed']}, Removed: {stats['removed']}, Unchanged: {stats['unchanged']}")
    finally:
        idx.close()


@cli.command()
@click.argument("query", required=False, default=None)
@click.option("--tag", "-t", "tags", multiple=True, help="Filter by tag (repeatable, AND logic)")
@click.option("--after", default=None, help="ISO date (inclusive), e.g. 2026-01-01")
@click.option("--before", default=None, help="ISO date (inclusive), e.g. 2026-12-31")
@click.option("--date-field", type=click.Choice(["created", "modified"]), default="created", help="Date field for range filter")
@click.option("--mode", type=click.Choice(["hybrid", "semantic", "fulltext"]), default="hybrid", help="Search mode (when query provided)")
@click.option("--limit", "-n", default=10, help="Max results")
@click.option("--json-output", "as_json", is_flag=True, help="Output as JSON")
@click.pass_context
def search(
    ctx: click.Context,
    query: str | None,
    tags: tuple[str, ...],
    after: str | None,
    before: str | None,
    date_field: str,
    mode: str,
    limit: int,
    as_json: bool,
) -> None:
    """Search the wiki. Combine query, tags, and date filters freely.

    \b
    Examples:
      wiki search "kubernetes"
      wiki search -t devops -t kubernetes
      wiki search "deployment" -t devops --after 2026-01-01
      wiki search --after 2026-04-01
    """
    from .index import WikiIndex
    from .search import WikiSearch

    if not query and not tags and not after and not before:
        raise click.UsageError("Provide at least a query, --tag, --after, or --before.")

    config = _get_config(ctx)
    idx = WikiIndex(config)
    try:
        ws = WikiSearch(idx)
        tag_list = list(tags) if tags else None

        if mode in ("semantic", "fulltext") and query:
            if mode == "semantic":
                results = ws.semantic(query, limit=limit)
            else:
                results = ws.fulltext(query, limit=limit)
        else:
            results = ws.hybrid(
                query=query, tags=tag_list, after=after, before=before,
                date_field=date_field, limit=limit,
            )

        if as_json:
            click.echo(json.dumps([
                {"path": r.path, "title": r.title, "zettel_id": r.zettel_id,
                 "score": round(r.score, 4), "snippet": r.snippet, "heading": r.heading_path,
                 "match_type": r.match_type}
                for r in results
            ], indent=2))
        else:
            if not results:
                click.echo("No results found.")
                return
            for i, r in enumerate(results, 1):
                title = r.title or Path(r.path).stem
                zid = f" [{r.zettel_id}]" if r.zettel_id else ""
                click.echo(f"{i}. {title}{zid} ({r.match_type}, score: {r.score:.3f})")
                click.echo(f"   {r.path}")
                if r.heading_path:
                    click.echo(f"   § {r.heading_path}")
                click.echo()
    finally:
        idx.close()


@cli.command()
@click.pass_context
def tags(ctx: click.Context) -> None:
    """List all tags and their document counts."""
    from .index import WikiIndex
    from .search import WikiSearch

    config = _get_config(ctx)
    idx = WikiIndex(config)
    try:
        ws = WikiSearch(idx)
        tag_list = ws.list_tags()
        if not tag_list:
            click.echo("No tags found.")
            return
        for t, count in tag_list:
            click.echo(f"  #{t}  ({count})")
    finally:
        idx.close()


@cli.command()
@click.pass_context
def stats(ctx: click.Context) -> None:
    """Show wiki health and structure overview."""
    from .index import WikiIndex
    from .search import WikiSearch

    config = _get_config(ctx)
    idx = WikiIndex(config)
    try:
        ws = WikiSearch(idx)
        s = ws.stats()
        click.echo(f"Documents: {s['documents']}")
        click.echo(f"  with tags: {s['documents_with_tags']}")
        click.echo(f"  with outgoing links: {s['documents_with_links']}")
        click.echo(f"  orphans (no links): {s['orphan_count']}")
        click.echo(f"  stale (>90 days): {s['stale_count']}")
        click.echo(f"Unique tags: {s['unique_tags']}")
        click.echo(f"Total links: {s['total_links']}")
        if s["top_tags"]:
            click.echo()
            click.echo("Top tags:")
            for tag, count in s["top_tags"]:
                click.echo(f"  #{tag} ({count})")
        if s["most_linked"]:
            click.echo()
            click.echo("Most linked-to (hubs):")
            for target, count in s["most_linked"]:
                click.echo(f"  {target} ({count} incoming)")
    finally:
        idx.close()


@cli.command()
@click.argument("identifier")
@click.option("--depth", "-d", default=1, help="How many hops to traverse (1-3)")
@click.pass_context
def graph(ctx: click.Context, identifier: str, depth: int) -> None:
    """Explore the link graph around a document."""
    from .index import WikiIndex
    from .search import WikiSearch

    config = _get_config(ctx)
    idx = WikiIndex(config)
    try:
        ws = WikiSearch(idx)
        result = ws.graph_neighbors(identifier, depth=min(depth, 3))
        if "error" in result:
            click.echo(result["error"], err=True)
            sys.exit(1)
        center = result["center"]
        click.echo(f"Graph around: {center.get('title') or center['path']}")
        click.echo(f"Nodes: {len(result['nodes'])}, Edges: {len(result['edges'])}")
        click.echo()
        for node in sorted(result["nodes"], key=lambda n: n["depth"]):
            title = node.get("title") or Path(node["path"]).stem
            zid = f" [{node.get('zettel_id')}]" if node.get("zettel_id") else ""
            marker = " *" if node["depth"] == 0 else f" (depth {node['depth']})"
            click.echo(f"  {title}{zid}{marker}")
        if result["edges"]:
            click.echo()
            id_to_title = {n["id"]: n.get("title") or Path(n["path"]).stem for n in result["nodes"]}
            for edge in result["edges"]:
                src = id_to_title.get(edge["source"], "?")
                tgt = id_to_title.get(edge["target"], "?")
                click.echo(f"  {src} -> {tgt}")
    finally:
        idx.close()


@cli.command()
@click.pass_context
def orphans(ctx: click.Context) -> None:
    """Find documents with no links to or from anything."""
    from .index import WikiIndex
    from .search import WikiSearch

    config = _get_config(ctx)
    idx = WikiIndex(config)
    try:
        ws = WikiSearch(idx)
        results = ws.orphans()
        if not results:
            click.echo("No orphans. Every note is connected.")
            return
        click.echo(f"Found {len(results)} orphan(s):")
        for r in results:
            title = r.title or Path(r.path).stem
            zid = f" [{r.zettel_id}]" if r.zettel_id else ""
            click.echo(f"  {title}{zid}  {r.path}")
    finally:
        idx.close()


@cli.command()
@click.argument("title")
@click.option("--template", "-t", default="default", help="Template name")
@click.option("--folder", "-f", default=None, help="Subfolder to create in")
@click.pass_context
def new(ctx: click.Context, title: str, template: str, folder: str | None) -> None:
    """Create a new note from a template."""
    from .templates import create_note

    config = _get_config(ctx)
    path = create_note(config, title=title, template_name=template, subfolder=folder)
    click.echo(f"Created: {path}")


@cli.command()
@click.argument("file", type=click.Path(exists=True, path_type=Path))
@click.option("--id", "zettel_id", default=None, help="Explicit Zettelkasten ID to assign")
@click.pass_context
def stamp(ctx: click.Context, file: Path, zettel_id: str | None) -> None:
    """Add a Zettelkasten ID to an existing document."""
    from .templates import stamp_document

    zid = stamp_document(file, zettel_id=zettel_id)
    click.echo(f"Stamped {file} with ID: {zid}")


@cli.command("stamp-all")
@click.argument("directory", type=click.Path(exists=True, path_type=Path), default=".")
@click.pass_context
def stamp_all(ctx: click.Context, directory: Path) -> None:
    """Stamp all markdown files in a directory with Zettelkasten IDs.

    Skips files that already have an ID. Useful for onboarding existing notes.
    """
    from .templates import batch_stamp

    files = sorted(directory.rglob("*.md"))
    if not files:
        click.echo("No markdown files found.")
        return
    results = batch_stamp(files)
    for path, zid in results:
        click.echo(f"  {path} -> {zid}")
    click.echo(f"\nStamped {len(results)} file(s).")


@cli.command("resolve")
@click.argument("identifier")
@click.pass_context
def resolve_id(ctx: click.Context, identifier: str) -> None:
    """Resolve a Zettelkasten ID to a file path."""
    from .index import WikiIndex

    config = _get_config(ctx)
    idx = WikiIndex(config)
    try:
        idx.sync()
        path = idx.resolve_id(identifier)
        if path:
            click.echo(path)
        else:
            click.echo(f"No document found with ID: {identifier}", err=True)
            sys.exit(1)
    finally:
        idx.close()


@cli.command("templates")
@click.pass_context
def list_templates(ctx: click.Context) -> None:
    """List available note templates."""
    from .templates import list_templates as _list

    config = _get_config(ctx)
    templates = _list(config)
    if not templates:
        click.echo("No templates found.")
        return
    for t in templates:
        click.echo(f"  {t.stem}")
