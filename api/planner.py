"""LLM seam over :meth:`axiom.pipeline.QueryPlanner.parse` — no core edits.

``QueryPlanner.parse`` (pipeline.py:75) is a deterministic keyword cascade. It
has no injectable LLM, so to use one without editing frozen working core we
subclass it and override ``parse`` only. The base class's logic is reused
verbatim via ``super()``; the override exists purely to attach an optional
planner.

Why the augmentation is gated so hard
-------------------------------------
The base parser is not "a heuristic we beat" — it is the thing that keeps a
question like *"is there any trend in the kidney function?"* off the general
dump path. So the LLM is consulted **only** when the deterministic parse yields
the uninformative ``intent == "general"``, it must return a predicate that is
already in the base class's vocabulary, and any failure (no client, network
error, hallucinated intent) falls through to the deterministic answer. A
planner that can widen its own vocabulary is a planner that can talk itself
into answering something the record cannot support.
"""

from __future__ import annotations

from typing import Any, Optional

from axiom.pipeline import QueryPlanner

__all__ = ["LLMQueryPlanner", "build_planner"]

# The LLM may only *choose* among these. It may not introduce new intents.
_VALID_INTENTS = {"general", "trend", "interaction", "allergy", "followup",
                   "change", "administrative"}
_VALID_ENTITIES = {None, "renal"}

_SYSTEM = (
    "You classify a clinical question into a retrieval intent for a medical "
    "record system. Reply with JSON only: "
    '{"intent": one of "trend"|"interaction"|"allergy"|"followup"|"change"'
    '|"administrative"|"general", "entity": "renal" or null, '
    '"window_months": integer or null}. '
    'If the question is not about a time trend, a drug interaction, an allergy, '
    'a follow-up gap, a change since a prior visit, or a scheduling detail, '
    'reply exactly {"intent":"general","entity":null,"window_months":null}.'
)


class LLMQueryPlanner(QueryPlanner):
    """``QueryPlanner`` with an optional, strictly bounded LLM assist.

    Passing ``client=None`` (the default) makes this behaviourally identical to
    the base class — the deterministic parse is authoritative and no network
    call is ever attempted.
    """

    def __init__(self, client: Optional[Any] = None, timeout: float = 15.0) -> None:
        super().__init__()
        self.client = client
        self.timeout = timeout
        self.llm_calls = 0
        self.llm_fallbacks = 0

    def parse(self, q: str) -> dict:
        parsed = super().parse(q)
        if parsed.get("intent") != "general" or self.client is None:
            return parsed

        suggestion = self._ask_llm(q)
        if suggestion is None:
            return parsed

        self.llm_calls += 1
        merged = dict(parsed)
        if suggestion["intent"] != "general":
            merged["intent"] = suggestion["intent"]
        if suggestion.get("entity") in _VALID_ENTITIES:
            merged["entity"] = suggestion["entity"]
        if suggestion.get("window_months") is not None and merged.get("window_months") is None:
            merged["window_months"] = suggestion["window_months"]
        merged["llm_assisted"] = True
        return merged

    # -- internals ------------------------------------------------------
    def _ask_llm(self, q: str) -> Optional[dict]:
        """Return a validated predicate dict, or None to keep the base parse."""
        try:
            raw = self.client.json(_SYSTEM, q)
        except Exception:
            # Deliberately broad: any provider failure must not degrade the
            # deterministic path, and the reason is recorded, not raised.
            self.llm_fallbacks += 1
            return None
        if not isinstance(raw, dict):
            self.llm_fallbacks += 1
            return None
        intent = raw.get("intent")
        if intent not in _VALID_INTENTS:
            self.llm_fallbacks += 1
            return None
        window = raw.get("window_months")
        if not isinstance(window, int) or isinstance(window, bool) or window <= 0:
            window = None
        return {"intent": intent,
                "entity": raw.get("entity") if raw.get("entity") in _VALID_ENTITIES else None,
                "window_months": window}


def build_planner(llm_client: Optional[Any] = None) -> LLMQueryPlanner:
    """Planner factory. With no client this is exactly the frozen behaviour."""
    return LLMQueryPlanner(client=llm_client)