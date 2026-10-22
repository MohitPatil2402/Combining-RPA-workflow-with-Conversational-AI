"""
Turn spoken numbers back into digits.

This is the piece that decides whether voice input works at all. Speech
recognition returns words, so "where is my order 4521" comes back as one of:

    where is my order four five two one
    where is my order forty five twenty one
    where is my order four thousand five hundred twenty one
    where is my order four five oh nine

Every downstream step - the order_id regex, the CRM lookup, the routing rules
- needs "4521". Without this, a voice demo fails on the single most important
field in the whole system, and it fails silently: the intent classifies fine
and the order simply is not found.

It is deliberately a pure function over text, with no dependency on the
speech engine, so it can be tested exhaustively without a microphone.
"""
import re

UNITS = {
    "zero": 0, "nought": 0,
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9,
}

# Words that sound like digits but are ordinary English far more often.
# Mapping these unconditionally is a trap: it turns "refund for order 4521"
# into "refund 4 order 4521". They are only read as digits when they sit
# directly beside a spelled-out number word - see _is_active_homophone.
HOMOPHONES = {
    "for": 4, "fore": 4,
    "to": 2, "too": 2,
    "won": 1,
    "ate": 8, "tree": 3,
    "oh": 0, "o": 0,
}

TEENS = {
    "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
    "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18,
    "nineteen": 19,
}

TENS = {
    "twenty": 20, "thirty": 30, "forty": 40, "fourty": 40, "fifty": 50,
    "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
}

MULTIPLIERS = {"hundred": 100, "thousand": 1000}

# "double four" -> 44, "triple seven" -> 777. Common when reading a number
# aloud, and Vosk transcribes them literally.
REPEATERS = {"double": 2, "triple": 3, "treble": 3}

# Words that are unambiguously numeric wherever they appear.
STRICT_WORDS = set(UNITS) | set(TEENS) | set(TENS) | set(MULTIPLIERS)
NUMBER_WORDS = STRICT_WORDS | set(REPEATERS) | set(HOMOPHONES)

# Words that may sit inside a spoken number without ending it.
FILLERS = {"and"}

_TOKEN_RE = re.compile(r"[A-Za-z']+|\d+|[^\sA-Za-z\d]+|\s+")


def _value(token):
    """Numeric value of a single number word, or None."""
    token = token.lower()
    for table in (UNITS, TEENS, TENS, HOMOPHONES):
        if token in table:
            return table[token]
    return None


def _words_only(tokens):
    return [i for i, t in enumerate(tokens) if not t.isspace()]


def _is_active_homophone(tokens, index):
    """Is this "for"/"to"/"oh" actually a digit here?

    Only when an immediate neighbour is a spelled-out number word. A digit
    literal next door does not count: people say "refund for 4521", meaning
    the preposition, but nobody says "four" and then switches to numerals
    mid-number. That single distinction is what keeps ordinary English
    intact while still recovering "order for five one six" as 4516.
    """
    positions = _words_only(tokens)
    try:
        here = positions.index(index)
    except ValueError:
        return False
    for offset in (-1, 1):
        neighbour = here + offset
        if 0 <= neighbour < len(positions):
            word = tokens[positions[neighbour]].lower()
            if word in STRICT_WORDS or word in REPEATERS:
                return True
    return False


def _counts_as_number(tokens, index):
    token = tokens[index]
    lowered = token.lower()
    if token.isdigit() or lowered in STRICT_WORDS or lowered in REPEATERS:
        return True
    if lowered in HOMOPHONES:
        return _is_active_homophone(tokens, index)
    return False


def _arithmetic(words):
    """Parse a genuine spoken cardinal: four thousand five hundred twenty one."""
    total = current = 0
    for word in words:
        if word in FILLERS:
            continue
        if word in MULTIPLIERS:
            multiplier = MULTIPLIERS[word]
            current = (current or 1) * multiplier
            if multiplier >= 1000:
                total += current
                current = 0
            continue
        if word.isdigit():
            current += int(word)
            continue
        value = _value(word)
        if value is not None:
            current += value
    return total + current


def _run_to_digits(run):
    """Convert one run of consecutive number tokens into a digit string.

    Two different things get spoken and they need different handling:

      "four thousand five hundred twenty one"  -> arithmetic, 4521
      "four five two one"                      -> concatenation, 4521

    The presence of hundred/thousand is what distinguishes them.
    """
    words = [w.lower() for w in run]
    if any(w in MULTIPLIERS for w in words):
        return str(_arithmetic(words))

    digits = []
    index = 0
    while index < len(words):
        word = words[index]
        if word in FILLERS:
            index += 1
            continue
        if word in REPEATERS:
            times = REPEATERS[word]
            if index + 1 < len(words):
                repeated = _value(words[index + 1])
                if repeated is not None:
                    digits.append(str(repeated) * times)
                    index += 2
                    continue
            index += 1
            continue
        if word.isdigit():
            digits.append(word)
            index += 1
            continue
        value = _value(word)
        if value is None:
            index += 1
            continue
        # "forty" + "five" is one two-digit group, not "40" then "5".
        if word in TENS and index + 1 < len(words):
            following = _value(words[index + 1])
            if following is not None and 1 <= following <= 9:
                digits.append(str(value + following))
                index += 2
                continue
        digits.append(str(value))
        index += 1
    return "".join(digits)


def spoken_numbers_to_digits(text):
    """Rewrite spoken numbers in `text` as digit strings."""
    if not text:
        return text

    tokens = _TOKEN_RE.findall(text)
    output, run = [], []

    def flush():
        if run:
            output.append(_run_to_digits(run))
            run.clear()

    index = 0
    while index < len(tokens):
        token = tokens[index]
        if _counts_as_number(tokens, index):
            run.append(token)
            lookahead = index + 1
            while lookahead < len(tokens) and (
                tokens[lookahead].isspace()
                or tokens[lookahead].lower() in FILLERS
            ):
                lookahead += 1
            if lookahead < len(tokens) and _counts_as_number(tokens, lookahead):
                for skipped in tokens[index + 1:lookahead]:
                    if not skipped.isspace():
                        run.append(skipped)
                index = lookahead
                continue
            flush()
            index += 1
            continue
        flush()
        output.append(token)
        index += 1

    flush()
    return "".join(output)


def normalise_transcript(text):
    """Everything a raw speech transcript needs before the NLU sees it."""
    if not text:
        return ""
    return re.sub(r"\s+", " ", spoken_numbers_to_digits(text)).strip()
