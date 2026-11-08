# Roadmap

**Last updated:** 2026-11-08

## Done

- `ls`, `switch` (by name or `--limited`), `save`, `restore`, `setup`. Used live: two sessions moved from an out-of-usage account to another, conversation intact ([journal](docs/journal/2026-11-06-account-switch.md)).
- Restore at boot through the crontab, on by default, asked at setup ([journal](docs/journal/2026-11-06-boot-restore.md)).
- Crashed sessions stay restorable: `cco restore NAME`, `cco forget NAME` ([journal](docs/journal/2026-11-08-crashed-session.md)).

## Next

1. Verify restore at boot on a real reboot of the workstation.
2. Multi-pane windows: cco restores one pane per window.
