"""
Generate the Word report for submission.

    python scripts/build_report.py

Produces docs/Project_Report.docx containing the architecture diagrams, the
install and run instructions, and the real captured output from
samples/output/ - so the figures in the document always match what the code
actually produced.

Screenshots are the one thing this cannot generate. Every place one belongs
is a clearly marked, empty placeholder: click it, paste, and the caption is
already written.
"""
import re
import sys
from datetime import date
from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Inches, Pt, RGBColor

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

SAMPLES = ROOT / "samples" / "output"
DOCS = ROOT / "docs"
GREY = RGBColor(0x66, 0x66, 0x66)
ACCENT = RGBColor(0x1F, 0x38, 0x64)

# Each screenshot the report expects, with the caption already written.
SCREENSHOTS = [
    ("The orchestration webhook running",
     "Terminal 1, after `python -m orchestrator.webhook_service`. This is "
     "Layer 2 serving the routing decisions the robot acts on."),
    ("Scenario 1 - resolved automatically",
     "`python demo.py`. High confidence and a routine request, so the robot "
     "reads the order and answers with no human involved."),
    ("Scenario 3 - confident, and still escalated",
     "The classifier is 0.99 sure this is a refund. It escalates anyway, "
     "because Rs 72,990 is above the Rs 10,000 sensitivity cap. Confidence "
     "alone never decides."),
    ("The escalation queue as an agent receives it",
     "`python demo.py --queue`. The agent is handed intent, confidence, the "
     "reason for escalation and a recommended action - a decision to review, "
     "not a transcript to investigate."),
    ("Live, unscripted input",
     "`python demo.py --interactive`, with messages typed during the "
     "demonstration rather than from the script."),
    ("Voice input and digit recovery",
     "`python demo.py --voice`. The recogniser returns words; the line "
     "beneath shows the spoken digits converted back to the order number "
     "the CRM needs."),
    ("The UiPath workflow in Studio",
     "uipath/Main.xaml. The robot asks for the message, calls the "
     "orchestration webhook, reads the decision and branches on it."),
    ("UiPath - the AI decision received by the robot",
     "The message box raised by the running robot, showing the intent, "
     "confidence, route and reason returned by Layer 2."),
    ("UiPath - the escalation branch",
     "The same workflow taking the other path, with the suggested "
     "resolution the human agent will receive."),
    ("The order database after the run",
     "data/MockCRM_ApplianceOrders.xlsx, Orders sheet. The refunded order "
     "now reads 'Refund Initiated' and its refund eligibility has been "
     "cleared, so the same refund cannot be run twice."),
    ("The audit log",
     "AuditLog sheet. One row per automated resolution, recording the "
     "confidence that produced it."),
    ("The escalation queue",
     "EscalationQueue sheet. One row per handoff, carrying the context "
     "packet and the case reference given to the customer."),
]


def _read(name, limit=None):
    path = SAMPLES / name
    if not path.exists():
        return f"[{name} not found - run python scripts/build_submission_samples.py]"
    text = path.read_text(encoding="utf-8")
    if limit:
        lines = text.splitlines()
        if len(lines) > limit:
            text = "\n".join(lines[:limit]) + f"\n... ({len(lines) - limit} more lines)"
    return text


def code_block(document, text, size=7.5):
    """Captured terminal output, kept monospaced so columns line up."""
    paragraph = document.add_paragraph()
    paragraph.paragraph_format.space_after = Pt(10)
    paragraph.paragraph_format.left_indent = Inches(0.15)
    run = paragraph.add_run(text.rstrip())
    run.font.name = "Consolas"
    run.font.size = Pt(size)
    return paragraph


def note(document, text):
    paragraph = document.add_paragraph()
    run = paragraph.add_run(text)
    run.italic = True
    run.font.size = Pt(9)
    run.font.color.rgb = GREY
    return paragraph


def screenshot_slot(document, index, title, caption):
    document.add_heading(f"Figure {index}: {title}", level=2)
    placeholder = document.add_paragraph()
    placeholder.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = placeholder.add_run(
        "\n\n[  PASTE SCREENSHOT HERE  ]\n\n"
    )
    run.bold = True
    run.font.size = Pt(11)
    run.font.color.rgb = GREY
    note(document, caption)


