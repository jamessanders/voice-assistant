import argparse
import asyncio
import os
from concurrent.futures import ThreadPoolExecutor

import numpy as np
from fastapi import FastAPI, File, UploadFile, Form
import uvicorn

BACKEND = os.environ.get("TRANSCRIPTION_BACKEND", "cohere").lower()
MODEL_ID = os.environ.get("MODEL_ID", "CohereLabs/cohere-transcribe-03-2026")
WHISPER_MODEL = os.environ.get("WHISPER_MODEL", "base")
LANGUAGE = os.environ.get("TRANSCRIPTION_LANGUAGE", "en")

app = FastAPI()
executor = ThreadPoolExecutor(max_workers=1)

# Populated at startup depending on BACKEND
_processor = None
_model = None


# -- Cohere (HuggingFace transformers) ----------------------------------------

def _load_cohere():
    global _processor, _model
    import torch
    from transformers import AutoProcessor, CohereAsrForConditionalGeneration

    if not os.environ.get("HF_TOKEN"):
        print(
            "WARNING: HF_TOKEN is not set. The Cohere model is gated — you must:\n"
            "  1. Accept the terms at https://huggingface.co/CohereLabs/cohere-transcribe-03-2026\n"
            "  2. Set HF_TOKEN=<your token> (from https://huggingface.co/settings/tokens)\n"
            "     or run: huggingface-cli login"
        )

    print(f"Loading Cohere model '{MODEL_ID}'...")
    _processor = AutoProcessor.from_pretrained(MODEL_ID)
    _model = CohereAsrForConditionalGeneration.from_pretrained(MODEL_ID, device_map="auto")
    _model.eval()
    print(f"Cohere model loaded on {_model.device}")


def _infer_cohere(samples: np.ndarray, sample_rate: int) -> str:
    import torch
    inputs = _processor(samples, sampling_rate=sample_rate, return_tensors="pt", language=LANGUAGE)
    inputs = inputs.to(_model.device, dtype=_model.dtype)
    with torch.no_grad():
        outputs = _model.generate(**inputs, max_new_tokens=256)
    return _processor.decode(outputs[0], skip_special_tokens=True)


# -- Whisper ------------------------------------------------------------------

def _load_whisper():
    global _model
    import whisper
    print(f"Loading Whisper model '{WHISPER_MODEL}'...")
    _model = whisper.load_model(WHISPER_MODEL)
    print("Whisper model loaded.")


def _infer_whisper(samples: np.ndarray, sample_rate: int) -> str:
    result = _model.transcribe(samples, language=LANGUAGE, fp16=False)
    return result["text"]


# -- Dispatch -----------------------------------------------------------------

def _run_inference(samples: np.ndarray, sample_rate: int) -> str:
    if BACKEND == "whisper":
        return _infer_whisper(samples, sample_rate)
    return _infer_cohere(samples, sample_rate)


@app.post("/transcribe")
async def transcribe(
    audio: UploadFile = File(...),
    sample_rate: int = Form(16000),
):
    raw = await audio.read()
    samples = np.frombuffer(raw, dtype=np.float32)
    loop = asyncio.get_event_loop()
    text = await loop.run_in_executor(executor, _run_inference, samples, sample_rate)
    return {"text": text.strip()}


def main():
    parser = argparse.ArgumentParser(description="Transcription service (cohere or whisper)")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8787)
    args = parser.parse_args()

    if BACKEND == "whisper":
        _load_whisper()
    else:
        _load_cohere()

    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
