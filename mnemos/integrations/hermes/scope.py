"""Scope and configuration helpers for the Hermes integration."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ...file_security import atomic_write_text
from ...simple_scope import named_in_the_environment

logger = logging.getLogger(__name__)


def conversation_id(*, gateway_session_key: str = "", session_id: str = "") -> str:
    """One id for one conversation, however many sessions it runs through.

    Hermes's gateway names a conversation with its session key: a chat, or a
    topic in one (a Telegram forum topic, a Discord thread). The key stays the
    same across a ``/new``, an idle reset and a compression; the session id
    changes with each. Without a gateway (the command line), the session id is
    all there is.

    Hashed because the key holds chat and user ids and a handoff keeps this
    beside its words, and because Mnemos reads it as a session id, which has
    no colons (``clean_session_id``).
    """

    raw = (gateway_session_key or "").strip() or (session_id or "").strip()
    return f"hermes-{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:32]}" if raw else ""


def slugify(value: str | None, fallback: str) -> str:
    """Return a stable identifier that is safe in paths and SQLite scopes."""

    raw = (value or "").strip()
    clean = re.sub(r"[^a-zA-Z0-9_.-]+", "-", raw.lower()).strip("-._")
    return clean or fallback


# The home Hermes told a provider it's running for, while one of its calls is under way.
_HOME_TOLD: ContextVar[Path | None] = ContextVar("mnemos_hermes_home_told", default=None)


def default_hermes_home() -> Path:
    """Resolve the active Hermes home without importing Hermes: the one Hermes told the
    provider, inside a provider's call, and otherwise the environment's. They can differ:
    recent Hermes can run a profile with ``HERMES_HOME`` still naming its root, and hands
    the provider the profile's home to go by."""

    told = _HOME_TOLD.get()
    if told is not None:
        return told
    raw = os.environ.get("HERMES_HOME", "").strip()
    return Path(raw).expanduser() if raw else Path.home() / ".hermes"


@contextmanager
def running_for_home(home: str | Path | None) -> Iterator[None]:
    """A provider's call, for the home Hermes told it."""

    token = _HOME_TOLD.set(Path(home).expanduser() if home else None)
    try:
        yield
    finally:
        _HOME_TOLD.reset(token)


def _same_home(one: str | Path, other: str | Path) -> bool:
    return Path(one).expanduser().resolve() == Path(other).expanduser().resolve()


def profile_home(name: str) -> Path:
    """Where Hermes keeps a profile, or an error naming how to make one."""

    home = Path.home() / ".hermes" / "profiles" / name
    if not home.is_dir():
        raise ValueError(f"Hermes has no profile called {name!r} here ({home}). To make one: hermes profile create {name}")
    return home


def profile_agent_id(hermes_home: str | Path) -> str:
    """The agent a Hermes home is, when nobody has named one: each profile is an
    agent of its own, with its own memory, as any two agents are. ``hermes`` for
    Hermes' default home, ``hermes-<name>`` for a profile, and for a home kept
    anywhere else its folder's name and a few letters of its path, since two
    folders elsewhere can share a name."""

    home = Path(hermes_home).expanduser()
    default = Path.home() / ".hermes"
    if _same_home(home, default):
        return "hermes"
    if _same_home(home.parent, default / "profiles"):
        return f"hermes-{slugify(home.name, 'profile')}"
    place = hashlib.sha256(str(home.resolve()).encode("utf-8")).hexdigest()[:6]
    name = slugify(home.name, "hermes")
    return f"hermes-{place}" if name == "hermes" else f"hermes-{name}-{place}"


def profile_store(hermes_home: str | Path) -> str:
    """Where that agent's memory is kept, as any agent's is."""

    return str(Path.home() / ".mnemos" / f"{profile_agent_id(hermes_home)}.db")


