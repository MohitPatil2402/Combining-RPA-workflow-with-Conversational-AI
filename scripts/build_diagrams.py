"""
Generate the block diagrams as SVG.


Two diagrams:
  docs/architecture_block_diagram.svg  - the three-layer system, for the
                                         report and the deck
  docs/uipath_workflow_diagram.svg     - the activity-by-activity flow of
                                         the UiPath robot, which doubles as
                                         the build map for Studio

SVG so they stay sharp at any size. PowerPoint and Word both insert SVG
directly (Insert > Pictures), and scripts/render_diagrams.py makes PNGs if
you need them.

    python scripts/build_diagrams.py
"""
from pathlib import Path

DOCS = Path(__file__).resolve().parent.parent / "docs"

INK = "#16191d"
MUTED = "#5b6470"
BORDER = "#c9d0da"
PANEL = "#f6f8fa"
WHITE = "#ffffff"

L1 = "#2563eb"   # NLU
L2 = "#7c3aed"   # orchestration
L3 = "#0f9d58"   # RPA
RED = "#d93025"  # escalate
AMBER = "#e37400"  # need info
SLATE = "#475569"

FONT = ("-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, "
        "'Helvetica Neue', Arial, sans-serif")
MONO = "'SF Mono', Menlo, Consolas, 'Liberation Mono', monospace"


