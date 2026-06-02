# 🎙️ Meeting Transcription System

**Desktop transcription with configurable speech-to-text and AI summaries.**

A live meeting transcription system that captures audio from Zoom, Google Meet, Teams, or any online meeting. It can transcribe speech in real-time using either OpenAI-compatible speech-to-text APIs or local faster-whisper, detects speakers, optionally translates speech to English, and generates AI-powered meeting summaries using either OpenAI-compatible APIs or local Ollama.

## ✨ Features

- **Configurable transcription pipeline** — use OpenAI-compatible speech-to-text or local faster-whisper
- **Real-time transcription** — live speech-to-text as the meeting happens
- **Provider choice** — OpenAI-compatible APIs for transcription and summaries, or local engines where available
- **GPU auto-detection** — uses CUDA float16 when available, int8 on CPU
- **System audio capture** — records meeting audio from PulseAudio/PipeWire
- **Microphone support** — optionally captures your mic audio too
- **Multilingual** — automatically translates any language to English
- **Normal English output** — mixed-language speech is routed into readable English for both live capture and uploaded files
- **Anti-hallucination** — never fabricates words, marks unclear audio as `[unclear]`
- **Speaker detection** — identifies speaker changes (Speaker 1, Speaker 2, etc.)
- **Configurable summaries** — OpenAI-compatible APIs or Ollama, with a built-in local fallback
- **Timestamped transcript** — every segment includes a timestamp
- **Export formats** — TXT, Markdown, DOCX, PDF
- **Meeting history** — browse and review past meetings

## 🚀 Quick Start

### 1. System Dependencies
```bash
sudo apt install ffmpeg portaudio19-dev pulseaudio-utils
```

### 2. Python Setup
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r backend/requirements.txt
```

### 3. Configure providers
For OpenAI-compatible transcription and summaries:
```bash
cp .env.example .env
# then set OPENAI_API_KEY in .env
```

If you want fully local transcription instead, set:
```bash
TRANSCRIBE_ENGINE=faster-whisper
```

For fully local summaries with Ollama instead:
```bash
curl -fsSL https://ollama.com/install.sh | sh
ollama pull llama3.1
```

### 4. Start the Server
```bash
source venv/bin/activate
cd backend && python main.py
```

### 5. Open the UI
Navigate to **http://localhost:8000**

### 6. Create a public share link
If the backend is already running on port `8000`, you can expose it temporarily with:
```bash
./scripts/share-public.sh
```

This prints an `https://...ngrok-free.app` URL you can share.

Important:
- The link is temporary and changes when you restart the tunnel.
- Live meeting capture still uses the audio devices on the server machine.
- Uploaded-file transcription works well for remote users over the public link.

## 🌍 Hosted Deployment

This repo now supports a proper hosted mode for public deployment:

- **Server-side auth** protects API routes and WebSocket access with signed sessions
- **Hosted mode** disables Linux-only local audio capture features that do not work from a cloud server
- **Uploaded-file transcription** remains available for shared/public use
- **Free Render option** is available, with ephemeral storage tradeoffs

### Render deployment

Files included for deployment:

- `Dockerfile`
- `render.yaml`
- `.dockerignore`

Recommended environment values for hosted mode:

```bash
APP_MODE=hosted
AUTH_REQUIRED=true
AUTH_USERNAME=your-admin-name
AUTH_PASSWORD=your-strong-password
SESSION_SECRET=generate-a-random-secret
OPENAI_API_KEY=your-provider-key
OPENAI_BASE_URL=https://openrouter.ai/api/v1
```

### Free Render mode

The included `render.yaml` is set up for a free Render web service.

Tradeoffs in the free setup:

- the service can sleep after inactivity
- local files are ephemeral
- SQLite meeting history and export files can disappear after restart or redeploy
- uploaded-file transcription still works, but stored records are not durable

### Hosted-mode limitation

Cloud hosting does **not** let each visitor capture their own Zoom/Meet/system audio through your server.

In hosted mode, this app is designed for:

- uploading audio/video meeting recordings
- generating transcripts and summaries
- reviewing meeting history
- exporting transcript and summary files

## ⚙️ Environment Variables

All settings in `.env` (copy from `.env.example`):

