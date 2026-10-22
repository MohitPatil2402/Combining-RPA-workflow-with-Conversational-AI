"""
The demo driver.

Runs the scripted scenarios end to end and shows what each layer decided, so
the confidence routing is visible on screen rather than something you have to
promise is happening.

    python demo.py                  # the full scripted run
    python demo.py --interactive    # type your own messages
    python demo.py --voice          # speak instead of typing
    python demo.py --audio clip.wav # transcribe a recording and run it
    python demo.py --reset          # restore the CRM to its starting state

Run --reset between rehearsals. The robot really does write to the workbook,
so a rehearsed refund will already be spent by the time you present.
"""
import argparse
import subprocess
import sys

import config
from nlu import engine
from orchestrator import pipeline, routing, sessions
from rpa import crm

BOLD, DIM, RESET = "\033[1m", "\033[2m", "\033[0m"
GREEN, YELLOW, RED, BLUE = "\033[32m", "\033[33m", "\033[31m", "\033[36m"

ROUTE_COLOURS = {
    routing.AUTO_RESOLVE: GREEN,
    routing.NEED_INFO: YELLOW,
    routing.ESCALATE: RED,
}

# Each scenario names what it is meant to prove, so the demo narrates itself.
SCENARIOS = [
    ("Straightforward request, handled start to finish",
     "The classifier is confident and the request is routine, so the robot "
     "reads the order and answers. No human involved.",
     [("Where is my order #4521?", "demo-1")]),

    ("Vague message - the system knows that it does not know",
     "Nothing here identifies a request. Rather than guessing at an intent, "
     "confidence falls below the threshold and it goes to a person.",
     [("Something's wrong with my stuff", "demo-2")]),

    ("Confident AND still escalated - the sensitivity cap",
     "The classifier is sure this is a refund. It is escalated anyway, "
     "because the amount is above the authorisation cap. Confidence alone "
     "never decides.",
     [("I want a refund for order 4516", "demo-3")]),

    ("A refund the robot can complete",
     "Same intent as the previous case, but within the cap and eligible, so "
     "the robot updates the database and issues a reference number.",
     [("i want my money back for order 4521", "demo-4")]),

    ("Missing information - ask, do not fail",
     "No order number, so the system asks for one and then completes the "
     "original request with the answer.",
     [("i want a refund", "demo-5"),
      ("4509", "demo-5")]),

    ("A complaint - escalated on policy, not on confidence",
     "The classifier is confident this is a complaint. Complaints are never "
     "automated, whatever the score.",
     [("my washing machine arrived broken and it wont start", "demo-6")]),
]


def _c(text, colour):
    return f"{colour}{text}{RESET}"


def show_turn(message, result):
    decision, outcome = result["decision"], result["outcome"]
    route = decision["route"]
    colour = ROUTE_COLOURS.get(route, "")

    print(f"  {_c('Customer', BOLD)}  {message}")
    print()
    print(f"    {DIM}Layer 1  NLU{RESET}          "
          f"intent={decision.get('intent') or '(none)'}  "
          f"confidence={decision.get('confidence', 0):.2f}  "
          f"engine={decision.get('engine')}")

    entities = decision.get("entities") or {}
    if entities:
        rendered = ", ".join(f"{k}={v}" for k, v in entities.items())
        print(f"    {DIM}         entities{RESET}     {rendered}")

    print(f"    {DIM}Layer 2  Routing{RESET}      "
          f"{_c(route, colour)}  ({decision.get('reason')})")
    print(f"    {DIM}         because{RESET}      {decision.get('reason_detail')}")

    if route == routing.AUTO_RESOLVE:
        print(f"    {DIM}Layer 3  Robot{RESET}        "
              f"{outcome.get('action')} -> {outcome.get('result')}")
        if outcome.get("reference_no"):
            print(f"    {DIM}         reference{RESET}    "
                  f"{_c(outcome['reference_no'], BOLD)}")
    elif route == routing.ESCALATE:
        print(f"    {DIM}Layer 3  Robot{RESET}        "
              f"queued in {config.SHEET_ESCALATION} for a human")
        suggestion = decision.get("suggested_resolution", "")
        if suggestion:
            print(f"    {DIM}         packet{RESET}       "
                  f"{_c('agent sees:', YELLOW)} {suggestion[:150]}"
                  f"{'...' if len(suggestion) > 150 else ''}")

    print()
    print(f"  {_c('Bot', BOLD)}       {outcome.get('reply')}")


def run_scripted():
    print()
    print("=" * 78)
    print(f"  {BOLD}RPA + Conversational AI - customer service that resolves{RESET}")
    print("=" * 78)
    print(f"  NLU engine      : {engine.active_engine_description()}")
    print(f"  Threshold       : {config.threshold_for('local')} "
          f"(derived in nlu/evaluate.py, not guessed)")
    print(f"  Sensitivity cap : Rs {config.SENSITIVITY_CAP_INR:,.0f}")
    print(f"  Mock CRM        : {config.CRM_WORKBOOK.name}")
    print("=" * 78)

    for index, (title, rationale, turns) in enumerate(SCENARIOS, start=1):
        print()
        print(f"{BLUE}{'-' * 78}{RESET}")
        print(f"{BLUE}  SCENARIO {index}: {title}{RESET}")
        print(f"{BLUE}{'-' * 78}{RESET}")
        print(f"  {DIM}{rationale}{RESET}")
        print()
        for message, session_id in turns:
            result = pipeline.handle_message(message, session_id=session_id)
            show_turn(message, result)
            print()

    summarise()


