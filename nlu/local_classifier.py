"""
Layer 1, offline: a self-contained intent classifier.

Why this exists
---------------
The project's NLU layer is Dialogflow ES. But Dialogflow needs a Google Cloud
project, a service account and network access, and a demo that dies when the
wifi does is not a demo. This module is a drop-in replacement that trains in
a few milliseconds from the same training phrases and returns the same
(intent, confidence, entities) contract, using nothing but the standard
library. Layer 2 cannot tell the two apart.

How it works
------------
A TF-IDF vector space model with nearest-centroid classification:

  1. Each phrase is tokenised into word unigrams, word bigrams, and character
     4-grams. The character n-grams are what make "refnd" still look like
     "refund" - typo tolerance without a spell checker.
  2. Order numbers are masked to a single <orderid> token, so the model
     learns the *shape* of the request rather than memorising order 4521.
  3. Each intent gets a centroid: the mean of its L2-normalised phrase
     vectors. Classification is cosine similarity against those centroids.

Confidence calibration
----------------------
Raw cosine similarity is not a probability, and an uncalibrated model that
reports 0.99 for "hello" would make the whole confidence-routing design
meaningless. So the score is blended with the margin over the runner-up
intent (an unsure classification is one where two intents score alike) and
then scaled against a reference computed by leave-one-out on the *training*
set only. The held-out validation set is never used for calibration - it is
only used to measure, in nlu/evaluate.py.
"""
import math
import re
from collections import defaultdict

from nlu import training_data as td

_WORD_RE = re.compile(r"[a-z0-9#]+")
_ORDER_RE = re.compile(td.ORDER_ID_PATTERN)

# Currency-ish amounts: "500", "rs 500", "₹12,000", "12000 rupees"
_AMOUNT_RE = re.compile(
    r"(?:(?:₹|rs\.?|inr)\s*([0-9][0-9,]*(?:\.[0-9]{1,2})?))"
    r"|(?:([0-9][0-9,]*(?:\.[0-9]{1,2})?)\s*(?:rupees|rs\.?|inr))",
    re.IGNORECASE,
)

CHAR_NGRAM = 4


def _mask(text):
    """Lowercase and replace concrete order numbers with a placeholder."""
    return _ORDER_RE.sub(" <orderid> ", text.lower())


def _tokenize(text):
    """Word unigrams + bigrams + character n-grams."""
    masked = _mask(text)
    words = _WORD_RE.findall(masked.replace("<orderid>", " orderidtok "))
    features = list(words)
    features += [f"{a}_{b}" for a, b in zip(words, words[1:])]
    for word in words:
        if len(word) > CHAR_NGRAM and not word.startswith("orderid"):
            padded = f"^{word}$"
            features += [
                padded[i:i + CHAR_NGRAM]
                for i in range(len(padded) - CHAR_NGRAM + 1)
            ]
    return features


def _l2_normalise(vec):
    norm = math.sqrt(sum(v * v for v in vec.values()))
    if norm == 0:
        return vec
    return {k: v / norm for k, v in vec.items()}


def _cosine(a, b):
    # Both inputs are L2-normalised, so the dot product is the cosine.
    if len(a) > len(b):
        a, b = b, a
    return sum(v * b.get(k, 0.0) for k, v in a.items())


