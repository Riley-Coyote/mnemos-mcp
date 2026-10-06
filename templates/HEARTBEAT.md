# Heartbeat Configuration — {agent_name}

<!--
HEARTBEAT.md configures the health monitoring for this agent.
Each cron job that has nothing to report sends HEARTBEAT_OK.
This file defines what to check and when to alert.

Replace {placeholders} with actual values.
-->

## Health Checks

<!--
What systems to monitor and what "healthy" looks like.
-->

### Memory System
| Check | Healthy | Warning | Critical |
|-------|---------|---------|----------|
| Active engrams | > 10 | < 10 | 0 |
| Last consolidation | < 8h ago | < 24h ago | > 24h ago |
| Database size | < 500MB | < 1GB | > 1GB |

### Cron Health
| Check | Healthy | Warning | Critical |
|-------|---------|---------|----------|
| Observer heartbeats | Regular | Missed 2+ | Missed 5+ |
| Bridge heartbeats | Regular | Missed 3+ | Missed 6+ |

### Context Freshness
| Check | Healthy | Warning | Critical |
|-------|---------|---------|----------|
| active-context.md | Updated < 1h | Updated < 3h | Updated > 3h |
| MEMORY.md | Updated < 12h | Updated < 24h | Updated > 24h |
| cross-agent-context.md | Updated < 4h | Updated < 8h | Updated > 8h |

## Notification Rules

<!--
When and how to notify about health issues.
-->

### During Active Hours
- **Warning**: Include in next morning brief
- **Critical**: Flag in active-context.md for immediate attention

### During Quiet Hours
- **Warning**: Log only, include in morning brief
- **Critical**: Log and flag in active-context.md

## Quiet Hours

<!--
Times when the agent should minimize background activity.
Adjust based on user's schedule.
-->

| Setting | Value |
|---------|-------|
| **Quiet start** | 6:00 AM |
| **Quiet end** | 9:00 AM |
| **Timezone** | {timezone} |

During quiet hours:
- Non-critical crons still run but operate silently
- No notifications unless critical
- Morning brief is prepared but not delivered until quiet hours end

## Heartbeat Log

<!--
Recent heartbeat status. Updated automatically by cron jobs.
Format: timestamp | cron | status | note
-->

| Timestamp | Cron | Status | Note |
|-----------|------|--------|------|
| _No heartbeats recorded yet_ | | | |
