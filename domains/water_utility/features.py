"""Water-domain feature extractors: raw readings -> evidence items (pure Python only).

The engine discovers these via the EXTRACTORS registry; NO domain logic lives in core/.
Each extractor takes a pack-scenario raw reading and returns a list of evidence dicts
(fields matching core.evidence.EvidenceRecord, without support/contradict labels).
Registered in S2 when scenarios land.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List

Extractor = Callable[[Any], List[Dict[str, Any]]]

EXTRACTORS: Dict[str, Extractor] = {}
