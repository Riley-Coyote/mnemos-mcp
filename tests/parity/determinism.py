"""A frozen clock and ids that follow from the op, for the process that drives the engine.

Two stores that lived the same life can only hash the same if every id and
timestamp the engine writes follows from the life, not from the machine. The
engine takes "now" from ``datetime`` and its ids from ``ulid.new`` (engrams,
beliefs) and ``uuid.uuid4`` (notes, queue rows, sessions). In the worker
process, and only there, :func:`install` replaces those three before Mnemos is
imported:

- ``datetime.datetime.now/utcnow/today`` and ``datetime.date.today`` return the
  life's clock, which stands still for the whole of one op;
- ``ulid.new`` and ``uuid.uuid4`` count from the op's index.

:func:`at` sets both at the start of each delivery. Everything an op writes is
then a function of (store before, op), whichever process runs it and however
many times it was cut off before: a retry after a kill writes the same ids at
the same instant as the first, uncut run did.
"""

from __future__ import annotations

import datetime as _dt
import sys
import types
import uuid

T0 = _dt.datetime(2026, 3, 2, 9, 0, tzinfo=_dt.timezone.utc)

_real_datetime = _dt.datetime
_real_date = _dt.date


class _Clock:
    now: _dt.datetime = T0
    op: int = 0
    n: int = 0


def _next() -> int:
    _Clock.n += 1
    return _Clock.n


class FrozenDatetime(_real_datetime):
    @classmethod
    def now(cls, tz=None):  # noqa: D102 - the stdlib's signature
        moment = _Clock.now
        if tz is None:
            # Naive local time, as the stdlib gives it; the life runs in UTC.
            return cls._of(moment.replace(tzinfo=None))
        return cls._of(moment.astimezone(tz))

    @classmethod
    def utcnow(cls):  # noqa: D102
        return cls._of(_Clock.now.replace(tzinfo=None))

    @classmethod
    def today(cls):  # noqa: D102
        return cls.now()

    @classmethod
    def _of(cls, value: _dt.datetime) -> "FrozenDatetime":
        return cls(
            value.year, value.month, value.day, value.hour, value.minute,
            value.second, value.microsecond, value.tzinfo,
        )


class FrozenDate(_real_date):
    @classmethod
    def today(cls):  # noqa: D102
        moment = _Clock.now
        return cls(moment.year, moment.month, moment.day)


def _ulid_new():
    import ulid

    ms = int(_Clock.now.timestamp() * 1000)
    randomness = ((_Clock.op + 1) << 40) | _next()
    return ulid.from_int((ms << 80) | randomness)


def _uuid4() -> uuid.UUID:
    return uuid.UUID(int=((_Clock.op + 1) << 96) | _next(), version=4)


def install() -> None:
    """Freeze this process's clock and id sources. Call before importing Mnemos."""
    shim = types.ModuleType("datetime")
    shim.__dict__.update(_dt.__dict__)
    shim.datetime = FrozenDatetime
    shim.date = FrozenDate
    sys.modules["datetime"] = shim

    import ulid

    ulid.new = _ulid_new
    try:
        import ulid.api as ulid_api

        ulid_api.new = _ulid_new
    except ImportError:  # pragma: no cover - ulid-py 1.1 has it
        pass
    uuid.uuid4 = _uuid4


def at(op_index: int, moment: _dt.datetime) -> None:
    """Start an op: the clock reads ``moment`` until the next call, ids count from the op."""
    _Clock.now = moment
    _Clock.op = op_index
    _Clock.n = 0
