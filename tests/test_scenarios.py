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


class TestReplyQuality(ScenarioTest):
    """Replies have to carry facts, a next step and a reference.

    The old replies were single-fact f-strings, and every escalation emitted
    the same sentence whatever caused it. These tests pin the properties
    that make a reply useful rather than merely polite.
    """

    def test_escalation_replies_differ_by_reason(self):
        """One generic sentence for every handoff is what this replaces."""
        replies = {
            "cap": self.resolve("I want a refund for order 4516", "a"),
            "complaint": self.resolve("my washing machine arrived broken", "b"),
            "agent": self.resolve("connect me to an agent", "c"),
            "unclear": self.resolve("Something's wrong with my stuff", "d"),
        }
        texts = {k: r["outcome"]["reply"] for k, r in replies.items()}
        self.assertEqual(len(set(texts.values())), 4,
                         "each escalation reason needs its own explanation")

    def test_low_confidence_reply_does_not_claim_to_understand(self):
        """The bug this guards against is subtle and was real.

        "Something's wrong with my stuff" classifies as order.complaint at
        0.19. Branching on the intent before the reason produced "I'm sorry
        about your washing machine" - asserting an understanding the system
        explicitly does not have. Reason is checked first, as in routing.
        """
        result = self.resolve("Something's wrong with my stuff")
        reply = result["outcome"]["reply"].lower()

        self.assertEqual(result["decision"]["reason"],
                         routing.REASON_LOW_CONFIDENCE)
        self.assertIn("confident", reply)
        self.assertNotIn("washing machine", reply)
        self.assertNotIn("product issues are handled", reply)

    def test_cap_escalation_explains_the_limit_with_real_numbers(self):
        reply = self.resolve("I want a refund for order 4516")["outcome"]["reply"]
        self.assertIn("72,990", reply)        # the actual amount
        self.assertIn("10,000", reply)        # the limit it exceeded
        self.assertIn("supervisor", reply.lower())

    def test_every_escalation_gives_the_customer_a_reference(self):
        for message in ["I want a refund for order 4516",
                        "my washing machine arrived broken",
                        "Something's wrong with my stuff"]:
            with self.subTest(message=message):
                outcome = self.resolve(message, message[:6])["outcome"]
                self.assertTrue(outcome["reference_no"].startswith("ESC"))
                self.assertIn(outcome["reference_no"], outcome["reply"])

    def test_case_reference_is_recorded_for_the_agent(self):
        outcome = self.resolve("I want a refund for order 4516")["outcome"]
        rows = crm.read_log(config.SHEET_ESCALATION)
        self.assertEqual(rows[0]["CaseReference"], outcome["reference_no"])

    def test_replies_address_the_customer_by_name(self):
        reply = self.resolve("where is my order 4508")["outcome"]["reply"]
        self.assertIn("Meera", reply, "the CRM knows the customer's name")

    def test_replies_state_a_next_step(self):
        """A reply that ends without telling the customer what happens next
        is where a bot starts feeling like a dead end."""
        reply = self.resolve("where is my order 4508")["outcome"]["reply"]
        self.assertIn("working days", reply)

    def test_refund_reply_carries_amount_reference_and_timeline(self):
        outcome = self.resolve("i want my money back for order 4509")["outcome"]
        reply = outcome["reply"]
        self.assertIn("4,299", reply)
        self.assertIn(outcome["reference_no"], reply)
        self.assertIn("5-7 working days", reply)

    def test_declined_refund_offers_a_route_that_is_not_a_dead_end(self):
        reply = self.resolve("refund my order 4511")["outcome"]["reply"]
        self.assertIn("returns window", reply)
        self.assertIn("faulty", reply.lower())


class TestVoiceTranscripts(ScenarioTest):
    """Layer 0: speech transcripts must reach the NLU as usable text.

    Vosk returns words, not digits, so "order 4521" arrives as "order four
    five two one". Each case here is a real way a recogniser renders a
    spoken order number, and each must route exactly as the typed message
    would. Tested without a microphone on purpose: the conversion is a pure
    function, and it is the part most likely to break a voice demo.
    """

    def test_spoken_digit_forms_all_recover_the_order_number(self):
        from voice.numbers import normalise_transcript
        for transcript, expected in {
            "where is my order four five two one": "4521",
            "where is my order forty five twenty one": "4521",
            "order four thousand five hundred twenty one": "4521",
            "order four five oh nine": "4509",
            "order forty five zero nine": "4509",
            "order double four five one": "4451",
        }.items():
            with self.subTest(transcript=transcript):
                self.assertIn(expected, normalise_transcript(transcript))

    def test_ordinary_english_is_not_mangled_into_digits(self):
        """The trap: "for"/"to"/"oh" sound like digits but rarely are.

        Mapping them unconditionally rewrites "refund for order 4521" as
        "refund 4 order 4521" - breaking messages that were already correct.
        """
        from voice.numbers import normalise_transcript
        for text in ["refund for 4521", "i want to refund order 4521",
                     "change the delivery address for order 4503",
                     "connect me to an agent",
                     "my washing machine arrived broken"]:
            with self.subTest(text=text):
                self.assertEqual(normalise_transcript(text), text)

    def test_homophone_beside_a_spelled_number_is_read_as_a_digit(self):
        from voice.numbers import normalise_transcript
        self.assertIn("4516", normalise_transcript("order for five one six"))

    def test_a_spoken_message_routes_the_same_as_a_typed_one(self):
        """The point of Layer 0: voice changes the input, not the logic."""
        from voice.numbers import normalise_transcript
        typed = self.resolve("where is my order 4521", "typed")
        spoken = self.resolve(
            normalise_transcript("where is my order four five two one"),
            "spoken")
        self.assertEqual(spoken["decision"]["intent"], typed["decision"]["intent"])
        self.assertEqual(spoken["decision"]["route"], typed["decision"]["route"])
        self.assertEqual(spoken["decision"]["entities"]["order_id"],
                         typed["decision"]["entities"]["order_id"])

    def test_a_spoken_high_value_refund_still_hits_the_cap(self):
        from voice.numbers import normalise_transcript
        result = self.resolve(
            normalise_transcript("i want a refund for order four five one six"),
            "spoken-cap")
        self.assertEqual(result["decision"]["route"], routing.ESCALATE)
        self.assertEqual(result["decision"]["reason"],
                         routing.REASON_SENSITIVITY_CAP)


class TestVoiceWiring(unittest.TestCase):
    """Voice is optional: absent Vosk must not break anything else."""

    def test_absent_vosk_reports_a_reason_instead_of_raising(self):
        from voice import transcribe
        available, reason = transcribe.availability()
        self.assertIsInstance(available, bool)
        self.assertTrue(reason, "availability() must always explain itself")

    def test_grammar_covers_the_demo_vocabulary(self):
        import json
        from voice import transcribe
        vocabulary = set(json.loads(transcribe.build_grammar())[0].split())
        for word in ["order", "refund", "address", "agent", "washing",
                     "machine", "four", "five", "twenty", "double"]:
            with self.subTest(word=word):
                self.assertIn(word, vocabulary)

    def test_wav_conversion_targets_what_vosk_needs(self):
        from voice.audio import TARGET_RATE, TARGET_CHANNELS, TARGET_WIDTH
        self.assertEqual((TARGET_RATE, TARGET_CHANNELS, TARGET_WIDTH),
                         (16000, 1, 2))
