"""
The agent's own time.

Mnemos is the memory of one mind, and that mind lives only while it runs: in
its sessions and its quiet hours. Decay used to run on wall-clock hours since
a memory was last used, so a month in which the person never opened a session
cost the agent a month of fading, and how often the person came back decided
how much the agent remembered.

So memories fade with the time the agent lived, not the calendar. A day counts
as lived when the agent did anything that day (``lived_days`` in the store,
marked by EngramStore.mark_lived). Decay, its ceiling per cycle, the recency
floor, softening's minimum age and the month before a belief is put to the
agent again all run on this clock.
"""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections.abc import Iterable
from datetime import datetime, timezone
from typing import Any


class LivedClock:
    """The agent's own time: hours pass only on the days it lived.

    L(t) is 24 hours for every lived day before t's date, plus the hours into
    t's date when that date is lived. The lived hours between two moments are
    L(end) - L(start). A day the agent didn't live adds nothing, so an absence
    costs it no memory; an agent that lives every day keeps wall-clock time.
    """

    def __init__(self, days: Iterable[str]):
        self.days: list[str] = sorted(set(days))
        self._lived = set(self.days)

    @classmethod
    def for_agent(cls, store: Any, agent_id: str) -> LivedClock:
        """The clock of ``agent_id``'s lived days in ``store``; empty when it
        has none."""
        return cls(store.lived_days(agent_id))

    def at(self, moment: datetime) -> float:
        """L(moment): lived hours from the beginning up to ``moment``."""
        moment = _utc(moment)
        day = moment.date().isoformat()
        hours = 24.0 * bisect_left(self.days, day)
        if day in self._lived:
            midnight = datetime(moment.year, moment.month, moment.day, tzinfo=timezone.utc)
            hours += (moment - midnight).total_seconds() / 3600.0
        return hours

    def hours_between(self, start: str | datetime, end: datetime | None = None) -> float:
        """Lived hours from ``start`` to ``end`` (default now), never below
        0. A start that can't be read gives 0."""
        begun = _moment(start)
        if begun is None:
            return 0.0
        finish = _utc(end) if end is not None else datetime.now(timezone.utc)
        return max(0.0, self.at(finish) - self.at(begun))

    def days_since(self, start: str | datetime, end: datetime | None = None) -> int:
        """How many lived dates fall after ``start``'s date, up to and
        including ``end``'s (default now). A start that can't be read gives
        0."""
        begun = _moment(start)
        if begun is None:
            return 0
        finish = _utc(end) if end is not None else datetime.now(timezone.utc)
        low = bisect_right(self.days, begun.date().isoformat())
        high = bisect_right(self.days, finish.date().isoformat())
        return max(0, high - low)


def _utc(moment: datetime) -> datetime:
    if moment.tzinfo is None:
        return moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def _moment(value: str | datetime | None) -> datetime | None:
    if isinstance(value, datetime):
        return _utc(value)
    try:
        return _utc(datetime.fromisoformat(str(value)))
    except (TypeError, ValueError):
        return None
