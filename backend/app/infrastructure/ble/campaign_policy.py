from __future__ import annotations

from typing import Any


POSITIVE_TARGET_VALIDATION = "positive_target_validation"
NEGATIVE_CONTROL = "negative_control"
EXPLORATORY_TARGET_SEARCH = "exploratory_target_search"

CAMPAIGN_INTENTS = {
    POSITIVE_TARGET_VALIDATION,
    NEGATIVE_CONTROL,
    EXPLORATORY_TARGET_SEARCH,
}

CURRENT_OBSERVATION_SOURCES = {
    "native_current_scan",
    "uc02_current_native_scan",
}

NEGATIVE_CONTROL_TYPES = {
    "target_powered_off",
    "target_physically_absent",
    "other_device_substituted",
    "ambient_only",
}


def target_seen_now(target: dict[str, Any]) -> bool:
    return target.get("kind") == "device" and target.get("selection_source") in CURRENT_OBSERVATION_SOURCES


def validate_campaign_contract(payload: dict[str, Any], target: dict[str, Any]) -> dict[str, Any]:
    """Validate the experimental claim before any session is created.

    The UI is not scientific authority. These checks are repeated in the
    backend so controller and UC-02 cannot assign different semantics to the
    same campaign payload.
    """
    intent = str(payload.get("campaign_intent") or "").strip().lower()
    if not intent:
        raise ValueError("CAMPAIGN_INTENT_REQUIRED")
    if intent not in CAMPAIGN_INTENTS:
        raise ValueError("INVALID_CAMPAIGN_INTENT")

    specific = target.get("kind") == "device" and bool(target.get("address"))
    seen_now = target_seen_now(target)
    negative_type = payload.get("negative_control_type")
    confirmed = payload.get("operator_confirmation") is True

    if intent == POSITIVE_TARGET_VALIDATION:
        if not specific:
            raise ValueError("POSITIVE_TARGET_REQUIRES_SPECIFIC_TARGET")
        if not seen_now:
            raise ValueError("POSITIVE_TARGET_REQUIRES_SEEN_NOW")
    elif intent == NEGATIVE_CONTROL:
        if not specific:
            raise ValueError("NEGATIVE_CONTROL_REQUIRES_SPECIFIC_TARGET")
        if negative_type not in NEGATIVE_CONTROL_TYPES:
            raise ValueError("NEGATIVE_CONTROL_DECLARATION_REQUIRED")
        if not confirmed:
            raise ValueError("NEGATIVE_CONTROL_OPERATOR_CONFIRMATION_REQUIRED")
    elif negative_type is not None or payload.get("operator_confirmation") is True:
        raise ValueError("NEGATIVE_CONTROL_FIELDS_REQUIRE_NEGATIVE_INTENT")

    return {
        "campaign_intent": intent,
        "target_seen_before_start": seen_now,
        "negative_control_type": negative_type if intent == NEGATIVE_CONTROL else None,
        "operator_confirmation": confirmed if intent == NEGATIVE_CONTROL else False,
    }


def contract_from_session(session: dict[str, Any]) -> dict[str, Any]:
    """Return explicit semantics, conservatively migrating legacy sessions.

    A legacy session without a pre-declared intent can never be retroactively
    promoted to a positive validation or negative control. It is exploratory.
    """
    intent = str(session.get("campaign_intent") or "").strip().lower()
    if intent not in CAMPAIGN_INTENTS:
        intent = EXPLORATORY_TARGET_SEARCH
    negative_type = str(session.get("negative_control_type") or "").strip().lower() or None
    return {
        "campaign_intent": intent,
        "campaign_intent_display": intent.upper(),
        "negative_control_type": negative_type if intent == NEGATIVE_CONTROL else None,
        "operator_confirmation": session.get("operator_confirmation") is True if intent == NEGATIVE_CONTROL else False,
        "legacy_intent_inferred": "campaign_intent" not in session,
    }
