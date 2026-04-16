"""Search across the wiki index — semantic, full-text, tags, graph."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .embeddings import embed_query
from .index import WikiIndex, _serialize_vec


def _sanitize_fts_query(query: str) -> str:
    """Escape a user query for safe use in FTS5 MATCH.

    Wraps each term in double quotes to prevent FTS5 syntax characters
    (-, *, OR, AND, NOT, parentheses, etc.) from being interpreted as operators.
    """
    # Split on whitespace, strip punctuation-only tokens, quote each term
    terms = []
    for token in query.split():
        # Remove surrounding punctuation but keep internal chars
        cleaned = token.strip("\"'()[]{}!@#$%^&*,;:")
        if cleaned:
            # Escape any internal double quotes
            cleaned = cleaned.replace('"', '""')
            terms.append(f'"{cleaned}"')
    return " ".join(terms)


@dataclass
class SearchResult:
    path: str
    title: str | None
    zettel_id: str | None
    score: float
    snippet: str
    heading_path: str
    match_type: str  # "semantic", "fulltext", "tag", "hybrid", "backlink"


def _dedup_by_document(rows: list[dict], score_key: str = "score") -> list[dict]:
    """Keep only the best-scoring chunk per document."""
    best: dict[int, dict] = {}
    for row in rows:
        doc_id = row["doc_id"]
        if doc_id not in best or row[score_key] > best[doc_id][score_key]:
            best[doc_id] = row
    return list(best.values())


def _rrf_fuse(
    ranked_lists: list[list[SearchResult]],
    k: int = 60,
    limit: int = 10,
) -> list[SearchResult]:
    """Reciprocal Rank Fusion across multiple ranked result lists.

    Each result gets score = sum(1 / (k + rank)) across all lists it appears in.
    k=60 is the standard constant from the original RRF paper.
    """
    scores: dict[str, float] = {}
    best_result: dict[str, SearchResult] = {}

    for ranked in ranked_lists:
        for rank, r in enumerate(ranked, 1):
            scores[r.path] = scores.get(r.path, 0.0) + 1.0 / (k + rank)
            # Keep the result object with the highest individual score for snippet
            if r.path not in best_result or r.score > best_result[r.path].score:
                best_result[r.path] = r

    fused = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:limit]
    results = []
    for path, score in fused:
        r = best_result[path]
        results.append(SearchResult(
            path=r.path,
            title=r.title,
            zettel_id=r.zettel_id,
            score=score,
            snippet=r.snippet,
            heading_path=r.heading_path,
            match_type="hybrid",
        ))
    return results


class WikiSearch:
    """Query interface over a WikiIndex."""

    def __init__(self, index: WikiIndex) -> None:
        self.index = index
        self.config = index.config

    def _ensure_synced(self) -> None:
        """Lazy sync: update any changed files before querying."""
        self.index.sync()

    def semantic(self, query: str, limit: int = 10) -> list[SearchResult]:
        """Semantic similarity search using embeddings."""
        self._ensure_synced()
        vec = embed_query(query, self.config.embedding_model)
        rows = self.index.conn.execute(
            """
            SELECT v.id, v.distance, c.content, c.heading_path, c.doc_id,
                   d.path, d.title, d.zettel_id
            FROM chunks_vec v
            JOIN chunks c ON c.id = v.id
            JOIN documents d ON d.id = c.doc_id
            WHERE v.embedding MATCH ? AND k = ?
            ORDER BY v.distance
            """,
            (_serialize_vec(vec), limit * 3),  # fetch extra for dedup
        ).fetchall()

        # Convert to dicts for dedup
        scored = [
            {**dict(row), "score": 1.0 - row["distance"]}
            for row in rows
        ]
        deduped = _dedup_by_document(scored)
        deduped.sort(key=lambda r: r["score"], reverse=True)

        return [
            SearchResult(
                path=r["path"],
                title=r["title"],
                zettel_id=r["zettel_id"],
                score=r["score"],
                snippet=r["content"][:300],
                heading_path=r["heading_path"],
                match_type="semantic",
            )
            for r in deduped[:limit]
        ]

    def fulltext(self, query: str, limit: int = 10) -> list[SearchResult]:
        """Full-text search using FTS5.

        Searches chunk content, document titles, and tags together.
        FTS5 ranks matches across all columns.
        """
        self._ensure_synced()
        safe_query = _sanitize_fts_query(query)
        if not safe_query:
            return []
        rows = self.index.conn.execute(
            """
            SELECT c.id, c.content, c.heading_path, c.doc_id,
                   d.path, d.title, d.zettel_id,
                   fts.rank AS fts_rank
            FROM chunks_fts fts
            JOIN chunks c ON c.id = fts.rowid
            JOIN documents d ON d.id = c.doc_id
            WHERE chunks_fts MATCH ?
            ORDER BY fts.rank
            LIMIT ?
            """,
            (safe_query, limit * 3),  # fetch extra for dedup
        ).fetchall()

        scored = [
            {**dict(row), "score": -row["fts_rank"]}  # FTS5 rank is negative
            for row in rows
        ]
        deduped = _dedup_by_document(scored)
        deduped.sort(key=lambda r: r["score"], reverse=True)

        return [
            SearchResult(
                path=r["path"],
                title=r["title"],
                zettel_id=r["zettel_id"],
                score=r["score"],
                snippet=r["content"][:300],
                heading_path=r["heading_path"],
                match_type="fulltext",
            )
            for r in deduped[:limit]
        ]

    def by_tag(self, tag: str) -> list[SearchResult]:
        """Find all documents with a given tag."""
        self._ensure_synced()
        tag_clean = tag.lstrip("#")
        rows = self.index.conn.execute(
            """
            SELECT d.path, d.title, d.zettel_id, d.body
            FROM tags t
            JOIN documents d ON d.id = t.doc_id
            WHERE t.tag = ?
            ORDER BY d.title
            """,
            (tag_clean,),
        ).fetchall()

        return [
            SearchResult(
                path=row["path"],
                title=row["title"],
                zettel_id=row["zettel_id"],
                score=1.0,
                snippet=row["body"][:300],
                heading_path="",
                match_type="tag",
            )
            for row in rows
        ]

    def list_tags(self) -> list[tuple[str, int]]:
        """List all tags with document counts."""
        self._ensure_synced()
        rows = self.index.conn.execute(
            "SELECT tag, COUNT(*) as cnt FROM tags GROUP BY tag ORDER BY cnt DESC"
        ).fetchall()
        return [(row["tag"], row["cnt"]) for row in rows]

    def stats(self) -> dict:
        """Compute wiki-wide statistics."""
        self._ensure_synced()
        conn = self.index.conn

        doc_count = conn.execute("SELECT COUNT(*) as n FROM documents").fetchone()["n"]
        tag_count = conn.execute("SELECT COUNT(DISTINCT tag) as n FROM tags").fetchone()["n"]
        link_count = conn.execute("SELECT COUNT(*) as n FROM links").fetchone()["n"]
        tagged_docs = conn.execute("SELECT COUNT(DISTINCT doc_id) as n FROM tags").fetchone()["n"]
        linked_docs = conn.execute("SELECT COUNT(DISTINCT source_id) as n FROM links").fetchone()["n"]

        # Top tags
        top_tags = conn.execute(
            "SELECT tag, COUNT(*) as cnt FROM tags GROUP BY tag ORDER BY cnt DESC LIMIT 10"
        ).fetchall()

        # Most linked-to (hub notes)
        hubs = conn.execute(
            """
            SELECT l.target, COUNT(*) as cnt
            FROM links l
            GROUP BY l.target
            ORDER BY cnt DESC
            LIMIT 5
            """,
        ).fetchall()

        # Stale notes (not modified in 90+ days)
        stale = conn.execute(
            """
            SELECT COUNT(*) as n FROM documents
            WHERE modified_date IS NOT NULL
              AND modified_date < date('now', '-90 days')
            """,
        ).fetchone()["n"]

        # Orphan count
        orphan_count = len(self.orphans())

        return {
            "documents": doc_count,
            "unique_tags": tag_count,
            "total_links": link_count,
            "documents_with_tags": tagged_docs,
            "documents_with_links": linked_docs,
            "orphan_count": orphan_count,
            "stale_count": stale,
            "top_tags": [(r["tag"], r["cnt"]) for r in top_tags],
            "most_linked": [(r["target"], r["cnt"]) for r in hubs],
        }

    def _resolve_doc(self, identifier: str) -> dict | None:
        """Resolve a note identifier (path, title, zettel ID, or partial filename) to a document row."""
        # Try exact path
        row = self.index.conn.execute(
            "SELECT id, path, title, zettel_id FROM documents WHERE path = ?",
            (identifier,),
        ).fetchone()
        if row:
            return dict(row)
        # Try zettel ID
        row = self.index.conn.execute(
            "SELECT id, path, title, zettel_id FROM documents WHERE zettel_id = ?",
            (identifier,),
        ).fetchone()
        if row:
            return dict(row)
        # Try title match
        row = self.index.conn.execute(
            "SELECT id, path, title, zettel_id FROM documents WHERE title = ?",
            (identifier,),
        ).fetchone()
        if row:
            return dict(row)
        # Try partial path/title match
        row = self.index.conn.execute(
            "SELECT id, path, title, zettel_id FROM documents WHERE path LIKE ? OR title LIKE ?",
            (f"%{identifier}%", f"%{identifier}%"),
        ).fetchone()
        if row:
            return dict(row)
        return None

    def _backlink_docs(self, doc_id: int) -> list[dict]:
        """Get documents that link TO this document."""
        doc = self.index.conn.execute(
            "SELECT path, title, zettel_id FROM documents WHERE id = ?", (doc_id,)
        ).fetchone()
        if not doc:
            return []
        # Match against path filename, title, and zettel_id
        path_stem = Path(doc["path"]).stem
        matchers = [doc["path"], path_stem]
        if doc["title"]:
            matchers.append(doc["title"])
        if doc["zettel_id"]:
            matchers.append(doc["zettel_id"])

        conditions = " OR ".join("l.target LIKE ?" for _ in matchers)
        params = [f"%{m}%" for m in matchers]
        rows = self.index.conn.execute(
            f"""
            SELECT DISTINCT d.id, d.path, d.title, d.zettel_id
            FROM links l
            JOIN documents d ON d.id = l.source_id
            WHERE ({conditions}) AND d.id != ?
            """,
            [*params, doc_id],
        ).fetchall()
        return [dict(r) for r in rows]

    def _outgoing_docs(self, doc_id: int) -> list[dict]:
        """Get documents that this document links TO, resolved to actual docs."""
        link_rows = self.index.conn.execute(
            "SELECT target FROM links WHERE source_id = ?", (doc_id,)
        ).fetchall()
        results = []
        seen: set[int] = set()
        for link in link_rows:
            target = link["target"]
            resolved = self._resolve_doc(target)
            if resolved and resolved["id"] != doc_id and resolved["id"] not in seen:
                results.append(resolved)
                seen.add(resolved["id"])
        return results

    def graph_neighbors(self, identifier: str, depth: int = 1) -> dict:
        """Explore the graph around a document.

        Returns a dict with the center node plus all connected nodes up to `depth` hops,
        and the edges between them.

        Args:
            identifier: Path, title, or zettel ID of the starting document.
            depth: How many hops to traverse (1 = direct neighbors, 2 = neighbors of neighbors).
        """
        self._ensure_synced()
        center = self._resolve_doc(identifier)
        if not center:
            return {"error": f"Document not found: {identifier}"}

        nodes: dict[int, dict] = {center["id"]: {**center, "depth": 0}}
        edges: list[dict] = []
        frontier = {center["id"]}

        for d in range(1, depth + 1):
            next_frontier: set[int] = set()
            for doc_id in frontier:
                # Outgoing
                for linked in self._outgoing_docs(doc_id):
                    edges.append({"source": doc_id, "target": linked["id"], "direction": "outgoing"})
                    if linked["id"] not in nodes:
                        nodes[linked["id"]] = {**linked, "depth": d}
                        next_frontier.add(linked["id"])
                # Incoming
                for linker in self._backlink_docs(doc_id):
                    edges.append({"source": linker["id"], "target": doc_id, "direction": "incoming"})
                    if linker["id"] not in nodes:
                        nodes[linker["id"]] = {**linker, "depth": d}
                        next_frontier.add(linker["id"])
            frontier = next_frontier

        # Deduplicate edges
        seen_edges: set[tuple[int, int]] = set()
        unique_edges = []
        for e in edges:
            key = (min(e["source"], e["target"]), max(e["source"], e["target"]))
            if key not in seen_edges:
                seen_edges.add(key)
                unique_edges.append(e)

        return {
            "center": center,
            "nodes": list(nodes.values()),
            "edges": unique_edges,
        }

    def orphans(self) -> list[SearchResult]:
        """Find documents with no incoming or outgoing links."""
        self._ensure_synced()
        rows = self.index.conn.execute(
            """
            SELECT d.path, d.title, d.zettel_id, d.body
            FROM documents d
            WHERE d.id NOT IN (SELECT DISTINCT source_id FROM links)
              AND d.id NOT IN (
                  SELECT DISTINCT d2.id
                  FROM documents d2
                  JOIN links l ON l.target LIKE '%' || d2.title || '%'
                     OR l.target LIKE '%' || d2.zettel_id || '%'
                  WHERE d2.title IS NOT NULL OR d2.zettel_id IS NOT NULL
              )
            ORDER BY d.title
            """,
        ).fetchall()
        return [
            SearchResult(
                path=row["path"], title=row["title"], zettel_id=row["zettel_id"],
                score=0.0, snippet=row["body"][:300], heading_path="",
                match_type="orphan",
            )
            for row in rows
        ]

    def by_date_range(
        self,
        after: str | None = None,
        before: str | None = None,
        date_field: str = "created",
    ) -> list[SearchResult]:
        """Find documents within a date range.

        Args:
            after: ISO date string (inclusive). e.g. "2026-01-01"
            before: ISO date string (inclusive). e.g. "2026-12-31"
            date_field: "created" or "modified"
        """
        self._ensure_synced()
        col = "created_date" if date_field == "created" else "modified_date"
        conditions = [f"{col} IS NOT NULL"]
        params: list[str] = []
        if after:
            conditions.append(f"{col} >= ?")
            params.append(after)
        if before:
            conditions.append(f"{col} <= ?")
            params.append(before)

        where = " AND ".join(conditions)
        rows = self.index.conn.execute(
            f"""
            SELECT path, title, zettel_id, body, created_date, modified_date
            FROM documents
            WHERE {where}
            ORDER BY {col} DESC
            """,
            params,
        ).fetchall()

        return [
            SearchResult(
                path=row["path"],
                title=row["title"],
                zettel_id=row["zettel_id"],
                score=1.0,
                snippet=row["body"][:300],
                heading_path="",
                match_type="date_range",
            )
            for row in rows
        ]

    def _tag_matches(self, query: str) -> list[SearchResult]:
        """Find documents whose tags overlap with query terms.

        Used internally by hybrid search to boost tag-matching docs.
        """
        terms = [t.lower().strip() for t in query.split() if t.strip()]
        if not terms:
            return []

        placeholders = ",".join("?" for _ in terms)
        rows = self.index.conn.execute(
            f"""
            SELECT d.path, d.title, d.zettel_id, d.body,
                   COUNT(DISTINCT t.tag) as matching_tags
            FROM tags t
            JOIN documents d ON d.id = t.doc_id
            WHERE LOWER(t.tag) IN ({placeholders})
            GROUP BY d.id
            ORDER BY matching_tags DESC
            """,
            terms,
        ).fetchall()

        return [
            SearchResult(
                path=row["path"],
                title=row["title"],
                zettel_id=row["zettel_id"],
                score=float(row["matching_tags"]),
                snippet=row["body"][:300],
                heading_path="",
                match_type="tag",
            )
            for row in rows
        ]

    def _eligible_doc_ids(
        self,
        tags: list[str] | None = None,
        after: str | None = None,
        before: str | None = None,
        date_field: str = "created",
    ) -> set[int] | None:
        """Build a set of document IDs matching hard filters.

        Returns None if no filters are active (meaning all docs eligible).
        """
        if not tags and not after and not before:
            return None

        sets: list[set[int]] = []

        if tags:
            clean = [t.lstrip("#").lower() for t in tags]
            placeholders = ",".join("?" for _ in clean)
            rows = self.index.conn.execute(
                f"""
                SELECT doc_id FROM tags
                WHERE LOWER(tag) IN ({placeholders})
                GROUP BY doc_id
                HAVING COUNT(DISTINCT LOWER(tag)) = ?
                """,
                [*clean, len(clean)],
            ).fetchall()
            sets.append({r["doc_id"] for r in rows})

        if after or before:
            col = "created_date" if date_field == "created" else "modified_date"
            conditions = [f"{col} IS NOT NULL"]
            params: list[str] = []
            if after:
                conditions.append(f"{col} >= ?")
                params.append(after)
            if before:
                conditions.append(f"{col} <= ?")
                params.append(before)
            where = " AND ".join(conditions)
            rows = self.index.conn.execute(
                f"SELECT id FROM documents WHERE {where}", params
            ).fetchall()
            sets.append({r["id"] for r in rows})

        # Intersect all filter sets
        result = sets[0]
        for s in sets[1:]:
            result &= s
        return result

    def hybrid(
        self,
        query: str | None = None,
        tags: list[str] | None = None,
        after: str | None = None,
        before: str | None = None,
        date_field: str = "created",
        limit: int = 10,
    ) -> list[SearchResult]:
        """Unified search with optional filters.

        All parameters are optional — combine as needed:
        - query: semantic + full-text search terms
        - tags: require ALL listed tags (AND logic)
        - after/before: date range filter on created or modified date
        - date_field: "created" or "modified"

        When a query is provided, results are ranked by RRF across semantic,
        full-text, and tag-matching signals. Date and tag filters are applied
        as hard constraints on top of ranking.

        When no query is provided, returns filtered documents sorted by date.
        """
        self._ensure_synced()
        eligible = self._eligible_doc_ids(tags=tags, after=after, before=before, date_field=date_field)

        def _filter(results: list[SearchResult]) -> list[SearchResult]:
            if eligible is None:
                return results
            # We need doc_id to filter — look it up by path
            filtered = []
            for r in results:
                row = self.index.conn.execute(
                    "SELECT id FROM documents WHERE path = ?", (r.path,)
                ).fetchone()
                if row and row["id"] in eligible:
                    filtered.append(r)
            return filtered

        # If no query, just return filtered documents sorted by date
        if not query:
            if eligible is None:
                # No query, no filters — return recent documents
                eligible_ids = None
            else:
                eligible_ids = eligible

            col = "created_date" if date_field == "created" else "modified_date"
            if eligible_ids is not None:
                if not eligible_ids:
                    return []
                placeholders = ",".join("?" for _ in eligible_ids)
                rows = self.index.conn.execute(
                    f"""
                    SELECT path, title, zettel_id, body
                    FROM documents WHERE id IN ({placeholders})
                    ORDER BY {col} DESC LIMIT ?
                    """,
                    [*eligible_ids, limit],
                ).fetchall()
            else:
                rows = self.index.conn.execute(
                    f"SELECT path, title, zettel_id, body FROM documents ORDER BY {col} DESC LIMIT ?",
                    (limit,),
                ).fetchall()

            return [
                SearchResult(
                    path=row["path"], title=row["title"], zettel_id=row["zettel_id"],
                    score=1.0, snippet=row["body"][:300], heading_path="",
                    match_type="filter",
                )
                for row in rows
            ]

        # Query-based search with RRF
        fetch_limit = limit * 3  # over-fetch to survive filtering
        ranked_lists: list[list[SearchResult]] = []

        sem = _filter(self.semantic(query, limit=fetch_limit))
        if sem:
            ranked_lists.append(sem)

        fts = _filter(self.fulltext(query, limit=fetch_limit))
        if fts:
            ranked_lists.append(fts)

        tag_matches = _filter(self._tag_matches(query))
        if tag_matches:
            ranked_lists.append(tag_matches)

        if not ranked_lists:
            return []

        return _rrf_fuse(ranked_lists, limit=limit)