def config_copied_from_elsewhere(hermes_home: str | Path) -> bool:
    """Whether this home's ``mnemos.json`` was written for another home that is still
    there, so it, and the server in its config, came with a copied profile. A home
    that has gone was moved or renamed (``hermes profile rename``), and it's the same
    agent, with the same memory."""

    written_for = str(_load_json_config(Path(hermes_home).expanduser()).get("hermes_home") or "").strip()
    return bool(written_for) and not _same_home(written_for, hermes_home) and Path(written_for).expanduser().is_dir()


def settle_config_home(hermes_home: str | Path | None = None) -> None:
    """Write down, the first time a copied or moved home is used, that its config is
    its own now. Until then only the home it came from says which it is: if that goes
    a copy would take the original's memory, and if a new one takes a renamed profile's
    old name, that profile would lose its own."""

    home = Path(hermes_home).expanduser() if hermes_home else default_hermes_home()
    written_for = str(_load_json_config(home).get("hermes_home") or "").strip()
    if not written_for or _same_home(written_for, home):
        return
    updates = {"hermes_home": str(home)}
    if config_copied_from_elsewhere(home):
        updates.update(agent_id=profile_agent_id(home), db_path=profile_store(home))
    try:
        save_hermes_mnemos_config(home, updates)
    except OSError:
        pass  # A home it can't write to: it goes on as it was.


def _as_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "y", "on"}:
            return True
        if lowered in {"0", "false", "no", "n", "off"}:
            return False
    return default


def _as_int(value: Any, default: int, *, minimum: int, maximum: int) -> int:
    try:
        return max(minimum, min(maximum, int(value)))
    except Exception:
        return default


class SettingsUnreadable(ValueError):
    """A home's ``mnemos.json`` that is there, isn't blank, and doesn't read as
    an object of settings."""


def _config_path(hermes_home: Path) -> Path:
    return hermes_home / "mnemos.json"


def read_settings(hermes_home: str | Path) -> dict[str, Any]:
    """A home's own ``mnemos.json``, as an object of settings: {} when there is
    none or it is blank. One that is there and can't be read, or doesn't read
    as an object, raises ``SettingsUnreadable``, naming the file and what is
    wrong: the plugin doesn't start for that home and the file isn't written
    over. Until 0.6.7 it counted as no settings, and the next session settled a
    new, empty memory and wrote it over the person's edit."""

    path = _config_path(Path(hermes_home).expanduser())
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    except (OSError, UnicodeError) as exc:
        reason = getattr(exc, "strerror", None) or str(exc)
        raise SettingsUnreadable(_unreadable(path, f"it can't be read ({reason})")) from exc
    if not text.strip():
        return {}
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as exc:
        raise SettingsUnreadable(_unreadable(
            path, f"it isn't valid JSON ({exc.msg}, line {exc.lineno}, column {exc.colno})",
        )) from exc
    if not isinstance(raw, dict):
        kind = {list: "a list", str: "a string", type(None): "null"}.get(type(raw), "a number")
        raise SettingsUnreadable(_unreadable(path, f"it holds {kind}, not settings between {{ and }}"))
    return raw


def _unreadable(path: Path, what: str) -> str:
    return (
        f"Mnemos isn't starting for this Hermes home: its settings in {path} can't be used, as {what}. "
        "Mend the file and start Hermes again. Mnemos hasn't changed it, or started another memory."
    )


def _load_json_config(hermes_home: Path) -> dict[str, Any]:
    path = _config_path(hermes_home)
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return raw if isinstance(raw, dict) else {}


def _cwd_project_scope() -> str:
    cwd = Path.cwd()
    try:
        for parent in (cwd, *cwd.parents):
            if (parent / ".git").exists():
                return slugify(parent.name, "global")
    except Exception:
        pass
    return slugify(cwd.name, "global")


