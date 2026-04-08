import asyncio
import json
import os
import time

import httpx
import numpy as np
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from openai import AsyncOpenAI
import uvicorn

TRANSCRIPTION_URL = os.environ.get("TRANSCRIPTION_URL", "http://localhost:8787")
LLM_URL = os.environ.get("LLM_URL", "http://localhost:1234/v1")
LLM_MODEL = os.environ.get("LLM_MODEL", "default-model")
TTS_URL = os.environ.get("TTS_URL", "http://localhost:5423")
TTS_VOICE = os.environ.get("TTS_VOICE", "af_heart")
TTS_SPEED = float(os.environ.get("TTS_SPEED", "1.0"))

# RMS energy threshold below which audio is treated as silence without calling
# the transcription model.  Tune via SILENCE_THRESHOLD env var (0.0 disables).
SILENCE_THRESHOLD = float(os.environ.get("SILENCE_THRESHOLD", "0.01"))


def _audio_is_silent(raw_bytes: bytes) -> bool:
    """Return True when the RMS energy of the audio is below SILENCE_THRESHOLD."""
    if SILENCE_THRESHOLD <= 0 or len(raw_bytes) < 4:
        return False
    samples = np.frombuffer(raw_bytes, dtype=np.float32)
    rms = float(np.sqrt(np.mean(samples ** 2)))
    return rms < SILENCE_THRESHOLD


WAKE_WORDS = ["computer"]
SAMPLE_RATE = 16000
MAX_LISTEN_SECONDS = 30

app = FastAPI()

script_dir = os.path.dirname(os.path.abspath(__file__))
static_dir = os.path.join(script_dir, "static")
app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.get("/")
async def index():
    return FileResponse(os.path.join(static_dir, "index.html"))


async def send_status(ws: WebSocket, status: str, text: str = ""):
    msg = {"type": "status", "status": status}
    if text:
        msg["text"] = text
    await ws.send_text(json.dumps(msg))


async def transcribe_audio(audio_bytes: bytes) -> str:
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            f"{TRANSCRIPTION_URL}/transcribe",
            files={"audio": ("chunk.pcm", audio_bytes, "application/octet-stream")},
            data={"sample_rate": str(SAMPLE_RATE)},
        )
        resp.raise_for_status()
        return resp.json().get("text", "")


SYSTEM_PROMPT = (
    "You are a helpful voice assistant on a public kiosk. "
    "Keep every response to 1-3 short sentences. "
    "Use plain, conversational language that sounds natural when spoken aloud. "
    "Avoid bullet points, lists, markdown, code blocks, URLs, or special formatting. "
    "Never spell out punctuation. Do not use abbreviations or acronyms unless they are commonly spoken. "
    "If a question requires a longer answer, give a brief summary and offer to elaborate."
)


async def query_llm(query: str, history: list[dict]) -> str:
    client = AsyncOpenAI(base_url=LLM_URL, api_key="not-needed")
    messages = [{"role": "system", "content": SYSTEM_PROMPT}] + history + [{"role": "user", "content": query}]
    response = await client.chat.completions.create(
        model=LLM_MODEL,
        messages=messages,
        max_tokens=200,
    )
    return response.choices[0].message.content


async def synthesize_speech(text: str) -> bytes:
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(
            f"{TTS_URL}/synthesize",
            json={"text": text, "voice": TTS_VOICE, "speed": TTS_SPEED},
        )
        resp.raise_for_status()
        return resp.content


