"""Load wiki.toml configuration."""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

if sys.version_info >= (3, 12):
    import tomllib
else:
    try:
        import tomllib
    except ModuleNotFoundError:
        import tomli as tomllib  # type: ignore[no-redef]


@dataclass
class WikiConfig:
    root: Path
    include: list[str] = field(default_factory=lambda: ["**/*.md"])
    exclude: list[str] = field(default_factory=list)
    database: str = ".wiki/index.db"
    embedding_model: str = "all-MiniLM-L6-v2"
    chunk_strategy: str = "heading"
    max_chunk_tokens: int = 512
    templates_dir: str = "templates"

    @property
    def db_path(self) -> Path:
        return self.root / self.database

    @property
    def templates_path(self) -> Path:
        return self.root / self.templates_dir


def find_config(start: Path | None = None) -> Path:
    """Walk up from *start* looking for wiki.toml."""
    current = (start or Path.cwd()).resolve()
    while True:
        candidate = current / "wiki.toml"
        if candidate.is_file():
            return candidate
        if current.parent == current:
            raise FileNotFoundError("No wiki.toml found in any parent directory")
        current = current.parent


def load_config(path: Path | None = None) -> WikiConfig:
    """Load configuration from wiki.toml."""
    config_path = path or find_config()
    with open(config_path, "rb") as f:
        raw = tomllib.load(f)

    root = config_path.parent
    wiki = raw.get("wiki", {})
    index = raw.get("index", {})
    embeddings = raw.get("embeddings", {})
    templates = raw.get("templates", {})

    return WikiConfig(
        root=root / wiki.get("root", "."),
        include=wiki.get("include", ["**/*.md"]),
        exclude=wiki.get("exclude", []),
        database=index.get("database", ".wiki.db"),
        embedding_model=embeddings.get("model", "all-MiniLM-L6-v2"),
        chunk_strategy=embeddings.get("chunk_strategy", "heading"),
        max_chunk_tokens=embeddings.get("max_chunk_tokens", 512),
        templates_dir=templates.get("directory", "templates"),
    )
