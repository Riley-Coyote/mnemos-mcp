"""Meaning stays on this machine unless the person chooses Gemini for it.

Until 2026-10-19 a GEMINI_API_KEY anywhere Mnemos looks (the environment, the
working folder's .env, ~/.mnemos/.env) was enough: meaning search switched to
Google's Gemini API, and every memory it indexed and every question asked of
it by meaning went to Google, with no Mnemos setting at all. People keep that
key for other tools, and a mind that runs in a home folder with one in ~/.env
sent its memory out. Mnemos's model has needed a choice since 2026-10-05
(test_a_model_only_when_chosen.py); now meaning does too. A key on its own
chooses nothing: the choice is MNEMOS_EMBEDDING_PROVIDER, in the environment
or a .env file Mnemos reads, or ``embeddings.provider`` in its config.
``local`` is the default, and Gemini chosen with no key is local too: never
off, and never another service.

Nothing here reaches the network. Every request goes to ``Google``, a stand-in
for ``urllib.request.urlopen`` that keeps where each one was going: it answers
as the Gemini API would when the test chose Gemini, and refuses otherwise, so
a test that finds a request there fails. A connection anywhere off this
machine fails the test too. The keys are fake.
"""

from __future__ import annotations

import io
import json
import logging
import math
import re
import socket
import urllib.error
import urllib.request
from pathlib import Path

import pytest

import mnemos.store.embedding_index as ei
from mnemos.cli import main
from mnemos.config.loader import save_config
from mnemos.simple_runtime import MnemosRuntime
from mnemos.store.embedding_index import EmbeddingIndex

SCOPE = {"agent_id": "nova", "person_id": "sam", "project_scope": "demo"}
SCOPE_ARGS = ["--agent-id", "nova", "--person-id", "sam", "--project-scope", "demo"]
FAKE_KEY = "test-key-not-real"
GOOGLE = "https://generativelanguage.googleapis.com/"
LOCAL = "local (all-MiniLM-L6-v2)"
GEMINI = "gemini (gemini-embedding-2-preview)"
INDENT = " " * 14


# ── A local model whose meaning is controlled, and Google, caught ──

_CONCEPTS = (
    {"sourdough", "starter", "bread", "baking", "loaf"},
    {"ferry", "harbour", "pier", "boat"},
)


def concept_vector(text: str) -> list[float]:
    """Similar meaning without shared words: "bread baking" is near "sourdough starter"."""
    words = set(re.findall(r"[a-z]+", text.lower()))
    raw = [float(len(words & group)) for group in _CONCEPTS] + [0.05]
    norm = math.sqrt(sum(v * v for v in raw))
    return [v / norm for v in raw]


class _Vector(list):
    def tolist(self):
        return list(self)


class _ConceptModel:
    def encode(self, texts, normalize_embeddings=True, batch_size=32):
        if isinstance(texts, str):
            return _Vector(concept_vector(texts))
        return [_Vector(concept_vector(text)) for text in texts]


class _ConceptEmbedder(ei._LocalEmbedder):
    """The real local embedder, with the model swapped for concept vectors."""

    def _get_model(self):
        if self._model is None:
            self._model = _ConceptModel()
        return self._model


class Google:
    """``urllib.request.urlopen``, with nothing let out. ``sent`` keeps where
    each request was going, without its key. Told to ``answer``, it replies as
    the Gemini API does; otherwise it refuses, as a network that is down would."""

    def __init__(self) -> None:
        self.sent: list[str] = []
        self.answer = False

    def __call__(self, request, timeout=None, **kwargs):
        url = request.full_url if isinstance(request, urllib.request.Request) else str(request)
        self.sent.append(url.split("?", 1)[0])
        if not self.answer:
            raise urllib.error.URLError("refused by the test: nothing was to leave this machine")
        payload = json.loads(request.data)
        if "requests" in payload:
            body = {"embeddings": [
                {"values": concept_vector(item["content"]["parts"][0]["text"])}
                for item in payload["requests"]
            ]}
        else:
            body = {"embedding": {"values": concept_vector(payload["content"]["parts"][0]["text"])}}
        return io.BytesIO(json.dumps(body).encode())


