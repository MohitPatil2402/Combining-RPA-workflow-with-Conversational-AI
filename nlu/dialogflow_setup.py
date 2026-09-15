"""
Provision the Dialogflow ES agent from nlu/training_data.py.

Creating five intents and 159 annotated training phrases by hand in the
Dialogflow console is a couple of hours of clicking and a guarantee that the
console and this repository will drift apart. This script builds the agent
from the same module the local classifier trains on, so the two engines are
always taught the same thing, and rebuilding after a change is one command.

Usage
-----
    # See exactly what would be created - no GCP account needed:
    python -m nlu.dialogflow_setup --dry-run

    # For real:
    pip install google-cloud-dialogflow
    set GOOGLE_APPLICATION_CREDENTIALS=C:\\path\\to\\key.json
    set DIALOGFLOW_PROJECT_ID=your-project-id
    python -m nlu.dialogflow_setup

What it creates
---------------
  Entity types
    order-id            KIND_REGEXP matching the 45xx range in the mock CRM
    appliance-category  KIND_MAP over the five categories, with the synonyms
                        customers actually type ("fridge", "AC", "mixie")

  Intents
    Order Status, Refund Request, Address Update, Complaint,
    Escalation Request - each with its training phrases automatically
    annotated: order numbers and category words in every phrase are marked
    up as entity references, which is what lets Dialogflow extract them at
    runtime instead of just matching the intent.

Re-running is safe: existing intents and entity types with the same display
names are deleted and recreated, so the agent ends up matching this file.
"""
import argparse
import re
import sys

import config
from nlu import training_data as td

ORDER_ENTITY = "order-id"
CATEGORY_ENTITY = "appliance-category"

_ORDER_RE = re.compile(td.ORDER_ID_PATTERN)


def _category_pattern():
    """One regex matching any category synonym, longest first."""
    synonyms = [
        syn for values in td.CATEGORY_ENTITY.values() for syn in values
    ]
    synonyms.sort(key=len, reverse=True)
    joined = "|".join(re.escape(s) for s in synonyms)
    return re.compile(rf"(?<![a-z])({joined})(?![a-z])", re.IGNORECASE)


_CATEGORY_RE = _category_pattern()


def annotate(phrase):
    """Split a phrase into Dialogflow training-phrase parts.

    Returns a list of (text, entity_type, alias) tuples, where entity_type is
    None for ordinary words. Doing this automatically is what makes 159
    annotated phrases practical - by hand it is where the typos come from.
    """
    spans = []
    for match in _ORDER_RE.finditer(phrase):
        spans.append((match.start(), match.end(), ORDER_ENTITY, "order_id"))
    for match in _CATEGORY_RE.finditer(phrase):
        # Do not annotate a category word that sits inside an order number.
        if any(s <= match.start() < e for s, e, _, _ in spans):
            continue
        spans.append((match.start(), match.end(), CATEGORY_ENTITY, "category"))

    spans.sort()
    parts, cursor = [], 0
    for start, end, entity, alias in spans:
        if start < cursor:
            continue
        if start > cursor:
            parts.append((phrase[cursor:start], None, None))
        parts.append((phrase[start:end], entity, alias))
        cursor = end
    if cursor < len(phrase):
        parts.append((phrase[cursor:], None, None))
    return parts or [(phrase, None, None)]


# ---------------------------------------------------------------------------
# Dry run
# ---------------------------------------------------------------------------
def dry_run():
    print("=" * 74)
    print("DRY RUN - nothing will be sent to Google Cloud")
    print("=" * 74)
    print(f"\nEntity type '{ORDER_ENTITY}' (KIND_REGEXP)")
    print(f"  pattern: {td.ORDER_ID_PATTERN}")

    print(f"\nEntity type '{CATEGORY_ENTITY}' (KIND_MAP)")
    for value, synonyms in td.CATEGORY_ENTITY.items():
        print(f"  {value:<18} <- {', '.join(synonyms)}")

    print(f"\nIntents ({len(td.INTENTS)}):")
    for name, meta in td.INTENTS.items():
        phrases = td.TRAINING_PHRASES.get(name, [])
        required = meta["required_entities"]
        print(f"\n  {meta['display_name']}  ({name})")
        print(f"    training phrases : {len(phrases)}")
        print(f"    required params  : {', '.join(required) or 'none'}")
        print(f"    automatable      : {meta['automatable']}")
        print("    sample annotation:")
        for phrase in phrases[:2]:
            rendered = "".join(
                f"[{text}]({alias})" if entity else text
                for text, entity, alias in annotate(phrase)
            )
            print(f"      {rendered}")

    total = sum(len(v) for v in td.TRAINING_PHRASES.values())
    print(f"\nTotal: {len(td.INTENTS)} intents, {total} training phrases, "
          f"2 entity types")
    print("\nTo create these for real, set GOOGLE_APPLICATION_CREDENTIALS and "
          "DIALOGFLOW_PROJECT_ID, then re-run without --dry-run.")


