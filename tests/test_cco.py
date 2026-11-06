"""cco's logic against fake homes, processes and tmux."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import pytest
from typer.testing import CliRunner

from cco import autostart, claude, cli, config, state, tmux
from tests.conftest import FakeTmux, register

SID = "98c4d784-49fe-4596-bb58-426655bf23ad"


def write_transcript(cfg: Path, lines: list[dict[str, object]], sid: str = SID) -> Path:
    proj = cfg / "projects" / "-work-repo"
    proj.mkdir(parents=True, exist_ok=True)
    path = proj / f"{sid}.jsonl"
    path.write_text("".join(json.dumps(x) + "\n" for x in lines))
    return path


def answer(ts: str, tokens: int = 1000) -> dict[str, object]:
    usage = {"input_tokens": 2, "cache_read_input_tokens": tokens, "output_tokens": 10}
    return {"type": "assistant", "timestamp": ts, "message": {"usage": usage}}


def limit_error(ts: str, reset: int) -> dict[str, object]:
    return {
        "type": "assistant",
        "timestamp": ts,
        "error": "rate_limit",
        "quotaLimits": {"resetsAt": reset},
        "message": {"content": [{"type": "text", "text": "You've hit your weekly limit"}]},
    }


# ---------------------------------------------------------------- accounts


def test_detect_names_accounts_after_shell_aliases(home: Path) -> None:
    assert config.detect() == {
        "claude": (home / ".claude").resolve(),
        "claude2": (home / ".claude-ecos").resolve(),
    }


def test_saved_accounts_win_over_detection(home: Path) -> None:
    config.save_accounts({"main": home / ".claude"})
    assert config.accounts() == {"main": (home / ".claude").resolve()}
    assert "~/.claude" in config.config_path().read_text()


# ---------------------------------------------------------------- launching


@pytest.mark.parametrize(
    ("args", "kept"),
    [
        (["--resume", "x", "--model", "haiku"], ["--model", "haiku"]),
        (["-r", "x", "-c", "--session-id=y"], []),
        (["--continue", "--permission-mode", "auto"], ["--permission-mode", "auto"]),
    ],
)
def test_strip_resume(args: list[str], kept: list[str]) -> None:
    assert claude.strip_resume(args) == kept


def test_launch_cmd_unsets_config_dir_for_the_default_account(home: Path) -> None:
    assert claude.launch_cmd(home / ".claude", "id", ["--model", "a b"]) == (
        "env -u CLAUDE_CONFIG_DIR claude --resume id --model 'a b'"
    )
    other = home / ".claude-ecos"
    assert claude.launch_cmd(other, None, []) == f"CLAUDE_CONFIG_DIR={other} claude"


def test_find_reads_process_and_registry(home: Path, proc: Callable[..., None]) -> None:
    ecos = (home / ".claude-ecos").resolve()
    proc(100, ["-bash"])
    proc(101, ["claude", "--resume", SID], {"CLAUDE_CONFIG_DIR": str(ecos)}, parent=100)
    register(ecos, 101, sessionId=SID, cwd="/work/repo", status="idle", startedAt=5000)
    c = claude.find(101)
    assert (c.account, c.session_id, c.cwd, c.started_at, c.args) == (
        "claude2",
        SID,
        "/work/repo",
        5.0,
        [],
    )


# ---------------------------------------------------------------- transcripts


def test_info_reads_context_title_and_limit(home: Path) -> None:
    path = write_transcript(
        home / ".claude",
        [
            {"type": "ai-title", "aiTitle": "Port the baseline"},
            answer("2026-11-06T07:00:00Z", tokens=455_000),
            limit_error("2026-11-06T07:50:42.543Z", reset=2_000_000_000),
        ],
    )
    i = claude.info(path, started_at=0, now=1_900_000_000)
    assert i.title == "Port the baseline"
    assert i.context_tokens == 455_002
    assert i.limit_reset == 2_000_000_000


def test_limit_from_before_this_process_does_not_count(home: Path) -> None:
    path = write_transcript(home / ".claude", [limit_error("2026-11-06T07:50:00Z", 2_000_000_000)])
    after_switch = claude._epoch("2026-11-06T08:00:00")
    assert claude.info(path, started_at=after_switch, now=1_900_000_000).limit_reset is None


def test_limit_followed_by_an_answer_does_not_count(home: Path) -> None:
    path = write_transcript(
        home / ".claude",
        [limit_error("2026-11-06T07:50:00Z", 2_000_000_000), answer("2026-11-06T08:00:00Z")],
    )
    assert claude.info(path, now=1_900_000_000).limit_reset is None


def test_copy_session_moves_transcript_and_per_session_files(home: Path) -> None:
    src, dst = home / ".claude-ecos", home / ".claude"
    write_transcript(src, [answer("2026-11-06T07:00:00Z")])
    (src / "projects" / "-work-repo" / SID / "subagents").mkdir(parents=True)
    (src / "projects" / "-work-repo" / SID / "subagents" / "a.jsonl").write_text("{}")
    (src / "file-history" / SID).mkdir(parents=True)
    (src / "file-history" / SID / "f@v1").write_text("old")
    (src / "file-history" / "other-session").mkdir()
    claude.copy_session(src, dst, SID)
    assert (dst / "projects" / "-work-repo" / f"{SID}.jsonl").exists()
    assert (dst / "projects" / "-work-repo" / SID / "subagents" / "a.jsonl").exists()
    assert (dst / "file-history" / SID / "f@v1").read_text() == "old"
    assert not (dst / "file-history" / "other-session").exists()
    assert (src / "projects" / "-work-repo" / f"{SID}.jsonl").exists()


def test_copy_session_without_transcript_fails(home: Path) -> None:
    with pytest.raises(FileNotFoundError):
        claude.copy_session(home / ".claude-ecos", home / ".claude", SID)


def test_trust_is_inherited_from_a_parent_folder(home: Path) -> None:
    projects = {"projects": {"/work": {"hasTrustDialogAccepted": True}}}
    (home / ".claude.json").write_text(json.dumps(projects))
    assert claude.trusted(home / ".claude", "/work/repo")
    assert not claude.trusted(home / ".claude", "/elsewhere")
    assert not claude.trusted(home / ".claude-ecos", "/work/repo")  # reads its own .claude.json


def test_cost_note_is_free_once_the_cache_expired() -> None:
    i = claude.Info(context_tokens=455_000, last_turn=0)
    assert "no extra cost" in cli.cost_note(i, now=14 * 3600)
    assert "uncached" in cli.cost_note(i, now=600)
    assert cli.cost_note(claude.Info(), now=0) == ""


# ---------------------------------------------------------------- tmux


def test_wait_started_answers_both_dialogs(
    home: Path, proc: Callable[..., None], fake_tmux: FakeTmux
) -> None:
    proc(100, ["-bash"])
    proc(101, ["claude"], parent=100)
    register(home / ".claude", 101, sessionId=SID, cwd="/work/repo")
    fake_tmux.screens = ["Yes, I trust this folder", "Resume this conversation?"]
    c = tmux.wait_started("%1", trust_ok=True, sleep=lambda _: None)
    assert c is not None and c.session_id == SID
    keys = [x[3] for x in fake_tmux.calls if x[0] == "send-keys"]
    assert keys == ["Down", "Enter", "Enter"]


def test_wait_started_leaves_an_unknown_folder_to_the_user(
    home: Path, proc: Callable[..., None], fake_tmux: FakeTmux
) -> None:
    proc(100, ["-bash"])
    fake_tmux.screens = ["Yes, I trust this folder"]
    assert tmux.wait_started("%1", trust_ok=False, sleep=lambda _: None) is None
    assert not [x for x in fake_tmux.calls if x[0] == "send-keys"]


# ---------------------------------------------------------------- state


def pane(session: str, sid: str | None = SID) -> tmux.Pane:
    c = claude.Claude(101, Path.home() / ".claude", sid, "/work/repo", args=["--model", "x"])
    return tmux.Pane(session, 0, 0, "%1", 100, "/work/repo", c if sid else None)


def test_save_then_restore_rebuilds_missing_sessions(
    home: Path, fake_tmux: FakeTmux, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert state.save([pane("lepinet"), pane("oca", sid=None)]).startswith("saved 2")
    monkeypatch.setattr(tmux, "wait_started", lambda *a, **k: object())
    r = CliRunner().invoke(cli.app, ["restore"])
    assert r.exit_code == 0, r.output
    assert ("new-session", "-d", "-s", "lepinet", "-c", "/work/repo") in fake_tmux.calls
    assert ("new-session", "-d", "-s", "oca", "-c", "/work/repo") in fake_tmux.calls
    assert fake_tmux.typed() == [f"env -u CLAUDE_CONFIG_DIR claude --resume {SID} --model x"]


def test_save_after_reboot_keeps_the_snapshot_until_restore(
    home: Path, fake_tmux: FakeTmux, monkeypatch: pytest.MonkeyPatch
) -> None:
    state.save([pane("a"), pane("b")])
    state.BOOT_ID.write_text("boot-2\n")
    assert "run `cco restore`" in state.save([pane("new")])
    assert [e["session"] for e in state.load()["entries"]] == ["a", "b"]
    monkeypatch.setattr(tmux, "wait_started", lambda *a, **k: object())
    CliRunner().invoke(cli.app, ["restore"])
    assert state.save([pane("new")]).startswith("saved 1")


def test_limits_are_remembered_until_they_reset(home: Path) -> None:
    assert state.limits({"claude2": 2000.0}, now=1000) == {"claude2": 2000.0}
    assert state.limits({}, now=1500) == {"claude2": 2000.0}
    assert state.limits({}, now=2500) == {}


# ---------------------------------------------------------------- crontab


def test_crontab_block_replaces_itself_and_keeps_other_lines(home: Path) -> None:
    mine = "*/5 * * * * ucloud q tick\n"
    legacy = "# cco: snapshot\n*/2 * * * * /x/cco save -q\n"
    env = {"PATH": "/a b:/c%d"}
    block = autostart.block("/bin/cco", True, env, home / "log")
    text = autostart.without(mine + legacy) + block
    assert text.startswith(mine) and text.count(autostart.BEGIN) == 1
    assert "PATH='/a b:/c\\%d'" in text
    assert autostart.installed(text) == (True, True)
    again = autostart.without(text) + autostart.block("/bin/cco", False, env, home / "log")
    assert autostart.installed(again) == (True, False)
    assert autostart.without(again) == mine


def test_environment_dedupes_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PATH", "/a:/b:/a")
    assert autostart.environment()["PATH"] == "/a:/b"


def test_setup_with_defaults_names_accounts_and_turns_boot_on(
    home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    written: list[str] = []
    monkeypatch.setattr(autostart, "read", lambda: "")
    monkeypatch.setattr(autostart, "write", written.append)
    r = CliRunner().invoke(cli.app, ["setup", "--yes"])
    assert r.exit_code == 0, r.output
    assert set(config.accounts()) == {"claude", "claude2"}
    assert autostart.installed(written[0]) == (True, True)


def test_switch_needs_a_known_account(home: Path, fake_tmux: FakeTmux) -> None:
    r = CliRunner().invoke(cli.app, ["switch", "x", "--to", "nope"])
    assert r.exit_code != 0
