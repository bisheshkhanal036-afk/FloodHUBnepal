"""Citizen Mode: a public-facing flood-susceptibility awareness tool.

One tap, one plain-language answer, in English or Nepali, for the
Kathmandu Valley pilot area. Built on the same overlay engine as the
researcher tool, but with the criteria, weights and class breaks fixed to
a configuration selected by measurement against an observed flood
inventory — see profile.py for the numbers and the reasoning.
"""

from .router import router

__all__ = ["router"]
