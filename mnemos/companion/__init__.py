"""The companion: a small page to watch an agent's days (``mnemos log``).

The log shows what the agent does on its own and what it keeps: its quiet
hours, its journal, the notes it leaves you, what its memory asks it, its
beliefs and every memory, read straight from its memory and never written.
``export`` makes the page's documents; ``server`` serves the page on
127.0.0.1 only. The page itself is in ``page/``.
"""

import logging

logger = logging.getLogger(__name__)
