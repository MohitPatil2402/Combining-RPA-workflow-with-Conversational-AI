"""
Layer 3: the robot's work, in Python.

This module is the reference implementation of what the UiPath robot does.
It exists for two reasons:

  1. It is the specification. uipath/Main.xaml performs these exact steps
     against these exact columns, and uipath/README.md walks through building
     it. When the two disagree, this file is what the tests check, so it is
     the version that is definitively correct.
  2. It makes the system testable and demonstrable without UiPath Studio
     running - useful at 2am, and useful as a fallback if Studio misbehaves
     five minutes before a review.

The steps mirror the methodology slide exactly:

    1. Validate order & customer
    2. Check refund eligibility
    3. Update order database
    4. Generate reference number
    5. Log for audit
"""
import random

from rpa import crm

# Statuses past the point where a parcel can still be redirected.
UNREDIRECTABLE_STATUSES = {"shipped", "out for delivery", "delivered",
                           "cancelled", "refunded"}

# Statuses where a refund makes no sense.
NON_REFUNDABLE_STATUSES = {"cancelled", "refunded"}


def _reference(prefix):
    """Reference numbers customers can quote back, e.g. RF1123."""
    return f"{prefix}{random.randint(1000, 9999)}"


def _money(value):
    try:
        return float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return 0.0


class ExecutionResult(dict):
    """The outcome of one robot run.

    A dict so it serialises straight to JSON for UiPath, with the fields
    callers actually branch on promoted to attributes for readability.
    """

    @property
    def success(self):
        return self.get("success", False)

    @property
    def reply(self):
        return self.get("reply", "")


def execute(decision):
    """Run the transaction described by a routing decision.

    Only ever called for decisions routed AUTO_RESOLVE. Anything else is a
    programming error, and is reported as one rather than quietly doing
    nothing.
    """
    action = decision.get("action")
    handlers = {
        "READ_STATUS": _do_status,
        "PROCESS_REFUND": _do_refund,
        "UPDATE_ADDRESS": _do_address_update,
    }
    handler = handlers.get(action)
    if handler is None:
        return ExecutionResult(
            success=False,
            action=action,
            result=f"No robot action is defined for '{action}'.",
            reply="Sorry - I couldn't complete that automatically. "
                  "Let me pass you to an agent.",
            escalate=True,
        )

    try:
        # Step 1: validate the order exists before touching anything.
        order = decision.get("order") or crm.get_order(
            decision["entities"]["order_id"]
        )
        result = handler(decision, order)
    except crm.OrderNotFound as exc:
        return ExecutionResult(
            success=False, action=action, result=str(exc),
            reply="I couldn't find that order number in our system. "
                  "Could you double-check it?",
            escalate=True,
        )
    except crm.CrmError as exc:
        # A failed write falls back to the human queue rather than reporting
        # a success that did not happen.
        return ExecutionResult(
            success=False, action=action, result=f"CRM error: {exc}",
            reply="Our order system isn't responding right now. I'm passing "
                  "this to an agent who'll follow up shortly.",
            escalate=True,
        )

    # Step 5: log every automated resolution for audit.
    crm.log_audit(
        order_id=decision.get("entities", {}).get("order_id", ""),
        intent=decision.get("intent"),
        confidence=decision.get("confidence"),
        engine=decision.get("engine", "local"),
        action=action,
        result=result.get("result", ""),
        reference_no=result.get("reference_no", ""),
    )
    return result


# ---------------------------------------------------------------------------
# Order status  -  a read, so no database update and no reference number
# ---------------------------------------------------------------------------
def _do_status(decision, order):
    status = str(order.get("Status", "Unknown"))
    product = order.get("Product", "your order")
    tracking = str(order.get("TrackingNo") or "").strip()

    phrasing = {
        "processing": f"Your {product} is being prepared for dispatch.",
        "shipped": f"Your {product} has shipped and is on its way.",
        "out for delivery": f"Your {product} is out for delivery today.",
        "delivered": f"Your {product} has been delivered.",
        "cancelled": f"Your order for the {product} was cancelled.",
        "refunded": f"Your order for the {product} was refunded.",
    }
    reply = phrasing.get(status.lower(), f"Your {product} is currently: {status}.")
    if tracking and status.lower() in {"shipped", "out for delivery"}:
        reply += f" You can track it with {tracking}."

    return ExecutionResult(
        success=True,
        action="READ_STATUS",
        result=f"Status read: {status}",
        reference_no="",
        reply=reply,
        order_id=order.get("OrderID"),
        escalate=False,
    )


