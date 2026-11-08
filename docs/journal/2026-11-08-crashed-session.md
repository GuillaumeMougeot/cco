# A crashed session could not be restored

**Status:** RESOLVED

**What happened.** tmux session mt vanished at about 07:52 on 2026-11-08, and `cco restore` did nothing.

**Why restore failed.** `save` replaced the snapshot with what was alive, so within 2 minutes the crashed session was gone from it. A missing window was read as closed on purpose.

**Fix.** cco can't tell a crash from a close, and losing a session is worse than restoring one too many. So:
- A missing window stays in the snapshot, marked `gone_since`, until `cco forget`. `cco ls` lists it.
- `cco restore NAME` restores one session. It also resumes Claude in a window that still exists but whose Claude exited.
- This also closes a gap in the boot-id guard: after a tmux server crash with no reboot, the same boot id let `save` overwrite the snapshot.

**Why mt died (likely, not confirmed).** Its last action at 07:52:15 was a GPU Python job, `rare_eval.py`. Claude left a stale registry file, so it did not exit cleanly, and the tmux session vanished, so the pane's shell died too. Only mt was hit. This fits systemd-oomd: tmux puts each pane in its own `tmux-spawn-*.scope`, oomd watches the user session's memory pressure (limit 50% for 20 s) and kills a whole scope. `oomctl` shows 1 min 19 s of accumulated pressure. Confirming needs the system journal, which this user can't read: `sudo journalctl -u systemd-oomd`.

**Consequence.** A heavy job started from a Claude session shares its pane's scope, so oomd takes Claude down with it.
