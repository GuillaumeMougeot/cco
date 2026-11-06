# Moving a session to another Claude account

**Status:** RESOLVED

**Question.** Two sessions (lepinet, mt) ran on an account that hit its weekly limit. Can they carry on under the other account without losing the conversation?

**Findings** (Claude Code 2.1.31x):
- `<config dir>/sessions/<pid>.json` maps each live Claude to its session id, cwd, tmux pane and status. The account is the process's `CLAUDE_CONFIG_DIR` (from `/proc/<pid>/environ`).
- A conversation is `projects/<cwd>/<id>.jsonl` plus `projects/<cwd>/<id>/` (subagents, tool results) and `file-history/<id>`. Once these are copied, `claude --resume <id>` under the other account continues the conversation. Tested both ways: after two switches, the session still quoted its first message.
- Two startup dialogs block the resume:
  - Folder trust, per account. mt's repo pre-approves tools in `.claude/settings.json`, so the dialog showed even though a parent folder was trusted. cco accepts it only if the old account had trusted the folder.
  - "Resume this conversation?" after long inactivity. The default is Resume.
- A usage-limit hit is in the transcript: an assistant entry with `"error": "rate_limit"` and `quotaLimits.resetsAt`. mt never got one (it was waiting on a question), so cco flags the account, not the session, and remembers it until the reset.
- After a resume, the copied transcript still holds the old account's limit error. cco ignores errors older than the process.

**Lost on a switch:** a pending question dialog (the transcript keeps its text, so answer it again), Remote Control bridges, Artifact comment monitors.
