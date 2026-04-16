---
name: wiki
description: Work with documents in the personal wiki — search, create, link, organize, and answer questions from the knowledge base
user_invocable: true
---

# Wiki Skill

You are working inside a personal wiki — a collection of markdown documents managed as a Zettelkasten-style knowledge base.

## Tools available

The wiki MCP tools **complement** your existing tools (Read, Write, Edit, Grep, Glob, etc.) — they don't replace them. Use whichever is best for the task:

- For **discovery** (finding relevant documents by meaning or concept): use the wiki MCP tools — they leverage the semantic index and are better at fuzzy/conceptual queries.
- For **exact matches** (specific strings, filenames, known patterns): Grep and Glob may be faster and more precise.
- For **reading and editing** documents: use Read, Write, Edit as normal.
- For **creating new notes** with proper Zettelkasten IDs and templates: use the wiki MCP tools.

### Wiki MCP tools

- `wiki_search(query?, tags?, after?, before?, date_field?, mode?, limit?)` — Unified search. Combine freely: text query (semantic + full-text), tag filters (AND logic), date range. All params optional. Prefer this over multiple separate calls.
- `wiki_list_tags()` — List all tags with counts
- `wiki_stats()` — Bird's-eye view: doc count, tag distribution, link density, orphans, hubs, stale notes. Call this when you need to understand the wiki's shape.
- `wiki_graph(identifier, depth?)` — Explore the link graph around a document. Returns neighbors (backlinks + outgoing), resolved to real documents, up to `depth` hops (default 1, max 3). Use this to understand how topics connect.
- `wiki_orphans()` — Find documents with no links to or from anything. Useful for maintenance.
- `wiki_resolve_id(zettel_id)` — Resolve a Zettelkasten ID to a file path
- `wiki_index(force)` — Sync the index (call if results seem stale or after file changes)
- `wiki_create_note(title, template, folder)` — Create a new note from a template
- `wiki_stamp(path, zettel_id)` — Add a Zettelkasten ID to a document
- `wiki_stamp_all(directory?)` — Batch stamp all markdown files in a directory. Skips files with existing IDs. Use for onboarding existing notes.
- `wiki_list_templates()` — List available templates
- `wiki_generate_id()` — Generate a new Zettelkasten ID

## How to work

1. **Answering questions**: Search the wiki first. Read the relevant documents. Synthesize an answer grounded in the wiki content. Cite sources by title or ID.

2. **Creating documents**: Use `wiki_create_note` with the appropriate template. After creating, read the file and fill in the content. Always ensure new documents have proper frontmatter (id, title, tags, created, modified).

3. **Linking — THIS IS CRITICAL**: The core value of a Zettelkasten is in connections between notes. Unlinked notes are wasted knowledge. Follow this workflow:

   **When creating a new note:**
   - BEFORE writing content, search the wiki for related notes (`wiki_search` with relevant terms)
   - Read the top 3-5 results to understand what already exists
   - Add `[[wikilinks]]` to related notes in the new document's body
   - If existing notes should link back to the new note, edit them to add the link

   **When editing an existing note:**
   - Use `wiki_graph` to see its current connections
   - If the edit introduces new topics, search for related notes and add links
   - Consider: "what other notes would benefit from knowing about this content?"

   **Proactive linking:**
   - When you notice a note mentions a concept that exists as another note, add the link
   - Prefer linking to specific notes over generic references
   - Use the note's title in the wikilink: `[[Note Title]]`

4. **Organizing**: If the user asks you to organize or file notes, search for related content first to understand existing structure. Respect the wiki's established conventions.

5. **Tagging**: Use tags consistently. Check existing tags with `wiki_list_tags()` before introducing new ones.

6. **Maintenance**: Periodically (or when the user asks), use `wiki_stats()` to check wiki health. Look for:
   - High orphan count → notes that need linking
   - Stale notes → might need updating or archiving
   - Untagged documents → might need categorization

## Important

- **Read CLAUDE.md** at the wiki root if it exists — it contains the user's decisions about wiki structure, conventions, and intent. Follow those conventions.
- **Do not impose structure** that isn't established in CLAUDE.md or by the user. If CLAUDE.md doesn't exist yet, suggest the user run the `/setup` skill.
- **Preserve existing content** — never delete or overwrite without explicit instruction.
- **Zettelkasten IDs are stable identifiers** — prefer referencing notes by ID over path when the ID exists.
- After creating or modifying documents, the index will auto-sync on next search. If the user needs immediate index freshness, call `wiki_index()`.
