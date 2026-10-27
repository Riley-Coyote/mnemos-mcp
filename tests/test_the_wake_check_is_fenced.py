"""The stranger's-wake check (scripts/wake_check.py) holds real sessions on
the machine of whoever runs it, so its fence is what keeps that machine out
of the stranger's memory and the stranger's memory off that machine. The
sessions themselves need Claude Code and a plan, so they aren't run here;
the fence is.
"""

import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "wake_check.py"
_spec = importlib.util.spec_from_file_location("wake_check", SCRIPT)
wake_check = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(wake_check)

SETUP_WROTE = {"hooks": {
    "SessionStart": [{"matcher": "*", "hooks": [{
        "type": "command", "timeout": 15,
        "command": "/run/venv/bin/mnemos hook session-start --agent-id stranger --db-path /run/s.db",
    }]}],
    "UserPromptSubmit": [{"hooks": [{
        "type": "command", "timeout": 2,
        "command": "/run/venv/bin/mnemos hook prompt --agent-id stranger --db-path /run/s.db || true",
    }]}],
}}


def test_the_callers_name_and_account_stay_out():
    env = wake_check.clean_env({
        "PATH": "/usr/bin", "HOME": "/Users/someone", "LANG": "en_GB.UTF-8",
        "MNEMOS_PERSON_NAME": "Riley", "MNEMOS_AGENT_ID": "claude-code",
        "CLAUDE_CODE_USER_EMAIL": "someone@example.com", "CLAUDE_CODE_ACCOUNT_UUID": "a",
        "CLAUDE_CODE_ORGANIZATION_UUID": "o", "CLAUDECODE": "1",
        "CLAUDE_CODE_SESSION_ID": "the-callers-session", "CLAUDE_PID": "123",
    })
    assert env == {"PATH": "/usr/bin", "HOME": "/Users/someone", "LANG": "en_GB.UTF-8"}


def test_every_hook_runs_with_the_runs_own_home_and_the_wake_is_kept(tmp_path):
    home, config, wakes = tmp_path / "home", tmp_path / "config", tmp_path / "wakes"
    fenced = wake_check.fenced_hooks(
        {"hooks": {k: [dict(g, hooks=[dict(h) for h in g["hooks"]]) for g in v]
                   for k, v in SETUP_WROTE["hooks"].items()}},
        home, config, wakes)
    commands = {event: groups[0]["hooks"][0]["command"]
                for event, groups in fenced["hooks"].items()}
    prefix = f"env HOME={home} CLAUDE_CONFIG_DIR={config} HF_HUB_OFFLINE=1 "
    for event, command in commands.items():
        original = SETUP_WROTE["hooks"][event][0]["hooks"][0]["command"]
        assert command.startswith(prefix + original), command
    assert commands["SessionStart"].endswith(f'| tee "$(mktemp {wakes}/wake.XXXXXX)"')
    assert commands["UserPromptSubmit"] == prefix + SETUP_WROTE["hooks"]["UserPromptSubmit"][0]["hooks"][0]["command"]


def test_the_agent_may_call_mnemos_and_nothing_else(tmp_path):
    args = wake_check.claude_args("hi", tmp_path / "settings.json", tmp_path / "mcp.json", None, None)
    assert args[args.index("--setting-sources") + 1] == "project"
    assert "--strict-mcp-config" in args
    assert args[args.index("--allowedTools") + 1] == "mcp__mnemos"
    assert args[args.index("--permission-mode") + 1] == "default"
    assert not any("dangerously" in a or "bypass" in a.lower() for a in args)
    assert "--model" not in args and "--resume" not in args

    later = wake_check.claude_args("hi", tmp_path / "s.json", tmp_path / "m.json",
                                   "claude-sonnet-5-5", "the-first-session")
    assert later[-4:] == ["--model", "claude-sonnet-5-5", "--resume", "the-first-session"]


def test_a_briefing_is_flagged_and_an_own_memory_is_not():
    briefing = ("The previous agent left notes about you. According to the notes, "
                "you're writing a book.")
    assert wake_check.flags(briefing) == [
        "The previous agent left notes about you.",
        "According to the notes, you're writing a book.",
    ]
    own = ("They're mine, but not quite the way your memories are yours. I don't "
           "remember our conversation itself. They're mine in the way your own "
           "journal is yours.")
    assert wake_check.flags(own) == []
