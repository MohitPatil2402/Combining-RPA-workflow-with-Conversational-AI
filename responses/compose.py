"""
Composing the customer-facing reply.

Replies used to be f-strings scattered through rpa/executor.py, which made
them single-fact and context-blind - and every escalation, whatever its
cause, produced the same sentence. A customer told "I'm passing you to an
agent" learns nothing: not why, not what happens next, not when.

Everything a reply needs is already in the system: the CRM row has the
customer's name, the product, the order date, the amount; the routing
decision has the reason and the policy that produced it. This module turns
those facts into something a professional service desk would actually send.

Four things every reply does:

  1. Acknowledge - by name when the order is known.
  2. State the facts - the real product, amount and date, never a placeholder.
  3. Say what happens next, and by when - a promise with a time on it.
  4. Give a reference - so the customer can quote it back.

It is deliberately deterministic: no model, no network, no randomness except
the reference number. Every sentence can be traced to a rule, which is what
makes the replies defensible rather than merely fluent.
"""
import random
from datetime import datetime

import config

# How long each kind of handoff should take. Stated to the customer, so these
# are promises - keep them consistent with whatever the real desk commits to.
SLA = {
    "SENSITIVITY_CAP": "4 working hours",
    "POLICY_INTENT_COMPLAINT": "4 working hours",
    "POLICY_INTENT_AGENT": "under 5 minutes",
    "LOW_CONFIDENCE": "4 working hours",
    "ORDER_NOT_FOUND": "4 working hours",
    "CRM_UNAVAILABLE": "shortly",
    "EXECUTION_BLOCKED": "4 working hours",
    "DEFAULT": "4 working hours",
}

# What the robot tells the customer to expect, by order status.
NEXT_STEP = {
    "processing": "It will be dispatched within 1-2 working days, and you'll "
                  "get a tracking number by SMS as soon as it leaves our "
                  "warehouse.",
    "shipped": "It's on its way and should reach you within 2-3 working days.",
    "out for delivery": "It's out for delivery today, so expect it before "
                        "this evening.",
}


def reference(prefix):
    """A reference number the customer can quote back."""
    return f"{prefix}{random.randint(1000, 9999)}"


def money(amount):
    try:
        return f"Rs {float(amount):,.2f}"
    except (TypeError, ValueError):
        return "the order amount"


def first_name(order):
    """Just the given name - "Hi Ananya" reads better than the full name."""
    if not order:
        return ""
    full = str(order.get("CustomerName", "")).strip()
    return full.split()[0] if full else ""


def greeting(order, apologise=False):
    """Open the reply. An apology outranks a greeting when something is wrong."""
    name = first_name(order)
    if apologise:
        return f"I'm sorry about this, {name}." if name else "I'm sorry about this."
    return f"Hi {name} - " if name else ""


def pretty_date(value):
    """2026-09-10 -> 10 Sep. Falls back to whatever was stored."""
    text = str(value or "").strip()
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(text[:10], fmt).strftime("%d %b")
        except ValueError:
            continue
    return text


def describe_order(order):
    """"Prestige Iris 750W (order 4521)" - product first, people think that way."""
    if not order:
        return "your order"
    product = order.get("Product") or "your order"
    order_id = order.get("OrderID")
    return f"{product} (order {order_id})" if order_id else str(product)


def contact_line(order):
    phone = str(order.get("Phone", "")).strip() if order else ""
    return f" on {phone}" if phone else ""