def detect_wake_word(text: str) -> tuple[bool, str]:
    """Check if text starts with a wake word. Returns (found, remainder)."""
    text_lower = text.lower().strip()
    for word in WAKE_WORDS:
        if text_lower.startswith(word):
            remainder = text[len(word):].strip().lstrip(",").strip()
            return True, remainder
    return False, text


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    text_buffer = ""
    listening_for_command = False
    heard_content = False
    listen_start: float = 0
    history: list[dict] = []

    audio_inbox: asyncio.Queue[bytes | None] = asyncio.Queue()
    OVERLAP_BYTES = int(SAMPLE_RATE * 0.5) * 4  # 0.5 s of float32 samples
    previous_tail = b""

    async def process_query(query_text: str):
        nonlocal text_buffer, listening_for_command, heard_content, listen_start, previous_tail
        text_buffer = ""
        listening_for_command = False
        heard_content = False
        previous_tail = b""

        await ws.send_text(json.dumps({"type": "query", "text": query_text}))
        await send_status(ws, "thinking")

        try:
            llm_response = await query_llm(query_text, history)
        except Exception as e:
            print(f"LLM error: {e}")
            await send_status(ws, "idle", f"LLM error: {e}")
            return

        history.append({"role": "user", "content": query_text})
        history.append({"role": "assistant", "content": llm_response})

        await ws.send_text(json.dumps({"type": "response", "text": llm_response}))
        await send_status(ws, "speaking")

        try:
            audio_bytes = await synthesize_speech(llm_response)
            await ws.send_bytes(audio_bytes)
        except Exception as e:
            print(f"TTS error: {e}")

        if llm_response.rstrip().endswith("?"):
            await ws.send_text(json.dumps({"type": "ding"}))
            listening_for_command = True
            heard_content = False
            listen_start = time.monotonic()
            await send_status(ws, "listening", "Listening...")
        else:
            await send_status(ws, "idle")

    async def audio_receiver():
        """Continuously pull audio from the websocket into a queue."""
        try:
            while True:
                data = await ws.receive_bytes()
                await audio_inbox.put(data)
        except WebSocketDisconnect:
            await audio_inbox.put(None)

    async def audio_processor():
        nonlocal text_buffer, listening_for_command, heard_content, listen_start, previous_tail

        while True:
            first = await audio_inbox.get()
            if first is None:
                return

            # Merge all chunks that queued up while we were busy
            chunks = bytearray(first)
            while not audio_inbox.empty():
                try:
                    chunk = audio_inbox.get_nowait()
                except asyncio.QueueEmpty:
                    break
                if chunk is None:
                    return
                chunks.extend(chunk)

            new_audio = bytes(chunks)

            # Fast energy check — skip the (potentially slow) transcription model
            # entirely when the new audio is silent.
            if _audio_is_silent(new_audio):
                is_silence = True
                transcribed = ""
            else:
                # Prepend overlap from the previous call to bridge word boundaries
                audio_to_transcribe = previous_tail + new_audio

                if len(new_audio) > OVERLAP_BYTES:
                    previous_tail = new_audio[-OVERLAP_BYTES:]
                else:
                    previous_tail = new_audio

                try:
                    transcribed = await transcribe_audio(audio_to_transcribe)
                except Exception as e:
                    print(f"Transcription error: {e}")
                    if not listening_for_command:
                        await send_status(ws, "idle")
                    continue

                is_silence = not transcribed.strip()

            if listening_for_command:
                now = time.monotonic()
                timed_out = (now - listen_start) > MAX_LISTEN_SECONDS

                if not is_silence:
                    text_buffer = f"{text_buffer} {transcribed}".strip()
                    heard_content = True
                    await ws.send_text(json.dumps({
                        "type": "transcript",
                        "text": transcribed,
                    }))
                    if not timed_out:
                        await send_status(ws, "listening", "Listening...")
                        continue

                if (heard_content and is_silence) or timed_out:
                    _, query = detect_wake_word(text_buffer)
                    if len(query) >= 3:
                        await process_query(query)
                        continue

                await send_status(ws, "listening", "Listening...")
                continue

            await send_status(ws, "processing")

            if is_silence:
                await send_status(ws, "idle")
                continue

            await ws.send_text(json.dumps({
                "type": "transcript",
                "text": transcribed,
            }))
            text_buffer = transcribed

            found, remainder = detect_wake_word(text_buffer)

            if not found:
                text_buffer = ""
                await send_status(ws, "idle")
                continue

            await ws.send_text(json.dumps({"type": "ding"}))
            listening_for_command = True
            heard_content = len(remainder) >= 3
            listen_start = time.monotonic()
            await send_status(ws, "listening", "Listening...")

    receiver_task = asyncio.create_task(audio_receiver())
    try:
        await audio_processor()
    except WebSocketDisconnect:
        pass
    finally:
        receiver_task.cancel()
        print("Client disconnected")


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8080)
