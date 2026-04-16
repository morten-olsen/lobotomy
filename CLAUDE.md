# Lobotomy

This is a template repository for a personal LLM-assisted wiki. It is not yet configured for a specific use case.

## Getting Started

Run `/setup` to interactively configure this wiki — choose what it captures, define structure, templates, and conventions. The setup skill will rewrite this file with your decisions.

## Project Structure

- `tools/` — Python tooling (uv-managed). Provides CLI (`lobotomy`) and MCP server (`lobotomy-mcp`) for indexing and searching.
- `templates/` — Note templates. Used by `lobotomy new` and the wiki skill.
- `.wiki/` — Derived artifacts (SQLite index). Gitignored, rebuilt with `lobotomy index`.
- `.claude/skills/` — Claude skills: `wiki` (document work) and `setup` (interactive configuration).
- `wiki.toml` — Tool configuration (embedding model, paths, patterns).

## For Claude

- Use the wiki MCP tools (`wiki_search`, `wiki_create_note`, etc.) to interact with documents.
- If this file still says "not yet configured", suggest the user runs `/setup`.
- Do not impose document structure — follow whatever conventions are defined below after setup.
