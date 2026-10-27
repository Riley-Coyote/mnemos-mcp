"""Where a session works: the folder, for ranking only.

Scope never comes from the working directory: an MCP server's cwd belongs to
whichever client spawned it. But Claude Code starts each session, and its
memory server, in the session's own folder, so the folder says which thread a
session is most likely picking up. A handoff records the place it was written
(``author_place``), and a starting session reads its own place's thread first.
"""

from __future__ import annotations

from pathlib import Path

# How near two places are, for ranking. A worktree of a repository is the
# repository: a session in ``.claude/worktrees/x`` of ``mnemos`` is in mnemos.
SAME_PLACE = 2
RELATED_PLACE = 1
ELSEWHERE = 0

# Words in folder names that say nothing about which work it is. Search's
# list of common words is no use here: it holds the words every note shares,
# such as the memory's own name, and a folder named for a project is exactly
# that word.
_GENERIC_FOLDER_WORDS = frozenset({
    "app", "apps", "claude", "code", "copy", "data", "docs", "documents", "draft",
    "files", "local", "main", "page", "pages", "project", "projects", "repo", "repos",
    "repositories", "site", "temp", "test", "tests", "the", "tmp", "work", "worktree",
    "worktrees",
})


def place_of(workdir: str) -> str:
    """The place a session in ``workdir`` works in, as a path: the repository
    the folder is in (a worktree's main checkout), else the folder itself.
    ``""`` for no folder, the home folder or the root, which say nothing about
    the work."""
    if not workdir:
        return ""
    try:
        folder = Path(workdir).expanduser()
        if folder == Path.home() or folder == Path(folder.anchor):
            return ""
        return str(repository(folder) or folder)
    except (OSError, ValueError, RuntimeError):
        return ""


def place_name(workdir: str) -> str:
    """Where the session wakes, as the briefing's opening says it: the name
    of its place. Nothing for no folder, the home folder or the root."""
    place = place_of(workdir)
    return Path(place).name if place else ""


def place_words(workdir: str) -> set[str]:
    """The distinctive words of a folder's name and of its repository's name.

    A worktree is named for its repository, so a session in
    ``/tmp/wt-mnemos-r04`` ranks by "mnemos" as one in the checkout does.
    """
    from .store.fts import fts_words

    if not workdir:
        return set()
    try:
        folder = Path(workdir).expanduser()
        names = [folder.name]
        found = repository(folder)
        if found is not None:
            names.append(found.name)
    except (OSError, ValueError, RuntimeError):
        return set()
    words: set[str] = set()
    for name in names:
        words |= {
            word.lower() for word in fts_words(name, min_len=3)
            if word.lower() not in _GENERIC_FOLDER_WORDS
        }
    return words


def nearness(here: str, there: str) -> int:
    """How near place ``there`` is to ``here``, both as ``place_of`` gives
    them: ``SAME_PLACE``, ``RELATED_PLACE`` when their names share a
    distinctive word (``mnemos`` and ``mnemos-site``), else
    ``ELSEWHERE``. An unknown place is elsewhere."""
    if not here or not there:
        return ELSEWHERE
    if Path(here) == Path(there):
        return SAME_PLACE
    if place_words(here) & place_words(there):
        return RELATED_PLACE
    return ELSEWHERE


def repository(folder: Path) -> Path | None:
    """The repository a folder is in: the main checkout for a worktree."""
    for candidate in (folder, *folder.parents):
        marker = candidate / ".git"
        if marker.is_dir():
            return candidate
        if marker.is_file():
            try:
                pointer = marker.read_text(encoding="utf-8", errors="replace").strip()
            except OSError:
                return candidate
            gitdir = pointer.removeprefix("gitdir:").strip()
            if "/.git/worktrees/" in gitdir:
                return Path(gitdir.split("/.git/worktrees/", 1)[0])
            return candidate
    return None
