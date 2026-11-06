# cco: Claude Code orchestrator for tmux

You run several Claude Code sessions in tmux, maybe on more than one Claude account. cco lists them, moves a session to another account when one runs out of usage, and brings them all back after a reboot.

```bash
curl -LsSf https://raw.githubusercontent.com/GuillaumeMougeot/cco/main/install.sh | sh
```

The installer runs `cco setup`, which names your accounts and asks whether sessions come back at boot (yes by default, for this machine only).

| Command | Does |
|---|---|
| `cco ls` | every tmux window: account, status (`LIMIT` = account out of usage), context size, title, folder |
| `cco switch lepinet mt --to claude` | move these tmux sessions' conversations to another account, same pane |
| `cco switch --limited --to claude` | move every session whose account is out of usage |
| `cco switch mt --to claude --say continue` | and send a message once resumed |
| `cco save` | snapshot the tmux windows and their Claude sessions (cron does it every 2 min) |
| `cco restore [-n]` | recreate missing tmux windows and resume each Claude (at boot, if setup said so) |
| `cco setup` | rename accounts, turn restore at boot on or off |

An account is a Claude config dir: `~/.claude` (launched with `CLAUDE_CONFIG_DIR` unset) or any other dir, such as `~/.claude-work` behind `alias claude2='CLAUDE_CONFIG_DIR=~/.claude-work claude'`. Setup finds them and takes names from such aliases. They are saved in `~/.config/cco/config.json`.

## What a switch does

1. Finds the Claude in the pane and its session id, from `<config dir>/sessions/<pid>.json`.
2. Stops it. Sessions mid-turn or running a command are skipped unless you pass `--force`.
3. Copies the transcript, its subagents and tool results, and its file history to the other account. The old copy stays.
4. Resumes it there with its original arguments, and answers Claude's startup dialogs: "Resume this conversation?" gets Resume, and folder trust gets yes, but only if the old account had already trusted that folder.

**Cost.** The prompt cache belongs to an account, so the first turn after a switch re-reads the whole context. That costs nothing extra if the session has been idle for longer than the cache lasts (1 h): the old account would have re-read it too. `cco switch -n` shows which case applies ([journal](docs/journal/2026-11-06-switch-cost.md)).

Requires Linux (cco reads `/proc`), tmux, and Python 3.12+ (the installer brings it through uv).

Status: [ROADMAP.md](ROADMAP.md). Why things are the way they are: [docs/journal](docs/journal/README.md).

Development: `uv sync`, then `uv run pytest`, `uv run ruff check .`, `uv run mypy`.
