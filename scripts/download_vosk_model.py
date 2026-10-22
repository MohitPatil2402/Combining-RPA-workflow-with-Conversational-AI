"""
Fetch the Vosk speech model (~40 MB), if you do not already have one.

    python scripts/download_vosk_model.py

If you already have a model on disk, you do not need this - point
config.VOSK_MODEL_PATH or the VOSK_MODEL_PATH environment variable at it
instead.
"""
import sys
import urllib.request
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config  # noqa: E402

MODEL_NAME = "vosk-model-small-en-us-0.15"
MODEL_URL = f"https://alphacephei.com/vosk/models/{MODEL_NAME}.zip"


def _progress(count, block_size, total_size):
    if total_size <= 0:
        return
    done = count * block_size
    percent = min(100, done * 100 // total_size)
    sys.stdout.write(f"\r  [{'#' * (percent // 3):<33}] {percent:3d}%  "
                     f"{done / 1_048_576:.1f} / {total_size / 1_048_576:.1f} MB")
    sys.stdout.flush()


def main():
    target = Path(config.VOSK_MODEL_PATH)
    if target.exists():
        print(f"Model already present: {target}")
        return

    target.parent.mkdir(parents=True, exist_ok=True)
    archive = target.parent / f"{MODEL_NAME}.zip"
    print(f"Downloading {MODEL_NAME} (~40 MB)\n  from {MODEL_URL}")
    try:
        urllib.request.urlretrieve(MODEL_URL, archive, _progress)
        print()
    except Exception as exc:
        sys.exit(f"\nDownload failed: {exc}\nDownload it manually from "
                 f"{MODEL_URL} and unzip so this path exists:\n  {target}")

    print("Unpacking...")
    with zipfile.ZipFile(archive) as zf:
        zf.extractall(target.parent)
    archive.unlink()
    print(f"Ready: {target}\n\nTry it:  python demo.py --voice")


if __name__ == "__main__":
    main()
