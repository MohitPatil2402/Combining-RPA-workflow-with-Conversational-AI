"""
Layer 2 as a service - the join between conversational AI and RPA.

UiPath's HTTP Request activity posts a customer message here and gets back a
flat JSON object telling it exactly what to do. Putting the Google
authentication and the routing rules on this side of the boundary is what
keeps the UiPath workflow simple: the robot deals in plain HTTP and plain
JSON, with no OAuth2, no JWT signing and no SDK inside Studio.

Run it:

    python -m orchestrator.webhook_service

Endpoints
---------
GET  /health          liveness, plus which NLU engine is actually live
GET  /config          the thresholds and rules currently in force
POST /classify        layers 1+2. THIS is what the UiPath robot calls.
POST /resolve         all three layers in Python, for testing without Studio
GET  /orders/<id>     REST-style CRM read
GET  /logs/<name>     read back AuditLog or EscalationQueue
"""
from flask import Flask, jsonify, request

import config
from nlu import engine
from orchestrator import pipeline, sessions
from rpa import crm

app = Flask(__name__)


def _message_from_request():
    """Accept JSON, form posts or a query string.

    UiPath's HTTP Request activity is easy to misconfigure, and a webhook
    that 400s because the content-type header was not set exactly right
    costs an hour of a build night. So take the message however it arrives.
    """
    payload = request.get_json(silent=True) or {}
    text = (
        payload.get("text")
        or payload.get("message")
        or payload.get("query")
        or request.form.get("text")
        or request.args.get("text")
        or ""
    ).strip()
    session_id = (
        payload.get("session_id")
        or request.form.get("session_id")
        or request.args.get("session_id")
        or "uipath-default"
    )
    return text, session_id


def _flatten(decision):
    """Flatten the decision into the shape UiPath reads most easily.

    Deserialize JSON in Studio gives a JObject, and reaching into nested
    objects from there is fiddly, so the fields the workflow branches on are
    all promoted to the top level as simple strings and numbers.
    """
    entities = decision.get("entities") or {}
    order = decision.get("order") or {}
    return {
        "route": decision.get("route"),
        "intent": decision.get("intent") or "",
        "confidence": decision.get("confidence", 0.0),
        "engine": decision.get("engine", ""),
        "action": decision.get("action") or "",
        "reason": decision.get("reason", ""),
        "reason_detail": decision.get("reason_detail", ""),

        # Entities, promoted.
        "order_id": str(entities.get("order_id", "")),
        "amount": entities.get("amount", 0) or 0,
        "category": entities.get("category", ""),
        "new_address": entities.get("new_address", ""),

        # Escalation payload - the context packet.
        "suggested_resolution": decision.get("suggested_resolution", ""),
        "followup_question": decision.get("followup_question") or "",
        "entities_text": "; ".join(f"{k}={v}" for k, v in entities.items()),

        # Order enrichment, so the robot can skip a lookup if it wants to.
        "order_product": order.get("Product", ""),
        "order_status": order.get("Status", ""),
        "order_amount": order.get("Amount", 0) or 0,
        "order_refund_eligible": order.get("RefundEligible", ""),
        "customer_name": order.get("CustomerName", ""),

        # The policy that produced this decision, echoed for the audit trail.
        "threshold": decision.get("threshold"),
        "sensitivity_cap": decision.get("sensitivity_cap"),
        "customer_message": decision.get("text", ""),
    }


@app.get("/health")
def health():
    return jsonify({
        "status": "ok",
        "nlu_engine": engine.active_engine_description(),
        "crm_workbook": str(config.CRM_WORKBOOK),
        "crm_reachable": config.CRM_WORKBOOK.exists(),
    })


@app.get("/config")
def show_config():
    return jsonify({
        "nlu_engine_mode": config.NLU_ENGINE,
        "active_engine": engine.active_engine_description(),
        "confidence_threshold_local": config.CONFIDENCE_THRESHOLD_LOCAL,
        "confidence_threshold_dialogflow": config.CONFIDENCE_THRESHOLD_DIALOGFLOW,
        "sensitivity_cap_inr": config.SENSITIVITY_CAP_INR,
        "always_escalate_intents": sorted(config.ALWAYS_ESCALATE_INTENTS),
        "categories": config.CATEGORIES,
    })


@app.post("/classify")
def classify():
    """Layers 1 and 2. The UiPath robot posts here and acts on the answer."""
    text, session_id = _message_from_request()
    if not text:
        return jsonify({"error": "no message supplied",
                        "hint": 'POST {"text": "..."}'}), 400

    decision = pipeline.classify_and_route(text, session_id=session_id)
    response = _flatten(decision)
    response["session_id"] = session_id
    return jsonify(response)


@app.post("/resolve")
def resolve():
    """All three layers in Python - the no-Studio-required path."""
    text, session_id = _message_from_request()
    if not text:
        return jsonify({"error": "no message supplied"}), 400

    result = pipeline.handle_message(text, session_id=session_id)
    response = _flatten(result["decision"])
    outcome = result["outcome"]
    response.update({
        "session_id": session_id,
        "executed": outcome.get("action", ""),
        "execution_success": outcome.get("success", False),
        "execution_result": outcome.get("result", ""),
        "reference_no": outcome.get("reference_no", ""),
        "reply": outcome.get("reply", ""),
        "escalated_to_human": outcome.get("escalated_to_human",
                                          outcome.get("escalate", False)),
    })
    return jsonify(response)


@app.post("/session/reset")
def reset_session():
    _, session_id = _message_from_request()
    sessions.clear(session_id)
    return jsonify({"status": "cleared", "session_id": session_id})


@app.get("/orders/<order_id>")
def get_order(order_id):
    try:
        return jsonify(crm.get_order(order_id))
    except crm.OrderNotFound:
        return jsonify({"error": f"order {order_id} not found"}), 404
    except crm.CrmError as exc:
        return jsonify({"error": str(exc)}), 503


@app.get("/logs/<name>")
def get_log(name):
    sheets = {
        "audit": config.SHEET_AUDIT,
        "escalations": config.SHEET_ESCALATION,
    }
    sheet = sheets.get(name.lower())
    if sheet is None:
        return jsonify({"error": f"unknown log '{name}'",
                        "available": sorted(sheets)}), 404
    try:
        return jsonify(crm.read_log(sheet))
    except crm.CrmError as exc:
        return jsonify({"error": str(exc)}), 503


def main():
    print("=" * 70)
    print("  Layer 2 - Orchestration webhook")
    print("=" * 70)
    print(f"  NLU engine        : {engine.active_engine_description()}")
    print(f"  Local threshold   : {config.CONFIDENCE_THRESHOLD_LOCAL}")
    print(f"  Sensitivity cap   : Rs {config.SENSITIVITY_CAP_INR:,.0f}")
    print(f"  CRM workbook      : {config.CRM_WORKBOOK}")
    if not config.CRM_WORKBOOK.exists():
        print("  WARNING: workbook missing. Run: "
              "python scripts/build_mock_crm.py")
    print()
    print(f"  Listening on http://{config.WEBHOOK_HOST}:{config.WEBHOOK_PORT}")
    print(f"  UiPath should POST to "
          f"http://{config.WEBHOOK_HOST}:{config.WEBHOOK_PORT}/classify")
    print("=" * 70)
    app.run(host=config.WEBHOOK_HOST, port=config.WEBHOOK_PORT, debug=False)


if __name__ == "__main__":
    main()
