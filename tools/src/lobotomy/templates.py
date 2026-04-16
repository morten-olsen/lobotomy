"""Template management and Zettelkasten ID generation."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from .config import WikiConfig


def generate_zettel_id(dt: datetime | None = None) -> str:
    """Generate a Zettelkasten timestamp ID (YYYYMMDDHHmm)."""
    dt = dt or datetime.now(timezone.utc)
    return dt.strftime("%Y%m%d%H%M")


def list_templates(config: WikiConfig) -> list[Path]:
    """List available templates."""
    tpl_dir = config.templates_path
    if not tpl_dir.is_dir():
        return []
    return sorted(tpl_dir.glob("*.md"))


def render_template(
    template_path: Path,
    title: str,
    zettel_id: str | None = None,
    extra: dict[str, str] | None = None,
) -> str:
    """Render a template with variable substitution."""
    now = datetime.now(timezone.utc)
    zettel_id = zettel_id or generate_zettel_id(now)
    now_iso = now.strftime("%Y-%m-%d")

    variables = {
        "id": zettel_id,
        "title": title,
        "created": now_iso,
        "modified": now_iso,
    }
    if extra:
        variables.update(extra)

    content = template_path.read_text(encoding="utf-8")
    for key, value in variables.items():
        content = content.replace("{{" + key + "}}", value)
    return content


def create_note(
    config: WikiConfig,
    title: str,
    template_name: str = "default",
    subfolder: str | None = None,
    zettel_id: str | None = None,
) -> Path:
    """Create a new note from a template.

    Returns the path to the created file.
    """
    tpl_path = config.templates_path / f"{template_name}.md"
    if not tpl_path.is_file():
        raise FileNotFoundError(f"Template not found: {tpl_path}")

    now = datetime.now(timezone.utc)
    zid = zettel_id or generate_zettel_id(now)
    content = render_template(tpl_path, title=title, zettel_id=zid)

    # Filename: ID + slugified title
    slug = title.lower().replace(" ", "-")
    # Remove non-alphanumeric chars except hyphens
    slug = "".join(c for c in slug if c.isalnum() or c == "-")
    filename = f"{zid}-{slug}.md"

    target_dir = config.root
    if subfolder:
        target_dir = target_dir / subfolder
        target_dir.mkdir(parents=True, exist_ok=True)

    out_path = target_dir / filename
    out_path.write_text(content, encoding="utf-8")
    return out_path


def stamp_document(path: Path, zettel_id: str | None = None) -> str:
    """Add or update a Zettelkasten ID in a document's frontmatter.

    If the document has a 'created' date, derives the ID from it.
    Returns the assigned ID.
    """
    import yaml

    text = path.read_text(encoding="utf-8")

    # Parse frontmatter
    from .parser import parse_frontmatter
    meta, body = parse_frontmatter(text)

    if not meta:
        meta = {}

    # Determine ID
    if zettel_id:
        zid = zettel_id
    elif meta.get("id"):
        return str(meta["id"])  # already stamped
    elif meta.get("created"):
        # Try to derive from created date
        try:
            dt = datetime.fromisoformat(str(meta["created"]))
            zid = generate_zettel_id(dt)
        except (ValueError, TypeError):
            zid = generate_zettel_id()
    else:
        zid = generate_zettel_id()

    meta["id"] = zid
    if "modified" in meta:
        meta["modified"] = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Reconstruct file
    frontmatter_str = yaml.dump(meta, default_flow_style=False, sort_keys=False).strip()
    new_text = f"---\n{frontmatter_str}\n---\n{body}"
    path.write_text(new_text, encoding="utf-8")
    return zid


def batch_stamp(paths: list[Path]) -> list[tuple[Path, str]]:
    """Stamp multiple documents. Skips files that already have IDs.

    Returns list of (path, assigned_id) for each file that was stamped.
    """
    results = []
    for path in paths:
        if not path.is_file():
            continue
        zid = stamp_document(path)
        results.append((path, zid))
    return results
