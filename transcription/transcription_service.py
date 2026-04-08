import argparse
import asyncio
import os
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import torch
from transformers import AutoProcessor, CohereAsrForConditionalGeneration
from fastapi import FastAPI, File, UploadFile, Form
import uvicorn

MODEL_ID = os.environ.get("MODEL_ID", "CohereLabs/cohere-transcribe-03-2026")
LANGUAGE = os.environ.get("TRANSCRIPTION_LANGUAGE", "en")

app = FastAPI()
processor = None
model = None
executor = ThreadPoolExecutor(max_workers=1)


def _run_inference(samples: np.ndarray, sample_rate: int) -> str:
    inputs = processor(samples, sampling_rate=sample_rate, return_tensors="pt", language=LANGUAGE)
    inputs = inputs.to(model.device, dtype=model.dtype)
    with torch.no_grad():
        outputs = model.generate(**inputs, max_new_tokens=256)
    return processor.decode(outputs, skip_special_tokens=True)


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
    global processor, model

    parser = argparse.ArgumentParser(description="Cohere local transcription service")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8787)
    args = parser.parse_args()

    if not os.environ.get("HF_TOKEN"):
        print(
            "WARNING: HF_TOKEN is not set. The model is gated — you must:\n"
            "  1. Accept the terms at https://huggingface.co/CohereLabs/cohere-transcribe-03-2026\n"
            "  2. Set HF_TOKEN=<your token> (from https://huggingface.co/settings/tokens)\n"
            "     or run: huggingface-cli login"
        )

    print(f"Loading model '{MODEL_ID}'...")
    processor = AutoProcessor.from_pretrained(MODEL_ID)
    model = CohereAsrForConditionalGeneration.from_pretrained(MODEL_ID, device_map="auto")
    model.eval()
    print(f"Model loaded on {model.device}")

    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
