# cco: Claude Code orchestrator for tmux

One Python file, standard library only. It manages Claude Code sessions that run in tmux, across several Claude accounts (config dirs).

```bash
cco ls                              # every tmux pane: account, session id, status (LIMIT = account out of usage)
cco switch lepinet mt --to claude   # move these tmux sessions' conversations to another account
cco switch --limited --to claude    # move every session whose account hit its usage limit
cco switch mt --to claude --say "continue"   # also send a message once resumed
cco save                            # snapshot tmux + Claude sessions (cron runs this every 2 min)
cco restore [-n]                    # after a reboot: recreate missing tmux sessions, resume each Claude
```

Accounts: `~/.config/cco/accounts.json`, default `{"claude": "~/.claude", "claude2": "~/.claude-ecos"}`.
The default dir (`~/.claude`) is launched with `CLAUDE_CONFIG_DIR` unset, the others with it set.

## How `switch` works
1. Finds the Claude process in the pane and its session id (`<config>/sessions/<pid>.json`).
2. Stops it (SIGTERM, then SIGKILL after 5 s). Skips panes that are mid-turn or running a shell command, unless you pass `--force`.
3. Copies the transcript `projects/<cwd>/<id>.jsonl`, its `<id>/` folder (subagents, tool results) and `file-history/<id>`, `session-env/<id>` into the target config dir. The source stays as it was.
4. Runs `claude --resume <id> <original args>` in the same pane under the target account.
5. Answers startup dialogs: "Resume this conversation?" → Resume; folder trust → yes, but only if the old account had trusted that folder.

The prompt cache does not carry over between accounts, so the first turn after a switch re-reads the whole context.

## Limits
An account is flagged as limited when a live session's transcript shows a `rate_limit` error from its current process. cco remembers the flag, with the reset time, in `~/.local/state/cco/state.json`.

## Reboot
The snapshot records the boot id. After a reboot `save` refuses to overwrite it until `cco restore` has run.
