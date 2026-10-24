from io import BytesIO

from fastapi import HTTPException, UploadFile
from pypdf import PdfReader

from .config import settings


async def extract_notice(file: UploadFile | None, text: str | None) -> tuple[str, str]:
    if file is None:
        value = (text or "").strip()
        if not value:
            raise HTTPException(status_code=422, detail="Provide notice text or upload a PDF/TXT file.")
        if len(value) > settings.max_text_chars:
            raise HTTPException(status_code=413, detail=f"Pasted text exceeds the {settings.max_text_chars:,} character limit.")
        return value, "Pasted notice"

    filename = file.filename or "notice"
    extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if extension not in {"pdf", "txt"}:
        raise HTTPException(status_code=415, detail="Unsupported file type. Upload a PDF or TXT file.")
    content = await file.read(settings.max_upload_mb * 1024 * 1024 + 1)
    if not content:
        raise HTTPException(status_code=422, detail="The uploaded file is empty.")
    if len(content) > settings.max_upload_mb * 1024 * 1024:
        raise HTTPException(status_code=413, detail=f"File exceeds the {settings.max_upload_mb} MB limit.")

    if extension == "txt":
        try:
            extracted = content.decode("utf-8-sig").strip()
        except UnicodeDecodeError as exc:
            raise HTTPException(status_code=422, detail="TXT files must use UTF-8 text encoding.") from exc
    else:
        try:
            reader = PdfReader(BytesIO(content))
            extracted = "\n".join(page.extract_text() or "" for page in reader.pages).strip()
        except Exception as exc:
            raise HTTPException(status_code=422, detail="This PDF could not be read. Check that it is a valid, unencrypted PDF.") from exc
        if not extracted:
            raise HTTPException(status_code=422, detail="No selectable text was found. This may be a scanned/image-only PDF; OCR is not supported yet.")

    if not extracted:
        raise HTTPException(status_code=422, detail="The document contains no readable text.")
    if len(extracted) > settings.max_text_chars:
        raise HTTPException(status_code=413, detail=f"Extracted notice exceeds the {settings.max_text_chars:,} character limit.")
    return extracted, filename
