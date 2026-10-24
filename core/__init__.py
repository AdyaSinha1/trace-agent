"""Core engine of Trace — config-driven and domain-agnostic.

No water-specific (or any domain-specific) logic may live here: all domain content
arrives through a DomainPack (domains/<name>/pack.json + features.py).
"""

__version__ = "0.1.0"
