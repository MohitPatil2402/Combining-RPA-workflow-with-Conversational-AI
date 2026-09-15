"""
End-to-end: message in, resolution out.

This wires Layer 1 -> Layer 2 -> Layer 3 together in one call. Two callers
use it:

  * The /resolve endpoint, and demo.py, which run the whole system in Python.
  * The tests, which assert on the scenarios from the methodology slides.

When UiPath is driving, it does NOT use this. The robot calls /classify for
layers 1 and 2 and then performs layer 3 itself - that is the real
architecture, and this module is the reference the robot is built to match.
"""
from nlu import engine
from orchestrator import routing, sessions
from rpa import executor


def _fill_pending_slot(text, session_id):
    """If we asked a follow-up question, treat this message as the answer.

    The key insight in slot filling: once we have asked "what's the new
    address?", the customer's next message IS the address. Re-classifying it
    would be wrong - "21 MG Road, Pune" is not an intent.
    """
    pending = sessions.get_pending(session_id)
    if not pending:
        return None

    entities = dict(pending["entities"])
    slot = pending["missing_entity"]

    if slot == "order_id":
        # An order id is structured, so extract it rather than trusting the
        # whole message to be one.
        from nlu.local_classifier import extract_entities
        found = extract_entities(text).get("order_id")
        if not found:
            return None
        entities["order_id"] = found
    else:
        entities[slot] = text.strip()

    sessions.clear(session_id)
    return {
        "text": text,
        "intent": pending["intent"],
        # The confidence belongs to the original classification; answering a
        # follow-up question does not make us more or less sure of it.
        "confidence": pending.get("confidence", 0.99),
        "entities": entities,
        "engine": pending.get("engine", "local"),
        "slot_filled": slot,
    }


def classify_and_route(text, session_id=None):
    """Layers 1 and 2 only. This is what the UiPath robot calls."""
    classification = _fill_pending_slot(text, session_id)
    if classification is None:
        classification = engine.detect_intent(text, session_id=session_id)

    decision = routing.decide(classification)

    if decision["route"] == routing.NEED_INFO:
        sessions.set_pending(
            session_id,
            intent=decision.get("intent"),
            entities=decision.get("entities"),
            missing_entity=decision.get("missing_entity"),
        )
        # Carry the confidence forward so the resumed turn keeps it.
        pending = sessions.get_pending(session_id)
        if pending is not None:
            pending["confidence"] = decision.get("confidence")
            pending["engine"] = decision.get("engine")
            sessions.set_pending(
                session_id, pending["intent"], pending["entities"],
                pending["missing_entity"],
            )

    return decision


def handle_message(text, session_id=None):
    """All three layers, in Python. Returns decision + execution outcome."""
    decision = classify_and_route(text, session_id=session_id)
    route = decision["route"]

    if route == routing.NEED_INFO:
        outcome = executor.ExecutionResult(
            success=True,
            action="ASK_FOLLOWUP",
            result=f"Asked the customer for '{decision.get('missing_entity')}'.",
            reply=decision.get("followup_question", ""),
            escalate=False,
        )
    elif route == routing.AUTO_RESOLVE:
        outcome = executor.execute(decision)
        # A robot that starts a transaction and finds it cannot finish still
        # owes the customer a person, not an apology.
        if outcome.get("escalate"):
            decision.setdefault("reason", "EXECUTION_BLOCKED")
            decision["suggested_resolution"] = (
                decision.get("suggested_resolution")
                or outcome.get("result", "")
            )
            escalation = executor.escalate(decision)
            outcome["escalated_to_human"] = True
            outcome["escalation_result"] = escalation.get("result")
    else:
        outcome = executor.escalate(decision)

    return {"decision": decision, "outcome": outcome}
