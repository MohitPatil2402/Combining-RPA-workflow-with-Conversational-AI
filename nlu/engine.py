"""
Picks which NLU engine answers, so nothing downstream has to care.

config.NLU_ENGINE controls it:

    auto        use Dialogflow when it is configured and reachable, and fall
                back to the local classifier when it is not. This is the
                default, and it is what keeps the demo alive when the wifi
                is not.
    dialogflow  Dialogflow only. Errors instead of silently falling back,
                which is what you want when you are specifically testing the
                real agent.
    local       the built-in classifier only.

The fallback is deliberately loud in the returned payload: every response
carries the engine that produced it, and a fallback carries the reason too,
so a demo never silently stops exercising the thing you meant to show.
"""
import config
from nlu import dialogflow_client, local_classifier


def detect_intent(text, session_id=None):
    mode = config.NLU_ENGINE

    if mode == "local":
        return local_classifier.detect_intent(text)

    if mode == "dialogflow":
        return dialogflow_client.detect_intent(text, session_id=session_id)

    # auto
    available, reason = dialogflow_client.availability()
    if available:
        try:
            return dialogflow_client.detect_intent(text, session_id=session_id)
        except Exception as exc:
            result = local_classifier.detect_intent(text)
            result["engine_fallback_from"] = "dialogflow"
            result["engine_fallback_reason"] = str(exc)
            return result

    result = local_classifier.detect_intent(text)
    result["engine_fallback_from"] = "dialogflow"
    result["engine_fallback_reason"] = reason
    return result


def active_engine_description():
    """A one-line summary of which engine is live, for startup banners."""
    mode = config.NLU_ENGINE
    if mode == "local":
        return "local classifier (forced by NLU_ENGINE=local)"
    available, reason = dialogflow_client.availability()
    if mode == "dialogflow":
        return ("Dialogflow ES" if available
                else f"Dialogflow ES - NOT READY: {reason}")
    return ("Dialogflow ES (auto)" if available
            else f"local classifier (auto; Dialogflow unavailable: {reason})")
