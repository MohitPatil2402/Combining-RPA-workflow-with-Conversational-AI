"""
Layer 2: the routing decision.

This is the module the whole design rests on. It takes a classified message
and decides which of three things happens to it:

    AUTO_RESOLVE  the robot may execute the transaction
    NEED_INFO     a required entity is missing; ask a follow-up question
    ESCALATE      a person handles it, with a context packet attached

The rules, in the order they are applied:

  1. No intent, or confidence below the engine's threshold  -> ESCALATE
  2. Intent is one that is never automated (complaints, explicit requests
     for a human)                                           -> ESCALATE
  3. A required entity is missing                           -> NEED_INFO
  4. Money involved exceeds the sensitivity cap             -> ESCALATE
  5. Otherwise                                              -> AUTO_RESOLVE

Two properties are deliberate:

*Order matters.* Confidence is checked before anything else, because an
entity extracted from a message we did not understand is not evidence.

*Every path terminates somewhere a human can see.* There is no branch that
drops a customer. Failure to reach the CRM escalates rather than guessing,
which is the fail-safe-not-silent principle in practice.
"""
import config
from rpa import crm

# Route constants
AUTO_RESOLVE = "AUTO_RESOLVE"
NEED_INFO = "NEED_INFO"
ESCALATE = "ESCALATE"

# Machine-readable escalation reasons, so the audit trail can be grouped and
# counted later instead of parsed out of prose.
REASON_LOW_CONFIDENCE = "LOW_CONFIDENCE"
REASON_POLICY_INTENT = "POLICY_INTENT"
REASON_SENSITIVITY_CAP = "SENSITIVITY_CAP"
REASON_CRM_UNAVAILABLE = "CRM_UNAVAILABLE"
REASON_ORDER_NOT_FOUND = "ORDER_NOT_FOUND"

# Which robot action each automatable intent maps to.
INTENT_ACTIONS = {
    "order.status": "READ_STATUS",
    "order.refund": "PROCESS_REFUND",
    "order.address_update": "UPDATE_ADDRESS",
}

FOLLOWUP_QUESTIONS = {
    "order_id": "Sure - could you tell me your order number? "
                "It's the 4-digit number on your confirmation email.",
    "new_address": "Of course. What's the new delivery address "
                   "you'd like to use?",
}


def _money(value):
    try:
        return float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def decide(classification):
    """Turn an NLU classification into a routing decision.

    `classification` is whatever the NLU layer returned: a dict with intent,
    confidence, entities and engine. The return value is that same dict
    enriched with the decision, so callers get one flat object to work with.
    """
    intent = classification.get("intent")
    confidence = classification.get("confidence") or 0.0
    entities = dict(classification.get("entities") or {})
    engine = classification.get("engine", "local")
    message = classification.get("text", "")

    threshold = config.threshold_for(engine)

    decision = dict(classification)
    decision.update({
        "entities": entities,
        "threshold": threshold,
        "sensitivity_cap": config.SENSITIVITY_CAP_INR,
        "order": None,
        "action": None,
        "followup_question": None,
    })

    # -- Rule 1: did we understand it at all? -------------------------------
    if intent is None or confidence < threshold:
        return _escalate(
            decision,
            REASON_LOW_CONFIDENCE,
            f"Confidence {confidence:.2f} is below the {threshold:.2f} "
            f"automation threshold for the {engine} engine.",
            _suggest_for_unclear(decision),
        )

    # -- Rule 2: intents policy says a person always handles ----------------
    if intent in config.ALWAYS_ESCALATE_INTENTS:
        return _escalate(
            decision,
            REASON_POLICY_INTENT,
            f"Intent '{intent}' is never automated by policy, regardless of "
            f"confidence ({confidence:.2f}).",
            _suggest_for_policy(decision),
        )

    # -- Rule 3: slot filling ------------------------------------------------
    required = _required_entities(intent)
    missing = [name for name in required if not entities.get(name)]
    if missing:
        slot = missing[0]
        decision.update({
            "route": NEED_INFO,
            "reason": f"MISSING_{slot.upper()}",
            "reason_detail": f"Intent '{intent}' needs '{slot}' before it can "
                             f"be actioned.",
            "missing_entity": slot,
            "followup_question": FOLLOWUP_QUESTIONS.get(
                slot, f"Could you provide your {slot.replace('_', ' ')}?"
            ),
            "suggested_resolution": "",
        })
        return decision

    # -- Enrich from the CRM so the cap applies to the real order value ------
    order_id = entities.get("order_id")
    if order_id:
        try:
            decision["order"] = crm.get_order(order_id)
        except crm.OrderNotFound:
            return _escalate(
                decision,
                REASON_ORDER_NOT_FOUND,
                f"Order {order_id} was quoted by the customer but does not "
                f"exist in the CRM.",
                f"Confirm the correct order number with the customer - "
                f"{order_id} is not in the system. The message may contain a "
                f"typo, or the order may belong to another account.",
            )
        except crm.CrmError as exc:
            # Fail safe, not silent: an unreachable CRM means a person picks
            # this up, never a guessed answer.
            return _escalate(
                decision, REASON_CRM_UNAVAILABLE,
                f"CRM lookup failed: {exc}",
                "Retry once the order system is reachable, then action "
                "normally.",
            )

    # -- Rule 4: the sensitivity cap ----------------------------------------
    if intent == "order.refund":
        amount = _money(entities.get("amount"))
        if amount is None and decision["order"]:
            amount = _money(decision["order"].get("Amount"))
        if amount is not None:
            entities.setdefault("amount", amount)
            if amount > config.SENSITIVITY_CAP_INR:
                return _escalate(
                    decision,
                    REASON_SENSITIVITY_CAP,
                    f"Refund of Rs {amount:,.2f} exceeds the Rs "
                    f"{config.SENSITIVITY_CAP_INR:,.2f} sensitivity cap. "
                    f"Escalated despite {confidence:.2f} confidence.",
                    _suggest_for_refund(decision, amount),
                )

    # -- Rule 5: automate ----------------------------------------------------
    decision.update({
        "route": AUTO_RESOLVE,
        "reason": "WITHIN_POLICY",
        "reason_detail": f"Confidence {confidence:.2f} >= {threshold:.2f} and "
                         f"the request is within automation policy.",
        "action": INTENT_ACTIONS.get(intent),
        "suggested_resolution": "",
    })
    return decision