def summarise():
    print()
    print("=" * 78)
    print(f"  {BOLD}WHAT THE ROBOT LEFT BEHIND{RESET}")
    print("=" * 78)

    audit = crm.read_log(config.SHEET_AUDIT)
    escalations = crm.read_log(config.SHEET_ESCALATION)

    print(f"\n  {config.SHEET_AUDIT} - {len(audit)} case(s) resolved automatically")
    for row in audit:
        print(f"    {row['Timestamp']}  order {row['OrderID'] or '-':<6} "
              f"{str(row['Intent']):<22} conf={row['Confidence']}  "
              f"{row['Action']:<16} {row['ReferenceNo'] or '-'}")

    print(f"\n  {config.SHEET_ESCALATION} - {len(escalations)} case(s) sent to a human")
    for row in escalations:
        print(f"    {row['Timestamp']}  order {row['OrderID'] or '-':<6} "
              f"{str(row['Intent']):<22} conf={row['Confidence']}  "
              f"{row['Reason']}")

    total = len(audit) + len(escalations)
    if total:
        print(f"\n  {len(audit)}/{total} resolved without a human "
              f"({len(audit) / total:.0%}); every remaining case arrived with "
              f"a context packet, not a blank ticket.")
    print()


def show_transcript(result):
    """Print what was heard, and what it became.

    The raw line shows the recogniser's actual output, mangled digits and
    all; the second shows the recovery. Hiding the first would make the
    system look luckier than it is.
    """
    raw, text = result.get("raw", ""), result.get("text", "")
    print(f"    {DIM}Layer 0  Speech{RESET}       "
          f"{result.get('source')}  ({result.get('audio_format')}"
          f"{', grammar-constrained' if result.get('grammar') else ''})")
    print(f'    {DIM}         heard{RESET}         "{raw}"')
    if text != raw:
        print(f"    {DIM}         digits fixed{RESET}  {_c(chr(34) + text + chr(34), BOLD)}")
    print()


def _voice_or_explain():
    from voice import transcribe
    available, reason = transcribe.availability()
    if not available:
        print(f"\n  Voice input is not ready: {reason}\n")
        return None
    return transcribe


def run_voice():
    """Speak a message instead of typing it."""
    transcribe = _voice_or_explain()
    if transcribe is None:
        return

    print()
    print(f"Voice mode. Press Enter to speak for "
          f"{config.VOICE_RECORD_SECONDS} seconds, or 'quit' to exit.")
    print(f"NLU engine: {engine.active_engine_description()}\n")

    session_id = "voice"
    while True:
        try:
            command = input("Press Enter to speak> ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if command in {"quit", "exit"}:
            return
        if command == "reset":
            sessions.clear(session_id)
            print("  (conversation cleared)\n")
            continue

        try:
            result = transcribe.transcribe_microphone(
                seconds=config.VOICE_RECORD_SECONDS,
                use_grammar=config.VOICE_USE_GRAMMAR,
                on_start=lambda s: print(f"  {_c('listening...', YELLOW)} ({s}s)"),
            )
        except Exception as exc:
            print(f"  Could not record: {exc}\n")
            continue

        print()
        show_transcript(result)
        if not result["text"]:
            print("  Nothing was recognised. Try again, closer to the mic.\n")
            continue
        show_turn(result["text"],
                  pipeline.handle_message(result["text"], session_id=session_id))
        print()


def run_audio(path):
    """Transcribe one WAV file and run it through the system."""
    transcribe = _voice_or_explain()
    if transcribe is None:
        return
    try:
        result = transcribe.transcribe_file(
            path, use_grammar=config.VOICE_USE_GRAMMAR)
    except Exception as exc:
        print(f"\n  Could not transcribe {path}: {exc}\n")
        return
    print()
    show_transcript(result)
    if not result["text"]:
        print("  Nothing was recognised in that file.\n")
        return
    show_turn(result["text"],
              pipeline.handle_message(result["text"], session_id="audio"))
    print()


def run_interactive():
    print()
    print("Type a customer message. 'reset' clears the conversation, "
          "'quit' exits.")
    print(f"NLU engine: {engine.active_engine_description()}\n")
    session_id = "interactive"
    while True:
        try:
            message = input("Customer> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if not message:
            continue
        if message.lower() in {"quit", "exit"}:
            return
        if message.lower() == "reset":
            sessions.clear(session_id)
            print("  (conversation cleared)\n")
            continue
        print()
        show_turn(message, pipeline.handle_message(message, session_id=session_id))
        print()


def reset_crm():
    subprocess.run([sys.executable, "scripts/build_mock_crm.py"], check=True)
    sessions.clear_all()
    print("CRM restored to its starting state. Ready for a clean run.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--interactive", action="store_true",
                        help="type your own messages")
    parser.add_argument("--voice", action="store_true",
                        help="speak your messages (needs vosk + a model)")
    parser.add_argument("--audio", metavar="WAV",
                        help="transcribe a WAV file and run it")
    parser.add_argument("--reset", action="store_true",
                        help="restore the CRM workbook and exit")
    args = parser.parse_args()

    if args.reset:
        reset_crm()
    elif args.audio:
        run_audio(args.audio)
    elif args.voice:
        run_voice()
    elif args.interactive:
        run_interactive()
    else:
        run_scripted()


if __name__ == "__main__":
    main()
