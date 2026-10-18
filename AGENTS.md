# Repository Guidelines

## Project Structure & Module Organization

Original Words (原话考古) is a planned local-first Windows application for searching authorized QQ/WeChat chat history.

- `requirement.md`: product scope, `REQ-001`–`REQ-032`, acceptance criteria, and unresolved decisions.
- `Plan.md`: three-person ownership, contracts, concurrency, milestones, and acceptance gates.
- `README.md`: project status and contributor entry point.
- `.claude/settings.local.json`: ignored local agent configuration; do not publish it.

No source, tests, or build manifests exist yet. Follow the planned `src/original_words/` layout: A owns connectors/storage/contracts, B owns retrieval/LLM, and C owns UI/application/integration. Consult `Plan.md` before changing shared files.

## Build, Test, and Development Commands

No build, run, lint, or test commands are configured. Inspect the current specification in PowerShell:

```powershell
Get-Content .\requirement.md
Get-Content .\Plan.md
rg --files --hidden -g '!.git'
```

P0 must validate and pin the toolchain, then publish working commands in README. Commands in Plan are targets until their configuration and scripts exist.

## Coding Style & Naming Conventions

Python and PySide6 are agreed; Ruff and pytest are planned. Use four-space Python indentation, descriptive snake_case functions, and PascalCase classes. Preserve fields such as `message_id`, `chat_id`, `timestamp`, and `seq`. Keep requirement identifiers stable. Freeze shared contracts before parallel implementation; route schema changes through A and dependency changes through C.

## Testing Guidelines

Map tests to requirement acceptance criteria. Cover deterministic import, citation anchors, retrieval, no-evidence answers, offline operation, consent, and concurrency. Use synthetic fixtures. Record commands, actual results, and limitations; distinguish automated checks from manual UI acceptance. Follow Plan's gates rather than inventing a coverage threshold.

## Commit & Pull Request Guidelines

Remote history starts with `Initial commit`; no established detailed convention exists. Use imperative subjects such as `feat(A-01): add file import`. Work on task branches and submit PRs with affected requirements, checks, risks, and UI screenshots when relevant. C coordinates serial merges; reviewers approve shared-contract changes before integration. Never force-push main.

## Architecture & Privacy Boundaries

SQLite is the source of truth; Markdown is a view/export. MVP uses Tier A imports and synthetic demonstrations. Defer Tier B; exclude hooks, injection, and OCR.

Keep embeddings local and LLM calls limited to DeepSeek. Preview and authorize outgoing content. Never commit credentials, private messages, runtime databases, or model weights. Real-data mode remains blocked until privacy and encryption gates pass.
