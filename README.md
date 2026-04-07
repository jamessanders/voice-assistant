# Distributed Voice Assistant

A browser-based voice assistant with a distributed architecture. Say "Computer" followed by a question, and it will transcribe your speech, send the query to an LLM, and read the response back to you.

## Architecture

```
Browser (mic + speaker)
    │ WebSocket
    ▼
backend/server.py (lightweight backend, any machine)
    │
    ├── POST /transcribe ──► transcription/transcription_service.py (Whisper)
    ├── POST /v1/chat/completions ──► LMStudio (LLM)
    └── POST /synthesize ──► tts/server.py (Kokoro TTS)
```

Three external services are expected to be running:

| Service | Purpose | Default URL |
|---|---|---|
| **Transcription service** | Whisper speech-to-text (included) | `http://localhost:8787` |
| **LMStudio** | OpenAI-compatible LLM | `http://localhost:1234/v1` |
| **Kokoro TTS** | Speech synthesis (included, see `tts/`) | `http://localhost:5423` |

## Prerequisites

- Python 3.10+
- [LMStudio](https://lmstudio.ai/) running with a model loaded and the local server started
- Kokoro TTS server (included in `tts/`, see its [README](tts/README.md))

## Quick Start

Each startup script automatically creates an isolated virtual environment and installs dependencies on first run. Just run the scripts -- no manual setup needed.

Start each component in its own terminal. The transcription service and external services should be ready before you start talking.

### Step 1: Start the transcription service

```bash
./transcription/start-transcription.sh
```

All flags are passed through to the underlying Python script:

```bash
./transcription/start-transcription.sh --model small --port 9000
```

| Flag | Default | Description |
|---|---|---|
| `--model` | `base` | Whisper model size: `tiny`, `base`, `small`, `medium`, `large` |
| `--host` | `0.0.0.0` | Bind address |
| `--port` | `8787` | Listen port |

### Step 2: Start LMStudio

Open LMStudio, load a model, and start the local server (defaults to port 1234).

### Step 3: Start Kokoro TTS

```bash
cd tts && docker compose up -d
```

Or run directly with Python:

```bash
cd tts && pip install -r requirements.txt && python server.py
```

The model (~88 MB) is downloaded automatically on first run and cached. See `tts/README.md` for configuration options.

### Step 4: Start the backend server

```bash
./backend/start-server.sh
```

If your services are on different machines, configure via environment variables:

```bash
TRANSCRIPTION_URL=http://gpu-box:8787 \
LLM_URL=http://gpu-box:1234/v1 \
LLM_MODEL=my-model-name \
TTS_URL=http://gpu-box:5423 \
TTS_VOICE=af_heart \
./backend/start-server.sh
```

## Manual Setup

If you prefer to manage your own virtualenvs instead of using the startup scripts:

```bash
# Transcription service
pip install -r transcription/requirements-transcription.txt
python transcription/transcription_service.py

# Backend server
pip install -r backend/requirements-server.txt
python backend/server.py
```

### Step 5: Open the UI

Navigate to [http://localhost:8080](http://localhost:8080) in your browser.

1. Click the microphone button to start listening
2. Say **"Computer"** followed by your question (e.g., "Computer, what time is it?")
3. The status orb shows the current state:
   - **Gray** — idle
   - **Green** — listening (wake word detected, waiting for your question)
   - **Yellow** — processing (sending audio to transcription)
   - **Blue** — thinking (waiting for LLM response)
   - **Purple** — speaking (playing back TTS audio)
4. The response is read back to you and displayed in the log

## Environment Variables

All configuration for `backend/server.py`:

| Variable | Default | Description |
|---|---|---|
| `TRANSCRIPTION_URL` | `http://localhost:8787` | URL of the Whisper transcription service |
| `LLM_URL` | `http://localhost:1234/v1` | OpenAI-compatible LLM endpoint |
| `LLM_MODEL` | `default-model` | Model name to request from the LLM |
| `TTS_URL` | `http://localhost:5423` | Kokoro TTS base URL |
| `TTS_VOICE` | `af_heart` | Voice name for Kokoro TTS |
| `TTS_SPEED` | `1.0` | TTS speech speed multiplier |

## File Structure

```
voice-assistant/
  backend/
    server.py                    # Backend + WebSocket orchestrator
    start-server.sh              # Startup script (creates venv, installs deps, runs)
    requirements-server.txt      # Backend dependencies
    static/
      index.html                 # Browser UI
      audio-processor.js         # AudioWorklet for mic capture
  transcription/
    transcription_service.py     # Whisper transcription API
    start-transcription.sh       # Startup script (creates venv, installs deps, runs)
    requirements-transcription.txt
  tts/
    server.py                    # Kokoro TTS HTTP server
    Dockerfile                   # Container build
    docker-compose.yml           # Local Docker setup
    requirements.txt             # TTS service dependencies

```
