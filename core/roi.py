"""Business-value metric (S9, simulation only): measurements needed to reach a "separable"
ranking — Trace's recommended tests vs random vs cheapest-first. Never claim real savings."""

from __future__ import annotations


def measurements_to_separable(**kwargs) -> dict:
    raise NotImplementedError("S9")
