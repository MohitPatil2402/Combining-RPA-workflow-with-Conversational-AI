"""
The scenarios from the methodology slides, as executable tests.

Run with:

    python -m unittest discover -s tests -v

Every test here corresponds to something the deck claims the system does.
If these pass, the claim is true. Each test runs against a throwaway copy of
the CRM workbook, so running them never touches the demo data.
"""
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config  # noqa: E402
from nlu.local_classifier import detect_intent  # noqa: E402
from orchestrator import pipeline, routing, sessions  # noqa: E402
from rpa import crm  # noqa: E402
from scripts.build_mock_crm import build  # noqa: E402


class ScenarioTest(unittest.TestCase):
    """Base class: each test gets a clean, isolated CRM workbook."""

    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="rpa-crm-")
        self._original = config.CRM_WORKBOOK
        config.CRM_WORKBOOK = Path(self._tmp) / "MockCRM_Test.xlsx"
        build(config.CRM_WORKBOOK)
        sessions.clear_all()

    def tearDown(self):
        config.CRM_WORKBOOK = self._original
        shutil.rmtree(self._tmp, ignore_errors=True)
        sessions.clear_all()

    def resolve(self, message, session_id="test"):
        return pipeline.handle_message(message, session_id=session_id)


class TestRoutingDecisions(ScenarioTest):
    """Slide 5: the three confidence cases, plus the policy rules."""

    def test_clear_request_routes_to_automation(self):
        # "Where is my order #4521?" - clear intent, above threshold.
        result = self.resolve("Where is my order #4521?")
        decision = result["decision"]

        self.assertEqual(decision["route"], routing.AUTO_RESOLVE)
        self.assertEqual(decision["intent"], "order.status")
        self.assertEqual(decision["entities"]["order_id"], "4521")
        self.assertGreaterEqual(decision["confidence"], decision["threshold"])
        self.assertEqual(result["outcome"]["action"], "READ_STATUS")

    def test_vague_request_escalates_on_low_confidence(self):
        # "Something's wrong with my stuff" - vague, below threshold.
        result = self.resolve("Something's wrong with my stuff")
        decision = result["decision"]

        self.assertEqual(decision["route"], routing.ESCALATE)
        self.assertEqual(decision["reason"], routing.REASON_LOW_CONFIDENCE)
        self.assertLess(decision["confidence"], decision["threshold"])

    def test_large_refund_escalates_despite_high_confidence(self):
        # The case that proves confidence alone does not decide: order 4516
        # is Rs 72,990, well above the sensitivity cap.
        result = self.resolve("I want a refund for order 4516")
        decision = result["decision"]

        self.assertEqual(decision["route"], routing.ESCALATE)
        self.assertEqual(decision["reason"], routing.REASON_SENSITIVITY_CAP)
        self.assertGreaterEqual(
            decision["confidence"], decision["threshold"],
            "this case is only meaningful if the classifier WAS confident",
        )
        self.assertGreater(decision["entities"]["amount"],
                           config.SENSITIVITY_CAP_INR)

    def test_complaint_always_escalates(self):
        result = self.resolve("my washing machine arrived broken")
        decision = result["decision"]
        self.assertEqual(decision["route"], routing.ESCALATE)
        self.assertEqual(decision["reason"], routing.REASON_POLICY_INTENT)

    def test_explicit_human_request_escalates(self):
        result = self.resolve("connect me to an agent please")
        self.assertEqual(result["decision"]["route"], routing.ESCALATE)
        self.assertEqual(result["decision"]["reason"],
                         routing.REASON_POLICY_INTENT)

    def test_unknown_order_escalates_rather_than_guessing(self):
        result = self.resolve("where is my order 4999")
        self.assertEqual(result["decision"]["route"], routing.ESCALATE)
        self.assertEqual(result["decision"]["reason"],
                         routing.REASON_ORDER_NOT_FOUND)

    def test_out_of_scope_messages_never_automate(self):
        for message in ["hello", "do you sell laptops", "what are your hours"]:
            with self.subTest(message=message):
                decision = self.resolve(message)["decision"]
                self.assertNotEqual(
                    decision["route"], routing.AUTO_RESOLVE,
                    f"'{message}' should never be automated",
                )