# ---------------------------------------------------------------------------
# Automated resolutions
# ---------------------------------------------------------------------------
def status_reply(order):
    status = str(order.get("Status", "")).strip()
    lowered = status.lower()
    tracking = str(order.get("TrackingNo") or "").strip()
    ordered_on = pretty_date(order.get("OrderDate"))

    lines = []

    if lowered == "delivered":
        lines.append(f"{greeting(order)}your {describe_order(order)} was "
                     f"delivered.")
        lines.append("If something's wrong with it, I can start a return or "
                     "raise it with our product team - just tell me what the "
                     "problem is.")
    elif lowered in NEXT_STEP:
        lines.append(f"{greeting(order)}your {describe_order(order)} is "
                     f"currently {lowered}.")
        lines.append(NEXT_STEP[lowered])
        if tracking:
            lines.append(f"Tracking number: {tracking}")
    elif lowered == "cancelled":
        lines.append(f"{greeting(order)}order {order.get('OrderID')} for the "
                     f"{order.get('Product')} was cancelled.")
        lines.append("If you didn't request that, tell me and I'll have "
                     "someone look into it straight away.")
    elif lowered in {"refunded", "refund initiated"}:
        lines.append(f"{greeting(order)}a refund for your "
                     f"{describe_order(order)} has already been processed.")
        lines.append("It should reach your original payment method within "
                     "5-7 working days of being approved.")
    else:
        lines.append(f"{greeting(order)}your {describe_order(order)} is "
                     f"currently: {status}.")

    if ordered_on:
        lines.append(f"Ordered on {ordered_on}.")
    return "\n".join(lines)


def refund_approved_reply(order, amount, ref):
    name = first_name(order)
    opener = f"That's done, {name}." if name else "That's done."
    return "\n".join([
        f"{opener} I've approved a refund of {money(amount)} for your "
        f"{describe_order(order)}.",
        f"Reference: {ref}",
        "The amount will be returned to your original payment method within "
        "5-7 working days, and you'll get an SMS once your bank has processed "
        "it. Nothing further is needed from you.",
    ])


def refund_declined_reply(order):
    """A clear, explained no - with a route that isn't a dead end."""
    ordered_on = pretty_date(order.get("OrderDate"))
    return "\n".join([
        f"{greeting(order)}I've checked your {describe_order(order)}"
        f"{f', delivered {ordered_on}' if ordered_on else ''}, and it falls "
        f"outside our returns window, so I'm not able to approve a refund "
        f"automatically.",
        "If the product is faulty rather than unwanted, that's handled "
        "differently - tell me what's wrong with it and I'll raise it with "
        "our product team, who can authorise a replacement or a repair.",
    ])


def refund_not_applicable_reply(order):
    status = order.get("Status")
    return "\n".join([
        f"{greeting(order)}order {order.get('OrderID')} is already marked "
        f"'{status}', so there's no payment left to refund.",
        "If you think that's wrong, say so and I'll have an agent check the "
        "payment history on this order.",
    ])


def address_updated_reply(order, new_address, ref):
    return "\n".join([
        f"{greeting(order)}I've updated the delivery address for your "
        f"{describe_order(order)}.",
        f"New address: {new_address}",
        f"Reference: {ref}",
        "The change takes effect immediately, and the order will ship to the "
        "new address. No further action is needed.",
    ])


def address_too_late_reply(order):
    status = str(order.get("Status", "")).strip()
    return "\n".join([
        f"{greeting(order)}your {describe_order(order)} is already "
        f"'{status}', so I can't change the address from here - once a parcel "
        f"is with the courier, redirecting it needs their agreement.",
        "I've passed this to an agent who can arrange a redirect directly "
        "with the courier.",
    ])


def order_not_found_reply(order_id):
    return "\n".join([
        f"I couldn't find order {order_id} in our system.",
        "It's possible there's a typo in the number, or the order was placed "
        "under a different account. Could you check your confirmation email "
        "and share the exact order number?",
    ])


def system_unavailable_reply():
    return "\n".join([
        "I can't reach our order system at the moment, so I don't want to "
        "give you information that might be wrong.",
        "I've logged this for an agent, who will follow up as soon as the "
        "system is back. Your request hasn't been lost.",
    ])