@dataclass(frozen=True)
class HermesMnemosConfig:
    """Profile-local Mnemos settings stored in ``$HERMES_HOME/mnemos.json``.

    ``auto_capture``, ``auto_bootstrap``, ``auto_session_distill`` and
    ``capture_uncertain`` were settings for writing in the agent's place,
    which the provider no longer does (0.4.1); a file that still has them is
    read without them.

    A copied profile is its own agent: ``hermes profile create --clone-all`` copies
    this file with the rest, and two profiles must not share a memory by accident.
    The file says which home it was written for, and elsewhere its agent and store
    don't hold.

    ``max_context_chars`` bounds what recall adds to each message.
    ``max_wake_chars`` bounds the memory a session wakes with; 0 leaves that to
    the wake's own budget, the one every agent's wake has (``PACKET_MAX_CHARS``,
    and the handoff shown whole takes no room from it)."""

    db_path: str | None = None
    agent_id: str | None = None
    person_id: str | None = None
    project_scope: str | None = None
    auto_recall: bool = True
    mirror_builtin_memory: bool = True
    deep_maintenance: bool = False
    max_recall_results: int = 4
    max_context_chars: int = 2200
    max_wake_chars: int = 0
    maintenance_interval: int = 24

    @classmethod
    def load(cls, hermes_home: str | Path | None = None) -> "HermesMnemosConfig":
        home = Path(hermes_home).expanduser() if hermes_home else default_hermes_home()
        raw = _load_json_config(home)
        if config_copied_from_elsewhere(home):
            raw = {**raw, "agent_id": profile_agent_id(home), "db_path": profile_store(home)}
        return cls(
            db_path=str(raw.get("db_path") or "").strip() or None,
            agent_id=str(raw.get("agent_id") or "").strip() or None,
            person_id=str(raw.get("person_id") or "").strip() or None,
            project_scope=str(raw.get("project_scope") or "").strip() or None,
            auto_recall=_as_bool(raw.get("auto_recall"), True),
            mirror_builtin_memory=_as_bool(raw.get("mirror_builtin_memory"), True),
            deep_maintenance=_as_bool(raw.get("deep_maintenance"), False),
            max_recall_results=_as_int(raw.get("max_recall_results"), 4, minimum=1, maximum=16),
            max_context_chars=_as_int(raw.get("max_context_chars"), 2200, minimum=800, maximum=12000),
            max_wake_chars=_as_int(raw.get("max_wake_chars"), 0, minimum=0, maximum=100000),
            maintenance_interval=_as_int(raw.get("maintenance_interval"), 24, minimum=0, maximum=500),
        )

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "db_path": self.db_path,
            "agent_id": self.agent_id,
            "person_id": self.person_id,
            "project_scope": self.project_scope,
            "auto_recall": self.auto_recall,
            "mirror_builtin_memory": self.mirror_builtin_memory,
            "deep_maintenance": self.deep_maintenance,
            "max_recall_results": self.max_recall_results,
            "max_context_chars": self.max_context_chars,
            "max_wake_chars": self.max_wake_chars,
            "maintenance_interval": self.maintenance_interval,
        }


@dataclass(frozen=True)
class HermesScope:
    """Resolved durable identity scope for a Hermes provider instance."""

    agent_id: str
    person_id: str
    project_scope: str
    db_path: str
    hermes_home: Path
    session_id: str
    platform: str = "cli"
    agent_context: str = "primary"
    conversation: str = ""


def memory_file(
    home: Path,
    config: HermesMnemosConfig,
    named: Callable[[str], str] = named_in_the_environment,
) -> str:
    """The memory file a Hermes home opens: the one its ``mnemos.json`` names,
    or else the one ``MNEMOS_DB_PATH`` names as Hermes answers for that home
    (``named``: for the profile that is speaking, by default), or else one in
    the home's own folder. The one answer: the provider opens its memory by it,
    and a backup asks it for every profile (``backup_paths``)."""

    db_path = config.db_path or named("MNEMOS_DB_PATH") or str(home / "mnemos" / "mnemos.db")
    db_path = db_path.replace("$HERMES_HOME", str(home)).replace("${HERMES_HOME}", str(home))
    if db_path.startswith("~"):
        db_path = str(Path(db_path).expanduser())
    return _here_if_restored(home, db_path)


