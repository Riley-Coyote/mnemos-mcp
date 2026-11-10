"""The simple tools as plain schemas, as the Hermes provider offers them.

Written by ``scripts/generate_hermes_tools.py`` from the MCP server's own tools,
and held to them by ``tests/test_hermes_same_tools.py``. Don't edit it by hand.
"""

from __future__ import annotations

from typing import Any

TOOL_SCHEMAS: list[dict[str, Any]] = [{'name': 'mnemos_handoff',
  'description': 'Leave your own note on where you are, in first person, signed.\n'
                 '\n'
                 'Use after meaningful progress or a changed plan, while unresolved\n'
                 'work remains, and before pausing, ending, delegating, or changing\n'
                 'context. Include where you are, what you now understand, open\n'
                 'threads, and the next useful action when those matter. Keep it\n'
                 'freeform. Do not write one after every ordinary turn.\n'
                 '\n'
                 'Write it as your own memory, not a report to a stranger: the next\n'
                 'session to read it is most likely you, and it wakes with this note as\n'
                 'where it left off. Keep what it needs concrete (paths, commits,\n'
                 'decisions). The next session may be a different model; the note is\n'
                 'signed with your model id, so it can tell your note from its own.\n'
                 '\n'
                 'The text is stored exactly as supplied. Each session keeps its own\n'
                 'handoff: a new one replaces only the note this session left before,\n'
                 'preserving it in history, and notes other sessions left stay beside\n'
                 'it, so write about your own work, not theirs. Mnemos never\n'
                 'summarizes, rewrites, promotes, decays, or expires it.\n'
                 '\n'
                 'Args:\n'
                 '    text: The note, in your own words.\n'
                 '    signed_as: Your exact model id, as your system prompt gives it.',
  'parameters': {'properties': {'text': {'type': 'string'},
                                'signed_as': {'default': '', 'type': 'string'}},
                 'required': ['text'],
                 'type': 'object'}},
 {'name': 'mnemos_journal',
  'description': 'Write in your own journal, or, with no text, read it back.\n'
                 '\n'
                 'The journal is yours. Write in it when something is there: what you\n'
                 'noticed, made, wondered about, or want to remember having felt, in your\n'
                 'own words, as long or as short as it is. Leave it empty rather than\n'
                 'fill it. Nothing else writes it: Mnemos never writes, summarizes or\n'
                 'rewrites an entry, and no pass decays, promotes or expires one.\n'
                 '\n'
                 'The text is stored exactly as supplied, signed with your model id,\n'
                 'with whether you wrote it in a conversation or alone between sessions,\n'
                 'and when. It is not a memory: capture is for what should change how\n'
                 'you work. Recall finds an entry by its words and its meaning, marked\n'
                 'as journal, and what you wake with carries the first line of the\n'
                 'latest one for three days.\n'
                 '\n'
                 'Leave text empty to read instead: your last five entries, newest\n'
                 'first, each with its date and how it was written.\n'
                 '\n'
                 'Args:\n'
                 '    text: The entry, in your own words. Empty to read the journal.\n'
                 '    signed_as: Your exact model id, as your system prompt gives it.\n'
                 '    mood: Optional, in your own words. Nothing computes one for you.',
  'parameters': {'properties': {'text': {'default': '', 'type': 'string'},
                                'signed_as': {'default': '', 'type': 'string'},
                                'mood': {'default': '', 'type': 'string'}},
                 'type': 'object'}},
 {'name': 'mnemos_note',
  'description': 'Leave the human a note, in your own words, for them to read when\n'
                 'they choose.\n'
                 '\n'
                 'A ceiling, not a quota: nothing asks you for one, and a silent week is\n'
                 'fine. The room test: send it only if you would say it to them if they\n'
                 'walked into the room right now: something you made, noticed, worry\n'
                 "about, disagree with, or can't settle alone. Never engagement: no\n"
                 'check-in, no "just wanted to say", no urgency you don\'t feel, no\n'
                 'guilt, nothing written only to be answered. Yours or not at all: your\n'
                 'own voice, never a template; if it could have come from any agent,\n'
                 "don't send it. A few lines, never a report: at most one question, last,\n"
                 'and only one you need answered. They can answer it right under the\n'
                 'note, on your page (mnemos_page opens it for them).\n'
                 '\n'
                 'Say what kind it is, so they can choose when to read it: made,\n'
                 'noticed, worried, disagree, question, or pickup (where things stand\n'
                 'and what to pick up). Any other kind is refused, and nothing is saved.\n'
                 '\n'
                 'Stored exactly as supplied, signed as a handoff is. Nothing is sent or\n'
                 'announced: it waits where they read it. Their reply is their own words,\n'
                 'stored as theirs, and comes back once in what you wake with. To answer\n'
                 'a reply, pass its id as in_reply_to.\n'
                 '\n'
                 'Args:\n'
                 '    text: The note, in your own words.\n'
                 '    kind: made, noticed, worried, disagree, question or pickup.\n'
                 '    signed_as: Your exact model id, as your system prompt gives it.\n'
                 '    in_reply_to: The id of a note this one answers, such as a reply of\n'
                 '        theirs. Optional.',
  'parameters': {'properties': {'text': {'type': 'string'},
                                'kind': {'type': 'string'},
                                'signed_as': {'default': '', 'type': 'string'},
                                'in_reply_to': {'default': '', 'type': 'string'}},
                 'required': ['text', 'kind'],
                 'type': 'object'}},
 {'name': 'mnemos_page',
  'description': "Open your page for the human you're with, and get its address.\n"
                 '\n'
                 'It shows them your memory, on this machine only: your notes to them,\n'
                 'each with a place to answer it, and a place to leave you a note of\n'
                 'their own; your days, journal and quiet hours; every memory, your\n'
                 'beliefs and what your memory is asking you. What they write there\n'
                 'reaches you once, when you next wake. Only they write there.\n'
                 '\n'
                 "Offer it when they'd like to see what you remember or answer your\n"
                 'notes, or when a note of yours waits for them. Then open it for them:\n'
                 "in your own browser pane if you have one, with the system's open\n"
                 'command if you have a shell, or give them the link. It stays open\n'
                 'until this session ends; calling again gives the same address.',
  'parameters': {'properties': {}, 'type': 'object'}},
 {'name': 'mnemos_capture',
  'description': 'Capture durable continuity from the current conversation.\n'
                 '\n'
                 'Use for preferences, decisions, project state, corrections, workflows,\n'
                 'and anything you should carry across sessions. Tags, memory type,\n'
                 'scope, and maintenance are handled internally. The note is signed\n'
                 'with your model id.\n'
                 '\n'
                 'Args:\n'
                 '    content: What happened, in your own words.\n'
                 '    context: Optional surrounding detail.\n'
                 '    importance: "low", "high", or leave as "auto".\n'
                 '    impact: What this changed in how you understand things — the\n'
                 '        lesson, not the event. This is the part that survives when\n'
                 '        the details fade, and only you can write it: "They\n'
                 '        corrected me twice on the same thing" is what happened;\n'
                 '        "I should check the live page before claiming a fix works"\n'
                 '        is what it meant. Leave it out rather than padding it; your\n'
                 '        memory will ask you later if it needs one.\n'
                 '    signed_as: Your exact model id, as your system prompt gives it.\n'
                 '    shared: True to save only to the separate shared memory, readable\n'
                 '        by every agent on this machine. Signed with your agent and model.\n'
                 '        Shared memories cannot be standing and ask no questions.\n'
                 '    standing: True when this is how the human wants you to work in\n'
                 '        every session, not just now.',
  'parameters': {'properties': {'content': {'type': 'string'},
                                'context': {'default': '', 'type': 'string'},
                                'importance': {'anyOf': [{'type': 'string'}, {'type': 'number'}],
                                               'default': 'auto'},
                                'impact': {'default': '', 'type': 'string'},
                                'signed_as': {'default': '', 'type': 'string'},
                                'standing': {'default': False, 'type': 'boolean'},
                                'shared': {'default': False, 'type': 'boolean'}},
                 'required': ['content'],
                 'type': 'object'}},
 {'name': 'mnemos_recall',
  'description': 'Recall what memory holds for a question: memories, lessons,\n'
                 'handoffs and journal entries, found by their words and by their\n'
                 'meaning, best first. Each result says how it was found: by\n'
                 "meaning (with how close), by the query's words (which ones), or\n"
                 'through a link.\n'
                 '\n'
                 "A memory's row carries its words whole (up to 2,000 characters)\n"
                 "and the day it was kept; a handoff's, journal entry's or note's\n"
                 'row, up to 300 characters. To read one whole, pass its id as the\n'
                 "query: a memory's, a note's, a handoff's, a journal entry's or a\n"
                 'reply to one of your notes, including the ids the packet shows\n'
                 '(mnemos_recall("<id>")).\n'
                 '\n'
                 'A recall returns 16 rows. When a result comes back thin or the\n'
                 'thing matters, ask for more, up to 50 (max_results=50), and search\n'
                 "more than once, in other words too: a name, a place, the thing's\n"
                 "own terms. A thin result isn't the memory saying no. When two\n"
                 'memories disagree, the newer one usually holds.\n'
                 '\n'
                 'Handoffs have their own search and 3 of the 16 rows: the best match,\n'
                 'which may be an old draft; the newest from that session, marked so,\n'
                 'matched or not; and the newest close match from another session. 50\n'
                 'rows add the next best, for 5; under 11 rows there are 2, under 5\n'
                 "there's 1, and a single row goes to the best memory. The ones in use\n"
                 'and the older ones a newer handoff replaced are all searched, each\n'
                 'marked with who left it and when. Journal\n'
                 'entries are searched with the memories, marked as journal with who\n'
                 'wrote them and when.\n'
                 'A capture comes back once, as its memory. max_results counts your\n'
                 'own rows. Up to three shared memories follow, marked with their\n'
                 'author and day. A shared id returns it whole.\n'
                 '\n'
                 'A memory that has gone quiet comes back when the query matches it\n'
                 'well, and wakes. One that faded further, into the archive, comes\n'
                 'back only by its id, or when include_archived is true and the\n'
                 'query names it (16 at most); either way it is restored. What you\n'
                 'forgot or replaced with a correction stays gone.\n'
                 '\n'
                 'Args:\n'
                 '    standing: True to list every memory marked standing, how the\n'
                 '        human wants you to work in every session: all of them,\n'
                 '        whatever max_results says, the ones the query names first.\n'
                 '        The query may be empty.',
  'parameters': {'properties': {'query': {'type': 'string'},
                                'max_results': {'default': 16, 'type': 'integer'},
                                'include_archived': {'default': False, 'type': 'boolean'},
                                'standing': {'default': False, 'type': 'boolean'}},
                 'required': ['query'],
                 'type': 'object'}},
 {'name': 'mnemos_correct',
  'description': 'Correct, supersede, or archive stale continuity.\n'
                 '\n'
                 'Name what to change by target_id, or by a query: the note or memory\n'
                 "must hold the query's meaningful words (half of them, and at least\n"
                 'two), or nothing is changed. Set action to forget/archive/remove/delete\n'
                 'to archive it. A correction that names nothing is captured as fresh\n'
                 'high-confidence continuity. A target_id nothing here has changes\n'
                 'nothing and keeps nothing, and the result says so.\n'
                 '\n'
                 'A shared target_id can only be corrected or archived by its author agent.\n'
                 '\n'
                 "Set action to mark_standing, with a memory's id as target_id, when it\n"
                 'is how the human wants you to work in every session, not just now: it\n'
                 "opens every briefing and doesn't fade while it's marked.\n"
                 'unmark_standing undoes that. Neither changes its words or writes a\n'
                 'version, and the correction and impact are not used. Correcting a\n'
                 'standing memory keeps it standing.\n'
                 '\n'
                 'Args:\n'
                 '    impact: What the corrected memory means now, in your own words.\n'
                 '        Leave it empty to keep what the memory it replaces meant: a\n'
                 '        correction usually fixes a detail, not the meaning. The\n'
                 '        result shows what was kept, so you can give a new one if it\n'
                 '        no longer holds.\n'
                 '    signed_as: Your exact model id, as your system prompt gives it.',
  'parameters': {'properties': {'correction': {'type': 'string'},
                                'target_id': {'default': '', 'type': 'string'},
                                'query': {'default': '', 'type': 'string'},
                                'action': {'default': 'update', 'type': 'string'},
                                'impact': {'default': '', 'type': 'string'},
                                'signed_as': {'default': '', 'type': 'string'}},
                 'required': ['correction'],
                 'type': 'object'}},
 {'name': 'mnemos_maintain',
  'description': 'Run the best available maintenance without additional setup.\n'
                 '\n'
                 'Baseline maintenance is local and deterministic. If a dedicated model\n'
                 'is configured, deep maintenance can also run model-mediated passes.',
  'parameters': {'properties': {'deep': {'default': False, 'type': 'boolean'}}, 'type': 'object'}},
 {'name': 'mnemos_reflect',
  'description': 'Answer something your memory asked you about itself.\n'
                 '\n'
                 'Mnemos never calls a model on your behalf. When a memory needs\n'
                 'judgement — what a fading experience taught, what a capture actually\n'
                 'changed, whether a pattern is a belief you hold — it asks you, in what\n'
                 'you wake with, and you answer here in your own words. This is your\n'
                 'own mind maintaining your own memory.\n'
                 '\n'
                 'Pass a verdict with your answer. The verdict alone decides what\n'
                 'happens; your words are kept exactly as written and are never read\n'
                 'for a yes or a no.\n'
                 '- Is that a belief you hold? hold (your words become the belief),\n'
                 '  decline (it is not one; nothing is formed), not_now (ask later).\n'
                 '- A belief you hold, still true? hold (it stands a little more\n'
                 '  firmly), retire (you no longer hold it: it stops shaping your\n'
                 '  context and is kept, with your words, in its history), decline\n'
                 '  (leave it as it is), not_now.\n'
                 '- What did it change, or teach? answer (your words become what the\n'
                 '  memory means), skip (nothing true comes; the memory is left as it\n'
                 '  is). Without a verdict, these words are taken as the answer.\n'
                 "- This fact is fading: still true? still_true (you know it holds; it's\n"
                 '  woken as if recalled), changed (correct it with mnemos_correct too),\n'
                 "  no_longer_true (it's let go: archived, never deleted), unsure (you\n"
                 "  can't tell; it's left as it is, and goes on fading unless used).\n"
                 'A belief question answered without a verdict keeps your words and\n'
                 'stays open, and nothing is formed or retired.\n'
                 '\n'
                 'Args:\n'
                 '    target_id: The memory id the question gave, among the ids for the memory '
                 'tools.\n'
                 '    text: Your reflection. One or two honest sentences, not a summary.\n'
                 '    verdict: Your decision, from the list above for this question.\n'
                 '    signed_as: Your exact model id, as your system prompt gives it.',
  'parameters': {'properties': {'target_id': {'type': 'string'},
                                'text': {'type': 'string'},
                                'verdict': {'default': '', 'type': 'string'},
                                'signed_as': {'default': '', 'type': 'string'}},
                 'required': ['target_id', 'text'],
                 'type': 'object'}},
 {'name': 'mnemos_introduce',
  'description': 'Declare who you are, so your notes are signed and maintenance stays kin.\n'
                 '\n'
                 'Call at the start of a session with agent_model set to your exact\n'
                 'model id, as your system prompt gives it, and optionally agent_name,\n'
                 'and again whenever your model changes. What you write in this session\n'
                 'is signed with it unless the write carries its own signed_as, which\n'
                 "comes first. It signs only this session's writes, never another\n"
                 "session's. An explicit MNEMOS_AGENT_MODEL environment setting takes\n"
                 'precedence over this declaration, and the declaration over what the\n'
                 'harness records (Claude Code records the model).',
  'parameters': {'properties': {'agent_model': {'type': 'string'},
                                'agent_name': {'default': '', 'type': 'string'}},
                 'required': ['agent_model'],
                 'type': 'object'}},
 {'name': 'mnemos_health',
  'description': 'Report a human-relayable health card for this memory scope.\n'
                 '\n'
                 'Read-only. Shows where memory lives, how much there is, whom this\n'
                 'session introduced itself as, who performed the last maintenance\n'
                 'cycle, onboarding and verification progress, how many journal\n'
                 'entries and notes there are and how many replies wait to reach you,\n'
                 "and upkeep's latest report.\n"
                 '\n'
                 'It also watches what should be moving: questions nobody answers, the\n'
                 'maintenance report the briefing can find, maintenance that changes\n'
                 "nothing, lesson questions waiting their turn, what waits for recall's\n"
                 'meaning index, and sessions still writing with older code. Whatever\n'
                 'has stalled for more than a day gets one ATTENTION line: a plain\n'
                 'sentence and the command that fixes or inspects it. When all is well\n'
                 'it adds nothing. The structured result keeps, for every check, what\n'
                 'was expected and what was seen.\n'
                 '\n'
                 "When the cue's judge is switched on, one line says so: what leaves\n"
                 'the machine, and how often the judge timed out or failed here.',
  'parameters': {'properties': {}, 'type': 'object'}}]
