"""Mnemos for Hermes, from Hermes's plugin catalog: a memory of the agent's
own, as Hermes's memory provider.

Mnemos itself is the ``mnemos-continuity`` package, which Hermes installs into
its own environment from this folder's pyproject.toml. This file only hands
Hermes the provider, and nothing runs as it loads.
"""


def register(ctx):
    from agent.memory_provider import MemoryProvider

    from mnemos.integrations.hermes import build_memory_provider_class

    ctx.register_memory_provider(build_memory_provider_class(MemoryProvider, from_catalog=True)())