class TestRobotExecution(ScenarioTest):
    """Slide 6: validate, check eligibility, update, reference, log."""

    def test_refund_updates_database_and_returns_reference(self):
        before = crm.get_order(4521)
        self.assertEqual(before["Status"], "Delivered")
        self.assertEqual(before["RefundEligible"], "Y")

        result = self.resolve("I want a refund for order 4521")
        outcome = result["outcome"]

        self.assertTrue(outcome["success"])
        self.assertEqual(outcome["action"], "PROCESS_REFUND")
        self.assertTrue(outcome["reference_no"].startswith("RF"))

        after = crm.get_order(4521)
        self.assertEqual(after["Status"], "Refund Initiated")
        self.assertEqual(after["RefundEligible"], "N",
                         "an initiated refund must not be re-runnable")

    def test_status_read_does_not_modify_the_order(self):
        before = crm.get_order(4508)
        self.resolve("where is my order 4508")
        self.assertEqual(crm.get_order(4508), before)

    def test_ineligible_refund_is_declined_not_escalated(self):
        # Order 4511 is outside the returns window, and at Rs 2,199 it is
        # below the sensitivity cap - so it reaches the eligibility check
        # instead of escaping through the cap rule first. A clear, explained
        # "no" is a resolution; it does not need a human.
        result = self.resolve("refund my order 4511")
        outcome = result["outcome"]

        self.assertEqual(result["decision"]["route"], routing.AUTO_RESOLVE)
        self.assertFalse(outcome["success"])
        self.assertIn("returns window", outcome["reply"])
        self.assertEqual(crm.get_order(4511)["Status"], "Delivered",
                         "a declined refund must not change the order")

    def test_address_change_on_moving_parcel_escalates(self):
        # Order 4502 has already shipped, so redirecting it is a courier
        # decision rather than a database edit.
        self.resolve("change the delivery address for order 4502")
        result = self.resolve("14 New Street, Pune 411001")

        self.assertTrue(result["outcome"]["escalate"])
        self.assertIn("Shipped", result["outcome"]["result"])

    def test_address_change_before_dispatch_succeeds(self):
        self.resolve("change the delivery address for order 4503")
        result = self.resolve("88 Nehru Road, Pune 411001")

        self.assertTrue(result["outcome"]["success"])
        self.assertEqual(crm.get_order(4503)["DeliveryAddress"],
                         "88 Nehru Road, Pune 411001")


class TestSlotFilling(ScenarioTest):
    """Slide 5: ask a follow-up rather than failing on a missing entity."""

    def test_missing_order_id_asks_instead_of_failing(self):
        result = self.resolve("i want a refund", session_id="slots")
        decision = result["decision"]

        self.assertEqual(decision["route"], routing.NEED_INFO)
        self.assertEqual(decision["missing_entity"], "order_id")
        self.assertIn("order number", result["outcome"]["reply"].lower())

    def test_followup_answer_completes_the_original_request(self):
        self.resolve("i want a refund", session_id="slots")
        result = self.resolve("4521", session_id="slots")

        self.assertEqual(result["decision"]["route"], routing.AUTO_RESOLVE)
        self.assertEqual(result["decision"]["intent"], "order.refund")
        self.assertTrue(result["outcome"]["reference_no"].startswith("RF"))

    def test_sessions_do_not_leak_into_each_other(self):
        self.resolve("i want a refund", session_id="alice")
        result = self.resolve("where is my order 4508", session_id="bob")
        self.assertEqual(result["decision"]["intent"], "order.status")


class TestAuditTrail(ScenarioTest):
    """Slide 6: every decision is logged with its reason."""

    def test_automated_resolution_is_written_to_the_audit_log(self):
        self.resolve("where is my order 4508")
        rows = crm.read_log(config.SHEET_AUDIT)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["OrderID"], "4508")
        self.assertEqual(rows[0]["Intent"], "order.status")
        self.assertEqual(rows[0]["Action"], "READ_STATUS")
        self.assertIsNotNone(rows[0]["Confidence"])

    def test_escalation_is_queued_with_a_context_packet(self):
        self.resolve("I want a refund for order 4516")
        rows = crm.read_log(config.SHEET_ESCALATION)

        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["OrderID"], "4516")
        self.assertEqual(row["Reason"], routing.REASON_SENSITIVITY_CAP)
        self.assertEqual(row["Status"], "Pending")

        # The point of the whole design: the agent gets a reasoned proposal,
        # not a raw transcript.
        self.assertTrue(row["SuggestedResolution"])
        self.assertIn("approve", row["SuggestedResolution"].lower())
        self.assertIn("72,990", row["SuggestedResolution"])
        self.assertTrue(row["CustomerMessage"])

    def test_escalations_do_not_write_to_the_audit_log(self):
        self.resolve("Something's wrong with my stuff")
        self.assertEqual(crm.read_log(config.SHEET_AUDIT), [])
        self.assertEqual(len(crm.read_log(config.SHEET_ESCALATION)), 1)


