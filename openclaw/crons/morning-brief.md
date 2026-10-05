# Morning Brief

Prepares a daily morning summary for the user with open tasks, yesterday's recap, and suggested focus.

## Cron Definition

| Field | Value |
|-------|-------|
| **Schedule** | `0 10 * * *` (daily at 10 AM) |
| **Model** | default agent model |
| **Timeout** | 300s |
| **Session Target** | `isolated` |

## Purpose

Generates a structured morning briefing that helps the user (and agent) start the day
with full context. Reviews yesterday's activity, identifies open threads, suggests focus
areas, and reports on Mnemos system health.

## Prompt

```
You are {agent_name}'s morning briefing system.

Generate a morning brief for {user_name}. Follow this format exactly:

---
# Morning Brief — {date}

## Yesterday Recap
- What got done (summarize completed work from yesterday's sessions)
- Key decisions made
- Problems encountered

## Open Threads
- Active work items that need continuation
- Questions waiting for answers
- Blocked items and what's blocking them

## Suggested Focus
Based on open threads, urgency, and momentum:
1. [Most important item and why]
2. [Second priority]
3. [Third priority]

## Stale Threads
Items that haven't been touched in 3+ days but are still open:
- [Thread and last activity date]

## Mnemos Health
- Total active memories: [count]
- Memories created yesterday: [count]
- Beliefs updated: [count]
- Last consolidation: [timestamp]

## Cross-Agent Activity
- [Other agent activity summaries, if multi-agent setup]
---

STEPS:
1. Read {workspace}/memory/active-context.md for current state
2. Use sessions_list to review yesterday's sessions
3. Run mnemos stats for system health
4. Check {workspace}/memory/cross-agent-context.md if it exists
5. Generate the brief in the format above
6. Write to {workspace}/daily/morning-brief-{date}.md
```

## Notes

- The brief should be concise but comprehensive — aim for 300-500 words.
- If there's no activity from yesterday, note that and still provide the health check.
- The suggested focus section is the most valuable part — it should reflect genuine
  analysis of priorities, not just list everything.
- Stale threads help prevent work from falling through the cracks.
- The brief is written to `daily/` for archival, not to memory/.