@pytest.fixture(autouse=True)
def google(monkeypatch):
    stand_in = Google()
    monkeypatch.setattr(urllib.request, "urlopen", stand_in)
    return stand_in


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    """No connection leaves this machine, whatever the code under test does:
    one anywhere but loopback is refused, and fails the test."""
    attempts: list = []
    connect = socket.socket.connect
    create_connection = socket.create_connection

    def away(address) -> bool:
        return isinstance(address, tuple) and address[0] not in {"127.0.0.1", "::1", "localhost"}

    def guarded_connect(self, address):
        if away(address):
            attempts.append(address)
            raise OSError(f"no network in this test: {address!r}")
        return connect(self, address)

    def guarded_create_connection(address, *args, **kwargs):
        if away(address):
            attempts.append(address)
            raise OSError(f"no network in this test: {address!r}")
        return create_connection(address, *args, **kwargs)

    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
    monkeypatch.setattr(socket, "create_connection", guarded_create_connection)
    yield attempts
    assert attempts == [], f"a connection left this machine: {attempts}"


@pytest.fixture(autouse=True)
def local_model(monkeypatch):
    """A working local model, without torch, for every index the test makes,
    and the warnings this process has given forgotten, so each test sees its own."""
    monkeypatch.setattr(ei, "_check_local_deps", lambda: True)
    monkeypatch.setattr(ei, "_LocalEmbedder", _ConceptEmbedder)
    monkeypatch.setattr(ei, "_LOGGED", set())


