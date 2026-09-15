"""
Threshold selection for Layer 2, measured rather than guessed.

The architecture slide commits to picking the confidence threshold from a
held-out validation set instead of assuming 0.8. This script does that: it
sweeps every candidate threshold and reports what each one would actually
cost, then recommends one against a stated safety policy.

Run it with:

    python -m nlu.evaluate

The numbers that matter
-----------------------
  automation rate       how much work the robot takes off the queue. Higher
                        is better, but only as a secondary goal.
  automation precision  of the cases it automated, how many it understood
                        correctly. This is the safety metric: a wrong
                        automated refund is far more expensive than an
                        unnecessary escalation, so this is the constraint.
  false automation      untrained, out-of-scope messages that slipped above
                        the threshold and got automated anyway. Should be 0.

POLICY: take the threshold that automates the most, subject to automation
precision >= MIN_AUTOMATION_PRECISION and zero false automations. The policy
is stated here in code so the chosen number can be defended and re-derived
after any retraining, instead of being folk knowledge.
"""
import argparse

import config
from nlu import training_data as td
from nlu.local_classifier import LocalIntentClassifier

MIN_AUTOMATION_PRECISION = 0.95


def _score_validation(classifier):
    """Classify the held-out set once; reuse the results at every threshold."""
    results = []
    for text, expected in td.validation_pairs():
        predicted, confidence, _ = classifier.classify(text)
        results.append(
            {
                "text": text,
                "expected": expected,   # None means out of scope
                "predicted": predicted,
                "confidence": confidence,
            }
        )
    return results


def evaluate_at(results, threshold):
    in_scope = [r for r in results if r["expected"] is not None]
    out_scope = [r for r in results if r["expected"] is None]

    automated = [r for r in in_scope if r["confidence"] >= threshold]
    correct = [r for r in automated if r["predicted"] == r["expected"]]
    false_auto = [r for r in out_scope if r["confidence"] >= threshold]

    return {
        "threshold": threshold,
        "automation_rate": len(automated) / len(in_scope) if in_scope else 0.0,
        "automation_precision": len(correct) / len(automated) if automated else 1.0,
        "automated_n": len(automated),
        "in_scope_n": len(in_scope),
        "false_automation_n": len(false_auto),
        "out_scope_n": len(out_scope),
    }


def recommend(rows):
    """Lowest-escalation threshold that still satisfies the safety policy."""
    safe = [
        row for row in rows
        if row["automation_precision"] >= MIN_AUTOMATION_PRECISION
        and row["false_automation_n"] == 0
    ]
    if not safe:
        return None
    return max(safe, key=lambda row: (row["automation_rate"], -row["threshold"]))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--step", type=float, default=0.05, help="threshold sweep granularity"
    )
    args = parser.parse_args()

    classifier = LocalIntentClassifier().fit()
    results = _score_validation(classifier)

    # Overall accuracy ignoring confidence, for context.
    in_scope = [r for r in results if r["expected"] is not None]
    raw_correct = sum(1 for r in in_scope if r["predicted"] == r["expected"])

    print("=" * 74)
    print("LAYER 1 EVALUATION - held-out validation set")
    print("=" * 74)
    print(f"Training phrases    : {sum(len(v) for v in td.TRAINING_PHRASES.values())}")
    print(f"Validation phrases  : {len(in_scope)} in-scope, "
          f"{len(results) - len(in_scope)} out-of-scope")
    print(f"Raw accuracy        : {raw_correct}/{len(in_scope)} "
          f"({raw_correct / len(in_scope):.1%})  [ignoring confidence]")
    print()

    steps = int(round(1.0 / args.step))
    rows = [evaluate_at(results, round(i * args.step, 4)) for i in range(steps + 1)]

    print(f"{'thresh':>7} {'automated':>11} {'auto rate':>10} "
          f"{'precision':>10} {'false auto':>11}")
    print("-" * 74)
    for row in rows:
        flag = "  <-- FAILS POLICY" if (
            row["automation_precision"] < MIN_AUTOMATION_PRECISION
            or row["false_automation_n"] > 0
        ) else ""
        print(
            f"{row['threshold']:>7.2f} "
            f"{row['automated_n']:>5}/{row['in_scope_n']:<5} "
            f"{row['automation_rate']:>9.1%} "
            f"{row['automation_precision']:>10.1%} "
            f"{row['false_automation_n']:>7}/{row['out_scope_n']:<3}{flag}"
        )

    print()
    best = recommend(rows)
    if best is None:
        print("No threshold satisfies the policy - the model needs more "
              "training data before any request can be safely automated.")
        return

    print("=" * 74)
    print(f"RECOMMENDED THRESHOLD: {best['threshold']:.2f}")
    print("=" * 74)
    print(f"  Policy      : maximise automation subject to precision >= "
          f"{MIN_AUTOMATION_PRECISION:.0%} and zero false automations")
    print(f"  Automates   : {best['automation_rate']:.1%} of in-scope requests "
          f"({best['automated_n']}/{best['in_scope_n']})")
    print(f"  Precision   : {best['automation_precision']:.1%} of those "
          f"classified correctly")
    print(f"  Escalates   : {1 - best['automation_rate']:.1%} to a human, "
          f"including all {best['out_scope_n']} out-of-scope messages")
    print()
    print(f"  config.py currently uses CONFIDENCE_THRESHOLD_LOCAL = "
          f"{config.CONFIDENCE_THRESHOLD_LOCAL:.2f}")
    if abs(config.CONFIDENCE_THRESHOLD_LOCAL - best["threshold"]) > 1e-9:
        print("  -> These differ. Update config.py, or set the "
              "CONFIDENCE_THRESHOLD_LOCAL environment variable.")
    else:
        print("  -> Matches. Nothing to change.")

    print()
    print("Misclassified in-scope phrases (what to add training data for):")
    misses = [
        r for r in results
        if r["expected"] is not None and r["predicted"] != r["expected"]
    ]
    if not misses:
        print("  none")
    for r in misses:
        print(f"  {r['confidence']:.2f}  expected {r['expected']:<24} "
              f"got {str(r['predicted']):<24} \"{r['text']}\"")


if __name__ == "__main__":
    main()
