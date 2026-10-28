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

import json
import logging
import os
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

from .export import MOST_BYTES, Exporter

logger = logging.getLogger(__name__)

CACHE_SECONDS = 5.0
# What the page may write: only the person's own words, and which notes they read.
ACTS = ("reply", "note", "read")
MOST_READ = 200
MOST_ACT_BYTES = 32 * 1024
TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".woff2": "font/woff2",
    ".txt": "text/plain; charset=utf-8",
}
PICTURE_TYPES = {
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".gif": "image/gif", ".svg": "image/svg+xml", ".webp": "image/webp",
}
# The page asks nothing of anywhere but here; the browser holds it to that.
PAGE_POLICY = (
    "default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; font-src 'self'; connect-src 'self'; "
    "base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
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


class LogServer(ThreadingHTTPServer):
    """The log's server for one scope, bound to 127.0.0.1."""

    daemon_threads = True

    def __init__(self, exporter: Exporter, *, port: int = 0, token: str | None = None) -> None:
        self.exporter = exporter
        self.token = token or secrets.token_urlsafe(16)
        self.files = page_files()
        self._lock = threading.Lock()
        self._documents: tuple[float, bytes] | None = None
        self._memories: tuple[str | None, bytes] | None = None
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

    def act(self, request: dict) -> dict:
        """Write the person's own words, a reply or a note, as `mnemos notes`
        writes them, or that they read notes of the agent's, answered as
        ``mnemos interface`` answers (``{"result": ...}`` or ``{"error": one
        plain sentence}``). The page's documents are read again on its next
        look, so what was written shows at once."""
        from ..interface.person import Interface  # the writing runtime, only when someone writes

        if request.get("command") == "read":
            return self._read(request.get("note_ids"))
        scope = self.exporter.scope
        interface = Interface(db_path=scope.db_path, agent_id=scope.agent_id,
                              person_id=scope.person_id, project_scope=scope.project_scope)
        answer = interface.answer(json.dumps(request))
        answer.pop("id", None)
        with self._lock:
            self._documents = None
        return answer

    def _read(self, ids: object) -> dict:
        """Mark these notes of the agent's read, each once (one already read
        keeps its time), as `mnemos notes` marks the notes it shows: ``{"result":
        the ids this marked}``. Ids that aren't the agent's notes here mark
        nothing, and no store is ever made."""
        from ..simple_runtime import MnemosRuntime

        if (not isinstance(ids, list) or not ids or len(ids) > MOST_READ
                or not all(isinstance(i, str) and i.strip() for i in ids)):
            return {"error": f'"note_ids" is a list of the notes read, at most {MOST_READ}.'}
        if not self.exporter.db.is_file():
            return {"result": []}
        scope = self.exporter.scope
        writer = MnemosRuntime(db_path=scope.db_path, agent_id=scope.agent_id, person_id=scope.person_id,
                               project_scope=scope.project_scope, use_dedicated_model=False, marks_lived=False)
        try:
            marked = writer.mark_notes_read([i.strip() for i in ids])
        except sqlite3.Error:
            return {"error": "It couldn't be marked read just now."}
        finally:
            writer.close()
        with self._lock:
            self._documents = None
        return {"result": marked}

    def addressed_here(self, host: str) -> bool:
        """Whether a request names this server by the loopback address or
        localhost, as the page always does; anything else (another site whose
        name now points here) is refused."""
        return host.strip().lower() in {f"127.0.0.1:{self.port}", f"localhost:{self.port}"}

    def documents(self) -> tuple[bytes, bytes]:
        """``(life.json, memories.json)``, exported at most every few seconds.
        memories.json is made again only when its version changes."""
        with self._lock:
            now = time.monotonic()
            if self._documents is None or now - self._documents[0] >= CACHE_SECONDS:
                life, memories = self.exporter.export()
                version = memories.get("version")
                if self._memories is None or self._memories[0] != version or version is None:
                    self._memories = (version, _dumps(memories))
                self._documents = (now, _dumps(life))
            assert self._memories is not None
            return self._documents[1], self._memories[1]


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
            return self._json(HTTPStatus.BAD_REQUEST, {"error": "The page can leave a reply or a note, or say a note was read, and nothing else."})
        answer = server.act(request)
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
            life, memories = self.server.documents()
        except Exception:
            # The page keeps what it has and asks again in twenty seconds.
            logger.warning("mnemos log: the memory couldn't be read just now", exc_info=True)
            return self._send(HTTPStatus.SERVICE_UNAVAILABLE, b'{"error":"the memory could not be read"}',
                              "application/json; charset=utf-8", body)
        content = life if rel == "data/life.json" else memories
        return self._send(HTTPStatus.OK, content, "application/json; charset=utf-8", body)

    def _picture(self, rel: str, body: bool) -> None:
        """A picture from the studio, as it is: only a picture, only from
        inside the studio (links followed), never a hidden file."""
        root = self.server.exporter.studio_dir
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
        self.send_response(HTTPStatus.FOUND)
        self.send_header("Location", location)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _send(self, status: HTTPStatus, content: bytes, kind: str, body: bool, *,
              cache: str = "no-store", **headers: str) -> None:
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
