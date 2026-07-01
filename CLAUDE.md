# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

UI UX Pro Max is an AI-powered design intelligence toolkit. It ships as a **skill/plugin** for AI coding assistants (Claude Code, Cursor, Windsurf, Copilot, Gemini, and ~15 others) plus an **npm CLI installer** (`ui-ux-pro-max-cli`, command `uipro`).

At its core is a Python search engine over a set of curated CSV databases: 84 UI styles, 161 color palettes, 73 font pairings, 25 chart types, ~192 product types, ~98 UX guidelines, ~104 icon sets, and per-framework guidelines for 22 tech stacks. A design-system generator turns a query into a complete, persistable design spec.

There are **no runtime dependencies** — the engine is pure Python 3 standard library.

## Search Command

The primary interface is `search.py`:

```bash
python3 src/ui-ux-pro-max/scripts/search.py "<query>" --domain <domain> [-n <max_results>]
```

Default `--max-results` is `3`. Add `--json` for machine-readable output. Domain is auto-detected when `--domain` is omitted.

**Domains** (`--domain` / `-d`): `product`, `style`, `color`, `typography`, `landing`, `chart`, `ux`, `icons`, `react`, `web`, `google-fonts`

**Stack search** (`--stack` / `-s`):
```bash
python3 src/ui-ux-pro-max/scripts/search.py "<query>" --stack <stack>
```
Available stacks (22): `html-tailwind` (default), `react`, `nextjs`, `vue`, `svelte`, `astro`, `nuxtjs`, `nuxt-ui`, `swiftui`, `react-native`, `flutter`, `shadcn`, `jetpack-compose`, `threejs`, `angular`, `laravel`, `javafx`, `wpf`, `winui`, `avalonia`, `uno`, `uwp`

**Design-system generation:**
```bash
# Print a full design system recommendation
python3 src/ui-ux-pro-max/scripts/search.py "<query>" --design-system [-p <project-name>] [-f ascii|markdown]

# Persist a hierarchical design system to disk
python3 src/ui-ux-pro-max/scripts/search.py "<query>" --design-system --persist [-o <output-dir>]
# Add a page-specific override under design-system/pages/
python3 src/ui-ux-pro-max/scripts/search.py "<query>" --design-system --persist --page <page-name>
```
`--persist` writes `design-system/MASTER.md` and creates a `design-system/pages/` structure for per-page overrides.

The engine uses BM25 ranking combined with regex matching (`core.py`), with the design-system logic in `design_system.py`.

**Note:** On Windows, use `python` instead of `python3`.

## Architecture

```
src/ui-ux-pro-max/                # SOURCE OF TRUTH for the search engine
├── data/                         # Canonical CSV databases
│   ├── products.csv, styles.csv, colors.csv, typography.csv, charts.csv,
│   │   ux-guidelines.csv, landing.csv, icons.csv, ui-reasoning.csv,
│   │   design.csv, app-interface.csv, react-performance.csv, google-fonts.csv, ...
│   ├── stacks/                   # 22 per-framework guideline CSVs
│   └── _sync_all.py              # Keeps colors/ui-reasoning aligned 1:1 with products.csv
├── scripts/
│   ├── search.py                 # CLI entry point (argparse)
│   ├── core.py                   # BM25 + regex hybrid search engine
│   └── design_system.py          # Design-system generation & persistence
└── templates/
    ├── base/                     # skill-content.md, quick-reference.md
    └── platforms/                # Per-platform config JSON (claude, cursor, windsurf, ...)

.claude/skills/                   # Installed Claude Code skills (7 total)
├── ui-ux-pro-max/                # Orchestrator skill (generated from templates + data/scripts)
└── banner-design/ brand/ design/ design-system/ slides/ ui-styling/
                                  # 6 sibling sub-skills — SOURCE OF TRUTH lives here

cli/                              # npm installer (ui-ux-pro-max-cli, bin: uipro)
├── src/
│   ├── index.ts                  # Commander program: init, update, uninstall, versions
│   ├── commands/                 # init.ts, update.ts, uninstall.ts, versions.ts
│   └── utils/                    # template.ts, detect.ts, extract.ts, github.ts, logger.ts
├── scripts/sync-assets.mjs       # Mirrors src/ + sub-skills into cli/assets/
└── assets/                       # Bundled at publish: data/, scripts/, templates/, skills/

.claude-plugin/                   # Claude marketplace publishing (plugin.json, marketplace.json)
projects/                         # Example outputs (healthcare-dashboard, portfolio-dark, saas-landing)
docs/                             # Design notes
scripts/                          # Repo tooling (smoke-stacks.sh, sync-release-version.mjs)
skill.json                        # Skill manifest (version, platforms, install command)
```

