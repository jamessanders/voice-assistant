import argparse
import io
import numpy as np
import whisper
from fastapi import FastAPI, File, UploadFile, Form
from fastapi.responses import JSONResponse
import uvicorn

app = FastAPI()
model = None


@app.post("/transcribe")
async def transcribe(
    audio: UploadFile = File(...),
    sample_rate: int = Form(16000),
):
    raw = await audio.read()
    samples = np.frombuffer(raw, dtype=np.float32)

    result = model.transcribe(samples, language="en", fp16=False)
    return {"text": result["text"].strip()}


def main():
    global model

    parser = argparse.ArgumentParser(description="Whisper transcription service")
    parser.add_argument("--model", default="base", help="Whisper model size (tiny, base, small, medium, large)")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8787)
    args = parser.parse_args()

    print(f"Loading Whisper model '{args.model}'...")
    model = whisper.load_model(args.model)
    print("Model loaded.")

    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
