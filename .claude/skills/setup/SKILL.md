---
name: setup
description: Interactive setup — define wiki intent, structure, conventions, and generate CLAUDE.md
user_invocable: true
---

# Wiki Setup Skill

You are helping the user set up their personal wiki. Your goal is to understand what they want to capture, then generate a `CLAUDE.md` file that encodes those decisions so all future interactions follow the agreed structure.

## Process

### Step 1: Understand Intent

Ask the user about their wiki's purpose. Guide the conversation with questions like:

- What kind of information will this wiki primarily capture? (research notes, project docs, meeting notes, learning journal, personal CRM, recipes, etc.)
- Who is the audience? (just you, a team, public?)
- Do you have existing notes to migrate? What format?
- How do you want to browse — primarily through Claude, Obsidian mobile, or both?

Don't ask all questions at once. Have a natural conversation. Adapt based on their answers.

### Step 2: Propose Structure

Based on their answers, propose:

1. **Top-level folders** — suggest 3-6 categories. Keep it shallow.
2. **Templates** — for each document type they described, propose a template with appropriate frontmatter fields and sections. Create these as actual template files in the `templates/` directory.
3. **Tagging conventions** — suggest a tag taxonomy or namespacing approach (e.g. `status/draft`, `type/reference`).
4. **Naming conventions** — Zettelkasten IDs are generated automatically, but suggest conventions for the human-readable part of filenames.
5. **Inbox workflow** — if appropriate, suggest how rough captures flow into permanent notes.

Present this as a clear proposal and ask for feedback. Iterate until the user is satisfied.

### Step 3: Generate CLAUDE.md

Once the user agrees, generate a `CLAUDE.md` at the wiki root that encodes:

```markdown
# Wiki: [Name]

## Purpose
[One paragraph describing what this wiki captures and why]

## Structure
[Folder layout with descriptions]

## Document Conventions
[Frontmatter requirements, linking conventions, ID usage]

## Templates
[List available templates and when to use each]

## Tags
[Tag taxonomy and conventions]

## Workflow
[How new notes enter the system, how inbox works if applicable]

## Rules for Claude
- [Specific instructions derived from the user's preferences]
- [e.g. "Always add a summary field to frontmatter"]
- [e.g. "Use ISO dates everywhere"]
- [e.g. "Link to related notes when creating new ones"]
```

### Step 4: Obsidian Configuration (if applicable)

If the user uses or wants to use Obsidian:

- Check if `.obsidian/` exists already
- If it does, review the existing config and suggest only additions that complement the wiki setup (e.g. template hotkeys, tag pane, graph view settings)
- If it doesn't, offer to create a minimal Obsidian config with sensible defaults for the wiki structure
- Never overwrite existing Obsidian configuration without explicit permission

### Step 5: Create Folders and Templates

After the user approves:

1. Create the agreed folder structure (with `.gitkeep` files so empty dirs are tracked)
2. Create template files in `templates/`
3. Write the `CLAUDE.md`
4. Run `wiki_index()` to initialize the index

## Important

- **This is collaborative** — propose, don't dictate. The user owns the structure.
- **Keep it simple** — resist over-engineering. 3 folders beats 12. One template can serve multiple purposes.
- **Be opinionated but flexible** — offer strong defaults based on best practices, but defer to the user's preferences.
- **Consider mobile** — if they use Obsidian mobile, suggest structures that work well on small screens (short filenames, shallow hierarchy).