@pytest.fixture
def home(tmp_path, monkeypatch) -> Path:
    """A stranger's home, with the mind running in it, as Ghost runs it: the
    working folder is the home folder, so its .env is ~/.env."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.chdir(home)
    return home


# Where a key, or a choice, can be: the environment, the working folder's .env,
# and Mnemos's own .env.
PLACES = ("environment", "working folder", "mnemos folder")


def _put(name: str, value: str, place: str, home: Path, monkeypatch) -> str:
    """``name=value`` in ``place``; returns where Mnemos says it found it."""
    if place == "environment":
        monkeypatch.setenv(name, value)
        return "the environment"
    env = home / ".env" if place == "working folder" else home / ".mnemos" / ".env"
    env.parent.mkdir(exist_ok=True)
    with env.open("a") as file:
        file.write(f"{name}={value}\n")
    monkeypatch.delenv("MNEMOS_DISABLE_DOTENV", raising=False)
    return str(env)


def _choose(provider: str, place: str, home: Path, monkeypatch) -> str:
    if place == "config":
        save_config({"embeddings": {"provider": provider}})
        return "config"
    return _put("MNEMOS_EMBEDDING_PROVIDER", provider, place, home, monkeypatch)


def _runtime(db: Path) -> MnemosRuntime:
    return MnemosRuntime(db_path=str(db), use_dedicated_model=False, **SCOPE)


def _capture_and_ask(db: Path) -> tuple[str, dict]:
    """A capture, then a question that shares none of its words, as an agent
    makes them: what recall found, and what meaning search says of itself."""
    runtime = _runtime(db)
    try:
        runtime.capture("Sam keeps a sourdough starter named Gerald.")
        found = runtime.recall("bread baking")
        semantic = runtime.semantic_status()
    finally:
        runtime.close()
    return found, semantic


# ── A key on its own chooses nothing ──


@pytest.mark.parametrize("place", PLACES)
def test_a_key_on_its_own_chooses_nothing(place, home, google, monkeypatch):
    _put("GEMINI_API_KEY", FAKE_KEY, place, home, monkeypatch)
    assert ei._load_env_key("GEMINI_API_KEY") == FAKE_KEY, "the key is where Mnemos looks"

    index = EmbeddingIndex(db_path=None)

    assert index.backend == LOCAL
    assert index.verify() is True
    assert google.sent == [], "meaning search sent a probe to Google"


@pytest.mark.parametrize("place", PLACES)
def test_memory_and_questions_stay_here_with_a_key_around(place, home, google, monkeypatch):
    _put("GEMINI_API_KEY", FAKE_KEY, place, home, monkeypatch)

    found, semantic = _capture_and_ask(home / "memory.db")

    assert google.sent == [], "a memory or a question went to Google"
    assert (semantic["backend"], semantic["model"]) == ("local", "all-MiniLM-L6-v2")
    assert "Gerald" in found, "found by meaning, here"


def test_a_key_given_in_code_chooses_nothing(home, google):
    index = EmbeddingIndex(db_path=None, gemini_api_key=FAKE_KEY)

    assert index.backend == LOCAL
    assert index.verify() is True
    assert google.sent == []


# ── Gemini when it is chosen ──


@pytest.mark.parametrize("place", (*PLACES, "config"))
def test_gemini_when_chosen(place, home, google, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", FAKE_KEY)
    _choose("gemini", place, home, monkeypatch)
    google.answer = True

    index = EmbeddingIndex(db_path=None)

    assert index.backend == GEMINI
    assert index.verify() is True
    assert google.sent and all(url.startswith(GOOGLE) for url in google.sent), google.sent


def test_a_capture_and_a_question_reach_gemini_when_chosen(home, google, monkeypatch):
    """The catch above can see a send: with Gemini chosen, the same capture and
    question reach it."""
    monkeypatch.setenv("GEMINI_API_KEY", FAKE_KEY)
    monkeypatch.setenv("MNEMOS_EMBEDDING_PROVIDER", "Gemini")
    google.answer = True

    found, semantic = _capture_and_ask(home / "memory.db")

    assert (semantic["backend"], semantic["model"]) == ("gemini", "gemini-embedding-2-preview")
    assert google.sent and all(url.startswith(GOOGLE) for url in google.sent), google.sent
    assert "Gerald" in found


@pytest.mark.parametrize("place", (*PLACES, "config"))
def test_gemini_chosen_without_a_key_is_local(place, home, google, monkeypatch):
    _choose("gemini", place, home, monkeypatch)

    index = EmbeddingIndex(db_path=None)

    assert index.backend == LOCAL
    assert index.available is True, "a choice without its key turned meaning off"
    assert index.verify() is True
    assert google.sent == []


@pytest.mark.parametrize("provider", ["openai", "google"])
def test_a_provider_mnemos_does_not_know_is_local_and_said_once(provider, home, google, monkeypatch, caplog):
    monkeypatch.setenv("MNEMOS_EMBEDDING_PROVIDER", provider)
    monkeypatch.setenv("GEMINI_API_KEY", FAKE_KEY)

    with caplog.at_level(logging.WARNING, logger="mnemos.store.embedding_index"):
        first = EmbeddingIndex(db_path=None)
        second = EmbeddingIndex(db_path=None)

    assert first.backend == second.backend == LOCAL
    said = [record.getMessage() for record in caplog.records if repr(provider) in record.getMessage()]
    assert len(said) == 1, said
    assert "local" in said[0]
    assert first.verify() is True
    assert google.sent == []


def test_a_provider_given_in_code_is_a_choice(home, google, monkeypatch):
    google.answer = True

    chosen = EmbeddingIndex(db_path=None, provider="gemini", gemini_api_key=FAKE_KEY)
    assert chosen.backend == GEMINI
    assert chosen.verify() is True
    assert google.sent and all(url.startswith(GOOGLE) for url in google.sent)

    # The code's choice outranks the person's settings, either way.
    google.sent.clear()
    monkeypatch.setenv("MNEMOS_EMBEDDING_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", FAKE_KEY)
    local = EmbeddingIndex(db_path=None, provider="local")
    assert local.backend == LOCAL
    assert local.verify() is True
    assert google.sent == []

    # Gemini chosen in code with no key anywhere is local, as anywhere else.
    monkeypatch.delenv("GEMINI_API_KEY")
    monkeypatch.delenv("MNEMOS_EMBEDDING_PROVIDER")
    assert EmbeddingIndex(db_path=None, provider="gemini").backend == LOCAL


# ── The doctor says which, and why ──


def _store(home: Path) -> Path:
    """A store with one memory in it, made before the test sets anything up."""
    db = home / "memory.db"
    runtime = _runtime(db)
    try:
        runtime.capture("Sam keeps a sourdough starter named Gerald.")
    finally:
        runtime.close()
    return db


def _doctor(db: Path, capsys) -> list[str]:
    capsys.readouterr()
    assert main(["doctor", "--db-path", str(db), *SCOPE_ARGS]) == 0
    return capsys.readouterr().out.splitlines()


def _meaning(lines: list[str]) -> list[str]:
    """Doctor's Meaning line, and the lines under it."""
    at = next((i for i, line in enumerate(lines) if line.startswith("Meaning:")), None)
    assert at is not None, "doctor has no Meaning line:\n" + "\n".join(lines)
    said = [lines[at]]
    for line in lines[at + 1:]:
        if not line.startswith(INDENT):
            break
        said.append(line)
    return said


