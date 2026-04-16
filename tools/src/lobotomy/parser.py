"""Markdown document parser — frontmatter, wikilinks, headings."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

# Matches [[target]] or [[target|alias]]
_WIKILINK_RE = re.compile(r"\[\[([^\]|]+)(?:\|[^\]]+)?\]\]")

# Matches [text](target.md) style markdown links to local files
_MDLINK_RE = re.compile(r"\[([^\]]*)\]\(([^)]+\.md)\)")

# Matches YAML frontmatter delimited by ---
_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)

# Matches markdown headings
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)


@dataclass
class DocumentChunk:
    """A section of a document, used for embedding."""

    heading_path: list[str]  # e.g. ["Architecture", "Details"]
    content: str
    start_line: int
    end_line: int


@dataclass
class ParsedDocument:
    path: Path
    frontmatter: dict = field(default_factory=dict)
    body: str = ""
    chunks: list[DocumentChunk] = field(default_factory=list)

    @property
    def zettel_id(self) -> str | None:
        return self.frontmatter.get("id")

    @property
    def title(self) -> str | None:
        return self.frontmatter.get("title")

    @property
    def tags(self) -> list[str]:
        raw = self.frontmatter.get("tags", [])
        if isinstance(raw, str):
            return [t.strip().lstrip("#") for t in raw.split(",") if t.strip()]
        if isinstance(raw, list):
            return [str(t).strip().lstrip("#") for t in raw]
        return []

    @property
    def outgoing_links(self) -> list[str]:
        """Extract all wiki-style and markdown-style links."""
        links: list[str] = []
        links.extend(_WIKILINK_RE.findall(self.body))
        links.extend(target for _, target in _MDLINK_RE.findall(self.body))
        return links


def parse_frontmatter(text: str) -> tuple[dict, str]:
    """Split YAML frontmatter from body. Returns (metadata, body)."""
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return {}, text
    try:
        meta = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError:
        meta = {}
    body = text[m.end():]
    return meta, body


def chunk_by_heading(body: str) -> list[DocumentChunk]:
    """Split markdown body into chunks at heading boundaries.

    Each chunk carries its heading hierarchy for context.
    """
    lines = body.split("\n")
    chunks: list[DocumentChunk] = []
    heading_stack: list[tuple[int, str]] = []  # (level, title)
    current_lines: list[str] = []
    current_start = 0

    def _flush(end_line: int) -> None:
        text = "\n".join(current_lines).strip()
        if text:
            chunks.append(DocumentChunk(
                heading_path=[title for _, title in heading_stack],
                content=text,
                start_line=current_start,
                end_line=end_line,
            ))

    for i, line in enumerate(lines):
        m = _HEADING_RE.match(line)
        if m:
            _flush(i)
            level = len(m.group(1))
            title = m.group(2).strip()
            # Pop headings at same or deeper level
            while heading_stack and heading_stack[-1][0] >= level:
                heading_stack.pop()
            heading_stack.append((level, title))
            current_lines = [line]
            current_start = i
        else:
            current_lines.append(line)

    _flush(len(lines))
    return chunks


def parse_document(path: Path) -> ParsedDocument:
    """Parse a markdown file into structured representation."""
    text = path.read_text(encoding="utf-8")
    frontmatter, body = parse_frontmatter(text)
    chunks = chunk_by_heading(body)

    # If no headings found, treat entire body as one chunk
    if not chunks and body.strip():
        chunks = [DocumentChunk(
            heading_path=[],
            content=body.strip(),
            start_line=0,
            end_line=len(body.split("\n")),
        )]

    return ParsedDocument(
        path=path,
        frontmatter=frontmatter,
        body=body,
        chunks=chunks,
    )