def _required_entities(intent):
    from nlu.training_data import INTENTS
    return INTENTS.get(intent, {}).get("required_entities", [])


def _escalate(decision, reason, detail, suggested_resolution):
    decision.update({
        "route": ESCALATE,
        "reason": reason,
        "reason_detail": detail,
        "action": None,
        "suggested_resolution": suggested_resolution,
    })
    return decision


# ---------------------------------------------------------------------------
# Suggested resolutions
# ---------------------------------------------------------------------------
# What separates this handoff from dumping a transcript on someone. The agent
# opens the case and already has a proposed next step and the evidence behind
# it, so they are reviewing a decision rather than starting an investigation.
# ---------------------------------------------------------------------------
def _order_summary(decision):
    order = decision.get("order")
    if not order:
        return ""
    return (
        f"Order {order.get('OrderID')} - {order.get('Product')} "
        f"({order.get('Category')}), Rs {_money(order.get('Amount')) or 0:,.2f}, "
        f"status '{order.get('Status')}', "
        f"refund-eligible: {order.get('RefundEligible')}. "
        f"Customer: {order.get('CustomerName')} ({order.get('Phone')})."
    )


def _suggest_for_unclear(decision):
    entities = decision.get("entities") or {}
    known = ", ".join(f"{k}={v}" for k, v in entities.items()) or "none"
    return (
        f"The message could not be classified confidently "
        f"(best guess: {decision.get('intent') or 'none'} at "
        f"{decision.get('confidence', 0):.2f}). Entities detected: {known}. "
        f"Read the customer's message, confirm what they need, and if this "
        f"phrasing is a common one, add it to the training data so the "
        f"classifier handles it next time."
    )


def _suggest_for_policy(decision):
    intent = decision.get("intent")
    summary = _order_summary(decision)
    if intent == "order.complaint":
        base = (
            "Product complaint - policy routes every complaint to a person. "
            "Acknowledge the issue, determine whether this is a replacement, "
            "a repair visit or a refund, and set expectations on timing."
        )
    else:
        base = (
            "The customer explicitly asked for a human. Open with a greeting "
            "that acknowledges they asked - do not restart the bot flow."
        )
    return f"{base} {summary}".strip()


def _suggest_for_refund(decision, amount):
    order = decision.get("order") or {}
    eligible = str(order.get("RefundEligible", "")).upper() == "Y"
    summary = _order_summary(decision)

    if eligible:
        recommendation = (
            f"The order IS marked refund-eligible and all automated checks "
            f"pass. Recommended action: approve the Rs {amount:,.2f} refund. "
            f"This case is above the cap for authorisation reasons only, not "
            f"because anything looks wrong."
        )
    else:
        recommendation = (
            f"The order is NOT marked refund-eligible. Recommended action: "
            f"review why before approving - check the delivery date against "
            f"the returns window and inspect any prior complaint on this "
            f"order."
        )
    return f"{recommendation} {summary}".strip()
