import argparse
import io
import os
import wave

import httpx
import numpy as np
from fastapi import FastAPI, File, UploadFile, Form
import uvicorn

COHERE_API_KEY = os.environ.get("COHERE_API_KEY", "")
COHERE_MODEL = os.environ.get("COHERE_MODEL", "cohere-transcribe-03-2026")
LANGUAGE = os.environ.get("TRANSCRIPTION_LANGUAGE", "en")

app = FastAPI()


def pcm_to_wav(raw: bytes, sample_rate: int) -> bytes:
    """Convert raw float32 PCM bytes to a 16-bit mono WAV file in memory."""
    samples = np.frombuffer(raw, dtype=np.float32)
    pcm16 = (np.clip(samples, -1.0, 1.0) * 32767).astype(np.int16)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm16.tobytes())
    return buf.getvalue()


@app.post("/transcribe")
async def transcribe(
    audio: UploadFile = File(...),
    sample_rate: int = Form(16000),
):
    raw = await audio.read()
    wav_bytes = pcm_to_wav(raw, sample_rate)

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            "https://api.cohere.com/v2/audio/transcriptions",
            headers={"Authorization": f"Bearer {COHERE_API_KEY}"},
            files={"file": ("audio.wav", wav_bytes, "audio/wav")},
            data={"model": COHERE_MODEL, "language": LANGUAGE},
        )
        resp.raise_for_status()
        return {"text": resp.json().get("text", "").strip()}


def main():
    parser = argparse.ArgumentParser(description="Cohere transcription service")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8787)
    args = parser.parse_args()

    if not COHERE_API_KEY:
        raise RuntimeError("COHERE_API_KEY environment variable is not set")

    print(f"Cohere transcription service ready (model: {COHERE_MODEL}, language: {LANGUAGE})")
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