| Variable | Default | Description |
|----------|---------|-------------|
| `TRANSCRIBE_ENGINE` | `openai` | Transcription engine: `openai` or `faster-whisper` |
| `OPENAI_TRANSCRIPTION_MODEL` | `openai/gpt-4o-mini-transcribe` | OpenAI-compatible speech-to-text model for the GPT-4o mini family |
| `OPENAI_TRANSCRIPTION_CHUNK_SECONDS` | `20` | Uploaded-file chunk size used to preserve timeline segments |
| `OPENAI_TRANSCRIPTION_MAX_RETRIES` | `2` | Retries for transient upstream provider failures such as 502/503 |
| `OPENAI_TRANSCRIPT_POLISH` | `true` | Runs a text-only cleanup pass on long uploaded transcripts to improve readability without summarizing |
| `OPENAI_TRANSCRIPT_POLISH_MIN_CHARS` | `600` | Minimum transcript length before the readability polish pass runs |
| `OPENAI_TRANSCRIPTION_PROMPT` | built-in clear-English prompt | Keeps mixed-language speech rendered in normal English without summarizing |
| `WHISPER_MODEL` | `large-v3` | Local model size when using `faster-whisper` |
| `WHISPER_TASK` | `translate` | `translate` (→ English) or `transcribe` (keep original) |
| `WHISPER_DEVICE` | `auto` | `auto`, `cpu`, or `cuda` |
| `WHISPER_COMPUTE_TYPE` | `auto` | `auto`, `float16`, `int8`, `int8_float16` |
| `APP_MODE` | `desktop` | `desktop` for local capture, `hosted` for public deployment |
| `AUTH_REQUIRED` | `false` locally / `true` in hosted mode | Enables backend session auth |
| `AUTH_USERNAME` | `admin` | Username for hosted login |
| `AUTH_PASSWORD` | empty | Password for hosted login |
| `SESSION_SECRET` | empty | Secret used to sign session cookies |
| `PUBLIC_BASE_URL` | empty | Optional canonical public URL |
| `AUDIO_CHUNK_SECONDS` | `5` | Audio chunk duration |
| `SUMMARY_ENGINE` | `openai` | Summary engine: `openai` or `ollama` |
| `SUMMARY_MODEL` | `gpt-5.4-mini` | Summary model ID |
| `OPENAI_API_KEY` | empty | OpenAI or OpenAI-compatible API key |
| `OPENAI_BASE_URL` | `https://api.openai.com/v1` | Override for OpenAI-compatible routers |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama API endpoint when using `ollama` |
| `CONFIDENCE_THRESHOLD` | `0.4` | Below this → marked `[unclear]` |
| `NO_SPEECH_THRESHOLD` | `0.6` | Silence detection strictness |

### Switching local whisper models if `large-v3` is too slow
Edit `.env`:
```
WHISPER_MODEL=medium
```
Model accuracy ranking: `large-v3` > `medium` > `small` > `base` > `tiny`

## 🧪 Testing Steps

1. Start the server: `cd backend && python main.py`
2. Open `http://localhost:8000`
3. Enter meeting title
4. Click **Start Transcription**
5. Play any audio (YouTube, Zoom, etc.) — transcript appears in real-time
6. Click **Stop Transcription** → summary generates via the configured provider or the built-in fallback
7. Export transcript/summary in any format
8. If `TRANSCRIBE_ENGINE=openai`, confirm `OPENAI_API_KEY` is set before testing live or uploaded transcription

### Testing hosted mode locally
```bash
APP_MODE=hosted AUTH_REQUIRED=true AUTH_USERNAME=admin AUTH_PASSWORD=changeme SESSION_SECRET=test-secret \
source venv/bin/activate && cd backend && python main.py
```

Then open `http://localhost:8000`, sign in, and test uploaded-file transcription.

### Testing System Audio Capture
```bash
# List available audio sources
pactl list sources short

# Look for a source ending in .monitor (e.g., alsa_output.*.monitor)
# This is what captures system/meeting audio
```

## ⚠️ Limitations

1. **System audio** requires PulseAudio or PipeWire (Linux)
2. **Speaker detection** is energy-based heuristic — works best with clear turns
3. **Local faster-whisper** still has a warm-up cost when you choose that engine
4. **GPU recommended** for `large-v3`; use `medium` on CPU if too slow
5. **OpenAI-compatible transcription** needs a valid API key and compatible base URL
6. **Best summaries** use your configured provider; if unavailable, the app falls back to a deterministic extractive summary
7. **Overlapping speech** detection is limited with heuristic approach
8. **No Windows/macOS** system audio capture (PulseAudio is Linux-only)
9. **Hosted mode** is upload-first by design; live capture stays a desktop-only feature

## 📁 Project Structure

```
├── backend/
│   ├── main.py                 # FastAPI app entry point
│   ├── config.py               # Environment config (GPU auto-detect)
│   ├── requirements.txt        # Python dependencies
│   ├── models/database.py      # SQLite models
│   ├── routes/
│   │   ├── transcription.py    # WebSocket streaming
│   │   ├── meetings.py         # Meeting CRUD
│   │   └── export.py           # Export downloads
│   └── services/
│       ├── audio_capture.py    # PulseAudio system audio + mic
│       ├── transcription.py    # OpenAI-compatible or faster-whisper transcription
│       ├── speaker_detect.py   # Speaker change detection
│       ├── post_process.py     # Text cleaning
│       ├── summary.py          # OpenAI-compatible / Ollama summaries
│       └── export.py           # TXT/DOCX/PDF/MD export
├── frontend/
│   ├── index.html
│   ├── css/styles.css
│   └── js/{app,websocket,export}.js
├── .env.example                # Environment template
├── .env                        # Your config
└── README.md
```
