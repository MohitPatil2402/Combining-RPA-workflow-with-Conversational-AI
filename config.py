"""
Central configuration for the RPA + Conversational AI prototype.

Every value can be overridden with an environment variable, so the same code
runs on a laptop, in a demo, or pointed at a real Dialogflow agent without
editing source. This is the "loosely coupled layers" design principle from
the architecture slide made concrete.
"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent


def _env_float(name, default):
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _env_int(name, default):
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


# --------------------------------------------------------------------------
# Layer 1 - NLU
# --------------------------------------------------------------------------
# Which NLU engine Layer 2 should ask. "auto" uses Dialogflow when credentials
# are present and falls back to the built-in local classifier otherwise.
#   auto | dialogflow | local
NLU_ENGINE = os.environ.get("NLU_ENGINE", "auto").strip().lower()

# Google Cloud / Dialogflow ES settings (only needed for the dialogflow engine)
DIALOGFLOW_PROJECT_ID = os.environ.get("DIALOGFLOW_PROJECT_ID", "").strip()
DIALOGFLOW_LANGUAGE = os.environ.get("DIALOGFLOW_LANGUAGE", "en").strip()
GOOGLE_APPLICATION_CREDENTIALS = os.environ.get(
    "GOOGLE_APPLICATION_CREDENTIALS", ""
).strip()

# --------------------------------------------------------------------------
# Layer 2 - Orchestration / routing rules
# --------------------------------------------------------------------------
# Confidence thresholds are a property of the *engine*, not of the project:
# two classifiers can both be right and still spread their scores completely
# differently, so a single shared number would be meaningless. Each engine
# therefore gets its own, derived from its own measurements.
#
# LOCAL: 0.55 is not a guess. `python -m nlu.evaluate` sweeps every threshold
# against the held-out validation set and picks the one that automates the
# most while keeping automation precision >= 95% with zero out-of-scope
# messages automated. At the time of writing that sweep reported:
#     0.55 -> automates 62% of requests at 96.8% precision
#     0.80 -> automates 40% of requests at 100% precision
# The extra 22% of automation costs one borderline misroute that escalation
# would have caught anyway. Re-run the sweep after any retraining.
CONFIDENCE_THRESHOLD_LOCAL = _env_float("CONFIDENCE_THRESHOLD_LOCAL", 0.55)

# DIALOGFLOW: still the conventional 0.80 placeholder. Dialogflow scores are
# calibrated differently from ours, so this number is NOT transferable from
# the local sweep above - it has to be re-derived against the real agent once
# it is trained. Until then, treat it as provisional.
CONFIDENCE_THRESHOLD_DIALOGFLOW = _env_float("CONFIDENCE_THRESHOLD_DIALOGFLOW", 0.80)


def threshold_for(engine):
    """The automation threshold that applies to a given NLU engine."""
    if engine == "dialogflow":
        return CONFIDENCE_THRESHOLD_DIALOGFLOW
    return CONFIDENCE_THRESHOLD_LOCAL


# Money above this amount (INR) always goes to a human, however confident
# the classifier is. This is the "sensitivity cap" from the routing rules.
SENSITIVITY_CAP_INR = _env_float("SENSITIVITY_CAP_INR", 10000.0)

# Intents that are never automated, regardless of confidence or amount.
ALWAYS_ESCALATE_INTENTS = {
    "order.complaint",
    "agent.escalation_request",
}

# --------------------------------------------------------------------------
# Layer 3 - RPA execution / mock CRM
# --------------------------------------------------------------------------
CRM_WORKBOOK = Path(
    os.environ.get(
        "CRM_WORKBOOK", str(BASE_DIR / "data" / "MockCRM_ApplianceOrders.xlsx")
    )
)
SHEET_ORDERS = "Orders"
SHEET_AUDIT = "AuditLog"
SHEET_ESCALATION = "EscalationQueue"

# The five appliance categories this prototype is scoped to.
CATEGORIES = [
    "Television",
    "Washing Machine",
    "Mixer Grinder",
    "Refrigerator",
    "Air Conditioner",
]

# --------------------------------------------------------------------------
# Webhook service
# --------------------------------------------------------------------------
WEBHOOK_HOST = os.environ.get("WEBHOOK_HOST", "127.0.0.1")
WEBHOOK_PORT = _env_int("WEBHOOK_PORT", 5000)
