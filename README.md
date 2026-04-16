# Lobotomy 🧠🔪

*You don't need to remember. It does.*

Your brain is a terrible database. It forgets names, loses context, and stores critical insights right next to song lyrics from 2003. Lobotomy fixes this by removing the burden of recall entirely and handing it to an AI that never sleeps, never forgets, and never judges you for how many notes you have titled "TODO".

This is a [Zettelkasten](https://zettelkasten.de/overview/) wiki template powered by [Claude Code](https://claude.ai/claude-code). You write markdown. It indexes everything into a local SQLite database with semantic search. Then you just... ask it things. Like having a second brain, except this one actually works.

Built on plain markdown and `[[wikilinks]]`, so it works natively as an [Obsidian](https://obsidian.md) vault. Browse your lobotomized knowledge base on your phone while pretending to be present in conversations. Drop it into an existing vault, or start fresh — the procedure adapts to the patient.

## The Procedure

```bash
make init    # prep the operating table
claude       # the surgeon is in
```

Type `/setup` and answer a few questions. Claude will structure your wiki, create templates, and write a `CLAUDE.md` that governs all future interactions. Think of it as the pre-op consultation — you decide what memories to keep organized, and how.

## Post-Op Life

**Talk to your wiki:**

```
/wiki
> "What do I know about kubernetes networking?"
> "Summarize everything tagged #project-x from last month"
> "Create a note about today's architecture decision"
```

**Or use the CLI, if you still trust your own hands:**

```bash
lobotomy search "query"                                    # hybrid semantic + full-text
lobotomy search "deployment" -t devops --after 2026-01-01  # combine query + tags + dates
lobotomy search --after 2026-04-01                         # what did I even do this month
lobotomy new "Note Title"                                  # fresh note from template
lobotomy stamp path/to/note.md                             # tattoo a Zettelkasten ID on it
lobotomy graph "Note Title"                                # see what connects to what
lobotomy graph "Note Title" -d 2                           # two hops out (the deep cut)
lobotomy orphans                                           # find notes nobody links to (the forgotten patients)
lobotomy index --force                                     # full re-index (electroshock)
```

## How It Works (The Science Bit)

- **Documents** are markdown with YAML frontmatter. Zettelkasten-style timestamp IDs give every thought a permanent address, unlike your actual memory.
- **Index** is SQLite with FTS5 (full-text) + sqlite-vec (semantic embeddings). Two ways to find things, because you won't remember which words you used.
- **Lazy sync** — the index watches for file changes via mtime. Edit a note, and the next query re-indexes it automatically. Like muscle memory, but real.
- **Local embeddings** — all-MiniLM-L6-v2 runs on your machine. Your thoughts never leave your skull. Well, your disk.
- **Link graph** — every `[[wikilink]]` is tracked. Ask "what connects to this note?" and get the full neural map — backlinks, outgoing links, multi-hop traversal. Find orphaned notes that slipped through the cracks. It's like Obsidian's graph view, except someone actually reads it.
- **MCP server** — Claude Code talks to the index directly via `.mcp.json`. No copy-pasting, no "let me check my notes." It already knows.
- **Obsidian native** — it's just a vault. `[[wikilinks]]`, tags, frontmatter, graph view — all work. The tooling is additive, not invasive. Remove it and your notes are still perfectly good markdown.

## Configuration

`wiki.toml` at the repo root. Touch it if you want, but the defaults are fine. Just like your brain was, supposedly.

## Anatomy

```
wiki.toml              <- configuration
.mcp.json              <- MCP server wiring (how Claude finds the index)
templates/             <- note templates
.wiki/                 <- index database (gitignored, disposable, unlike memories)
.claude/
  skills/
    wiki/SKILL.md      <- the part that talks to your notes
    setup/SKILL.md     <- the pre-op consultation
  settings.json        <- Claude Code settings
tools/
  src/lobotomy/        <- the toolkit
    cli.py             <- command line interface
    mcp_server.py      <- Claude's direct line to your thoughts
    index.py           <- SQLite + FTS5 + sqlite-vec
    search.py          <- finding what you forgot you knew
    embeddings.py      <- local sentence-transformers
    parser.py          <- markdown, frontmatter, wikilinks
    templates.py       <- note scaffolding + Zettelkasten IDs
    config.py          <- wiki.toml loader
```

## Side Effects

May include: reduced anxiety about forgetting things, an unsettling sense that your computer knows you better than you know yourself, and the occasional existential crisis when the search results are *too* good.

## License

MIT. Free as in "free your mind."
