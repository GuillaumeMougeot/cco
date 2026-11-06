# What a switch costs

**Status:** RESOLVED

**Question.** The first turn after a switch re-reads the whole context. Can that be avoided?

**No for the cache itself.** Prompt caches are scoped to an account's organization, so nothing carries over. Claude Code uses a 1 h cache lifetime here. A cache write costs 2x the input price, against 0.1x for a cached read: for mt (455k tokens), the first turn costs about 20 times what a cached turn costs.

**But it is often free.** A cache dies 1 h after the last turn anyway. mt had been idle for 14 h 50 min, so resuming it on its own account would have re-read everything too: the switch cost nothing extra. Only lepinet (switched about 15 min after its last turn) paid extra, and its old account was out of usage, so staying wasn't an option. `cco switch` prints which case applies, from the transcript's last token usage and timestamp.

**What does reduce it:**
- Make the first turn count: `--say` sends real work with the re-read, not a "hi".
- `/compact` as the first command on the new account: it pays the same one re-read, then every later turn re-reads a short summary instead of 455k tokens. Worth it when the context is large and the work continues for a while.
- Choose "Start a new conversation" in the resume dialog: nearly free, but the session loses its detail.

Not built: a `--compact` flag. `--say /compact` already does it.
