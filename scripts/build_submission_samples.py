"""
Generate the sample input and output files for submission.

Everything in samples/output/ is captured from a real run rather than
pasted by hand, so it can be regenerated after any change and will never
drift from what the code actually does:

    python scripts/build_submission_samples.py

Inputs are the messages used to demonstrate the system; outputs are what it
produced from them, including the CRM sheets the robot wrote to.
"""
import csv
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import config  # noqa: E402

SAMPLES = ROOT / "samples"
INPUT_DIR = SAMPLES / "input"
OUTPUT_DIR = SAMPLES / "output"

# Terminal colour codes make the captured files unreadable in a document.
ANSI = re.compile(r"\x1b\[[0-9;]*m")

TYPED_MESSAGES = """\
# Sample customer messages - typed input.
# Each line is one message. Lines starting with # are notes, not input.
#
# Used with:  python demo.py --interactive
# and pasted one at a time.

# --- resolved automatically, no human involved ---
where is my order 4502
i want my money back for order 4509
change the delivery address for order 4503
88 Nehru Road, Pune 411001

# --- resolved automatically as a clear, explained "no" ---
refund my order 4511

# --- escalated to a human, each for a different reason ---
I want a refund for order 4516
my fridge is making a loud noise
connect me to an agent
Something's wrong with my stuff

# --- multi-turn: the system asks for what it needs ---
i want a refund
4510
"""

VOICE_SCRIPT = """\
# Sample spoken input - read these aloud.
#
# Used with:  python demo.py --voice
#
# Speech recognition returns words, not digits, so an order number is
# spoken digit by digit. voice/numbers.py converts it back before the
# classifier sees it - the demo prints both the raw transcript and the
# corrected one.

Where is my order four five two one
I want a refund for order four five one six
My washing machine arrived broken
Connect me to an agent
"""


def _run(args, label):
    """Run a project command and capture its output with colours stripped."""
    print(f"  {label}...")
    result = subprocess.run(
        [sys.executable] + args, cwd=ROOT,
        capture_output=True, text=True, timeout=300,
    )
    return ANSI.sub("", result.stdout + result.stderr)


def _write(path, text):
    path.write_text(text, encoding="utf-8")
    print(f"    -> {path.relative_to(ROOT)}  ({len(text):,} bytes)")


def _export_sheet(sheet_name, path):
    """Export a CRM sheet to CSV so it can be read without Excel."""
    from rpa import crm
    rows = crm.read_log(sheet_name)
    if not rows:
        _write(path, "")
        return
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(f"    -> {path.relative_to(ROOT)}  ({len(rows)} rows)")


def main():
    INPUT_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print("Inputs")
    _write(INPUT_DIR / "customer_messages.txt", TYPED_MESSAGES)
    _write(INPUT_DIR / "voice_script.txt", VOICE_SCRIPT)

    print("\nRunning the system to capture real output")
    _run(["demo.py", "--reset"], "resetting the CRM")

    demo_output = _run(["demo.py"], "six scripted scenarios")
    _write(OUTPUT_DIR / "demo_run.txt", demo_output)

    queue_output = _run(["demo.py", "--queue"], "escalation queue")
    _write(OUTPUT_DIR / "escalation_queue_view.txt", queue_output)

    evaluation = _run(["-m", "nlu.evaluate"], "classifier evaluation")
    _write(OUTPUT_DIR / "classifier_evaluation.txt", evaluation)

    tests = _run(["-m", "unittest", "discover", "-s", "tests", "-t", "."],
                 "test suite")
    _write(OUTPUT_DIR / "test_results.txt", tests)

    print("\nCRM sheets the robot wrote to")
    _export_sheet(config.SHEET_AUDIT, OUTPUT_DIR / "audit_log.csv")
    _export_sheet(config.SHEET_ESCALATION, OUTPUT_DIR / "escalation_queue.csv")

    print("\nWebhook response (what the UiPath robot receives)")
    from orchestrator.webhook_service import app
    client = app.test_client()
    examples = {}
    for label, message in [
        ("auto_resolve", "where is my order 4521"),
        ("escalate_sensitivity_cap", "I want a refund for order 4516"),
        ("need_info", "i want a refund"),
    ]:
        examples[label] = {
            "request": message,
            "response": client.post("/classify", json={"text": message}).get_json(),
        }
    _write(OUTPUT_DIR / "webhook_responses.json",
           json.dumps(examples, indent=2) + "\n")

    print("\nDone. Everything in samples/ is reproducible with this script.")


if __name__ == "__main__":
    main()
