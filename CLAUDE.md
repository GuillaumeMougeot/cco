# CLAUDE.md

Router for agents working on cco. It holds only what the code can't tell you and what prevents mistakes.

## What

cco tracks the Claude Code sessions running in tmux, moves them between Claude accounts (config dirs), and restores them after a reboot. It reads Claude Code's own files; it never patches Claude Code.

## Read first

1. `ROADMAP.md`: status and next step.
2. `docs/journal/README.md`: why things are the way they are.
3. Module docstrings in `src/cco/`. `claude.py` documents the Claude Code file layout cco relies on.

## Invariants

- Never kill the Claude that runs cco (`procs.ancestors`), and never stop a session that is mid-turn or running a command without `--force`: a shell command may be a training job.
- Copy, never move, a session's files between accounts. The source copy is the fallback.
- Accept a folder-trust dialog only if the old account had trusted that folder. Trust is a per-account security decision.
- `~/.claude` is launched with `CLAUDE_CONFIG_DIR` unset: setting it to `~/.claude` makes Claude read `~/.claude/.claude.json` instead of `~/.claude.json`.
- The snapshot is per machine and guarded by the boot id. After a reboot, `save` must not overwrite it before `restore` has run.
- Claude Code's file layout and dialog texts are not a public API. When a Claude Code update breaks cco, journal what changed.

## How to work

- Smallest thing that works. Delete rather than add. No speculative options.
- Tests run offline: fake `/proc`, fake tmux, fake home (`tests/conftest.py`). Nothing real is started.
- Fewer, shorter docs.

## Maintainer preferences

- Journal everything: `docs/journal/YYYY-MM-DD-topic.md`, indexed in `docs/journal/README.md`.
- Commit and push freely to `main`.
- Use uv for everything.

## Before finishing

- Run `uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest`.
- Update ROADMAP status and the journal.
