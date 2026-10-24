from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .documents import extract_notice
from .ollama_client import analyze_notice, check_model

app = FastAPI(title="NoticeLens API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


@app.get("/api/health")
async def health():
    model_available, ollama_reachable, detail = await check_model()
    return {
        "api_status": "ok",
        "ollama_reachable": ollama_reachable,
        "model_available": model_available,
        "provider": "ollama",
        "model": settings.ollama_model,
        "detail": detail,
    }


@app.post("/api/analyze")
async def analyze(file: UploadFile | None = File(default=None), text: str | None = Form(default=None)):
    if file is not None and text and text.strip():
        raise HTTPException(status_code=422, detail="Provide either a file or pasted text, not both.")
    source, title = await extract_notice(file, text)
    result = await analyze_notice(source)
    payload = result.model_dump()
    payload["title"] = title if payload.get("title") in (None, "", "Notice analysis") else payload["title"]
    return payload
