"""
Getting audio into the shape Vosk expects: 16 kHz, mono, 16-bit PCM.

Almost nothing produces that by default - phone recordings are 44.1 kHz
stereo, Windows Voice Recorder gives 48 kHz - and Vosk's failure mode when
fed the wrong format is not an error, it is a transcript of plausible
nonsense. That is miserable to debug five minutes before a demo, so the
conversion happens here and unsupported input is rejected loudly.

Standard library only: wave for the container, audioop for the sample-rate
and channel conversion.
"""
import warnings
import wave
from pathlib import Path

with warnings.catch_warnings():
    # Deprecated in 3.11, removed in 3.13. Its absence is handled below, so
    # the warning is noise on every import.
    warnings.simplefilter("ignore", DeprecationWarning)
    try:
        import audioop
    except ImportError:  # pragma: no cover - gone in Python 3.13+
        audioop = None

TARGET_RATE = 16000
TARGET_WIDTH = 2
TARGET_CHANNELS = 1


class AudioError(RuntimeError):
    """The audio could not be read or converted."""


def read_wav(path):
    """Return (pcm_bytes, source_description) at 16 kHz mono 16-bit."""
    path = Path(path)
    if not path.exists():
        raise AudioError(f"Audio file not found: {path}")

    try:
        with wave.open(str(path), "rb") as wav:
            channels, width = wav.getnchannels(), wav.getsampwidth()
            rate = wav.getframerate()
            frames = wav.readframes(wav.getnframes())
    except wave.Error as exc:
        raise AudioError(
            f"{path.name} is not a readable WAV file ({exc}). Convert it: "
            f"ffmpeg -i {path.name} -ar 16000 -ac 1 output.wav"
        ) from exc

    described = f"{rate} Hz, {channels}ch, {width * 8}-bit"
    if not frames:
        raise AudioError(f"{path.name} contains no audio.")

    needs_work = (channels != TARGET_CHANNELS or width != TARGET_WIDTH
                  or rate != TARGET_RATE)
    if needs_work and audioop is None:
        raise AudioError(
            f"{path.name} is {described}; Vosk needs 16000 Hz mono 16-bit and "
            f"this Python has no audioop to convert it. Convert first: "
            f"ffmpeg -i {path.name} -ar 16000 -ac 1 out.wav"
        )

    if width != TARGET_WIDTH:
        frames = audioop.lin2lin(frames, width, TARGET_WIDTH)
    if channels == 2:
        frames = audioop.tomono(frames, TARGET_WIDTH, 0.5, 0.5)
    elif channels != 1:
        raise AudioError(
            f"{path.name} has {channels} channels; only mono and stereo are "
            f"supported."
        )
    if rate != TARGET_RATE:
        frames, _ = audioop.ratecv(
            frames, TARGET_WIDTH, TARGET_CHANNELS, rate, TARGET_RATE, None
        )
    return frames, described


def describe_target():
    return f"{TARGET_RATE} Hz, mono, {TARGET_WIDTH * 8}-bit PCM"