# ---------------------------------------------------------------------------
# Real provisioning
# ---------------------------------------------------------------------------
def _require_config():
    if not config.DIALOGFLOW_PROJECT_ID:
        sys.exit("DIALOGFLOW_PROJECT_ID is not set. "
                 "Use --dry-run to preview without an agent.")
    if not config.GOOGLE_APPLICATION_CREDENTIALS:
        sys.exit("GOOGLE_APPLICATION_CREDENTIALS is not set. "
                 "Use --dry-run to preview without an agent.")


def create_entity_types(dialogflow, parent):
    client = dialogflow.EntityTypesClient()

    existing = {
        entity.display_name: entity.name
        for entity in client.list_entity_types(request={"parent": parent})
    }
    for name in (ORDER_ENTITY, CATEGORY_ENTITY):
        if name in existing:
            client.delete_entity_type(request={"name": existing[name]})
            print(f"  deleted existing entity type '{name}'")

    order_type = dialogflow.EntityType(
        display_name=ORDER_ENTITY,
        kind=dialogflow.EntityType.Kind.KIND_REGEXP,
        entities=[
            dialogflow.EntityType.Entity(
                value=td.ORDER_ID_PATTERN, synonyms=[td.ORDER_ID_PATTERN]
            )
        ],
    )
    client.create_entity_type(
        request={"parent": parent, "entity_type": order_type}
    )
    print(f"  created entity type '{ORDER_ENTITY}' (regexp)")

    category_type = dialogflow.EntityType(
        display_name=CATEGORY_ENTITY,
        kind=dialogflow.EntityType.Kind.KIND_MAP,
        entities=[
            dialogflow.EntityType.Entity(value=value, synonyms=[value] + synonyms)
            for value, synonyms in td.CATEGORY_ENTITY.items()
        ],
    )
    client.create_entity_type(
        request={"parent": parent, "entity_type": category_type}
    )
    print(f"  created entity type '{CATEGORY_ENTITY}' "
          f"({len(td.CATEGORY_ENTITY)} values)")


def create_intents(dialogflow, parent):
    client = dialogflow.IntentsClient()

    existing = {
        intent.display_name: intent.name
        for intent in client.list_intents(request={"parent": parent})
    }

    for intent_name, meta in td.INTENTS.items():
        display_name = meta["display_name"]
        if display_name in existing:
            client.delete_intent(request={"name": existing[display_name]})
            print(f"  deleted existing intent '{display_name}'")

        phrases = []
        for phrase in td.TRAINING_PHRASES.get(intent_name, []):
            parts = [
                dialogflow.Intent.TrainingPhrase.Part(
                    text=text,
                    entity_type=f"@{entity}" if entity else None,
                    alias=alias,
                )
                for text, entity, alias in annotate(phrase)
            ]
            phrases.append(
                dialogflow.Intent.TrainingPhrase(
                    type_=dialogflow.Intent.TrainingPhrase.Type.EXAMPLE,
                    parts=parts,
                )
            )

        parameters = []
        for required in meta["required_entities"]:
            if required == "order_id":
                parameters.append(
                    dialogflow.Intent.Parameter(
                        display_name="order_id",
                        entity_type_display_name=f"@{ORDER_ENTITY}",
                        value="$order_id",
                        mandatory=False,
                    )
                )
            # new_address is filled by the orchestrator's own slot-filling
            # turn rather than by Dialogflow, so it is not declared here.

        intent = dialogflow.Intent(
            display_name=display_name,
            training_phrases=phrases,
            parameters=parameters,
            # Fulfilment is not used: the orchestration webhook calls
            # detectIntent itself rather than having Dialogflow call out.
            webhook_state=dialogflow.Intent.WebhookState.WEBHOOK_STATE_UNSPECIFIED,
        )
        client.create_intent(request={"parent": parent, "intent": intent})
        print(f"  created intent '{display_name}' "
              f"({len(phrases)} training phrases)")


def provision():
    _require_config()
    try:
        from google.cloud import dialogflow
    except ImportError:
        sys.exit("google-cloud-dialogflow is not installed. Run: "
                 "pip install google-cloud-dialogflow")

    parent = f"projects/{config.DIALOGFLOW_PROJECT_ID}/agent"
    print(f"Provisioning agent: {parent}\n")

    print("Entity types:")
    create_entity_types(dialogflow, parent)

    print("\nIntents:")
    create_intents(dialogflow, parent)

    print("\nDone. Dialogflow trains the agent automatically; give it a "
          "minute before testing.")
    print("Then re-derive the threshold for this engine - the local sweep in "
          "nlu/evaluate.py does NOT transfer to Dialogflow's score scale.")


def main():
    parser = argparse.ArgumentParser(description="Provision the Dialogflow ES agent.")
    parser.add_argument(
        "--dry-run", action="store_true",
        help="print what would be created without contacting Google Cloud",
    )
    args = parser.parse_args()
    dry_run() if args.dry_run else provision()


if __name__ == "__main__":
    main()
