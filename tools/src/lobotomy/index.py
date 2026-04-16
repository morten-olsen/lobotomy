"""SQLite index with FTS5 and sqlite-vec for the wiki."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
import sqlite_vec

from .config import WikiConfig
from .embeddings import embed_texts, get_dimension
from .parser import parse_document

if TYPE_CHECKING:
    from .parser import ParsedDocument


def _file_mtime(path: Path) -> float:
    """Get file modification time for change detection."""
    return path.stat().st_mtime


def _serialize_vec(vec: np.ndarray) -> bytes:
    """Serialize a numpy vector for sqlite-vec."""
    return vec.astype(np.float32).tobytes()


class WikiIndex:
    """Manages the SQLite index for wiki documents."""

    def __init__(self, config: WikiConfig) -> None:
        self.config = config
        self.db_path = config.db_path
        self._conn: sqlite3.Connection | None = None

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = self._open()
        return self._conn

    def _open(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.db_path))
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        self._ensure_schema(conn)
        return conn

    def _ensure_schema(self, conn: sqlite3.Connection) -> None:
        dim = get_dimension(self.config.embedding_model)

        conn.executescript(f"""
            CREATE TABLE IF NOT EXISTS documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                zettel_id TEXT,
                path TEXT NOT NULL UNIQUE,
                title TEXT,
                mtime REAL NOT NULL,
                body TEXT NOT NULL DEFAULT '',
                created_date TEXT,
                modified_date TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_documents_zettel_id
                ON documents(zettel_id) WHERE zettel_id IS NOT NULL;

            CREATE TABLE IF NOT EXISTS tags (
                doc_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
                tag TEXT NOT NULL,
                PRIMARY KEY (doc_id, tag)
            );

            CREATE INDEX IF NOT EXISTS idx_tags_tag ON tags(tag);

            CREATE TABLE IF NOT EXISTS links (
                source_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
                target TEXT NOT NULL,
                PRIMARY KEY (source_id, target)
            );

            CREATE INDEX IF NOT EXISTS idx_links_target ON links(target);

            CREATE TABLE IF NOT EXISTS chunks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                doc_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
                heading_path TEXT NOT NULL DEFAULT '',
                content TEXT NOT NULL,
                start_line INTEGER,
                end_line INTEGER
            );

            -- FTS indexes chunk content plus document title and tags for
            -- combined full-text search across all textual metadata.
            CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
                content,
                doc_title,
                doc_tags,
                content='',
                tokenize='porter unicode61'
            );

            CREATE VIRTUAL TABLE IF NOT EXISTS chunks_vec USING vec0(
                id INTEGER PRIMARY KEY,
                embedding float[{dim}]
            );

            CREATE TABLE IF NOT EXISTS meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
        """)

        # Store model info so we can detect model changes
        conn.execute(
            "INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)",
            ("embedding_model", self.config.embedding_model),
        )
        conn.execute(
            "INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)",
            ("embedding_dim", str(dim)),
        )
        conn.commit()

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    def _glob_documents(self) -> list[Path]:
        """Find all wiki documents matching config patterns."""
        root = self.config.root.resolve()
        files: set[Path] = set()
        for pattern in self.config.include:
            files.update(root.glob(pattern))

        # Filter exclusions
        excluded: set[Path] = set()
        for pattern in self.config.exclude:
            excluded.update(root.glob(pattern))

        return sorted(files - excluded)

    def _needs_update(self, path: Path) -> tuple[bool, float]:
        """Check if a file needs (re-)indexing. Returns (needs_update, mtime)."""
        mtime = _file_mtime(path)
        row = self.conn.execute(
            "SELECT mtime FROM documents WHERE path = ?",
            (str(path),),
        ).fetchone()
        if row is None:
            return True, mtime
        return mtime > row["mtime"], mtime

    def _remove_document(self, path: str) -> None:
        """Remove a document and all its related data."""
        row = self.conn.execute(
            "SELECT id FROM documents WHERE path = ?", (path,)
        ).fetchone()
        if not row:
            return
        doc_id = row["id"]
        # Get chunk IDs for FTS/vec cleanup
        chunks = self.conn.execute(
            "SELECT id, content FROM chunks WHERE doc_id = ?", (doc_id,)
        ).fetchall()
        # Get doc metadata for FTS delete
        doc = self.conn.execute(
            "SELECT title FROM documents WHERE id = ?", (doc_id,)
        ).fetchone()
        tags_str = " ".join(
            r["tag"] for r in self.conn.execute(
                "SELECT tag FROM tags WHERE doc_id = ?", (doc_id,)
            ).fetchall()
        )
        for chunk in chunks:
            self.conn.execute(
                "INSERT INTO chunks_fts(chunks_fts, rowid, content, doc_title, doc_tags) "
                "VALUES('delete', ?, ?, ?, ?)",
                (chunk["id"], chunk["content"], doc["title"] or "", tags_str),
            )
            self.conn.execute("DELETE FROM chunks_vec WHERE id = ?", (chunk["id"],))
        self.conn.execute("DELETE FROM documents WHERE id = ?", (doc_id,))

    def _index_document(self, doc: ParsedDocument, mtime: float) -> None:
        """Index a single parsed document."""
        path_str = str(doc.path)

        # Remove old data if re-indexing
        self._remove_document(path_str)

        # Insert document
        created = str(doc.frontmatter.get("created", "")) or None
        modified = str(doc.frontmatter.get("modified", "")) or None
        cur = self.conn.execute(
            "INSERT INTO documents(zettel_id, path, title, mtime, body, created_date, modified_date) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (doc.zettel_id, path_str, doc.title, mtime, doc.body, created, modified),
        )
        doc_id = cur.lastrowid

        # Tags
        for tag in doc.tags:
            self.conn.execute(
                "INSERT OR IGNORE INTO tags(doc_id, tag) VALUES (?, ?)",
                (doc_id, tag),
            )

        # Links
        for link in doc.outgoing_links:
            self.conn.execute(
                "INSERT OR IGNORE INTO links(source_id, target) VALUES (?, ?)",
                (doc_id, link),
            )

        # Chunks + FTS + embeddings
        if doc.chunks:
            tags_str = " ".join(doc.tags)
            title_str = doc.title or ""
            texts = []
            chunk_ids = []
            for chunk in doc.chunks:
                heading_path = " > ".join(chunk.heading_path)
                cur = self.conn.execute(
                    "INSERT INTO chunks(doc_id, heading_path, content, start_line, end_line) VALUES (?, ?, ?, ?, ?)",
                    (doc_id, heading_path, chunk.content, chunk.start_line, chunk.end_line),
                )
                cid = cur.lastrowid
                chunk_ids.append(cid)
                # FTS — include title and tags so they're searchable
                self.conn.execute(
                    "INSERT INTO chunks_fts(rowid, content, doc_title, doc_tags) VALUES (?, ?, ?, ?)",
                    (cid, chunk.content, title_str, tags_str),
                )
                # Prepend heading context for embedding
                embed_text = f"{heading_path}: {chunk.content}" if heading_path else chunk.content
                texts.append(embed_text)

            # Batch embed
            vectors = embed_texts(texts, self.config.embedding_model)
            for cid, vec in zip(chunk_ids, vectors):
                self.conn.execute(
                    "INSERT INTO chunks_vec(id, embedding) VALUES (?, ?)",
                    (cid, _serialize_vec(vec)),
                )

    def sync(self, force: bool = False) -> dict[str, int]:
        """Synchronize the index with the filesystem.

        Returns counts: {"indexed": n, "removed": n, "unchanged": n}
        """
        disk_files = {str(p): p for p in self._glob_documents()}
        stats = {"indexed": 0, "removed": 0, "unchanged": 0}

        # Remove documents no longer on disk
        db_paths = {
            row["path"]
            for row in self.conn.execute("SELECT path FROM documents").fetchall()
        }
        for gone in db_paths - set(disk_files.keys()):
            self._remove_document(gone)
            stats["removed"] += 1

        # Index new or changed documents
        for path_str, path in disk_files.items():
            needs_update, mtime = self._needs_update(path)
            if force or needs_update:
                doc = parse_document(path)
                self._index_document(doc, mtime)
                stats["indexed"] += 1
            else:
                stats["unchanged"] += 1

        self.conn.commit()
        return stats

    def resolve_id(self, zettel_id: str) -> str | None:
        """Resolve a Zettelkasten ID to a file path."""
        row = self.conn.execute(
            "SELECT path FROM documents WHERE zettel_id = ?", (zettel_id,)
        ).fetchone()
        return row["path"] if row else None

    def resolve_path(self, path: str) -> dict | None:
        """Get document info by path."""
        row = self.conn.execute(
            "SELECT id, zettel_id, path, title FROM documents WHERE path = ?",
            (path,),
        ).fetchone()
        return dict(row) if row else None