def esc(text):
    return (str(text).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;"))


class Canvas:
    def __init__(self, width, height, title):
        self.width, self.height, self.title = width, height, title
        self.parts = []

    def rect(self, x, y, w, h, fill=WHITE, stroke=BORDER, rx=8, sw=1.5,
             dash=None):
        dash_attr = f' stroke-dasharray="{dash}"' if dash else ""
        self.parts.append(
            f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" '
            f'fill="{fill}" stroke="{stroke}" stroke-width="{sw}"{dash_attr}/>'
        )

    def band(self, x, y, w, h, colour, rx=8):
        """A coloured spine down the left edge of a panel."""
        self.parts.append(
            f'<path d="M{x + rx} {y} h-{rx - 4} a{rx - 4} {rx - 4} 0 0 0 '
            f'-{rx - 4} {rx - 4} v{h - 2 * (rx - 4)} a{rx - 4} {rx - 4} 0 0 0 '
            f'{rx - 4} {rx - 4} h{rx - 4} z" fill="{colour}"/>'
        )
        self.parts.append(
            f'<rect x="{x}" y="{y}" width="5" height="{h}" fill="{colour}"/>'
        )

    def text(self, x, y, content, size=13, fill=INK, weight="400",
             anchor="start", font=None, spacing=None, opacity=1):
        extra = f' letter-spacing="{spacing}"' if spacing else ""
        op = f' opacity="{opacity}"' if opacity != 1 else ""
        self.parts.append(
            f'<text x="{x}" y="{y}" font-family="{font or FONT}" '
            f'font-size="{size}" fill="{fill}" font-weight="{weight}" '
            f'text-anchor="{anchor}"{extra}{op}>{esc(content)}</text>'
        )

    def arrow(self, x1, y1, x2, y2, colour=SLATE, sw=2, dash=None):
        dash_attr = f' stroke-dasharray="{dash}"' if dash else ""
        self.parts.append(
            f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{colour}" '
            f'stroke-width="{sw}" marker-end="url(#arrow-{colour[1:]})"'
            f'{dash_attr}/>'
        )
        self._marker(colour)

    def elbow(self, x1, y1, x2, y2, colour=SLATE, sw=2):
        """Down, across, then down again - for branch fan-outs."""
        mid = (y1 + y2) / 2
        self.parts.append(
            f'<path d="M{x1} {y1} V{mid} H{x2} V{y2}" fill="none" '
            f'stroke="{colour}" stroke-width="{sw}" '
            f'marker-end="url(#arrow-{colour[1:]})"/>'
        )
        self._marker(colour)

    def _marker(self, colour):
        key = f"marker:{colour}"
        if key in getattr(self, "_markers", set()):
            return
        self._markers = getattr(self, "_markers", set()) | {key}
        self.defs = getattr(self, "defs", [])
        self.defs.append(
            f'<marker id="arrow-{colour[1:]}" viewBox="0 0 10 10" refX="9" '
            f'refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">'
            f'<path d="M0 0 L10 5 L0 10 z" fill="{colour}"/></marker>'
        )

    def render(self):
        defs = "".join(getattr(self, "defs", []))
        body = "\n  ".join(self.parts)
        return (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{self.width}" '
            f'height="{self.height}" viewBox="0 0 {self.width} {self.height}" '
            f'font-family="{FONT}">\n'
            f'  <title>{esc(self.title)}</title>\n'
            f'  <defs>{defs}</defs>\n'
            f'  <rect width="{self.width}" height="{self.height}" fill="{WHITE}"/>\n'
            f'  {body}\n</svg>\n'
        )

    def save(self, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.render(), encoding="utf-8")
        return path


# ---------------------------------------------------------------------------
# Diagram 1 - the three-layer system
# ---------------------------------------------------------------------------
def build_architecture():
    c = Canvas(1040, 1165, "System block diagram")

    c.text(60, 46, "Beyond FAQs — RPA + Conversational AI", size=21,
           weight="700")
    c.text(60, 72, "System block diagram: understand, decide, act",
           size=13.5, fill=MUTED)

    # -- customer -----------------------------------------------------------
    c.rect(370, 100, 300, 52, fill=PANEL, stroke=BORDER)
    c.text(520, 124, "CUSTOMER MESSAGE", size=11, weight="700", anchor="middle",
           fill=MUTED, spacing="1.1")
    c.text(520, 142, "free text, typos and code-mixing included", size=11.5,
           anchor="middle", fill=MUTED)
    c.arrow(520, 152, 520, 182)

    # -- layer 1 ------------------------------------------------------------
    c.rect(60, 186, 920, 190, fill=WHITE, stroke=BORDER)
    c.band(60, 186, 920, 190, L1)
    c.text(88, 212, "LAYER 1 · CONVERSATIONAL INTERFACE", size=11.5,
           weight="700", fill=L1, spacing="1.1")
    c.text(88, 234, "Two interchangeable engines returning an identical "
                    "contract — the layer is swappable.", size=12.5, fill=MUTED)

    c.rect(90, 248, 410, 58, fill=PANEL)
    c.text(110, 272, "Dialogflow ES", size=13.5, weight="600")
    c.text(110, 292, "cloud NLU agent · 5 intents · 159 phrases", size=11.5,
           fill=MUTED)

    c.rect(540, 248, 410, 58, fill=PANEL)
    c.text(560, 272, "Local TF-IDF classifier", size=13.5, weight="600")
    c.text(560, 292, "offline fallback · no GCP or network needed", size=11.5,
           fill=MUTED)

    c.rect(90, 318, 860, 40, fill=WHITE, stroke=L1, dash="5 4")
    c.text(110, 343, "OUTPUT   intent  ·  entities (order_id, amount, "
                     "category)  ·  confidence score", size=12.5, font=MONO,
           fill=L1)
    c.arrow(520, 376, 520, 406)

    # -- layer 2 ------------------------------------------------------------
    c.rect(60, 410, 920, 212, fill=WHITE, stroke=BORDER)
    c.band(60, 410, 920, 212, L2)
    c.text(88, 436, "LAYER 2 · ORCHESTRATION LOGIC", size=11.5, weight="700",
           fill=L2, spacing="1.1")
    c.text(88, 458, "Five rules, applied in order. Confidence is checked "
                    "first — an entity from a message we did not understand "
                    "is not evidence.", size=12.5, fill=MUTED)

    rules = [
        ("1", "No intent, or confidence below the engine threshold", "escalate"),
        ("2", "Intent is a complaint, or an explicit request for a human",
         "escalate"),
        ("3", "A required entity is missing", "ask a follow-up"),
        ("4", "Amount exceeds the ₹10,000 sensitivity cap", "escalate"),
        ("5", "Otherwise", "automate"),
    ]
    y = 476
    for number, rule, outcome in rules:
        c.rect(90, y, 860, 26, fill=PANEL, rx=5, sw=0)
        c.text(104, y + 18, number, size=11.5, weight="700", fill=L2)
        c.text(124, y + 18, rule, size=12.5)
        c.text(936, y + 18, f"→ {outcome}", size=12, fill=MUTED, anchor="end")
        y += 28

    # -- the three routes ---------------------------------------------------
    routes = [
        (70, "NEED_INFO", "ask, keep the slot open", AMBER),
        (380, "AUTO_RESOLVE", "the robot may execute", L3),
        (690, "ESCALATE", "a person decides", RED),
    ]
    for x, label, caption, colour in routes:
        c.elbow(520, 622, x + 140, 656, colour=colour)
        c.rect(x, 660, 280, 56, fill=WHITE, stroke=colour, sw=2)
        c.text(x + 140, 686, label, size=13.5, weight="700", anchor="middle",
               fill=colour, font=MONO)
        c.text(x + 140, 705, caption, size=11.5, anchor="middle", fill=MUTED)

    # NEED_INFO loops back to the customer with a follow-up question.
    c.parts.append(
        f'<path d="M70 688 H30 V126 H364" fill="none" stroke="{AMBER}" '
        f'stroke-width="2" stroke-dasharray="6 5" '
        f'marker-end="url(#arrow-{AMBER[1:]})"/>'
    )
    # Label sits above the horizontal leg of the return path, where there is
    # clear space. In the left margin it would overlap the Layer 2 panel.
    c.text(84, 100, "follow-up question", size=11.5, fill=AMBER, weight="600")
    c.text(84, 116, "(multi-turn slot filling)", size=10.5, fill=AMBER)

    # -- layer 3 ------------------------------------------------------------
    c.elbow(520, 716, 360, 756, colour=L3)
    c.rect(60, 760, 600, 215, fill=WHITE, stroke=BORDER)
    c.band(60, 760, 600, 215, L3)
    c.text(88, 786, "LAYER 3 · RPA EXECUTION  (UiPath robot)", size=11.5,
           weight="700", fill=L3, spacing="1.1")

    steps = [
        "Validate order & customer",
        "Check refund eligibility",
        "Update the order database",
        "Generate a reference number",
        "Log the case for audit",
    ]
    y = 806
    for index, step in enumerate(steps, start=1):
        c.parts.append(
            f'<circle cx="103" cy="{y + 9}" r="10" fill="{L3}"/>'
        )
        c.text(103, y + 13, str(index), size=11, weight="700", fill=WHITE,
               anchor="middle")
        c.text(124, y + 13, step, size=12.5)
        y += 31

    # -- human agent --------------------------------------------------------
    c.arrow(830, 716, 838, 756, colour=RED)
    c.rect(700, 760, 280, 215, fill=WHITE, stroke=BORDER)
    c.band(700, 760, 280, 215, RED)
    c.text(728, 786, "HUMAN AGENT", size=11.5, weight="700", fill=RED,
           spacing="1.1")
    c.text(728, 808, "Receives a context packet:", size=12, fill=MUTED)

    packet = [
        "intent + confidence score",
        "entities extracted",
        "why it was escalated",
        "a suggested resolution",
        "the original message",
    ]
    y = 828
    for item in packet:
        c.parts.append(
            f'<circle cx="734" cy="{y + 5}" r="2.6" fill="{RED}"/>'
        )
        c.text(746, y + 9, item, size=12)
        y += 22
    c.text(728, 960, "Reviews a decision, not a blank ticket.", size=11.5,
           fill=RED, weight="600")

    # -- the data store -----------------------------------------------------
    c.arrow(360, 975, 360, 1009, colour=L3)
    c.arrow(840, 975, 840, 1009, colour=RED)
    c.rect(60, 1013, 920, 96, fill=PANEL, stroke=BORDER)
    c.text(88, 1040, "MOCK CRM  ·  MockCRM_ApplianceOrders.xlsx", size=11.5,
           weight="700", fill=MUTED, spacing="1.1")
    c.text(88, 1060, "Reached through a REST-style wrapper, so swapping in a "
                     "real CRM API is a configuration change, not a rebuild.",
           size=12, fill=MUTED)

    sheets = [
        (88, "Orders", "21 orders · 5 appliance categories"),
        (390, "AuditLog", "every automated resolution"),
        (680, "EscalationQueue", "every handoff + context packet"),
    ]
    for x, name, caption in sheets:
        c.text(x, 1090, name, size=12.5, weight="600", font=MONO)
        c.text(x, 1090, "", size=12)
        c.text(x + (len(name) * 8.2) + 12, 1090, caption, size=11.5, fill=MUTED)

    c.text(60, 1143, "Fail safe, not silent — every branch ends somewhere a "
                     "person can see. An unreachable CRM escalates rather "
                     "than guessing.", size=12, fill=MUTED)
    return c.save(DOCS / "architecture_block_diagram.svg")

# ---------------------------------------------------------------------------
# Diagram 2 - the UiPath workflow, activity by activity
# ---------------------------------------------------------------------------
def build_uipath_workflow():
    c = Canvas(1040, 1284, "UiPath workflow block diagram")

    c.text(60, 46, "Layer 3 — the UiPath robot", size=21, weight="700")
    c.text(60, 72, "Activity-by-activity flow. Doubles as the build map for "
                   "Studio.", size=13.5, fill=MUTED)

    def step(x, y, w, number, title, detail, colour=SLATE, h=62):
        c.rect(x, y, w, h, fill=WHITE, stroke=BORDER)
        c.band(x, y, w, h, colour)
        c.parts.append(f'<circle cx="{x + 26}" cy="{y + h / 2}" r="11" '
                       f'fill="{colour}"/>')
        c.text(x + 26, y + h / 2 + 4, number, size=11, weight="700",
               fill=WHITE, anchor="middle")
        c.text(x + 48, y + 25, title, size=13, weight="600")
        c.text(x + 48, y + 44, detail, size=11.5, fill=MUTED, font=MONO)

    # -- the linear preamble -------------------------------------------------
    step(260, 100, 520, "1", "Input Dialog", "→ customerText", L1)
    c.arrow(520, 162, 520, 190)
    step(260, 194, 520, "2", "HTTP Request  ·  POST /classify",
         "webhookUrl → responseJson", L2)
    c.arrow(520, 256, 520, 284)
    step(260, 288, 520, "3", "Deserialize JSON", "responseJson → result (JObject)",
         L2)
    c.arrow(520, 350, 520, 378)
    step(260, 382, 520, "4", "Assign × 9  —  unpack the decision",
         "route · intent · action · order_id · confidence …", L2, h=66)
    c.arrow(520, 448, 520, 476)
    step(260, 480, 520, "5", "Read Range (Workbook)  ·  Orders",
         "crmPath → dtOrders   (AddHeaders ✔)", L3)
    c.arrow(520, 542, 520, 570)

    # -- the branch ----------------------------------------------------------
    c.rect(300, 574, 440, 52, fill=PANEL, stroke=L2, sw=2)
    c.text(520, 605, 'If   route = "AUTO_RESOLVE"', size=13.5, weight="700",
           anchor="middle", font=MONO, fill=L2)

    c.elbow(520, 626, 280, 664, colour=L3)
    c.elbow(520, 626, 790, 664, colour=RED)

    # -- THEN: the automated path -------------------------------------------
    c.rect(50, 668, 460, 430, fill=WHITE, stroke=BORDER)
    c.band(50, 668, 460, 430, L3)
    c.text(78, 694, "THEN  ·  RPA EXECUTION", size=11.5, weight="700",
           fill=L3, spacing="1.1")

    # Label above the detail, not beside it. Sharing a column meant the wide
    # labels ("If PROCESS_REFUND") ran straight through the expression text.
    then_rows = [
        ("Assign", ['orderRow = dtOrders.Select("OrderID = " + orderId)']),
        ("If", ["orderRow IsNot Nothing"]),
        ("Assign × 3", ["orderRowNumber = index + 2 · status · amount"]),
        ("If READ_STATUS", ["build the reply string — no write"]),
        ("If PROCESS_REFUND", ['eligible? → Write Cell "I" = Refund Initiated',
                               '"J" = N   ·   ref = "RF" + Random(1000, 9999)']),
        ("If UPDATE_ADDRESS", ['Write Cell "K" = new_address']),
    ]
    y = 710
    for label, details in then_rows:
        c.text(78, y + 12, label, size=12, weight="600", fill=L3)
        for index, detail in enumerate(details):
            c.text(90, y + 29 + index * 15, detail, size=10.5, fill=MUTED,
                   font=MONO)
        y += 22 + len(details) * 15 + 6

    c.rect(78, y + 6, 404, 96, fill=PANEL, rx=6, sw=0)
    c.text(94, y + 28, "Then log it — 3 activities", size=12, weight="600",
           fill=L3)
    for index, line in enumerate([
        "Read Range (Workbook) · AuditLog → dtLog",
        "Add Data Row · {timestamp, orderId, intent, …}",
        "Write Range (Workbook) · AuditLog · A1 · AddHeaders ✔",
    ]):
        c.text(94, y + 50 + index * 18, f"{index + 1}. {line}", size=10.5,
               fill=MUTED, font=MONO)

    # -- ELSE: the escalation path ------------------------------------------
    c.rect(530, 668, 460, 430, fill=WHITE, stroke=BORDER)
    c.band(530, 668, 460, 430, RED)
    c.text(558, 694, "ELSE  ·  HUMAN ESCALATION", size=11.5, weight="700",
           fill=RED, spacing="1.1")
    c.text(558, 714, "Covers ESCALATE and NEED_INFO.", size=11.5, fill=MUTED)

    c.rect(558, 730, 404, 96, fill=PANEL, rx=6, sw=0)
    c.text(574, 752, "Queue the case — 3 activities", size=12, weight="600",
           fill=RED)
    for index, line in enumerate([
        "Read Range (Workbook) · EscalationQueue → dtLog",
        "Add Data Row · {…, reason, suggestedResolution}",
        "Write Range (Workbook) · EscalationQueue · A1",
    ]):
        c.text(574, 774 + index * 18, f"{index + 1}. {line}", size=10.5,
               fill=MUTED, font=MONO)

    c.rect(558, 842, 404, 152, fill=WHITE, stroke=RED, dash="5 4")
    c.text(574, 866, "Message Box — Action Center handoff", size=12,
           weight="600", fill=RED)
    c.text(574, 884, "The agent sees a reasoned decision, not a transcript:",
           size=10.5, fill=MUTED)
    for index, line in enumerate([
        "REASON: SENSITIVITY_CAP",
        "Customer said: …",
        "Intent: order.refund   Confidence: 0.99",
        "Why: Rs 72,990 exceeds the Rs 10,000 cap",
        "SUGGESTED RESOLUTION: approve the refund …",
    ]):
        c.text(586, 906 + index * 17, line, size=10, fill=INK, font=MONO)

    c.text(558, 1020, "Assign", size=12, weight="600", fill=RED)
    c.text(614, 1020, "replyText = If(route = \"NEED_INFO\",", size=10.5,
           fill=MUTED, font=MONO)
    c.text(614, 1037, "  followup_question, escalation message)", size=10.5,
           fill=MUTED, font=MONO)

    # -- converge ------------------------------------------------------------
    c.elbow(280, 1098, 520, 1136, colour=L3)
    c.elbow(790, 1098, 520, 1136, colour=RED)
    step(260, 1140, 520, "6", "Message Box  —  reply to the customer",
         "replyText", L1)

    c.text(60, 1252, "The robot never calls Dialogflow directly. Steps 1–4 "
                     "are the whole AI integration: plain HTTP, plain JSON, "
                     "no OAuth inside Studio.", size=12, fill=MUTED)
    return c.save(DOCS / "uipath_workflow_diagram.svg")


def main():
    for path in (build_architecture(), build_uipath_workflow()):
        print(f"Built {path}  ({path.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
