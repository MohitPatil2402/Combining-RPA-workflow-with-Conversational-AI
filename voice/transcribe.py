"""
Layer 0: speech to text, offline, with Vosk.

Sits in front of Layer 1. The customer speaks, this turns it into the same
plain text a typed message would be, and Layers 1-3 are unchanged. Voice is
an input mode, not a second pipeline.

Vosk is optional, handled the way Dialogflow is: if the package or model is
missing, availability() says so in a sentence you can act on and everything
else keeps working.

Two measures matter, and both are about order numbers:

  Grammar constraining - Vosk is told the vocabulary to expect, built from
      the same training phrases the classifier learns from. Unconstrained,
      "order 4521" is routinely heard as "order for five to one".

  Digit recovery - whatever Vosk returns goes through
      voice.numbers.normalise_transcript. See that module; it is the part
      most likely to decide whether a voice demo works.
"""
import json
from pathlib import Path

import config
from voice import numbers
from voice.audio import read_wav

SAMPLE_RATE = 16000


class VoiceUnavailable(RuntimeError):
    """Vosk is not installed, or the model is missing."""


def availability():
    """Return (is_available, reason). Never raises, so callers can branch."""
    try:
        import vosk  # noqa: F401
    except ImportError:
        return False, ("the vosk package is not installed "
                       "(pip install vosk sounddevice)")
    model_path = Path(config.VOSK_MODEL_PATH)
    if not model_path.exists():
        return False, (
            f"speech model not found at {model_path} - either run "
            f"python scripts/download_vosk_model.py, or point "
            f"VOSK_MODEL_PATH at the copy you already have"
        )
    return True, "ready"


def is_available():
    return availability()[0]


def _require():
    available, reason = availability()
    if not available:
        raise VoiceUnavailable(reason)


def build_grammar():
    """The vocabulary to constrain recognition to.

    Everything the classifier was trained on, plus the words used to read a
    number aloud. Restricting Vosk to this makes spoken order numbers far
    likelier to survive, at the cost of transcribing unrelated speech
    poorly - the right trade for a scoped assistant, and low-confidence
    input escalates anyway.
    """
    from nlu import training_data as td

    vocabulary = set()
    for phrases in td.TRAINING_PHRASES.values():
        for phrase in phrases:
            vocabulary.update(w.strip("?#.,!").lower() for w in phrase.split())
    for phrase in td.OUT_OF_SCOPE_PHRASES:
        vocabulary.update(w.strip("?#.,!").lower() for w in phrase.split())
    for synonyms in td.CATEGORY_ENTITY.values():
        for synonym in synonyms:
            vocabulary.update(synonym.lower().split())

    vocabulary |= set(numbers.STRICT_WORDS)
    vocabulary |= set(numbers.HOMOPHONES)
    vocabulary |= set(numbers.REPEATERS)
    vocabulary = {w for w in vocabulary if w and not w.isdigit()}
    return json.dumps([" ".join(sorted(vocabulary)), "[unk]"])


def _recognizer(use_grammar):
    import vosk

    vosk.SetLogLevel(-1)   # Vosk is extremely chatty on stderr by default
    model = vosk.Model(str(config.VOSK_MODEL_PATH))
    if use_grammar:
        return vosk.KaldiRecognizer(model, SAMPLE_RATE, build_grammar())
    return vosk.KaldiRecognizer(model, SAMPLE_RATE)


def _finish(recognizer):
    """Return (raw, normalised).

    Both are kept because the difference is worth seeing: "order four five
    two one" becoming "order 4521" is the step that makes voice usable, and
    hiding it makes the system look like it simply guessed correctly.
    """
    result = json.loads(recognizer.FinalResult())
    raw = result.get("text", "")
    return raw, numbers.normalise_transcript(raw)


def transcribe_file(path, use_grammar=True):
    """Transcribe a WAV file. Any sample rate or channel count."""
    _require()
    pcm, described = read_wav(path)
    recognizer = _recognizer(use_grammar)
    chunk = 4000
    for start in range(0, len(pcm), chunk):
        recognizer.AcceptWaveform(pcm[start:start + chunk])
    raw, text = _finish(recognizer)
    return {"text": text, "raw": raw, "source": f"file:{Path(path).name}",
            "audio_format": described, "grammar": use_grammar}


def transcribe_microphone(seconds=6, use_grammar=True, on_start=None):
    """Record from the default microphone and transcribe it."""
    _require()
    try:
        import sounddevice
    except ImportError as exc:
        raise VoiceUnavailable(
            "the sounddevice package is not installed "
            "(pip install sounddevice). --audio <file.wav> works without it."
        ) from exc

    if on_start:
        on_start(seconds)
    recording = sounddevice.rec(int(seconds * SAMPLE_RATE),
                                samplerate=SAMPLE_RATE, channels=1,
                                dtype="int16")
    sounddevice.wait()

    recognizer = _recognizer(use_grammar)
    recognizer.AcceptWaveform(bytes(recording))
    raw, text = _finish(recognizer)
    return {"text": text, "raw": raw, "source": "microphone",
            "audio_format": f"{SAMPLE_RATE} Hz, mono, 16-bit",
            "grammar": use_grammar}


def describe():
    available, reason = availability()
    return ("Vosk (offline speech recognition)" if available
            else f"NOT READY: {reason}")
