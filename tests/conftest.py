"""Shared test fixtures for Mnemos."""
import os
import tempfile
import pytest

# mcp's stdio_client takes the server's stderr as ``errlog=sys.stderr``, a
# default bound when mcp is first imported. Imported first inside a test that
# uses capsys, it bound pytest's in-memory capture, which has no file
# descriptor, and every later test that starts a server over stdio failed on
# fileno() (test_watchdog.py before test_min_code_version.py). Imported here,
# while pytest's own capture is in place, it binds the same stream whatever
# order the tests run in.
try:
    import mcp.client.stdio  # noqa: F401
except ImportError:  # pragma: no cover - mcp is a core dependency
    pass


@pytest.fixture(autouse=True)
def _isolate_mnemos_env(monkeypatch, tmp_path_factory):
    """No developer's real environment bleeds into tests.

    MNEMOS_DISABLE_DOTENV stops llm._load_env_key (and the OpenClaw key
    lookup) from reading workspace .env files; the MNEMOS_*/provider
    variables are cleared so every test starts from a clean slate and
    sets exactly what it needs via monkeypatch.setenv.

    And every test has a home of its own. With the developer's, whatever
    resolved a default path wrote into the real ~/.mnemos: a store named
    audit.db (bootstrap with no store path), the scheduler's log folder, and
    the cue's shown files. A test that needs a particular home sets its own.
    """
    home = tmp_path_factory.mktemp("home")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))  # where Windows looks
    for var in (
        "MNEMOS_LLM_PROVIDER", "MNEMOS_MODEL", "MNEMOS_AGENT_MODEL",
        "MNEMOS_SUBSTRATE_AFFINITY", "MNEMOS_AGENT_ID", "MNEMOS_PERSON_ID",
        "MNEMOS_PROJECT_SCOPE", "MNEMOS_DB_PATH", "MNEMOS_ENV_PATHS",
        "MNEMOS_WORKSPACE", "MNEMOS_MODE", "MNEMOS_PERSON_NAME",
        "ANTHROPIC_API_KEY", "OPENROUTER_API_KEY", "OPENAI_API_KEY",
        # A real key would send every captured test memory to the Gemini API,
        # if a developer's shell had also chosen it.
        "GEMINI_API_KEY", "MNEMOS_EMBEDDING_MODEL", "MNEMOS_EMBEDDING_PROVIDER",
        # A test run inside a Claude Code session inherits its session id, and
        # signing would then read that real transcript: notes written in the
        # suite would be signed by whatever model is running the developer's
        # session, while CI left them unsigned.
        "CLAUDE_CODE_SESSION_ID", "CLAUDE_CONFIG_DIR",
        # Claude Code's own pid, which the prompt hook uses to find its
        # session's answerer: a test run inside a session would otherwise
        # look for that session's server.
        "CLAUDE_PID",
        # The marks of an agent's own shell: `mnemos remember` keeps the
        # agent's words under them and the person's words without them, so a
        # suite run from Claude Code would take the agent's path everywhere
        # CI takes the person's. A test about the agent's shell sets them.
        "CLAUDECODE", "AI_AGENT",
        # The cue's judge: a developer who switched it on would otherwise
        # send test messages to Jev.
        "MNEMOS_CUE_JUDGE",
        # A suite run from inside one of the agent's quiet hours would
        # otherwise write every journal entry as written between sessions, and
        # refuse every reply (R22): the hour belongs to the process the hour's
        # runner woke, not to the tests.
        "MNEMOS_HOUR_ID",
    ):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("MNEMOS_DISABLE_DOTENV", "1")
    # Automatic maintenance runs in the call that asks for it, as it did before
    # it moved to a background process: the suite checks what a cycle did right
    # after the call, and a process of its own would still be writing a store
    # the test has finished with. tests/test_saving_does_not_wait.py covers
    # the background, the default.
    monkeypatch.setenv("MNEMOS_MAINTENANCE", "inline")
    # And no test reaches a real Jev key (~/.config/jev/api_key): an empty
    # file is no key. A test that needs one names its own.
    monkeypatch.setenv("MNEMOS_JEV_KEY_FILE", os.devnull)


class FakeScheduler:
    """The machine's schedulers, as the tests see them: what launchd has
    loaded, which systemd timers are enabled, and the crontab, all in memory.
    Every call is recorded in ``calls``."""

    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self.loaded: set[str] = set()
        self.enabled: set[str] = set()
        self.crontab = ""

    def launchctl(self, action, plist, *, allow_missing=False) -> None:
        from pathlib import Path

        label = Path(plist).stem
        self.calls.append(("launchctl", action, label))
        if action == "bootstrap":
            self.loaded.add(label)
        else:
            self.loaded.discard(label)

    def systemctl(self, *args) -> None:
        self.calls.append(("systemctl", *args))
        if args[:2] == ("enable", "--now"):
            self.enabled.add(args[2])
        elif args[:2] == ("disable", "--now"):
            self.enabled.discard(args[2])

    def read_crontab(self) -> str:
        return self.crontab

    def write_crontab(self, text: str) -> bool:
        self.calls.append(("crontab",))
        self.crontab = text
        return True

    def launchd_job_active(self, agent_id, job) -> bool:
        from mnemos.setup.scheduler import label_for

        return label_for(agent_id, job) in self.loaded

    def systemd_timer_active(self, agent_id, job) -> bool:
        from mnemos.setup.scheduler import systemd_unit_names

        return systemd_unit_names(agent_id, job)[1] in self.enabled


