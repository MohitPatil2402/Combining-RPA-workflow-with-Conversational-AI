# Beyond FAQs — RPA + Conversational AI for customer service

A working prototype of customer service automation that **resolves** requests
instead of answering them. Conversational AI interprets what the customer
wants, a UiPath robot performs the actual backend transaction, and a human
is brought in exactly when it matters — with the reasoning already done.

Scoped to five appliance categories — **Television, Washing Machine, Mixer
Grinder, Refrigerator, Air Conditioner** — so the domain is closed enough to
be genuinely finished rather than broadly half-built.

---

## Try it in two minutes

```bash
pip install -r requirements.txt
python scripts/build_mock_crm.py     # create the mock order database
python demo.py                       # run the six scripted scenarios
```

No Google Cloud account, no UiPath licence and no network needed for that —
the NLU layer falls back to a built-in classifier that trains in milliseconds
from the same training data the Dialogflow agent uses.

```bash
python -m unittest discover -s tests   # 23 tests
python -m nlu.evaluate                 # the threshold sweep
python demo.py --interactive           # type your own messages
```

---

## The three layers

| | Layer | What it does | Where |
|---|---|---|---|
| 1 | **Conversational interface** | Classifies the message into intent + entities and scores its own confidence | `nlu/` |
| 2 | **Orchestration** | Decides: automate, ask a follow-up, or escalate | `orchestrator/` |
| 3 | **RPA execution** | Performs the transaction on the order database | `uipath/`, `rpa/` |

Each layer is swappable without touching the others. The NLU layer already
demonstrates this: Dialogflow ES and the local classifier return byte-identical
contracts, and Layer 2 cannot tell which answered.

```
customer message
      │
      ▼
┌─────────────┐   intent, entities, confidence
│  LAYER 1    │──────────────────────────────┐
│  NLU        │                              │
└─────────────┘                              ▼
                                    ┌─────────────────┐
  Dialogflow ES ──┐                 │    LAYER 2      │
                  ├── same contract │  routing rules  │
  local model  ───┘                 └────────┬────────┘
                                             │
                    ┌────────────────────────┼────────────────────────┐
                    ▼                        ▼                        ▼
             AUTO_RESOLVE               NEED_INFO                ESCALATE
                    │                        │                        │
                    ▼                        ▼                        ▼
         ┌─────────────────┐        ask a follow-up      ┌──────────────────────┐
         │    LAYER 3      │        question, keep       │  EscalationQueue +   │
         │  UiPath robot   │        the slot open        │  context packet for  │
         │  + mock CRM     │                             │  a human agent       │
         └─────────────────┘                             └──────────────────────┘
                    │                                               │
                    ▼                                               ▼
              AuditLog row                              agent sees intent, entities,
                                                        confidence, reason, and a
                                                        suggested resolution
```

---

## The routing rules

Applied in this order, in `orchestrator/routing.py`:

1. No intent, or confidence below the engine's threshold → **escalate**
2. Intent is a complaint or an explicit request for a human → **escalate**
3. A required entity is missing → **ask a follow-up question**
4. Money involved exceeds the ₹10,000 sensitivity cap → **escalate**
5. Otherwise → **automate**

Confidence is checked first on purpose: an entity extracted from a message we
did not understand is not evidence. And every branch ends somewhere a person
can see — an unreachable CRM escalates rather than guessing, so there is no
path that drops a customer.

---

## The threshold is measured, not guessed

`python -m nlu.evaluate` sweeps every candidate threshold against a held-out
validation set of 50 in-scope phrases (deliberately worded differently from
the training data) plus 15 out-of-scope messages, and picks one against a
stated policy: *maximise automation subject to ≥95% precision and zero
out-of-scope messages automated*.

```
 thresh   automated  auto rate  precision  false auto
   0.50    36/50        72.0%      94.4%      0/15    <- fails precision
   0.55    31/50        62.0%      96.8%      0/15    <- chosen
   0.60    26/50        52.0%     100.0%      0/15
   0.80    20/50        40.0%     100.0%      0/15
```

Held-out accuracy ignoring confidence is **88%** (44/50).

So the conventional 0.80 would cost 22 percentage points of automation to
prevent a single borderline misroute that escalation catches anyway. **0.55
is the defensible number for this engine** — and it is engine-specific:
Dialogflow scores on a different scale, so `config.py` keeps a separate
threshold for it that must be re-derived once the real agent is trained.
Copying 0.55 across would be meaningless.

---

## What the classifier actually is

No scikit-learn, no numpy — pure standard library, so it installs anywhere.

- TF-IDF vector space model, nearest-centroid classification
- Word unigrams + bigrams + **character 4-grams**, which is what makes
  `refnd` still look like `refund` without a spell checker
- Order numbers masked to a placeholder, so it learns the *shape* of a
  request rather than memorising order 4521
