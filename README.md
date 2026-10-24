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
- `backend/app/schemas.py`: response schema consumed by the frontend.

`POST /api/analyze` accepts multipart form data with exactly one of `file` (PDF or TXT) or `text` (pasted notice content). It returns `title`, `summary`, `summary_evidence`, `audience`, `audience_evidence`, `deadlines`, `checklist`, `missing_information`, and `source_text`. Evidence is displayed only when its quote appears verbatim in extracted source text. A deadline without a verifiable quote is omitted; a normalized date is shown only when that exact ISO date appears in its source quote. Other date formats are left for the student to interpret.

## Configuration

Copy `.env.example` to `.env` at the repository root. Supported settings:

| Variable | Default | Meaning |
|---|---|---|
| `OLLAMA_URL` | `http://localhost:11434` | Local Ollama base URL |
| `OLLAMA_MODEL` | `qwen3:4b` | Local model tag used for inference |
| `OLLAMA_TIMEOUT_SECONDS` | `180` | Request timeout for generation |
| `MAX_UPLOAD_MB` | `10` | Maximum PDF/TXT upload size |
| `MAX_TEXT_CHARS` | `100000` | Maximum extracted or pasted text length |
| `CORS_ORIGINS` | Vite localhost origins | Comma-separated browser origins allowed to call the API |

## Tests and checks

From the repository root:

```powershell
cd .\backend
.\.venv\Scripts\python.exe -m pytest -q
cd ..\frontend
npm run build
npm run lint
```

Backend tests mock the Ollama HTTP response; they verify request formation and response handling without invoking a model. To verify real local inference, start the API and submit a real notice from the UI or use the API directly. Model output can vary, so always review important dates and requirements against the source.

## Limitations and troubleshooting

- OCR is not supported. Scanned/image-only PDFs return an explicit message asking for a text-based PDF or pasted text.
- Q&A is not included in this MVP.
- The model may omit facts or produce unsupported interpretations. Evidence quotes are checked literally; a quote that does not match is removed and the associated fact is flagged, but model output still needs human review.
- Health reports whether Ollama is reachable and the model tag is listed. It does not guarantee a successful generation; the first actual inference can still fail or time out.
- **“Could not reach NoticeLens”**: start the API and check `http://localhost:8000/api/health`.
- **Model not listed / model not found**: run `ollama pull qwen3:4b`, or set `OLLAMA_MODEL` to a model already in `ollama list`.
- **CORS error**: add the frontend origin to `CORS_ORIGINS`, then restart the API.
- **Slow analysis**: the first model load can take time; increase `OLLAMA_TIMEOUT_SECONDS` or use a shorter notice.

## License

MIT. See [LICENSE](LICENSE).
