# NoticeLens

NoticeLens turns university circulars into a concise summary, deadline list, and practical checklist. It uses a local Ollama model; uploaded and pasted notice content is sent only to the configured local Ollama instance and is not sent to a cloud AI provider by this application.

## Requirements

- Node.js and npm (frontend)
- Python 3.11 or newer (backend)
- Ollama installed and running locally
- The configured model pulled into Ollama (default: `qwen3:4b`)

## Windows PowerShell setup

Open three PowerShell windows from the repository root.

### 1. Prepare Ollama

```powershell
ollama serve
```

If Ollama is already running in the background, leave it running. In another terminal:

```powershell
ollama pull qwen3:4b
ollama list
```

### 2. Start the API

```powershell
cd .\backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item ..\.env.example ..\.env
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

The API health route is `http://localhost:8000/api/health`. It reports API status, Ollama reachability, and whether the configured model appears in Ollama's local model list; it does not run a generation as part of the health check. The UI labels this as model availability, not inference readiness.

### 3. Start the frontend

```powershell
cd .\frontend
npm install
npm run dev
```

Open the Vite URL printed in the terminal (normally `http://localhost:5173`). The frontend calls `http://localhost:8000` by default. To change that, create `frontend/.env.local` with:

```text
VITE_API_URL=http://localhost:8000
```

Restart Vite after changing environment configuration.

## Architecture

- `frontend/`: React + Vite interface for PDF/TXT upload, pasted notice text, summary, urgency-sorted deadlines, evidence excerpts, checklist completion/export, and ambiguity notes.
- `backend/app/main.py`: FastAPI health and analysis routes.
- `backend/app/documents.py`: input validation and TXT/PDF text extraction using `pypdf`.
- `backend/app/ollama_client.py`: local Ollama `/api/chat` calls, JSON validation, and exact evidence quote checks.
- `backend/app/notice_facts.py`: deterministic date/context, explicit date ranges, and payment-requirement candidates used to recover model omissions and flag ambiguity.
- `backend/app/schemas.py`: response schema consumed by the frontend.

For compact notice extraction, requests disable Qwen's optional thinking output, cap generation at `OLLAMA_NUM_PREDICT`, set an explicit context size, and retain the loaded runner for `OLLAMA_KEEP_ALIVE`. The response timeout includes cold model loading as well as generation; the loopback connection timeout is configured separately.

`POST /api/analyze` accepts multipart form data with exactly one of `file` (PDF or TXT) or `text` (pasted notice content). It returns `title`, `summary`, individually verified `summary_claims`, `summary_evidence`, `audience`, `audience_evidence`, `deadlines`, `checklist`, `missing_information`, and `source_text`. Quotes must match the extracted source (whitespace-only differences are normalized). Summary claims are accepted or rejected individually. Deterministic date candidates include nearby context and separate deadline, event, historical, and review-needed dates; normalized dates require a complete, valid source date. Payment amounts alone do not generate checklist actions; deterministic payment tasks require explicit action language such as “must bring” or “payable”.

## Configuration

Copy `.env.example` to `.env` at the repository root. Supported settings:

| Variable | Default | Meaning |
|---|---|---|
| `OLLAMA_URL` | `http://localhost:11434` | Local Ollama base URL |
| `OLLAMA_MODEL` | `qwen3:4b` | Local model tag used for inference |
| `OLLAMA_TIMEOUT_SECONDS` | `180` | Maximum wait for Ollama's response (includes cold loading and generation) |
| `OLLAMA_CONNECT_TIMEOUT_SECONDS` | `5` | Connection/pool timeout for the loopback request |
| `OLLAMA_NUM_CTX` | `4096` | Context size; matched to the current local runner and notice workflow |
| `OLLAMA_NUM_PREDICT` | `768` | Maximum generated tokens; bounded headroom for complete structured responses |
| `OLLAMA_KEEP_ALIVE` | `5m` | Keep a used model loaded briefly to avoid reloading between nearby notices |
| `MAX_UPLOAD_MB` | `10` | Maximum PDF/TXT upload size |
| `MAX_TEXT_CHARS` | `100000` | Maximum extracted or pasted text length |
| `CORS_ORIGINS` | Vite localhost origins | Comma-separated browser origins allowed to call the API |

## Tests and checks

From the repository root:

```powershell
cd .\backend
.\.venv\Scripts\python.exe -m pytest -q
cd ..\frontend
npm test
npm run build
npm run lint
```

Backend tests use a generic synthetic fixture, a test-only Spirit volleyball transcription made from facts supplied by the user (not extracted from the original PDF), and mocked Ollama responses. They verify evidence filtering, compact JSON expansion, date separation, PDF text extraction, API errors, and request formation without invoking a model; mocked responses do not establish that Qwen will produce the same output during real inference. The original PDF is not included in the repository; test with the original notice in the app when verifying real local inference, and review important facts against the source.

## Limitations and troubleshooting

- OCR is not supported. Scanned/image-only PDFs return an explicit message asking for a text-based PDF or pasted text.
- Q&A is not included in this MVP.
- The model may omit facts or produce unsupported interpretations. Unsupported summary claims and checklist actions are rejected individually; deterministic date and payment cues are safeguards, not a substitute for full notice understanding. Model output still needs human review.
- Health reports whether Ollama is reachable and the model tag is listed. It does not guarantee a successful generation; the first actual inference can still fail or time out.
- **“Could not reach NoticeLens”**: start the API and check `http://localhost:8000/api/health`.
- **Model not listed / model not found**: run `ollama pull qwen3:4b`, or set `OLLAMA_MODEL` to a model already in `ollama list`.
- **CORS error**: add the frontend origin to `CORS_ORIGINS`, then restart the API.
- **Slow analysis**: the first model load can take longer than warm requests. NoticeLens disables Qwen's optional thinking output and caps the response to a compact token budget; use a shorter notice if the API reports its response timeout.

## License

MIT. See [LICENSE](LICENSE).