def main():
    document = Document()

    for section in document.sections:
        section.left_margin = section.right_margin = Inches(0.9)

    # -- title page ---------------------------------------------------------
    title = document.add_heading("Beyond FAQs", level=0)
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    subtitle = document.add_paragraph()
    subtitle.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = subtitle.add_run(
        "Combining RPA Workflow with Conversational AI\n"
        "for customer service that resolves, not just replies"
    )
    run.bold = True
    run.font.size = Pt(13)
    run.font.color.rgb = ACCENT

    meta = document.add_paragraph()
    meta.alignment = WD_ALIGN_PARAGRAPH.CENTER
    meta_run = meta.add_run(
        "\n\nTeam members: ______________________________\n"
        "Registration numbers: ______________________\n"
        "Course / Slot: _____________________________\n"
        "Guide: _____________________________________\n\n"
        f"Submitted: {date.today():%d %B %Y}"
    )
    meta_run.font.size = Pt(11)
    note(document, "Fill in the blanks above before submitting.")
    document.add_page_break()

    # -- overview -----------------------------------------------------------
    document.add_heading("1. Overview", level=1)
    document.add_paragraph(
        "Conversational AI understands language but stops at retrieving an "
        "answer; RPA executes backend tasks but cannot interpret a free-text "
        "request. This project joins the two, so a customer's message is "
        "understood, acted on, and either resolved automatically or handed "
        "to a person with the reasoning already done."
    )
    document.add_paragraph(
        "The domain is scoped to five appliance categories - Television, "
        "Washing Machine, Mixer Grinder, Refrigerator and Air Conditioner - "
        "over a mock CRM of 21 orders, so the system can be finished and "
        "evaluated rather than left broadly half-built."
    )

    document.add_heading("Key results", level=2)
    for line in [
        "88% intent-classification accuracy on a held-out validation set",
        "Confidence threshold of 0.55, derived by sweeping a stated safety "
        "policy rather than assumed",
        "Five intents handled end to end; three automated, two escalated by "
        "policy",
        "40 automated tests, one per claim the project makes",
        "Offline throughout: no network needed for speech, classification, "
        "routing or execution",
    ]:
        document.add_paragraph(line, style="List Bullet")

    # -- architecture -------------------------------------------------------
    document.add_heading("2. System architecture", level=1)
    document.add_paragraph(
        "Four layers. Each is swappable without touching the others - the "
        "NLU layer already demonstrates this, with a cloud engine and an "
        "offline one behind one contract."
    )
    diagram = DOCS / "architecture_block_diagram.png"
    if diagram.exists():
        document.add_picture(str(diagram), width=Inches(6.4))
        document.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.CENTER
        note(document, "Figure A: System block diagram - understand, decide, act.")

    document.add_heading("Routing rules", level=2)
    document.add_paragraph(
        "Applied in this order. Confidence is checked first on purpose: an "
        "entity extracted from a message the system did not understand is "
        "not evidence."
    )
    for rule in [
        "No intent, or confidence below the engine's threshold -> escalate",
        "Intent is a complaint, or an explicit request for a human -> escalate",
        "A required entity is missing -> ask a follow-up question",
        "Amount exceeds the Rs 10,000 sensitivity cap -> escalate",
        "Otherwise -> automate",
    ]:
        document.add_paragraph(rule, style="List Number")

    document.add_page_break()
    document.add_heading("3. The UiPath robot", level=1)
    workflow = DOCS / "uipath_workflow_diagram.png"
    if workflow.exists():
        document.add_picture(str(workflow), width=Inches(6.0))
        document.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.CENTER
        note(document, "Figure B: The robot, activity by activity.")

    # -- install and run ----------------------------------------------------
    document.add_page_break()
    document.add_heading("4. What to install and how to run", level=1)
    document.add_paragraph(
        "Full instructions are in README.md. The essentials:"
    )

    document.add_heading("Requirements", level=2)
    code_block(document, """\
Python 3.9 or newer
pip install -r requirements.txt          (Flask, openpyxl)

Optional - voice input:
    pip install vosk sounddevice
    python scripts/download_vosk_model.py

Optional - the UiPath robot:
    UiPath Studio, with UiPath.System.Activities
    and UiPath.WebAPI.Activities installed""", size=9)

    document.add_heading("Running it", level=2)
    code_block(document, """\
python scripts/build_mock_crm.py     Create the mock CRM workbook (once)

python demo.py                       The six scripted scenarios
python demo.py --queue               The escalation queue, as an agent sees it
python demo.py --interactive         Type your own messages
python demo.py --voice               Speak instead of typing
python demo.py --reset               Restore the CRM to its starting state

python -m unittest discover -s tests Run the 40 tests
python -m nlu.evaluate               Threshold sweep and accuracy

python -m orchestrator.webhook_service   Start Layer 2 (needed by UiPath)""", size=9)
    note(document, "Close the workbook in Excel before running anything - "
                   "Excel holds an exclusive lock and every write will fail.")

    # -- results ------------------------------------------------------------
    document.add_page_break()
    document.add_heading("5. Results", level=1)

    document.add_heading("5.1 Classifier evaluation", level=2)
    document.add_paragraph(
        "The threshold is measured, not assumed. Every candidate value is "
        "swept against a held-out set under a stated policy: maximise "
        "automation subject to at least 95% precision and zero out-of-scope "
        "messages automated."
    )
    code_block(document, _read("classifier_evaluation.txt"))

    document.add_heading("5.2 Test suite", level=2)
    code_block(document, _read("test_results.txt"), size=9)

    document.add_page_break()
    document.add_heading("5.3 End-to-end run", level=2)
    document.add_paragraph(
        "Captured from `python demo.py`. Each scenario shows the decision "
        "made at every layer, so the routing can be followed rather than "
        "taken on trust."
    )
    code_block(document, _read("demo_run.txt", limit=120))

    document.add_page_break()
    document.add_heading("5.4 The escalation context packet", level=2)
    document.add_paragraph(
        "What a human agent receives. This is the project's central claim "
        "made concrete: the agent reviews a decision that has already been "
        "reasoned through, with the evidence attached."
    )
    code_block(document, _read("escalation_queue_view.txt", limit=45))

    # -- screenshots --------------------------------------------------------
    document.add_page_break()
    document.add_heading("6. Screenshots", level=1)
    note(document, "Paste each screenshot into the marked space below its "
                   "heading. The captions are already written.")
    for index, (heading, caption) in enumerate(SCREENSHOTS, start=1):
        screenshot_slot(document, index, heading, caption)

    # -- limitations --------------------------------------------------------
    document.add_page_break()
    document.add_heading("7. Honest status and limitations", level=1)
    document.add_paragraph(
        "Stated plainly, because a prototype that overstates itself is "
        "harder to defend than one that does not."
    )
    for item in [
        "The Dialogflow agent is implemented but not provisioned; "
        "nlu/dialogflow_setup.py creates it from the same training data in "
        "one command. The offline classifier runs in its place, and both "
        "return an identical contract.",
        "The UiPath robot receives the routing decision and acts on it, but "
        "is triggered by a Studio run rather than an Orchestrator job - a "
        "deployment difference, not an architectural one.",
        "The CRM is an Excel workbook behind a REST-style wrapper, so "
        "pointing the system at a real CRM API is a configuration change "
        "rather than a rebuild.",
        "Speech recognition accuracy depends on the microphone and the "
        "room. Recognition is constrained to the project's vocabulary to "
        "protect order numbers, which are the field everything downstream "
        "depends on.",
    ]:
        document.add_paragraph(item, style="List Bullet")

    output = DOCS / "Project_Report.docx"
    document.save(str(output))
    print(f"Written: {output.relative_to(ROOT)}")
    print(f"  {len(SCREENSHOTS)} screenshot placeholders")
    print("  Diagrams and captured output embedded")


if __name__ == "__main__":
    main()