class LocalIntentClassifier:
    """Nearest-centroid TF-IDF intent classifier with calibrated confidence."""

    def __init__(self):
        self.idf = {}
        self.centroids = {}
        # Confidence calibration, fitted on training data only (_calibrate).
        self.reference_similarity = 1.0
        self.temperature = 1.0
        self._trained = False

    # -- training ----------------------------------------------------------
    def fit(self, pairs=None):
        pairs = list(pairs if pairs is not None else td.training_pairs())
        docs = [(_tokenize(text), intent) for text, intent in pairs]

        # Inverse document frequency over the training corpus.
        doc_freq = defaultdict(int)
        for tokens, _ in docs:
            for token in set(tokens):
                doc_freq[token] += 1
        n_docs = len(docs)
        self.idf = {
            token: math.log((n_docs + 1) / (freq + 1)) + 1.0
            for token, freq in doc_freq.items()
        }

        # Per-document TF-IDF vectors, grouped by intent.
        by_intent = defaultdict(list)
        for tokens, intent in docs:
            by_intent[intent].append(self._vectorise(tokens))

        self.centroids = {
            intent: _l2_normalise(self._mean(vectors))
            for intent, vectors in by_intent.items()
        }
        self._trained = True
        self._calibrate(by_intent)
        return self

    @staticmethod
    def _mean(vectors):
        total = defaultdict(float)
        for vec in vectors:
            for key, value in vec.items():
                total[key] += value
        return {k: v / len(vectors) for k, v in total.items()}

    def _vectorise(self, tokens):
        term_freq = defaultdict(float)
        for token in tokens:
            term_freq[token] += 1.0
        vec = {
            token: (1.0 + math.log(count)) * self.idf.get(token, 1.0)
            for token, count in term_freq.items()
        }
        return _l2_normalise(vec)

    def _calibrate(self, by_intent):
        """Fit the confidence scale using the training set only.

        One quantity is measured: the median cosine similarity of a training
        phrase to its own intent's centroid *with that phrase left out*. That
        is what a typical correct match looks like when the model has not
        already memorised the phrase, and it becomes the reference the
        coverage term in classify() is measured against.

        The held-out validation set plays no part here. It is used only to
        measure the finished model, in nlu/evaluate.py - calibrating on it
        would make those numbers meaningless.
        """
        similarities = []
        for intent, vectors in by_intent.items():
            for i, vec in enumerate(vectors):
                others = vectors[:i] + vectors[i + 1:]
                if others:
                    loo_centroid = _l2_normalise(self._mean(others))
                    similarities.append(_cosine(vec, loo_centroid))

        if similarities:
            similarities.sort()
            self.reference_similarity = (
                similarities[len(similarities) // 2] or 1.0
            )

        # Softmax temperature, scaled to the data. Cosine similarities live in
        # a narrow band, so a temperature proportional to the reference is
        # what turns small score gaps into a usable spread of probabilities.
        self.temperature = max(1e-6, 0.30 * self.reference_similarity)

    # -- inference ---------------------------------------------------------
    def classify(self, text):
        """Return (intent_name, confidence, all_scores).

        intent_name is None when nothing scores above the noise floor, which
        is the honest answer for a message the agent was never trained on.
        """
        if not self._trained:
            self.fit()

        query = self._vectorise(_tokenize(text))
        scores = {
            intent: _cosine(query, centroid)
            for intent, centroid in self.centroids.items()
        }
        ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
        top_intent, top_score = ranked[0]
        runner_up = ranked[1][1] if len(ranked) > 1 else 0.0

        if top_score <= 1e-6:
            return None, 0.0, scores

        # Confidence has to answer two different questions, so it is the
        # product of two terms:
        #
        #   certainty - a temperature-scaled softmax over the intent scores:
        #       "given that this is a supported request, which intent is it?"
        #       Near 1.0 when one intent clearly wins, near 1/5 when several
        #       score alike.
        #   coverage  - the top similarity measured against the reference
        #       fitted in _calibrate: "is this anything the agent was trained
        #       on at all?" This is the term that keeps untrained messages
        #       ("hello", "something's wrong with my stuff") low instead of
        #       confidently mislabelled, because softmax alone will happily
        #       report 0.9 for the best of five equally bad matches.
        #
        # A message needs both to be automated, which is exactly the
        # fail-safe behaviour the routing layer depends on.
        shifted = {k: (v - top_score) / self.temperature for k, v in scores.items()}
        exponentials = {k: math.exp(v) for k, v in shifted.items()}
        certainty = exponentials[top_intent] / sum(exponentials.values())
        coverage = min(1.0, top_score / self.reference_similarity)

        confidence = min(0.99, certainty * coverage)
        return top_intent, round(confidence, 4), scores


# ---------------------------------------------------------------------------
# Entity extraction
# ---------------------------------------------------------------------------
def extract_entities(text):
    """Pull order_id, amount and appliance category out of raw text."""
    entities = {}

    order_match = _ORDER_RE.search(text)
    if order_match:
        entities["order_id"] = order_match.group(1)

    amount_match = _AMOUNT_RE.search(text)
    if amount_match:
        raw = amount_match.group(1) or amount_match.group(2)
        try:
            entities["amount"] = float(raw.replace(",", ""))
        except ValueError:
            pass
    else:
        # A bare number that is clearly not an order id, e.g. "refund of 500".
        for candidate in re.findall(r"\b([0-9][0-9,]{2,})\b", text):
            cleaned = candidate.replace(",", "")
            if _ORDER_RE.fullmatch(cleaned):
                continue
            try:
                entities["amount"] = float(cleaned)
            except ValueError:
                pass
            break

    lowered = text.lower()
    for category, synonyms in td.CATEGORY_ENTITY.items():
        for synonym in sorted(synonyms, key=len, reverse=True):
            if re.search(rf"(?<![a-z]){re.escape(synonym)}(?![a-z])", lowered):
                entities["category"] = category
                break
        if "category" in entities:
            break

    return entities


# A single shared, lazily trained instance.
_CLASSIFIER = None


def get_classifier():
    global _CLASSIFIER
    if _CLASSIFIER is None:
        _CLASSIFIER = LocalIntentClassifier().fit()
    return _CLASSIFIER


def detect_intent(text):
    """Mirror the Dialogflow client contract exactly."""
    intent, confidence, _ = get_classifier().classify(text)
    return {
        "text": text,
        "intent": intent,
        "confidence": confidence,
        "entities": extract_entities(text),
        "engine": "local",
    }