- Confidence = **softmax certainty × in-domain coverage**. Both terms are
  needed: softmax alone will happily report 0.9 for the best of five equally
  bad matches, which is exactly how `hello` ends up being confidently
  mislabelled and automated. Coverage is what holds untrained input down.

Calibration is fitted by leave-one-out on the training set only. The
validation set is never used to tune anything, or its numbers would mean
nothing.

---

## Honest status

| Piece | State |
|---|---|
| Intent classification, 5 intents | **Working** — 88% held-out accuracy |
| Entity extraction (order id, amount, category) | **Working** |
| Confidence calibration + threshold selection | **Working**, measured |
| Routing rules, all 6 branches | **Working**, tested |
| Multi-turn slot filling | **Working** |
| Mock CRM read/update, audit + escalation logs | **Working** |
| Orchestration webhook | **Working** — `/classify` ready for UiPath |
| Escalation context packets | **Working** |
| `rpa/executor.py` (reference Layer 3) | **Working**, 23 tests |
| `uipath/Main.xaml` | **Written, never opened in Studio** — see below |
| Dialogflow ES agent | **Code complete, unprovisioned** — needs a GCP project |

### The two things that are not done

**1. `uipath/Main.xaml` has not been opened in UiPath Studio.** It was written
by hand and is valid XML, but Studio is strict about activity package
versions and may reject it. `uipath/README.md` contains a complete
build-by-hand guide with every expression written out — roughly 30 minutes,
and it is the path that definitely works. Budget for that.

**2. The Dialogflow agent has not been created.** `nlu/dialogflow_setup.py`
provisions it from the same training data in one command, and
`python -m nlu.dialogflow_setup --dry-run` shows exactly what it would create
without needing an account. Until then the local classifier runs, and the
system reports which engine answered on every single response — so a fallback
is never silent.

### One thing worth knowing before you demo

The ₹10,000 sensitivity cap means **only mixer grinders can auto-refund** —
every other appliance in the catalogue costs more. That is realistic policy,
and it makes the escalation path the common case rather than the exception,
which suits the argument. But if you want the automated refund path to look
less like a special case, raise the cap:

```bash
SENSITIVITY_CAP_INR=25000 python demo.py
```

---

## Suggested demo order

Run `python demo.py --reset` first, then walk these four:

1. **`Where is my order 4521`** — confident, routine, resolved with no human.
2. **`Something's wrong with my stuff`** — 0.19 confidence. The system knows
   that it does not know, and escalates rather than guessing.
3. **`I want a refund for order 4516`** — **0.99 confidence, still escalated**,
   because ₹72,990 is over the cap. This is the one to dwell on: it is the
   whole argument that confidence alone does not decide.
4. **`i want a refund`** → **`4509`** — asks for the order number, then
   completes the original request. Multi-turn slot filling.

Then open the workbook and show `AuditLog` and `EscalationQueue`. The
escalation rows carry a **suggested resolution**, not a transcript — an agent
picking one up is reviewing a decision, not starting an investigation. That
is the novelty claim, made concrete.

---

## Repository layout

```
config.py                  thresholds, paths, policy — all env-overridable
demo.py                    scripted + interactive demo driver

nlu/
  training_data.py         5 intents, 159 training phrases, held-out set
  local_classifier.py      the offline TF-IDF classifier
  dialogflow_client.py     Dialogflow ES, same contract
  dialogflow_setup.py      provisions the agent from training_data.py
  engine.py                picks an engine, falls back loudly
  evaluate.py              the threshold sweep

orchestrator/
  routing.py               the five routing rules
  sessions.py              slot-filling conversation state
  pipeline.py              layers 1 -> 2 -> 3 wired together
  webhook_service.py       Flask service UiPath calls

rpa/
  crm.py                   REST-style wrapper over the Excel workbook
  executor.py              the five robot steps (reference implementation)

uipath/
  Main.xaml                the robot workflow
  README.md                build-by-hand guide + troubleshooting

scripts/build_mock_crm.py  generates the workbook (also resets it)
tests/test_scenarios.py    23 tests, one per claim the deck makes
data/                      the mock CRM workbook
```

---

## Wiring up the real Dialogflow agent

```bash
pip install google-cloud-dialogflow
export GOOGLE_APPLICATION_CREDENTIALS=/path/to/key.json
export DIALOGFLOW_PROJECT_ID=your-project-id

python -m nlu.dialogflow_setup --dry-run   # preview
python -m nlu.dialogflow_setup             # create 5 intents, 159 phrases
```

Order numbers and category words in every training phrase are annotated
automatically, which is what lets Dialogflow extract entities at runtime
rather than only matching the intent. Doing that by hand for 159 phrases is
where the typos come from.

Then re-derive the threshold for the new engine — the local sweep does not
transfer.

> Never commit the service-account key. `.gitignore` already excludes the
> usual filenames, but check before you push.
