# Restore at boot

**Status:** OPEN (a real reboot is still to be tested)

**Choice: the crontab.** It is per machine, needs no root, and `@reboot` runs without a login. A systemd user unit would need `loginctl enable-linger`, which is off on the workstation (`Linger=no`). It is on by default and asked at `cco setup`.

**Cron's bare environment.** The cron lines carry `SHELL` (or tmux panes get `/bin/sh`), `PATH` (for `claude`) and `LANG` (tmux draws Claude's UI wrong without UTF-8), as they were at setup.

**Snapshot guard.** `save` runs every 2 min. After a reboot it would overwrite the snapshot with the one session you opened first. The snapshot records the boot id, and `save` refuses to write until `restore` has adopted the new boot.

**Tested:**
- Killing a tmux session, then `cco restore`: it comes back with its conversation.
- The whole tmux server died (see below), then `cco restore`: all 11 windows came back, each Claude with its session id.
- Cron's bare environment (`env -i` plus the crontab's variables, on a separate `-S` socket): panes get a login bash, `LANG=en_US.UTF-8`, and `claude` on PATH.
- Not yet: a real reboot.

**Incident: all sessions killed by a test.** To test the environment, I started a second tmux server with `TMUX_TMPDIR`. The shell running the test was itself inside tmux, so `$TMUX` was set and won over `TMUX_TMPDIR`: the closing `tmux kill-server` killed the real server and every Claude in it. Turns in progress were lost. For a test server, run every command as `env -u TMUX tmux -S <socket>`.
