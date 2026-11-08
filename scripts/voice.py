"""Speech in and out, both offline: whisper.cpp hears and Piper speaks."""
import io
import os
import re
import subprocess
import tempfile
import wave
from pathlib import Path

from common import ROOT

WHISPER = ROOT / "tools" / "whisper.cpp" / "bin" / "Release" / ("whisper-cli.exe" if os.name == "nt" else "whisper-cli")
WHISPER_MODEL = ROOT / "tools" / "whisper.cpp" / "models" / "ggml-base.en.bin"
VOICE = ROOT / "tools" / "piper" / "voices" / "en_GB-alan-medium.onnx"
# Priming whisper with the names it's most likely to mishear.
HINT = "Gandalf, Frodo, Bilbo, Sauron, Saruman, Aragorn, Mordor, Gondor, Rivendell, Gollum, Galadriel, Isildur, Silmarillion, Mount Doom, Middle-earth."


class Voice:
    def __init__(self):
        from piper import PiperVoice, SynthesisConfig

        self.config = SynthesisConfig(length_scale=1.1)
        self.piper = PiperVoice.load(str(VOICE))

    def hear(self, audio):
        """Turn audio bytes in any format ffmpeg reads into text."""
        with tempfile.TemporaryDirectory() as folder:
            source, target = Path(folder) / "in", Path(folder) / "in.wav"
            source.write_bytes(audio)
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(source), "-ar", "16000", "-ac", "1", str(target)], check=True)
            result = subprocess.run(
                [str(WHISPER), "-m", str(WHISPER_MODEL), "-f", str(target), "-nt", "-np", "-t", "6", "--prompt", HINT],
                check=True, capture_output=True, text=True, encoding="utf-8", cwd=WHISPER.parent,
            )
        text = " ".join(result.stdout.split())
        # Whisper marks silence and noise with tags like [BLANK_AUDIO], which aren't speech.
        return re.sub(r"\[[^\]]*\]|\([^)]*\)", "", text).strip()

    def speak(self, text):
        """Return WAV bytes."""
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as output:
            self.piper.synthesize_wav(text, output, syn_config=self.config)
        return buffer.getvalue()
