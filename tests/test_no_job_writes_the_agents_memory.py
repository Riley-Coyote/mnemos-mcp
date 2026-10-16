"""No job Mnemos installs, or prints to install, writes the agent's memory.

`mnemos bootstrap` printed OpenClaw jobs that ran another model (a hard-coded
claude-sonnet-4-5) as an "Observer" every 30 minutes and a "Memory
Maintenance agent" every six hours: each read the agent's transcripts and
rewrote its memory files (memory/active-context.md, MEMORY.md) in that
model's words. That is the transcript indexer's flaw again, in files instead
of the store, and the indexer was retired for it in 0.4.0. A third job asked
a model to run `python -m mnemos.multiagent.shared_pool sync`, a command that
does nothing, and report what changed. All three are retired (2026-10-16);
the briefs that remain run as the agent itself and write reports for the
person, not memory.
"""

from __future__ import annotations

import json
import re

from mnemos.openclaw_cron import generate_cron_jobs
from mnemos.setup.cron_installer import generate_install_commands, get_job_definitions

# A memory file of an OpenClaw workspace, named in a job's prompt.
MEMORY_FILES = re.compile(r"MEMORY\.md|memory/[\w.-]+\.md|active-context")


def test_every_printed_job_runs_as_the_agent_itself():
    jobs = get_job_definitions(agent_name="Nova", workspace="~/nova")

    assert jobs, "premise: bootstrap still prints jobs"
    assert [job["model"] for job in jobs] == [None] * len(jobs)


def test_no_printed_job_rewrites_a_memory_file():
    jobs = get_job_definitions(agent_name="Nova", workspace="~/nova")

    assert [job["name"] for job in jobs if MEMORY_FILES.search(job["prompt"])] == []
    commands = generate_install_commands(agent_name="Nova", agent_id="nova", workspace="~/nova")
    assert not MEMORY_FILES.search(commands)
    assert "--model" not in commands


def test_no_job_runs_a_command_that_does_nothing():
    printed = json.dumps(get_job_definitions(agent_name="Nova", workspace="~/nova"))
    scheduled = json.dumps(generate_cron_jobs(agent_id="nova"))

    assert "shared_pool sync" not in printed + scheduled