### Two source-of-truth zones

1. **Search engine** — `src/ui-ux-pro-max/` (`data/`, `scripts/`, `templates/`). The `ui-ux-pro-max` orchestrator skill under `.claude/skills/` is *generated* from these templates + data/scripts at install time; do **not** hand-edit `.claude/skills/ui-ux-pro-max/` — edit `src/`.
2. **Sibling skills** — the 6 sub-skills (`banner-design`, `brand`, `design`, `design-system`, `slides`, `ui-styling`) are authored directly under `.claude/skills/` and bundled as static copies into `cli/assets/skills/`.

## Sync Rules

**Edit in the source of truth, then sync to `cli/assets/`.**

1. **Search engine data/scripts/templates** — edit under `src/ui-ux-pro-max/`.
   - When changing `products.csv`, run `_sync_all.py` to realign `colors.csv` / `ui-reasoning.csv`.
2. **Sibling skills** — edit under `.claude/skills/<skill>/` (not in `cli/assets/`).
3. **Sync bundled CLI assets** before publishing:
   ```bash
   cd cli
   npm run sync:assets      # copies src/ + sub-skills → cli/assets/
   npm run check:assets     # verifies assets match sources (byte hash, CRLF-normalized)
   ```
   `sync-assets.mjs` excludes heavy binaries (canvas fonts, images) and Python cruft (`__pycache__`, `.pyc`). CI enforces this via the **check-asset-sync** workflow — a PR that touches `src/ui-ux-pro-max/**` or `cli/assets/**` without a matching sync will fail.
4. **Reference/skill folders in user projects** are generated by `uipro init`; no manual sync needed.

## Testing & CI

- **Smoke test stacks:** `scripts/smoke-stacks.sh [query]` asserts every registered stack returns ≥1 result (catches a stack added to the registry but missing/emptied CSV). `EXPECTED_STACK_COUNT` (default 22) must be bumped deliberately when adding/removing a stack. CI: **smoke-stacks** workflow.
- **Asset sync:** `check-asset-sync` workflow (see Sync Rules).
- **Type check:** `cd cli && npm run typecheck`.

Run these locally before pushing changes to stacks, scripts, or CLI assets.

## CLI (`cli/`)

Built with **Bun** + TypeScript (Commander). Commands:

| Command | Purpose |
|---------|---------|
| `uipro init` | Install the skill(s) into the current project for a detected/specified AI platform |
| `uipro update` | Update to the latest version |
| `uipro uninstall` | Remove the skill from the project or globally |
| `uipro versions` | List available versions |

```bash
cd cli
npm run dev          # bun run src/index.ts
npm run build        # bun build → dist/
npm run typecheck    # tsc --noEmit
```

`init` renders the orchestrator skill from `templates/` for the target platform (config layouts in `templates/platforms/*.json`) and copies bundled assets. Supported platforms are listed in `skill.json` (`claude`, `cursor`, `windsurf`, `copilot`, `kiro`, `roocode`, `kilocode`, `codex`, `qoder`, `gemini`, `trae`, `opencode`, `continue`, `codebuddy`, `droid`, `warp`, `augment`, `antigravity`, `openclaw`).

## Versioning & Release

Releases are automated with **semantic-release** using **Conventional Commits** (`feat:`, `fix:`, `docs:`, etc.). Config in `.releaserc.json`:

- `main` → stable release; `dev` → `beta` prerelease channel.
- Publishes the npm package from `pkgRoot: cli`; creates GitHub releases; tags `v${version}`.
- The version string is duplicated across `skill.json`, `.claude-plugin/plugin.json`, and `.claude-plugin/marketplace.json`. Use `node scripts/sync-release-version.mjs <version>` to keep them aligned.

Because commit messages drive versioning, **write Conventional Commit messages**.

## Prerequisites

- Python 3.x (standard library only — no `pip install` needed)
- Node 20+ / Bun (only for CLI work)

## Git Workflow

Never push directly to `main`. Always:

1. Create a branch: `git checkout -b feat/...` or `fix/...`
2. Commit with a Conventional Commit message
3. Push: `git push -u origin <branch>`
4. Open a PR

See `CONTRIBUTING.md` for contribution details.
