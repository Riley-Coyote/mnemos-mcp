"""`mnemos log`: the log, served on this machine only.

The page is static (mnemos/companion/page) and asks for two documents,
../data/life.json and ../data/memories.json, every twenty seconds. This
answers them by exporting on request (``export.Exporter``), read-only, and
keeps the result a few seconds, so two tabs or a quick reload read the store
once.

It listens on 127.0.0.1 only, on a port the system picks, under a path made
fresh each run, and answers only requests addressed to 127.0.0.1 or
localhost, so neither another person on this machine nor a website in the
browser can read the memory through it. Nothing it serves leaves this
machine.

It writes the person's own words, left on the page, and that they read a
note there. A reply to one of the agent's notes, or a note of their own, goes
through the commands `mnemos notes reply` and `mnemos notes write` use
(``interface.person``), kept exactly as given and marked as theirs, and the
agent wakes with it. A note of the agent's they read on the page is marked
read here, as `mnemos notes` marks what it shows. Only the page itself can send
either: a request must come from the page's own address, as JSON, to the
run's own path, and anything else is refused.

``mnemos log`` serves it until Ctrl-C; an agent's ``mnemos_page`` serves the
same, from its MCP server, until that server stops.
"""

from __future__ import annotations

import dataclasses
import json
import logging
import os
import re
import secrets
import socketserver
import sqlite3
import sys
import threading
import time
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from pathlib import Path
from typing import TextIO
from urllib.parse import unquote, urlsplit

from .export import MOST_BYTES, UNFILED, Exporter

logger = logging.getLogger(__name__)

CACHE_SECONDS = 5.0
# What the page may write: only the person's own words (a note, a reply, a correction in their words, a memory they
# let go), which notes they read, whether and when the agent's quiet hours run, and whether Jev judges what comes
# to mind, with the person's own key (the settings that are the person's to decide; the rest of Mnemos tunes
# itself). A correction or a forget is always the person's, whoever serves the page.
ACTS = ("reply", "note", "read", "hours", "jev", "correct", "forget", "shared")
CLOCK = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")
MOST_READ = 200
MOST_ACT_BYTES = 32 * 1024
TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".woff2": "font/woff2",
    ".woff": "font/woff",
    ".txt": "text/plain; charset=utf-8",
}
PICTURE_TYPES = {
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".gif": "image/gif", ".svg": "image/svg+xml", ".webp": "image/webp",
}
# The page asks nothing of anywhere but here; the browser holds it to that.
PAGE_POLICY = (
    "default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; font-src 'self'; connect-src 'self'; frame-src 'self'; "
    "base-uri 'none'; form-action 'none'; frame-ancestors 'self'"
)
# A picture the hours made is shown, never run (an SVG can carry a script).
PICTURE_POLICY = "default-src 'none'; style-src 'unsafe-inline'; sandbox"


def page_files() -> dict[str, bytes]:
    """Every file of the page by its path under the page folder
    (``log/index.html``), read once."""
    files: dict[str, bytes] = {}

    def walk(node, prefix: str) -> None:
        for child in node.iterdir():
            if child.name.startswith(".") or child.name == "__pycache__":
                continue
            if child.is_dir():
                walk(child, f"{prefix}{child.name}/")
            else:
                files[prefix + child.name] = child.read_bytes()

    walk(resources.files(__package__).joinpath("page"), "")
    return files