# ---------------------------------------------------------------------------
# Refund  -  validate, check eligibility, update, generate reference, log
# ---------------------------------------------------------------------------
def _do_refund(decision, order):
    order_id = order.get("OrderID")
    amount = _money(order.get("Amount"))
    status = str(order.get("Status", "")).lower()
    eligible = str(order.get("RefundEligible", "")).upper() == "Y"

    # Step 2: check refund eligibility.
    if status in NON_REFUNDABLE_STATUSES:
        return ExecutionResult(
            success=False,
            action="PROCESS_REFUND",
            result=f"Refund declined: order already '{order.get('Status')}'.",
            reference_no="",
            reply=f"That order is already marked '{order.get('Status')}', "
                  f"so there's no payment left to refund. If you think that's "
                  f"wrong, I can put you through to an agent.",
            order_id=order_id,
            escalate=False,
        )

    if not eligible:
        # A clean, explained "no" is a resolution too - the customer is told
        # what happened and what is next, not dropped.
        return ExecutionResult(
            success=False,
            action="PROCESS_REFUND",
            result="Refund declined: order is outside the returns window.",
            reference_no="",
            reply=f"Order {order_id} is outside our returns window, so I "
                  f"can't process a refund automatically. I can raise this "
                  f"with an agent to review if you'd like.",
            order_id=order_id,
            escalate=False,
        )

    # Steps 3 and 4: update the database and generate the reference number.
    reference = _reference("RF")
    crm.update_order(order_id, {
        "Status": "Refund Initiated",
        "RefundEligible": "N",
    })

    return ExecutionResult(
        success=True,
        action="PROCESS_REFUND",
        result=f"Refund of Rs {amount:,.2f} initiated.",
        reference_no=reference,
        reply=f"Done - I've processed a refund of Rs {amount:,.2f} for order "
              f"{order_id}. Your reference number is {reference}, and the "
              f"money should be back in your account within 5-7 working days.",
        order_id=order_id,
        amount=amount,
        escalate=False,
    )


# ---------------------------------------------------------------------------
# Address update
# ---------------------------------------------------------------------------
def _do_address_update(decision, order):
    order_id = order.get("OrderID")
    status = str(order.get("Status", "")).lower()
    new_address = str(decision.get("entities", {}).get("new_address", "")).strip()

    if not new_address:
        return ExecutionResult(
            success=False, action="UPDATE_ADDRESS",
            result="No new address supplied.",
            reply="What's the new delivery address you'd like to use?",
            order_id=order_id, escalate=False,
        )

    # Once a parcel is moving, redirecting it is a courier decision, not a
    # database edit - so this is a person's call.
    if status in UNREDIRECTABLE_STATUSES:
        return ExecutionResult(
            success=False,
            action="UPDATE_ADDRESS",
            result=f"Address change refused: order is '{order.get('Status')}'.",
            reference_no="",
            reply=f"Order {order_id} is already '{order.get('Status')}', so I "
                  f"can't change the address automatically - it needs the "
                  f"courier's agreement. I'm passing this to an agent who can "
                  f"arrange a redirect.",
            order_id=order_id,
            escalate=True,
        )

    reference = _reference("AD")
    previous = order.get("DeliveryAddress", "")
    crm.update_order(order_id, {"DeliveryAddress": new_address})

    return ExecutionResult(
        success=True,
        action="UPDATE_ADDRESS",
        result=f"Delivery address updated (was: {previous})",
        reference_no=reference,
        reply=f"Updated - order {order_id} will now be delivered to "
              f"{new_address}. Your reference number is {reference}.",
        order_id=order_id,
        escalate=False,
    )


# ---------------------------------------------------------------------------
# Escalation  -  the context packet an agent picks up
# ---------------------------------------------------------------------------
def escalate(decision):
    """Queue a case for a human with the reasoning attached."""
    entities = decision.get("entities") or {}
    entities_text = "; ".join(f"{k}={v}" for k, v in entities.items()) or "none"

    crm.log_escalation(
        order_id=entities.get("order_id", ""),
        intent=decision.get("intent"),
        confidence=decision.get("confidence"),
        entities=entities_text,
        reason=decision.get("reason", ""),
        suggested_resolution=decision.get("suggested_resolution", ""),
        customer_message=decision.get("text", ""),
    )

    return ExecutionResult(
        success=True,
        action="ESCALATE",
        result=f"Queued for a human agent ({decision.get('reason')}).",
        reference_no="",
        reply="I want to make sure this is handled properly, so I'm passing "
              "you to one of our agents. They'll have the full details of "
              "your request - you won't need to explain it again.",
        order_id=entities.get("order_id", ""),
        escalate=True,
    )
