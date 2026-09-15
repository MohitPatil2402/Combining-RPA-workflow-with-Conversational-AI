"""
Layer 1, online: Dialogflow ES.

Returns exactly the same contract as nlu.local_classifier.detect_intent, so
Layer 2 never learns which engine answered. That interchangeability is the
point - the NLU layer is meant to be swappable without touching orchestration
or RPA.

Requires:
    pip install google-cloud-dialogflow
    set GOOGLE_APPLICATION_CREDENTIALS to your service-account JSON key
    set DIALOGFLOW_PROJECT_ID to your agent's GCP project id
"""
import os
import uuid
from pathlib import Path

import config


class DialogflowUnavailable(RuntimeError):
    """Dialogflow is not configured or not reachable."""


def availability():
    """Return (is_available, reason). Never raises, so callers can branch."""
    try:
        from google.cloud import dialogflow  # noqa: F401
    except ImportError:
        return False, ("the google-cloud-dialogflow package is not installed "
                       "(pip install google-cloud-dialogflow)")

    if not config.DIALOGFLOW_PROJECT_ID:
        return False, "DIALOGFLOW_PROJECT_ID is not set"

    credentials = config.GOOGLE_APPLICATION_CREDENTIALS
    if not credentials:
        return False, "GOOGLE_APPLICATION_CREDENTIALS is not set"
    if not Path(credentials).exists():
        return False, f"credentials file not found: {credentials}"

    return True, "ready"


def is_available():
    return availability()[0]


def detect_intent(text, session_id=None):
    """Classify one message with the real Dialogflow agent."""
    available, reason = availability()
    if not available:
        raise DialogflowUnavailable(reason)

    from google.cloud import dialogflow

    os.environ.setdefault(
        "GOOGLE_APPLICATION_CREDENTIALS", config.GOOGLE_APPLICATION_CREDENTIALS
    )

    session_id = session_id or str(uuid.uuid4())
    client = dialogflow.SessionsClient()
    session = client.session_path(config.DIALOGFLOW_PROJECT_ID, session_id)

    query_input = dialogflow.QueryInput(
        text=dialogflow.TextInput(
            text=text, language_code=config.DIALOGFLOW_LANGUAGE
        )
    )
    response = client.detect_intent(
        request={"session": session, "query_input": query_input}
    )
    result = response.query_result

    # Dialogflow's own fallback intent means "I did not understand", which we
    # represent the same way the local engine does: no intent at all.
    intent_name = result.intent.display_name
    if result.intent.is_fallback or not intent_name:
        intent_name = None

    entities = {}
    for key, value in (result.parameters or {}).items():
        if value in ("", None, []):
            continue
        # Dialogflow returns numbers as floats; order ids read better as the
        # digit strings the CRM stores.
        if key == "order_id":
            entities[key] = str(int(value)) if isinstance(value, float) else str(value)
        else:
            entities[key] = value

    return {
        "text": text,
        "intent": intent_name,
        "confidence": round(float(result.intent_detection_confidence), 4),
        "entities": entities,
        "engine": "dialogflow",
        "fulfillment_text": result.fulfillment_text or "",
        "session_id": session_id,
    }
