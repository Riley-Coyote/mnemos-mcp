"""Generate OpenClaw CLI commands to install Mnemos cron jobs.

Reads the cron template definitions and outputs ready-to-run openclaw CLI
commands for installing all cron jobs for a given agent.

Usage:
    from mnemos.setup.cron_installer import generate_install_commands
    commands = generate_install_commands(agent_name="Nova", agent_id="nova", workspace="~/nova")
    print(commands)
"""

from __future__ import annotations


# Cron job definitions — these match the templates in openclaw/crons/
_CRON_JOBS = [
    # No observer-context-sync or memory-maintenance job. Each ran another
    # model (a hard-coded claude-sonnet-4-5) over the agent's transcripts and
    # rewrote its memory files, memory/active-context.md and MEMORY.md, in
    # that model's words: the transcript indexer's flaw again, in files. The
    # agent keeps its own memory; `mnemos setup-openclaw`'s export job only
    # renders what it kept. Retired 2026-10-16.
    # No cross-agent-bridge job: it asked a model to run
    # `python -m mnemos.multiagent.shared_pool sync`, which does nothing.
    # No session-indexer job. On one live store the transcript indexer wrote
    # ~7,058 engrams against 13 deliberate captures and buried the continuity
    # layer; it was retired in 0.4.0, and `mnemos index` only says so.
    # No substrate-tick job either: its handlers wrote memories in a model's
    # words, not the agent's (setup/scheduler.py retires it the same way).
    # `mnemos substrate-tick` was retired in 0.4.0.
    {
        "name": "morning-brief",
        "schedule": "0 10 * * *",
        "model": None,  # Uses default agent model
        "timeout": 300,
        "session_target": "isolated",
        "prompt_template": (
            "You are {agent_name}'s morning briefing system.\n\n"
            "Generate a morning brief for {user_name}. Include:\n"
            "- Yesterday recap (completed work, key decisions, problems)\n"
            "- Open threads (active work, waiting items, blockers)\n"
            "- Suggested focus (top 3 priorities with rationale)\n"
            "- Stale threads (untouched 3+ days)\n"
            "- Mnemos health (stats, last consolidation)\n"
            "- Cross-agent activity (if multi-agent setup)\n\n"
            "Write to {workspace}/daily/morning-brief-$(date +%Y-%m-%d).md"
        ),
    },
    {
        "name": "daily-debrief",
        "schedule": "0 5 * * *",
        "model": None,  # Uses default agent model
        "timeout": 300,
        "session_target": "isolated",
        "prompt_template": (
            "You are {agent_name}'s daily debrief system.\n\n"
            "Generate an end-of-day debrief for {user_name}. Include:\n"
            "- What got done (completed work items)\n"
            "- Key decisions (with rationale)\n"
            "- Open threads (work in progress, waiting, planned)\n"
            "- Problems & blockers\n"
            "- Cross-agent activity\n"
            "- Memories created today\n"
            "- Tomorrow's candidates\n\n"
            "Write to {workspace}/daily/debrief-$(date +%Y-%m-%d).md"
        ),
    },
]


def generate_install_commands(
    agent_name: str,
    agent_id: str,
    workspace: str,
    user_name: str = "User",
    timezone: str = "America/New_York",
) -> str:
    """Generate OpenClaw CLI commands to install all Mnemos cron jobs.

    Args:
        agent_name: Human-readable agent name.
        agent_id: OpenClaw agent ID.
        workspace: Agent workspace path.
        user_name: User's name for personalization.
        timezone: Timezone for scheduling.

    Returns:
        Multi-line string with all the openclaw CLI commands.
    """
    replacements = {
        "agent_name": agent_name,
        "workspace": workspace,
        "user_name": user_name,
    }

    lines = [
        "# Mnemos Cron Jobs for " + agent_name,
        f"# Agent ID: {agent_id}",
        f"# Timezone: {timezone}",
        "",
        "# Run these commands to install all cron jobs:",
        "",
    ]

    for job in _CRON_JOBS:
        prompt = job["prompt_template"]
        for key, value in replacements.items():
            prompt = prompt.replace(f"{{{key}}}", value)

        # Escape the prompt for shell usage
        escaped_prompt = prompt.replace("'", "'\\''")

        cmd_parts = [
            "openclaw cron add",
            f"  --agent {agent_id}",
            f"  --name mnemos-{job['name']}",
            f"  --schedule '{job['schedule']}'",
            f"  --timezone '{timezone}'",
            f"  --timeout {job['timeout']}",
        ]

        if job.get("model"):
            cmd_parts.append(f"  --model '{job['model']}'")

        if job.get("session_target"):
            cmd_parts.append(f"  --session-target {job['session_target']}")

        cmd_parts.append(f"  --prompt '{escaped_prompt}'")

        lines.append(f"# {job['name']}")
        lines.append(" \\\n".join(cmd_parts))
        lines.append("")

    return "\n".join(lines)


def get_job_definitions(
    agent_name: str,
    workspace: str,
    user_name: str = "User",
) -> list[dict]:
    """Get structured job definitions for programmatic use.

    Args:
        agent_name: Human-readable agent name.
        workspace: Agent workspace path.
        user_name: User's name.

    Returns:
        List of job definition dicts with personalized prompts.
    """
    replacements = {
        "agent_name": agent_name,
        "workspace": workspace,
        "user_name": user_name,
    }

    jobs = []
    for job in _CRON_JOBS:
        prompt = job["prompt_template"]
        for key, value in replacements.items():
            prompt = prompt.replace(f"{{{key}}}", value)

        jobs.append({
            "name": f"mnemos-{job['name']}",
            "schedule": job["schedule"],
            "model": job.get("model"),
            "timeout": job["timeout"],
            "session_target": job.get("session_target", "isolated"),
            "prompt": prompt,
        })

    return jobs