# ---------------------------------------------------------------------------
# Escalations - the reply changes with the reason
# ---------------------------------------------------------------------------
def escalation_reply(decision, order, case_ref):
    """What the customer hears when a person takes over.

    One generic sentence for every escalation is what makes a bot feel like
    a dead end. The customer should learn why it was escalated, what the
    human will do, and when - and those differ completely between a refund
    over the approval limit and a message we simply didn't understand.
    """
    reason = decision.get("reason", "")
    intent = decision.get("intent") or ""
    entities = decision.get("entities") or {}

    if reason == "LOW_CONFIDENCE":
        # Checked first, and deliberately so. The classifier's best guess at
        # this confidence is not something to repeat back to the customer -
        # "I'm sorry about your washing machine" when we are 19% sure it is
        # even a complaint is worse than admitting we did not follow.
        body = [
            "I want to get this right rather than guess, and I'm not "
            "confident enough that I've understood what you need.",
            "I've passed your message to one of our agents exactly as you "
            "wrote it, along with what I was able to work out.",
        ]
        sla = SLA["LOW_CONFIDENCE"]
        closing = (f"Someone will come back to you within {sla}. If you have "
                   f"your order number to hand, sharing it now will help them "
                   f"get straight to it.")

    elif reason == "SENSITIVITY_CAP":
        amount = entities.get("amount") or (order or {}).get("Amount")
        eligible = str((order or {}).get("RefundEligible", "")).upper() == "Y"
        body = [
            f"{greeting(order)}I've reviewed your refund request for "
            f"{describe_order(order)}, and everything on my side checks out"
            f"{' - the order is eligible and within policy' if eligible else ''}.",
            f"Because {money(amount)} is above my approval limit of "
            f"{money(config.SENSITIVITY_CAP_INR)}, it needs a supervisor's "
            f"sign-off. I've passed it on with my recommendation"
            f"{' to approve' if eligible else ' and the details for review'}.",
        ]
        sla = SLA["SENSITIVITY_CAP"]
        closing = ("A member of the team will confirm within "
                   f"{sla}. You don't need to do anything else.")

    elif intent == "order.complaint":
        product = (order or {}).get("Product") or entities.get("category")
        subject = f"your {product}" if product else "what's happened"
        body = [
            f"I'm sorry to hear about {subject} - that's not the experience "
            f"we want you to have.",
            "Product issues are handled by our specialist team, who can "
            "arrange a replacement, a repair or a refund depending on what "
            "you'd prefer. I've passed on everything you've told me, so you "
            "won't need to explain it again.",
        ]
        sla = SLA["POLICY_INTENT_COMPLAINT"]
        closing = (f"They'll get in touch{contact_line(order)} within {sla}.")

    elif intent == "agent.escalation_request":
        body = [
            "Of course - I'm connecting you with one of our agents now.",
            "I've passed along our conversation and the details of your "
            "request, so you won't need to repeat yourself.",
        ]
        sla = SLA["POLICY_INTENT_AGENT"]
        closing = f"Typical wait is {sla}."

    elif reason == "ORDER_NOT_FOUND":
        order_id = entities.get("order_id", "that order")
        body = [
            f"I couldn't find order {order_id} in our system - it may have a "
            f"typo, or have been placed under a different account.",
            "I've passed this to an agent who can search our records more "
            "thoroughly than I can.",
        ]
        sla = SLA["ORDER_NOT_FOUND"]
        closing = (f"They'll come back to you within {sla}. If you can check "
                   f"your confirmation email for the exact number in the "
                   f"meantime, that will speed things up.")

    elif reason == "CRM_UNAVAILABLE":
        body = [
            "I can't reach our order system right now, and I'd rather hand "
            "this to a person than give you information that might be wrong.",
            "An agent has the details of your request and will pick it up as "
            "soon as the system is back.",
        ]
        sla = SLA["CRM_UNAVAILABLE"]
        closing = f"You should hear back {sla}."

    else:   # any reason not given its own wording above
        body = [
            "I'd rather a person handled this one properly than have me "
            "act on a request I'm not certain about.",
            "I've passed on your message and everything I was able to "
            "establish, so you won't need to explain it again.",
        ]
        sla = SLA["DEFAULT"]
        closing = f"Someone will come back to you within {sla}."

    return "\n".join(body + [f"Reference: {case_ref}", closing])


def followup_reply(decision):
    """Asking for a missing entity, without sounding like a form."""
    question = decision.get("followup_question") or ""
    return question