@pytest.fixture(autouse=True)
def os_scheduler(monkeypatch):
    """No test schedules anything on the machine that runs it.

    Setup schedules upkeep by default, so every test that installs hooks
    would otherwise load real launchd jobs (whose plists sit in the test's
    home), enable real systemd timers, or rewrite the developer's crontab.
    Every call that reaches the OS scheduler, reading or writing, goes to
    this fake instead; a test that needs it asks for ``os_scheduler``, and
    finds the real functions in ``os_scheduler.real``."""
    from mnemos import cli
    from mnemos.setup import scheduler

    fake = FakeScheduler()
    fake.real = {
        "_launchctl": cli._launchctl,
        "_systemctl": cli._systemctl,
        **{name: getattr(scheduler, name) for name in (
            "read_crontab", "write_crontab", "launchd_job_active", "systemd_timer_active",
        )},
    }
    monkeypatch.setattr("mnemos.cli._launchctl", fake.launchctl)
    monkeypatch.setattr("mnemos.cli._systemctl", fake.systemctl)
    monkeypatch.setattr("mnemos.setup.scheduler.read_crontab", fake.read_crontab)
    monkeypatch.setattr("mnemos.setup.scheduler.write_crontab", fake.write_crontab)
    monkeypatch.setattr("mnemos.setup.scheduler.launchd_job_active", fake.launchd_job_active)
    monkeypatch.setattr("mnemos.setup.scheduler.systemd_timer_active", fake.systemd_timer_active)
    # Anything that still starts a scheduler's own command fails the test
    # rather than reaching the machine.
    import subprocess
    from pathlib import Path

    run = subprocess.run

    def guarded(args, *more, **options):
        first = args[0] if isinstance(args, (list, tuple)) and args else str(args).split(" ")[0]
        if Path(str(first)).name in {"launchctl", "systemctl", "crontab"}:
            raise AssertionError(f"a test reached the machine's scheduler: {args}")
        return run(args, *more, **options)

    monkeypatch.setattr(subprocess, "run", guarded)
    # And no test waits on a person: setup asks about the quiet hours only at
    # a terminal, which a run with `pytest -s` in one would otherwise be. A
    # test of the question says there is someone there.
    monkeypatch.setattr("mnemos.cli._can_ask", lambda: False)
    return fake


_EVERY_DAY: list[str] | None = None


def _every_day() -> list[str]:
    """Every UTC date from 2000-01-01 through two days from now, built once."""
    global _EVERY_DAY
    if _EVERY_DAY is None:
        from datetime import date, datetime, timedelta, timezone

        day = date(2000, 1, 1)
        last = datetime.now(timezone.utc).date() + timedelta(days=2)
        days = []
        while day <= last:
            days.append(day.isoformat())
            day += timedelta(days=1)
        _EVERY_DAY = days
    return _EVERY_DAY


@pytest.fixture(autouse=True)
def every_day_lived(request, monkeypatch):
    """The agent lived every day, so its time is the calendar's.

    Memories fade with the days the agent lived (consolidation/lived.py). The
    suite's backdated timestamps assume an agent that lived through them, the
    case where nothing changes. A test marked ``lived_time`` keeps the days
    its store really holds.
    """
    if request.node.get_closest_marker("lived_time") is not None:
        return
    from mnemos.store.sqlite_store import EngramStore

    days = _every_day()
    monkeypatch.setattr(EngramStore, "lived_days", lambda self, agent_id: list(days), raising=False)


@pytest.fixture
def tmp_db(tmp_path):
    """Create a temporary database path."""
    return str(tmp_path / "test_memory.db")


@pytest.fixture
def store(tmp_db):
    """Create a temporary EngramStore."""
    from mnemos.store.sqlite_store import EngramStore
    s = EngramStore(tmp_db)
    yield s
    s.close()


@pytest.fixture
def encoder(store):
    """Create an Encoder with no LLM (rule-based fallback)."""
    from mnemos.encoding.encoder import Encoder
    return Encoder(store, llm_client=None)


@pytest.fixture
def retriever(store):
    """Create a ReactiveRetriever."""
    from mnemos.retrieval.reactive import ReactiveRetriever
    return ReactiveRetriever(store)