class TestClassifierQuality(unittest.TestCase):
    """Guardrails on Layer 1, so a training-data edit cannot quietly regress it."""

    def test_held_out_accuracy_stays_above_80_percent(self):
        from nlu import training_data as td
        correct = total = 0
        for text, expected in td.validation_pairs():
            if expected is None:
                continue
            total += 1
            if detect_intent(text)["intent"] == expected:
                correct += 1
        accuracy = correct / total
        self.assertGreaterEqual(
            accuracy, 0.80,
            f"held-out accuracy fell to {accuracy:.1%} ({correct}/{total})",
        )

    def test_out_of_scope_messages_score_below_the_threshold(self):
        from nlu import training_data as td
        threshold = config.threshold_for("local")
        for text in td.OUT_OF_SCOPE_PHRASES:
            with self.subTest(text=text):
                self.assertLess(
                    detect_intent(text)["confidence"], threshold,
                    f"'{text}' scored high enough to be automated",
                )

    def test_entities_are_extracted_from_natural_phrasing(self):
        from nlu.local_classifier import extract_entities
        self.assertEqual(extract_entities("where is order 4521")["order_id"], "4521")
        self.assertEqual(extract_entities("refund of 12000 please")["amount"], 12000.0)
        self.assertEqual(extract_entities("my fridge is late")["category"],
                         "Refrigerator")
        self.assertEqual(extract_entities("the AC broke")["category"],
                         "Air Conditioner")


if __name__ == "__main__":
    unittest.main(verbosity=2)


class TestUiPathContract(unittest.TestCase):
    """The XAML addresses cells by letter, so a column reorder would break it.

    uipath/Main.xaml writes to fixed cells - Status is column I, Delivery
    Address is column K, and so on. Nothing in Excel stops someone reordering
    the columns in scripts/build_mock_crm.py, and the robot would then quietly
    write refund statuses into the wrong field. This test makes that failure
    loud and immediate instead of discovering it during a demo.
    """

    # The column letters hardcoded in uipath/Main.xaml.
    EXPECTED_COLUMNS = {
        "Orders": {"I": "Status", "J": "RefundEligible", "K": "DeliveryAddress"},
        "AuditLog": {
            "A": "Timestamp", "B": "OrderID", "C": "Intent", "D": "Confidence",
            "E": "Engine", "F": "Action", "G": "Result", "H": "ReferenceNo",
            "I": "HandledBy",
        },
        "EscalationQueue": {
            "A": "Timestamp", "B": "OrderID", "C": "Intent", "D": "Confidence",
            "E": "Entities", "F": "Reason", "G": "SuggestedResolution",
            "H": "CustomerMessage", "I": "Status", "J": "AssignedTo",
        },
    }

    def test_xaml_cell_addresses_match_the_workbook_schema(self):
        from scripts.build_mock_crm import (
            ORDER_COLUMNS, AUDIT_COLUMNS, ESCALATION_COLUMNS,
        )
        schemas = {
            "Orders": ORDER_COLUMNS,
            "AuditLog": AUDIT_COLUMNS,
            "EscalationQueue": ESCALATION_COLUMNS,
        }
        for sheet, mapping in self.EXPECTED_COLUMNS.items():
            columns = schemas[sheet]
            for letter, expected_header in mapping.items():
                index = ord(letter) - ord("A")
                with self.subTest(sheet=sheet, cell=letter):
                    self.assertLess(index, len(columns))
                    self.assertEqual(
                        columns[index], expected_header,
                        f"uipath/Main.xaml writes '{expected_header}' to column "
                        f"{letter} of {sheet}, but that column is now "
                        f"'{columns[index]}'. Update the XAML or the schema.",
                    )

    def test_xaml_is_well_formed_xml(self):
        import xml.etree.ElementTree as ET
        xaml = Path(__file__).resolve().parent.parent / "uipath" / "Main.xaml"
        self.assertTrue(xaml.exists(), "uipath/Main.xaml is missing")
        ET.parse(xaml)  # raises if malformed
