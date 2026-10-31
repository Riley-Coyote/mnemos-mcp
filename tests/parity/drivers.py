"""How an op reaches the engine. One driver per way in; the harness doesn't care which.

A driver takes one delivery (the op and its resolved arguments) and returns the
host-mutation answer ``{protocol_version, operation, idempotency_key,
replayed, result}``. It runs inside the worker process, under the frozen clock
(determinism.py), and makes a fresh runtime for each delivery: what an op does
must follow from the store and the op alone, never from what the process
remembers. (In v1 a runtime counts one session per instance and reads the
runner's session from the environment, which is what v2's ``context`` ends.)

To add a way in, write a class with ``name`` and ``deliver`` and add it to
:data:`DRIVERS`. The harness runs the same life through it and compares hashes.
"""

from __future__ import annotations

import os
from typing import Any, Protocol

from .life import SCOPE, Op


class Driver(Protocol):
    name: str

    def deliver(self, db_path: str, op: Op, arguments: dict[str, Any]) -> dict[str, Any]:
        ...


class HostMutationV1:
    """``MnemosRuntime.execute_host_mutation`` at protocol 1, as on mnemos main today.

    v1 takes the runner's session from ``CLAUDE_CODE_SESSION_ID``, so the
    driver sets it per delivery; ``observed_at`` is the frozen clock."""

    name = "v1"

    def deliver(self, db_path: str, op: Op, arguments: dict[str, Any]) -> dict[str, Any]:
        from mnemos.simple_runtime import MnemosRuntime

        os.environ["CLAUDE_CODE_SESSION_ID"] = op.session
        runtime = MnemosRuntime(db_path=db_path, use_dedicated_model=False, **SCOPE)
        return runtime.execute_host_mutation(
            op.operation,
            arguments,
            host_namespace=op.namespace,
            idempotency_key=op.key,
            protocol_version=1,
        )


# MN1a: class HostMutationV2 passes protocol_version=2 and
#   context={"session": op.session, "observed_at": op.observed_at,
#            "base_seq": ..., "origin": op.runner} instead of the env var.
# MN5a: class HomeHTTP POSTs the same body to a home started on a temp
#   /data dir: POST /v2/companions/<id>/mutate with Mnemos-Namespace and
#   Idempotency-Key headers, and returns the JSON answer.
DRIVERS: dict[str, type] = {
    "v1": HostMutationV1,
}
