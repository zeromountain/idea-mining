# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

A personal Claude Code plugin marketplace. It is not an application — there is no build step, no runtime, no test framework. The only "code" is JSON manifests and Markdown skill files that Claude Code's plugin loader reads directly.

## Structure

```
claude-plugins/
├── .claude-plugin/marketplace.json     # marketplace manifest — lists every plugin in this repo
└── plugins/
    └── idea-mining/
        ├── .claude-plugin/plugin.json  # plugin manifest
        └── skills/idea-mining/
            ├── SKILL.md                # skill body — auto-discovered because the filename is SKILL.md
            └── references/             # loaded on demand by the skill, not always in context
```

This is a two-level manifest system:
- `.claude-plugin/marketplace.json` at the repo root declares the marketplace itself (`name: my-plugins`) and lists each plugin's `source` as a relative path (e.g. `./plugins/idea-mining`).
- Each plugin under `plugins/` has its own `.claude-plugin/plugin.json` and owns its `skills/`, `commands/`, `agents/`, or `hooks/` directories.

**Naming gotcha**: the marketplace's install identifier is `my-plugins` (the `name` field in `marketplace.json`), not the repo name (`idea-mining`). Installing this plugin is always `idea-mining@my-plugins`, regardless of what the GitHub repo is called.

## Adding a new plugin

1. Create `plugins/<plugin-name>/.claude-plugin/plugin.json` (minimum: `name`; recommended: `version`, `description`, `author`).
2. Add the plugin's components under `plugins/<plugin-name>/` — most commonly `skills/<skill-name>/SKILL.md`.
3. Append an entry to the `plugins` array in `.claude-plugin/marketplace.json` with `"source": "./plugins/<plugin-name>"`.

Each skill directory needs its own `SKILL.md` with YAML frontmatter (`name`, `description`). The `description` is the sole trigger mechanism — Claude decides whether to consult a skill based on it, so it must state concretely when the skill applies.

## Commands

There is no build/lint/test suite. The relevant checks are:

**Validate a manifest is well-formed JSON:**
```bash
python3 -m json.tool .claude-plugin/marketplace.json
python3 -m json.tool plugins/<plugin-name>/.claude-plugin/plugin.json
```

**Test a plugin locally before pushing** (loads it directly from disk, bypassing the marketplace):
```bash
cc --plugin-dir /Users/son-yeongsan/claude-plugins/plugins/<plugin-name>
```

**Register this marketplace and install a plugin from it** (run inside a Claude Code session, not the shell):
```
/plugin marketplace add zeromountain/idea-mining
/plugin install idea-mining@my-plugins
```

**Ship an edit to an installed plugin**: edit files under `plugins/<plugin-name>/`, commit, then `git push` — installed instances pick up changes on next sync (no version bump required for personal use, but bump `version` in `plugin.json` if you want to signal a real release).

## The idea-mining skill

`plugins/idea-mining/skills/idea-mining/SKILL.md` drives a fixed workflow (scoping → problem-finding → divergence → critique → scoring/convergence → save) across three modes (fast / deep / portfolio review), documented in full inside the skill file itself — don't duplicate that here.

Two things worth knowing without opening the skill:
- **It writes its output outside this repo**, to `~/ideas/` (individual idea files, `INDEX.md`, and `sessions/` logs), which it creates on first use. That directory is not part of this plugin and is never checked into this repo.
- **Domain-specific judgment lives in `references/domains/{business,product,tech,content}.md`**, one file per idea domain, each with the same four sections (required questions, extra scoring items, common failure patterns, cheap validation examples). When editing domain guidance, keep that section structure — the skill body reads all four domain files the same way regardless of which one applies.

Deep mode spawns subagents (via the `Agent` tool) for two things: parallel research across material sources, and an independent "red team" critique that is deliberately given only the idea summary and problem definition — not the reasoning that produced it — so it can't be talked into agreeing. If you change how deep mode is invoked, preserve that context isolation; it's the mechanism that makes the critique useful rather than a rubber stamp.
