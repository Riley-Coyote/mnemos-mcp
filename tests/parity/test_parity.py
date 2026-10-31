"""QA1a: the scripted life, delivered messily, gives the same memory.

Opt-in (it spawns processes and kills them): MNEMOS_PARITY=1, through the guard:
    MNEMOS_PARITY=1 scripts/hermetic.sh pytest -q tests/parity
PARITY_SEEDS sets how many seeds each messy test runs (default 3).
"""

from __future__ import annotations

import json
import os

import pytest

from . import canon, harness

pytestmark = pytest.mark.skipif(
    os.environ.get("MNEMOS_PARITY") != "1", reason="the parity harness runs with MNEMOS_PARITY=1"
)
SEEDS = range(int(os.environ.get("PARITY_SEEDS", "3")))


@pytest.fixture(scope="module")
def ref(tmp_path_factory):
    return harness.reference(tmp_path_factory.mktemp("parity-ref"))


def test_the_life_is_deterministic(ref, tmp_path):
    again = harness.reference(tmp_path)
    assert again.final == ref.final, canon.diff_tables(ref.db, again.db)


def test_the_hash_sees_every_op(ref):
    assert len(set(ref.after)) > 1 and ref.after[-2] != ref.final


def test_every_table_is_classified(ref):
    assert canon.unclassified_tables(ref.db) == []


def test_reference_lineage_is_intact(ref):
    assert canon.lineage_problems(ref.db) == []


@pytest.mark.parametrize("seed", SEEDS)
def test_duplicated_and_late_delivery_is_exactly_once(ref, tmp_path, seed):
    harness.exactly_once(ref, tmp_path, seed)


@pytest.mark.parametrize("seed", SEEDS)
def test_sigkill_mid_transaction_leaves_before_or_after(ref, tmp_path, seed):
    result = harness.crash(ref, tmp_path, seed)
    assert result["kills"], f"seed={seed}: no kill landed"


def test_reports_the_reflection_queue_collision_rate(ref):
    rates = harness.collision_rate(ref)
    print("\nPARITY collisions " + json.dumps(rates, sort_keys=True))
    assert rates["stale_corrections"] > 0