# The homes told that their memory was found in this user's own ~/.mnemos, in
# this process: (home, the path named).
_told_of_a_memory_found_here: set[tuple[str, str]] = set()
_told_lock = threading.Lock()


def _here_if_restored(home: Path, db_path: str) -> str:
    """The memory a home names, or, when that file isn't there, the folder it
    names is a ``.mnemos`` in another home folder beside this user's own
    (``/Users/old/.mnemos/x.db`` seen from ``/Users/new``), and this user's
    ``~/.mnemos/`` holds a file of the same name, that one: a backup restored
    under another home folder (a new Mac, another username) puts the memory
    there, and the settings it restores name it under the old one. The path the
    settings name is left as it is; the log says so once. Anything else, a drive
    that isn't plugged in among them, is the path as named."""

    named = Path(db_path)
    if not named.is_absolute() or named.parent.name != ".mnemos" or named.exists():
        return db_path
    old_home, own_home = named.parent.parent, Path.home()
    if old_home.parent != own_home.parent or old_home == own_home:
        return db_path
    here = own_home / ".mnemos" / named.name
    if not here.is_file():
        return db_path
    told = (str(home), db_path)
    with _told_lock:
        first = told not in _told_of_a_memory_found_here
        _told_of_a_memory_found_here.add(told)
    if first:
        logger.warning(
            "Mnemos's settings in %s name %s, which isn't there; the memory of the same name in this "
            "user's ~/.mnemos is opened instead: %s. The path the settings name is left as it is.",
            _config_path(home), db_path, here,
        )
    return str(here)


def derive_hermes_scope(
    *,
    session_id: str = "",
    hermes_home: str | Path | None = None,
    config: HermesMnemosConfig | None = None,
    runtime_context: dict[str, Any] | None = None,
) -> HermesScope:
    """Derive Mnemos agent/person/project scope from Hermes runtime context."""

    context = dict(runtime_context or {})
    home = Path(hermes_home or context.get("hermes_home") or default_hermes_home()).expanduser()
    cfg = config or HermesMnemosConfig.load(home)

    agent_raw = (
        cfg.agent_id
        or named_in_the_environment("MNEMOS_AGENT_ID")
        or context.get("agent_identity")
        or context.get("profile")
        or "hermes"
    )
    person_raw = (
        cfg.person_id
        or named_in_the_environment("MNEMOS_PERSON_ID")
        or context.get("user_name")
        or context.get("user_id")
        or context.get("chat_id")
        or "user"
    )
    project_raw = (
        cfg.project_scope
        or named_in_the_environment("MNEMOS_PROJECT_SCOPE")
        or context.get("project_scope")
        or context.get("chat_name")
        or _cwd_project_scope()
    )

    db_path = memory_file(home, cfg)
    session = str(session_id or context.get("session_id") or "")

    return HermesScope(
        agent_id=slugify(str(agent_raw), "hermes"),
        person_id=slugify(str(person_raw), "user"),
        project_scope=slugify(str(project_raw), "global"),
        db_path=db_path,
        hermes_home=home,
        session_id=session,
        platform=str(context.get("platform") or "cli"),
        agent_context=str(context.get("agent_context") or "primary"),
        conversation=conversation_id(
            gateway_session_key=str(context.get("gateway_session_key") or ""),
            session_id=session,
        ),
    )


def save_hermes_mnemos_config(
    hermes_home: str | Path,
    updates: dict[str, Any],
) -> Path:
    """Merge Mnemos settings into ``$HERMES_HOME/mnemos.json``."""

    home = Path(hermes_home).expanduser()
    home.mkdir(parents=True, exist_ok=True)
    path = _config_path(home)
    existing = read_settings(home)  # one that can't be read is never written over
    merged = {**existing, **{k: v for k, v in updates.items() if v not in (None, "")}}
    if merged == existing and path.exists():
        return path
    atomic_write_text(
        path, json.dumps(merged, indent=2, sort_keys=True) + "\n",
        backup_existing=True,
    )
    return path
