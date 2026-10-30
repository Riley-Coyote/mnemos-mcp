"""The guard on a person's live memory, for hermetic work on Mnemos.

A builder or a test suite runs Mnemos with a home of its own: a temporary
HOME, an explicit MNEMOS_DB_PATH and a venv of its own (scripts/hermetic.sh).
A path that still reaches the account's real ``~/.mnemos`` (an absolute path
pasted from a shell, a config read from the real home, a default resolved
before HOME moved) would migrate, serve or write the memory someone lives on.
In hermetic mode the engine refuses that path, unless ``--i-mean-it`` is
passed.

Hermetic mode is on when ``MNEMOS_HERMETIC=1``: scripts/hermetic.sh and the
test suite set it. Outside it nothing here applies, so a person's own server,
hooks and host apps open their store as they always have.

The real home is the account's own, as the system has it, whatever HOME says
(``pwd``), plus ``MNEMOS_PROTECTED_HOME`` when that is set. The variable only
adds a home to protect, never removes one: the suite names the real home with
it where the system gives none (Windows), and a test names a fake real home
with it to prove the guard without going near the real one.

The check is on the path alone: it never opens, creates or lists anything in
the home it protects.
"""

from __future__ import annotations

import os
from pathlib import Path

HERMETIC_ENV = "MNEMOS_HERMETIC"
PROTECTED_HOME_ENV = "MNEMOS_PROTECTED_HOME"
I_MEAN_IT_ENV = "MNEMOS_I_MEAN_IT"
I_MEAN_IT_FLAG = "--i-mean-it"


class LiveStoreRefused(PermissionError):
    """A hermetic run reached for a store under a real ``~/.mnemos``."""


# Every refusal this process made, newest last, kept even when the caller
# swallowed the error: the test suite fails any test that made one, so a
# path that reached the live home can't pass quietly behind an ``except``.
refusals: list[str] = []


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def hermetic() -> bool:
    """Whether this process is a hermetic run (MNEMOS_HERMETIC=1)."""
    return _truthy(os.environ.get(HERMETIC_ENV))


def i_mean_it() -> bool:
    """Whether the run said, on purpose, that it means the live store."""
    return _truthy(os.environ.get(I_MEAN_IT_ENV))


def _account_home() -> str | None:
    """The account's home as the system has it; None where it has none.

    Never HOME: in a hermetic run HOME is the temporary one."""
    try:
        import pwd

        return pwd.getpwuid(os.getuid()).pw_dir or None
    except (ImportError, AttributeError, KeyError, OSError):
        return None


def protected_roots() -> list[str]:
    """Every live ``.mnemos`` folder a hermetic run must not reach."""
    homes = [_account_home(), os.environ.get(PROTECTED_HOME_ENV)]
    roots: list[str] = []
    for home in homes:
        if not home:
            continue
        root = os.path.normpath(os.path.join(os.path.abspath(os.path.expanduser(home)), ".mnemos"))
        for form in (root, os.path.realpath(root)):
            if form not in roots:
                roots.append(form)
    return roots


def _forms(path: str | os.PathLike[str]) -> list[str]:
    text = os.path.abspath(os.path.expanduser(os.fspath(path)))
    plain = os.path.normpath(text)
    return [plain, os.path.realpath(plain)]


def _under(path: str, root: str) -> bool:
    if os.name == "nt":
        path, root = path.lower(), root.lower()
    return path == root or path.startswith(root.rstrip(os.sep) + os.sep)


def protected_root_for(path: str | os.PathLike[str]) -> str | None:
    """The live ``.mnemos`` folder ``path`` lies in, or None."""
    roots = protected_roots()
    for form in _forms(path):
        for root in roots:
            if _under(form, root):
                return root
    return None


def check_store_path(path: str | os.PathLike[str], *, action: str = "open for writing") -> None:
    """Refuse ``path`` in a hermetic run when it lies under a real ``~/.mnemos``.

    Nothing outside hermetic mode, and nothing when the run passed
    ``--i-mean-it`` (or set MNEMOS_I_MEAN_IT=1)."""
    if not hermetic() or i_mean_it():
        return
    root = protected_root_for(path)
    if root is None:
        return
    message = (
        f"Refusing to {action} {Path(os.fspath(path)).expanduser()}: it is under {root}, "
        f"a live Mnemos home, and this is a hermetic run ({HERMETIC_ENV}=1). "
        f"Point MNEMOS_DB_PATH into the temporary HOME, or pass {I_MEAN_IT_FLAG} "
        f"if you really mean the live store."
    )
    refusals.append(message)
    raise LiveStoreRefused(message)