def _dumps(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _inside_hermes() -> bool:
    """Whether this page is served from inside Hermes, which hands Mnemos its keys.
    Hermes's plugin rules: a plugin uses no other program's sign-in and keeps no
    key of its own outside Hermes, so from there the page changes neither the
    quiet hours (``claude -p``, on the person's own account, in the system's
    scheduler) nor Jev (a key in a file): both are Claude Code's, and set there."""
    from ..llm import host_secrets_active

    return host_secrets_active()


# The mind the log was started for is named as Mnemos names it, by the model that signs its memories ("Opus 5.5").
# A mind found beside it is named by its own agent id ("anima" is Anima, whatever model it runs on), unless that id
# only says what runs it (one of these), when its model names it too.
GENERIC_AGENTS = {"claude-code", "codex", "mnemos-agent", "default", "agent", "assistant"}
MINDS_SECONDS = 60.0


def mind_name(agent_id: str, signed: str) -> str:
    """What the page calls a mind: its own name, or for a generic agent id the model that signs it."""
    if agent_id in GENERIC_AGENTS or not agent_id:
        return signed or agent_id
    return " ".join(word[:1].upper() + word[1:] for word in re.split(r"[-_\s]+", agent_id) if word)


def minds_beside(home: Exporter) -> list[Exporter]:
    """The other minds that keep their memory in the same folder as this one, one store each, named for the agent
    (``<agent>.db``, as Mnemos makes them): each read from the person and project that hold most of its memories.
    A store that pools several agents (a shared pool, an old default store) is left out: its file names no one."""
    from ..simple_scope import resolve_scope
    from .. import shared_memory
    from .export import open_read_only

    found: list[Exporter] = []
    folder = home.db.parent
    if not folder.is_dir():
        return found
    for path in sorted(folder.glob("*.db")):
        try:
            if path.resolve() == shared_memory.path().resolve():
                continue
        except ValueError:
            pass
        agent = path.stem
        if agent == home.scope.agent_id or path.resolve() == home.db.resolve():
            continue
        try:
            conn = open_read_only(path)
        except Exception:
            continue
        try:
            columns = {r[1] for r in conn.execute("PRAGMA table_info(engrams)")}
            if "owner_agent_id" not in columns:
                continue
            person = "person_id" if "person_id" in columns else "NULL"
            project = "project_scope" if "project_scope" in columns else "NULL"
            row = conn.execute(
                f"SELECT {person}, {project}, count(*) FROM engrams WHERE owner_agent_id=? "
                "AND state IN ('active','dormant') GROUP BY 1, 2 ORDER BY 3 DESC LIMIT 1", (agent,)).fetchone()
        except sqlite3.Error:
            continue
        finally:
            conn.close()
        if not row or not row[2]:
            continue
        scope = resolve_scope(db_path=str(path), agent_id=agent)
        # read from where its memories are: a store from before they were filed by person and project reads as unfiled
        scope = dataclasses.replace(scope, person_id=row[0] or UNFILED, project_scope=row[1] or UNFILED)
        found.append(Exporter(scope, home.person))
    return found


class _Mind:
    """One mind the page can show: its exporter, and its documents as last made."""

    def __init__(self, exporter: Exporter) -> None:
        self.exporter = exporter
        self.lock = threading.Lock()
        self.documents: tuple[float, bytes] | None = None
        self.memories: tuple[str | None, bytes] | None = None
        self.searching = threading.Lock()
        self.interface = None                # the person's reading of it, for search, made on the first one

    def forget(self) -> None:
        with self.lock:
            self.documents = None


class LogServer(ThreadingHTTPServer):
    """The log's server for one scope, bound to 127.0.0.1: that mind first, and the others kept beside it."""

    daemon_threads = True
    # The page asks for a burst of small files at once (a dozen workers drawing the glyphs, the mind's builder and its
    # modules); Python's default backlog of 5 turns the rest away, and the browser reports ERR_SOCKET_NOT_CONNECTED.
    request_queue_size = 128

    def __init__(self, exporter: Exporter, *, port: int = 0, token: str | None = None) -> None:
        self.exporter = exporter
        self.token = token or secrets.token_urlsafe(16)
        self.files = page_files()
        self._lock = threading.Lock()
        self._settings = threading.Lock()  # one change to the schedule at a time
        self._home = _Mind(exporter)
        self._others: tuple[float, dict[str, _Mind]] | None = None
        super().__init__(("127.0.0.1", port), _Handler)

    def server_bind(self) -> None:
        # HTTPServer.server_bind looks up this host's name, which can stall
        # for seconds on some networks and isn't needed: the name is known.
        socketserver.TCPServer.server_bind(self)
        self.server_name, self.server_port = "127.0.0.1", self.server_address[1]

    @property
    def port(self) -> int:
        return self.server_address[1]

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/{self.token}/log/"

    def origins(self) -> set[str]:
        """The page's own address, as a browser names it on a request it sends."""
        return {f"http://127.0.0.1:{self.port}", f"http://localhost:{self.port}"}

    def act(self, request: dict, agent: str | None = None) -> dict:
        """Write the person's own words, a reply or a note, as `mnemos notes`
        writes them, or that they read notes of the agent's, answered as
        ``mnemos interface`` answers (``{"result": ...}`` or ``{"error": one
        plain sentence}``). The page's documents are read again on its next
        look, so what was written shows at once."""
        from ..interface.person import Interface  # the writing runtime, only when someone writes

        mind = self.mind(agent)
        if mind is None:
            return {"error": "There's no such mind on this machine."}
        if request.get("command") == "shared":
            from ..shared_memory import notebook_act
            with self._settings:
                answer = notebook_act(request)
            self._home.forget()
            for other in (self._others[1].values() if self._others else []):
                other.forget()
            return answer
        if request.get("command") == "jev":
            return self._jev(request, mind)
        if UNFILED in (mind.exporter.scope.person_id, mind.exporter.scope.project_scope):
            return {"error": "This mind's memory is from before notes and hours; the page only reads it."}
        if request.get("command") == "read":
            return self._read(request.get("note_ids"), mind)
        if request.get("command") == "hours":
            return self._hours(request, mind)
        if request.get("command") == "forget" and request.get("confirmed") is not True:
            return {"error": "Letting a memory go is asked for twice: the page asks first."}
        scope = mind.exporter.scope
        if request.get("command") in ("correct", "forget"):
            # through the warm reading the search keeps (a correction's words are embedded as they're kept), as the person
            with mind.searching:
                if mind.interface is None:
                    mind.interface = Interface(db_path=scope.db_path, agent_id=scope.agent_id, person_id=scope.person_id,
                                               project_scope=scope.project_scope, person=True)
                    mind.interface.warm()
                answer = mind.interface.answer(json.dumps({k: v for k, v in request.items() if k != "confirmed"}))
            answer.pop("id", None)
            mind.forget()
            return answer
        interface = Interface(db_path=scope.db_path, agent_id=scope.agent_id,
                              person_id=scope.person_id, project_scope=scope.project_scope)
        answer = interface.answer(json.dumps(request))
        answer.pop("id", None)
        mind.forget()
        return answer

    def _hours(self, request: dict, mind: _Mind) -> dict:
        """Turn the agent's quiet hours on, at the times given (each HH:MM, or
        its own default), or off: exactly what `mnemos daemon install --hours
        --write` and `mnemos daemon uninstall --hours --write` do for this
        scope, answered ``{"result": what it said}`` or ``{"error": ...}``."""
        import argparse
        import contextlib
        import io

        from .. import cli

        if _inside_hermes():
            return {"error": "Quiet hours use your selected CLI account and are set on the host, not inside Hermes."}
        on = request.get("on")
        if not isinstance(on, bool):
            return {"error": '"on" says whether the quiet hours run: true or false.'}
        times: dict[str, tuple[int, int] | None] = {}
        for key in ("mine", "ours", "dream"):
            value = request.get(key)
            if value in (None, ""):
                times[key] = None
                continue
            match = CLOCK.match(value) if isinstance(value, str) else None
            if not match:
                return {"error": f'"{key}" is a time of day, like 08:00.'}
            times[key] = (int(match.group(1)), int(match.group(2)))
        from ..setup.state import hour_settings
        from ..authorship import clean_model_id

        selected = hour_settings(mind.exporter.scope.agent_id)
        runner = request.get("runner", selected["runner"])
        model = request.get("model", selected["model"])
        if runner not in ("claude-code", "codex"):
            return {"error": '"runner" must be claude-code or codex.'}
        if on and (not isinstance(model, str) or (model.strip() and not clean_model_id(model))):
            return {"error": '"model" must be a model ID, or empty for the default.'}
        model = clean_model_id(model) if isinstance(model, str) else ""
        scope = mind.exporter.scope
        args = argparse.Namespace(
            daemon_command="install" if on else "uninstall", hours=True, write=True, runner=runner, model=model,
            mine_at=times["mine"] if on else None, ours_at=times["ours"] if on else None,
            dream_at=times["dream"] if on else None,
            db_path=scope.db_path, agent_id=scope.agent_id, person_id=scope.person_id,
            project_scope=scope.project_scope)
        said, failed = io.StringIO(), io.StringIO()
        with self._settings, contextlib.redirect_stdout(said), contextlib.redirect_stderr(failed):
            try:
                code = cli._cmd_daemon(args)
            except Exception as exc:  # anything else is one plain line, never a trace
                code, _ = 1, failed.write(f"{exc}")
        mind.forget()
        if code != 0:
            words = " ".join(failed.getvalue().split()) or " ".join(said.getvalue().split())
            return {"error": words[:400] or "The quiet hours couldn't be changed."}
        return {"result": " ".join(said.getvalue().split())[:400]}

    def _jev(self, request: dict, mind: _Mind) -> dict:
        """Jev, the cue's judge, as the person sets it, one change at a time:
        save its key (``{"key": ...}``), remove it (``{"remove_key": true}``,
        which turns Jev off too), or turn it on or off (``{"on": ...}``), on
        only with a key saved. What ``jev.save_key``, ``jev.remove_key`` and
        ``jev.set_switch`` do, for the whole machine. The key is never said
        back: not in a reply, an error or a log line."""
        from .. import jev

        if _inside_hermes():
            return {"error": "Jev judges the cue in Claude Code and never runs inside Hermes, so it's set "
                             "from Claude Code, not from here."}
        with self._settings:
            try:
                if request.get("remove_key") is True:
                    jev.remove_key()
                    jev.set_switch(False)
                    said = "The key is removed, and Jev is off."
                elif "key" in request:
                    key = request.get("key")
                    jev.save_key(key.strip() if isinstance(key, str) else key)
                    said = "The key is saved. Turn Jev on when you want it."
                elif isinstance(request.get("on"), bool):
                    if request["on"] and not jev.has_key():
                        return {"error": "Save a key first: without one, Jev can't run."}
                    jev.set_switch(request["on"])
                    said = "Jev is on." if request["on"] else "Jev is off."
                else:
                    return {"error": 'Jev takes a "key" to save, "remove_key", or "on": true or false.'}
            except ValueError as exc:  # its words never hold the key
                return {"error": str(exc)}
            except OSError:
                return {"error": "Jev's setting couldn't be saved on this machine."}
        mind.forget()
        return {"result": said}

    def _read(self, ids: object, mind: _Mind) -> dict:
        """Mark these notes of the agent's read, each once (one already read
        keeps its time), as `mnemos notes` marks the notes it shows: ``{"result":
        the ids this marked}``. Ids that aren't the agent's notes here mark
        nothing, and no store is ever made."""
        from ..simple_runtime import MnemosRuntime

        if (not isinstance(ids, list) or not ids or len(ids) > MOST_READ
                or not all(isinstance(i, str) and i.strip() for i in ids)):
            return {"error": f'"note_ids" is a list of the notes read, at most {MOST_READ}.'}
        if not mind.exporter.db.is_file():
            return {"result": []}
        scope = mind.exporter.scope
        writer = MnemosRuntime(db_path=scope.db_path, agent_id=scope.agent_id, person_id=scope.person_id,
                               project_scope=scope.project_scope, use_dedicated_model=False, marks_lived=False)
        try:
            marked = writer.mark_notes_read([i.strip() for i in ids])
        except sqlite3.Error:
            return {"error": "It couldn't be marked read just now."}
        finally:
            writer.close()
        mind.forget()
        return {"result": marked}

    def addressed_here(self, host: str) -> bool:
        """Whether a request names this server by the loopback address or
        localhost, as the page always does; anything else (another site whose
        name now points here) is refused."""
        return host.strip().lower() in {f"127.0.0.1:{self.port}", f"localhost:{self.port}"}

    def mind(self, agent: str | None = None) -> _Mind | None:
        """The mind a request names (``?agent=``), or this server's own; None for one not on this machine."""
        if not agent or agent == self.exporter.scope.agent_id:
            return self._home
        return self.others().get(agent)

    def others(self) -> dict[str, _Mind]:
        """The other minds beside this one, looked for again at most once a minute."""
        with self._lock:
            now = time.monotonic()
            if self._others is None or now - self._others[0] >= MINDS_SECONDS:
                kept = self._others[1] if self._others else {}
                self._others = (now, {e.scope.agent_id: kept.get(e.scope.agent_id) or _Mind(e)
                                      for e in minds_beside(self.exporter)})
            return self._others[1]

    def minds(self) -> bytes:
        """``minds.json``: every mind the page can show, this server's own first."""
        out = []
        for agent, mind in [(self.exporter.scope.agent_id, self._home), *self.others().items()]:
            try:
                life = json.loads(self.documents(agent)[0])
            except Exception:
                continue
            who, memory = life.get("identity", {}), life.get("memory", {})
            out.append({"agentId": agent, "name": who.get("name") or agent, "model": who.get("model", ""),
                        "memories": memory.get("count", 0), "newest": memory.get("newest"),
                        "home": mind is self._home, "missing": bool(life.get("missing"))})
        return _dumps({"minds": out})

    def pulse(self, agent: str | None, since: str | None) -> bytes:
        """``pulse.json``: what came to a mind since ``since`` (``export.pulse``)."""
        from .export import pulse

        mind = self.mind(agent)
        if mind is None:
            raise LookupError(agent)
        return _dumps(pulse(mind.exporter, since))

    def search(self, agent: str | None, query: str) -> bytes:
        """``search.json``: the memories a query finds, by meaning and by words, as
        ``mnemos search --json`` answers; it writes nothing and wakes nothing (a
        person looking is not the mind remembering). An empty query loads the
        meaning model and finds nothing, so the page can ask early."""
        from ..interface.person import Interface

        mind = self.mind(agent)
        if mind is None:
            raise LookupError(agent)
        with mind.searching:
            if mind.interface is None:
                scope = mind.exporter.scope
                mind.interface = Interface(db_path=scope.db_path, agent_id=scope.agent_id, person_id=scope.person_id,
                                           project_scope=scope.project_scope, person=True)
                mind.interface.warm()
            if not query.strip():
                return _dumps({"query": "", "results": []})
            answer = mind.interface.answer(json.dumps({"command": "search", "query": query[:400], "max_results": 24}))
        return _dumps(answer.get("result") or {"query": query, "results": [], "error": answer.get("error")})

    def documents(self, agent: str | None = None) -> tuple[bytes, bytes]:
        """``(life.json, memories.json)`` for a mind, exported at most every few
        seconds. memories.json is made again only when its version changes."""
        mind = self.mind(agent)
        if mind is None:
            raise LookupError(agent)
        with mind.lock:
            now = time.monotonic()
            if mind.documents is None or now - mind.documents[0] >= CACHE_SECONDS:
                life, memories = mind.exporter.export()
                if mind is not self._home:     # the server's own mind keeps the name its model gives it
                    who = life.get("identity") or {}
                    who["name"] = mind_name(who.get("agentId", ""), who.get("name", ""))
                    from urllib.parse import quote
                    for item in life.get("studio") or []:   # its pictures are its own studio's
                        if item.get("picture"):
                            item["picture"] += f"?agent={quote(mind.exporter.scope.agent_id)}"
                version = memories.get("version")
                if mind.memories is None or mind.memories[0] != version or version is None:
                    mind.memories = (version, _dumps(memories))
                mind.documents = (now, _dumps(life))
            assert mind.memories is not None
            return mind.documents[1], mind.memories[1]


def _agent(path: str) -> str | None:
    """The mind a request names, ``?agent=<id>``, or None for the server's own."""
    from urllib.parse import parse_qs

    named = parse_qs(urlsplit(path).query).get("agent")
    return named[0] if named else None


class _Handler(BaseHTTPRequestHandler):
    server: LogServer
    server_version = "mnemos-log"
    sys_version = ""

    def do_GET(self) -> None:
        self._answer(body=True)

    def do_HEAD(self) -> None:
        self._answer(body=False)

    def do_POST(self) -> None:
        """From the page: the person's reply or note, or the notes they read, and nothing else."""
        server = self.server
        if not server.addressed_here(self.headers.get("Host", "")):
            return self._json(HTTPStatus.FORBIDDEN, {"error": "The log answers only on 127.0.0.1."})
        if urlsplit(self.path).path != f"/{server.token}/act":
            return self._json(HTTPStatus.NOT_FOUND, {"error": "Not here."})
        # A browser names the page a request comes from, and a site elsewhere can't send JSON here
        # without asking first, which this never answers: so only the log's own page writes.
        if self.headers.get("Origin", "") not in server.origins():
            return self._json(HTTPStatus.FORBIDDEN, {"error": "Only the log's own page can write here."})
        if self.headers.get("Content-Type", "").split(";")[0].strip().lower() != "application/json":
            return self._json(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, {"error": "A request is JSON."})
        try:
            length = int(self.headers.get("Content-Length", ""))
        except ValueError:
            return self._json(HTTPStatus.LENGTH_REQUIRED, {"error": "A request says how long it is."})
        if length > MOST_ACT_BYTES:
            return self._json(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, {"error": "That's longer than a note can be here."})
        try:
            request = json.loads(self.rfile.read(length) or b"null")
        except ValueError:
            request = None
        if not isinstance(request, dict) or request.get("command") not in ACTS:
            return self._json(HTTPStatus.BAD_REQUEST, {"error": "The page can leave a reply or a note, correct a memory or let one go, say a note was read, turn the quiet hours on or off, or set Jev, and nothing else."})
        answer = server.act(request, _agent(self.path))
        return self._json(HTTPStatus.OK if "result" in answer else HTTPStatus.BAD_REQUEST, answer)

    def log_message(self, format: str, *args: object) -> None:
        # One line per request on stderr would bury the address; keep them for debugging.
        logger.debug("%s " + format, self.address_string(), *args)

    def _answer(self, *, body: bool) -> None:
        server = self.server
        if not server.addressed_here(self.headers.get("Host", "")):
            return self._send(HTTPStatus.FORBIDDEN, b"The log answers only on 127.0.0.1.\n", TYPES[".txt"], body)
        path = urlsplit(self.path).path
        base = f"/{server.token}"
        if path in (base, f"{base}/", f"{base}/log"):
            return self._redirect(f"{base}/log/")
        if not path.startswith(f"{base}/"):
            return self._send(HTTPStatus.NOT_FOUND, b"Not here.\n", TYPES[".txt"], body)
        rel = unquote(path[len(base) + 1:])
        if rel == "data/minds.json":
            return self._send(HTTPStatus.OK, server.minds(), "application/json; charset=utf-8", body)
        if rel in ("data/pulse.json", "data/search.json"):
            return self._looked(rel, body)
        if rel in ("data/life.json", "data/memories.json"):
            return self._data(rel, body)
        if rel.startswith("data/studio/"):
            return self._picture(rel[len("data/studio/"):], body)
        name = f"{rel}index.html" if rel.endswith("/") else rel
        content = server.files.get(name)
        if content is None:
            return self._send(HTTPStatus.NOT_FOUND, b"Not here.\n", TYPES[".txt"], body)
        kind = TYPES.get(Path(name).suffix.lower(), "application/octet-stream")
        extra = {"Content-Security-Policy": PAGE_POLICY} if name.endswith(".html") else {}
        return self._send(HTTPStatus.OK, content, kind, body, cache="no-cache", **extra)

    def _data(self, rel: str, body: bool) -> None:
        try:
            life, memories = self.server.documents(_agent(self.path))
        except LookupError:
            return self._send(HTTPStatus.NOT_FOUND, b'{"error":"there is no such mind on this machine"}',
                              "application/json; charset=utf-8", body)
        except Exception:
            # The page keeps what it has and asks again in twenty seconds.
            logger.warning("mnemos log: the memory couldn't be read just now", exc_info=True)
            return self._send(HTTPStatus.SERVICE_UNAVAILABLE, b'{"error":"the memory could not be read"}',
                              "application/json; charset=utf-8", body)
        content = life if rel == "data/life.json" else memories
        return self._send(HTTPStatus.OK, content, "application/json; charset=utf-8", body)

    def _looked(self, rel: str, body: bool) -> None:
        """What came to mind just now, or what a search finds: read on every request, never kept."""
        from urllib.parse import parse_qs

        asked = parse_qs(urlsplit(self.path).query)
        try:
            if rel == "data/pulse.json":
                since = (asked.get("since") or [None])[0]
                # a time's "+00:00" reads as " 00:00" in an address that didn't encode it: read it as it was meant
                content = self.server.pulse(_agent(self.path), since.replace(" ", "+") if since else None)
            else:
                content = self.server.search(_agent(self.path), (asked.get("q") or [""])[0])
        except LookupError:
            return self._send(HTTPStatus.NOT_FOUND, b'{"error":"there is no such mind on this machine"}',
                              "application/json; charset=utf-8", body)
        except Exception:
            logger.warning("mnemos log: %s couldn't be read just now", rel, exc_info=True)
            return self._send(HTTPStatus.SERVICE_UNAVAILABLE, b'{"error":"the memory could not be read"}',
                              "application/json; charset=utf-8", body)
        return self._send(HTTPStatus.OK, content, "application/json; charset=utf-8", body)

    def _picture(self, rel: str, body: bool) -> None:
        """A picture from the studio, as it is: only a picture, only from
        inside the studio (links followed), never a hidden file."""
        mind = self.server.mind(_agent(self.path))
        root = mind.exporter.studio_dir if mind else None
        kind = PICTURE_TYPES.get(Path(rel).suffix.lower())
        if root is None or kind is None or any(part.startswith(".") for part in Path(rel).parts):
            return self._send(HTTPStatus.NOT_FOUND, b"Not here.\n", TYPES[".txt"], body)
        studio = os.path.realpath(root)
        path = os.path.realpath(os.path.join(studio, rel))
        if not path.startswith(studio + os.sep):
            return self._send(HTTPStatus.NOT_FOUND, b"Not here.\n", TYPES[".txt"], body)
        try:
            if not os.path.isfile(path) or os.path.getsize(path) > MOST_BYTES:
                raise FileNotFoundError(rel)
            with open(path, "rb") as picture:
                content = picture.read()
        except OSError:
            return self._send(HTTPStatus.NOT_FOUND, b"Not here.\n", TYPES[".txt"], body)
        return self._send(HTTPStatus.OK, content, kind, body,
                          cache="no-cache", **{"Content-Security-Policy": PICTURE_POLICY})

    def _json(self, status: HTTPStatus, value: dict) -> None:
        self._send(status, json.dumps(value, ensure_ascii=False).encode("utf-8"),
                   "application/json; charset=utf-8", True)

    def _redirect(self, location: str) -> None:
        try:
            self.send_response(HTTPStatus.FOUND)
            self.send_header("Location", location)
            self.send_header("Content-Length", "0")
            self.end_headers()
        except (BrokenPipeError, ConnectionResetError):
            self.close_connection = True

    def _send(self, status: HTTPStatus, content: bytes, kind: str, body: bool, *,
              cache: str = "no-store", **headers: str) -> None:
        # The browser may hang up before the answer is all sent (a page closed, or reloaded mid-load): there's
        # no one left to answer, so the connection just ends, with no trace on the terminal.
        try:
            self.send_response(status)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Cache-Control", cache)
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            for name, value in headers.items():
                self.send_header(name, value)
            self.end_headers()
            if body:
                self.wfile.write(content)
        except (BrokenPipeError, ConnectionResetError):
            self.close_connection = True


def open_page(scope: dict[str, str | None], page: LogServer | None = None) -> tuple[str, LogServer | None]:
    """What ``mnemos_page`` answers, and the page now open: ``page`` when one is, or
    a new one for ``scope``, started in a thread of its own on 127.0.0.1. One that
    can't start, or can't read the memory, isn't opened: it says why in a sentence."""
    opened = page
    if opened is None:
        try:
            opened = LogServer(Exporter.for_scope(**scope))
        except OSError as exc:
            return f"The page couldn't start: {exc}", None
    try:
        # What the page will show, read now: one that can't be read isn't opened.
        missing = bool(json.loads(opened.documents()[0]).get("missing"))
    except Exception as exc:
        if opened is not page:
            opened.server_close()
        return f"The page couldn't read this memory just now: {type(exc).__name__}: {exc}", page
    if opened is not page:
        threading.Thread(target=opened.serve_forever, name="mnemos-page", daemon=True).start()
    lines = [
        f"Your page is open: {opened.url}",
        "Open it for them: in your own browser pane if you have one, with the system's open "
        "command if you have a shell, or give them the link. It runs on this machine only, "
        "until this session ends.",
    ]
    if missing:
        lines.append("Nothing is kept here yet, so the page says so.")
    return "\n".join(lines), opened


def serve(*, db_path: str | None = None, agent_id: str | None = None, person_id: str | None = None,
          project_scope: str | None = None, person: str | None = None, open_browser: bool = True,
          out: TextIO | None = None, err: TextIO | None = None) -> int:
    """Serve the log until interrupted (Ctrl-C). Returns the exit status."""
    out = out or sys.stdout
    err = err or sys.stderr
    exporter = Exporter.for_scope(db_path=db_path, agent_id=agent_id, person_id=person_id,
                                  project_scope=project_scope, person=person)
    try:
        server = LogServer(exporter)
    except OSError as exc:
        print(f"The log couldn't start: {exc}", file=err)
        return 1
    try:
        life = json.loads(server.documents()[0])
    except Exception as exc:
        server.server_close()
        print(f"The memory at {exporter.db} couldn't be read: {exc}", file=err)
        return 1
    who = life["identity"]
    print(f"The log of {who['name']}: {server.url}", file=out, flush=True)
    if life.get("missing"):
        print(f"There's no memory at {who['store']} for {who['agentId']} yet; the page says so. "
              "If your agent keeps its memory under another name, start the log with --agent-id.",
              file=out, flush=True)
    print("On this machine only. It keeps nothing but the replies and notes you leave, and which notes you've read. "
          "Ctrl-C stops it.",
          file=out, flush=True)
    if open_browser:
        try:
            webbrowser.open(server.url)
        except Exception:
            pass  # the address is printed above
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    print("Stopped.", file=out, flush=True)
    return 0
