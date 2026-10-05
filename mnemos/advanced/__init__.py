"""Self-audit of generated text, for the advanced server.

Modules:
- introspection: heuristic self-audit (the advanced server's
  ``mnemos_introspect``)
- introspection_api: the same audit from token logprobs, when a provider
  returns them
"""

__all__ = [
    "introspection",
    "introspection_api",
]
