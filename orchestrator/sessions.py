"""
Conversation state for multi-turn slot filling.

When a request is missing a required entity, the orchestrator asks a
follow-up question instead of failing outright. That only works if the next
message can be joined back to the request it belongs to, which is what this
store holds: per session, the intent we were part-way through and the
entities gathered so far.

Deliberately in-memory. A prototype restarting with an empty slot store is
correct behaviour, and swapping this for Redis later touches only this file.
"""
import threading
import time

# Abandoned conversations should not pin state forever.
SESSION_TTL_SECONDS = 15 * 60

_LOCK = threading.Lock()
_SESSIONS = {}


def _prune(now):
    stale = [
        key for key, value in _SESSIONS.items()
        if now - value["updated_at"] > SESSION_TTL_SECONDS
    ]
    for key in stale:
        del _SESSIONS[key]


def get_pending(session_id):
    """Return the pending slot-fill for a session, or None."""
    if not session_id:
        return None
    now = time.time()
    with _LOCK:
        _prune(now)
        pending = _SESSIONS.get(session_id)
        return dict(pending) if pending else None


def set_pending(session_id, intent, entities, missing_entity):
    """Remember that we are waiting on one entity for this session."""
    if not session_id:
        return
    with _LOCK:
        _SESSIONS[session_id] = {
            "intent": intent,
            "entities": dict(entities or {}),
            "missing_entity": missing_entity,
            "updated_at": time.time(),
        }


def clear(session_id):
    if not session_id:
        return
    with _LOCK:
        _SESSIONS.pop(session_id, None)


def clear_all():
    """Reset every session. Used by the tests and between demo runs."""
    with _LOCK:
        _SESSIONS.clear()