DEFAULT = "Meaning:      local, model all-MiniLM-L6-v2, the default: meaning stays on this machine"


def test_doctor_says_local_is_the_default(home, google, capsys):
    db = _store(home)

    assert _meaning(_doctor(db, capsys)) == [DEFAULT]
    assert google.sent == []


@pytest.mark.parametrize("place", PLACES)
def test_doctor_says_a_key_is_there_and_unused(place, home, google, monkeypatch, capsys):
    db = _store(home)
    where = _put("GEMINI_API_KEY", FAKE_KEY, place, home, monkeypatch)

    assert _meaning(_doctor(db, capsys)) == [
        DEFAULT,
        f"{INDENT}A GEMINI_API_KEY is set in {where}, but Mnemos doesn't use it: meaning stays "
        "on this machine. To choose Gemini, which sends the words of memories and questions "
        "to Google, set MNEMOS_EMBEDDING_PROVIDER=gemini.",
    ]
    assert google.sent == []


def test_doctor_says_gemini_when_chosen(home, google, monkeypatch, capsys):
    db = _store(home)
    monkeypatch.setenv("GEMINI_API_KEY", FAKE_KEY)
    monkeypatch.setenv("MNEMOS_EMBEDDING_PROVIDER", "gemini")
    google.answer = True

    lines = _doctor(db, capsys)

    assert _meaning(lines) == [
        "Meaning:      gemini, model gemini-embedding-2-preview, chosen with "
        "MNEMOS_EMBEDDING_PROVIDER in the environment: the words of memories and questions "
        "go to Google to be embedded",
    ]
    semantic = next(line for line in lines if line.startswith("Semantic:"))
    assert semantic.startswith("Semantic:     on — gemini model gemini-embedding-2-preview"), semantic


@pytest.mark.parametrize("place", (*PLACES, "config"))
def test_doctor_says_why_gemini_without_a_key_is_local(place, home, google, monkeypatch, capsys):
    db = _store(home)
    where = _choose("gemini", place, home, monkeypatch)
    by = "embeddings.provider in Mnemos's config" if where == "config" else (
        f"MNEMOS_EMBEDDING_PROVIDER in {where}"
    )

    assert _meaning(_doctor(db, capsys)) == [
        f"Meaning:      local, model all-MiniLM-L6-v2: Gemini is chosen ({by}), but no "
        "GEMINI_API_KEY was found, so meaning stays on this machine",
    ]
    assert google.sent == []


def test_doctor_says_a_provider_it_does_not_know_is_local(home, google, monkeypatch, capsys):
    db = _store(home)
    monkeypatch.setenv("MNEMOS_EMBEDDING_PROVIDER", "openai")
    monkeypatch.setenv("GEMINI_API_KEY", FAKE_KEY)

    assert _meaning(_doctor(db, capsys)) == [
        "Meaning:      local, model all-MiniLM-L6-v2: MNEMOS_EMBEDDING_PROVIDER in the "
        "environment is 'openai', which Mnemos doesn't know (it knows local and gemini), so "
        "meaning stays on this machine",
        f"{INDENT}A GEMINI_API_KEY is set in the environment, but Mnemos doesn't use it: meaning "
        "stays on this machine. To choose Gemini, which sends the words of memories and "
        "questions to Google, set MNEMOS_EMBEDDING_PROVIDER=gemini.",
    ]
    assert google.sent == []


def test_doctor_says_it_before_there_is_a_store(home, google, monkeypatch, capsys):
    monkeypatch.setenv("GEMINI_API_KEY", FAKE_KEY)

    said = _meaning(_doctor(home / "not-yet.db", capsys))

    assert said[0] == DEFAULT
    assert said[1].startswith(f"{INDENT}A GEMINI_API_KEY is set in the environment, but Mnemos doesn't use it")
    assert not (home / "not-yet.db").exists()
    assert google.sent == []
