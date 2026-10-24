import json
import asyncio

import httpx
import pytest
from fastapi.testclient import TestClient
from pypdf import PdfWriter
from io import BytesIO
from pydantic import ValidationError

from app.main import app
from app import ollama_client
from app.config import Settings


@pytest.fixture
def client():
    return TestClient(app)


def test_missing_input_is_rejected(client):
    response = client.post("/api/analyze", files={})
    assert response.status_code == 422
    assert "Provide notice text" in response.json()["detail"]


def test_ollama_endpoint_must_be_loopback():
    with pytest.raises(ValidationError, match="remote inference is not supported"):
        Settings(ollama_url="https://example.com")


def test_health_reports_model_availability_without_claiming_inference_ready(client, monkeypatch):
    async def fake_health():
        return True, True, None

    monkeypatch.setattr("app.main.check_model", fake_health)
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["model_available"] is True
    assert response.json()["ollama_reachable"] is True
    assert "inference_ready" not in response.json()


def test_unsupported_upload_is_rejected(client):
    response = client.post("/api/analyze", files={"file": ("notice.docx", b"content")})
    assert response.status_code == 415


def test_scanned_or_image_only_pdf_has_ocr_message(client):
    stream = BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    writer.write(stream)
    response = client.post("/api/analyze", files={"file": ("scan.pdf", stream.getvalue(), "application/pdf")})
    assert response.status_code == 422
    assert "OCR is not supported" in response.json()["detail"]


def test_empty_text_file_is_rejected(client):
    response = client.post("/api/analyze", files={"file": ("notice.txt", b"  \n", "text/plain")})
    assert response.status_code == 422


def test_successful_analysis_has_frontend_contract(client, monkeypatch):
    source = "Applications close on 2026-11-15. Applicants must submit the form to the registrar."
    model_data = {
        "title": "Application notice",
        "summary": "Applications close on 15 November 2026.",
        "summary_evidence": "Applications close on 2026-11-15.",
        "audience": "Applicants",
        "audience_evidence": "Applicants must submit the form to the registrar.",
        "deadlines": [{"title": "Application deadline", "date": "2026-11-15", "evidence": "Applications close on 2026-11-15."}],
        "checklist": [{"text": "Submit the form to the registrar", "evidence": "Submit the form to the registrar."}],
        "missing_information": [],
    }

    async def fake_analyze(text):
        assert text == source
        return ollama_client.Analysis.model_validate({**model_data, "source_text": text})

    monkeypatch.setattr("app.main.analyze_notice", fake_analyze)
    response = client.post("/api/analyze", data={"text": source})
    assert response.status_code == 200
    body = response.json()
    assert set(("title", "summary", "summary_evidence", "audience", "audience_evidence", "deadlines", "checklist", "missing_information", "source_text")) <= body.keys()
    assert body["deadlines"][0]["evidence"] in body["source_text"]


def test_invalid_model_evidence_is_not_presented_as_fact(client, monkeypatch):
    source = "The event will take place soon."

    async def fake_analyze(_):
        data = {"title": "Notice", "summary": "An event is planned.", "audience": "Not specified", "deadlines": [{"title": "Event", "date": "2026-12-01", "evidence": "December 1 is the event date."}], "checklist": [{"text": "Pay the fee", "evidence": "Pay the fee before the event."}], "missing_information": [], "source_text": source}
        ollama_client._verify_evidence(data, source)
        return ollama_client.Analysis.model_validate(data)

    monkeypatch.setattr("app.main.analyze_notice", fake_analyze)
    response = client.post("/api/analyze", data={"text": source})
    assert response.status_code == 200
    assert response.json()["deadlines"] == []
    assert response.json()["checklist"] == []
    assert any("deadline was omitted" in item for item in response.json()["missing_information"])


def test_natural_language_date_is_normalized_only_when_quote_supports_same_date():
    data = {"deadlines": [{"title": "Registration", "date": "2026-11-15", "evidence": "Register by 15 November 2026."}], "checklist": [], "missing_information": []}
    ollama_client._verify_evidence(data, "Register by 15 November 2026.")
    assert data["deadlines"][0]["date"] == "2026-11-15"
    assert data["deadlines"][0]["day"] == "15"
    assert data["deadlines"][0]["month"] == "Nov"


def test_mismatched_date_is_cleared_even_when_evidence_quote_exists():
    data = {"deadlines": [{"title": "Registration", "date": "2026-11-16", "evidence": "Register by 15 November 2026."}], "checklist": [], "missing_information": []}
    ollama_client._verify_evidence(data, "Register by 15 November 2026.")
    assert data["deadlines"][0]["date"] is None
    assert data["deadlines"][0]["ambiguity"]


def test_model_connection_failure_becomes_readable_api_error(client, monkeypatch):
    class FailingClient:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return None

        async def post(self, *_args, **_kwargs):
            raise httpx.ConnectError("Ollama unavailable")

    monkeypatch.setattr(ollama_client.httpx, "AsyncClient", FailingClient)
    response = client.post("/api/analyze", data={"text": "The meeting is Friday."})
    assert response.status_code == 503
    assert "Ollama" in response.json()["detail"]


def test_model_timeout_becomes_504(client, monkeypatch):
    class TimeoutClient:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return None

        async def post(self, *_args, **_kwargs):
            raise httpx.ReadTimeout("model response timed out")

    monkeypatch.setattr(ollama_client.httpx, "AsyncClient", TimeoutClient)
    response = client.post("/api/analyze", data={"text": "The meeting is Friday."})
    assert response.status_code == 504
    assert "timed out" in response.json()["detail"]


def test_model_missing_fields_become_uncertainty_not_fabricated_results(monkeypatch):
    content = {"deadlines": "not an array", "checklist": None}

    class MockResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"message": {"content": json.dumps(content)}}

    class MockClient:
        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return None

        async def post(self, *_args, **_kwargs):
            return MockResponse()

    monkeypatch.setattr(ollama_client.httpx, "AsyncClient", MockClient)
    result = asyncio.run(ollama_client.analyze_notice("A brief notice without a date."))
    assert result.deadlines == []
    assert result.checklist == []
    assert result.summary.startswith("The model did not return")
    assert result.missing_information


def test_real_client_request_is_made_to_local_ollama(monkeypatch):
    source = "Submit applications by 2026-11-15."
    content = {"title": "Applications", "summary": "Submit by the stated deadline.", "summary_evidence": "Submit applications by 2026-11-15.", "audience": "Not specified in the notice", "audience_evidence": None, "deadlines": [{"title": "Submission", "date": "2026-11-15", "evidence": "Submit applications by 2026-11-15."}], "checklist": [], "missing_information": []}
    request_seen = {}

    class MockResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"message": {"content": json.dumps(content)}}

    class MockClient:
        def __init__(self, **kwargs):
            request_seen["timeout"] = kwargs["timeout"]

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return None

        async def post(self, url, json):
            request_seen["url"] = url
            request_seen["request"] = json
            return MockResponse()

    monkeypatch.setattr(ollama_client.httpx, "AsyncClient", MockClient)
    result = asyncio.run(ollama_client.analyze_notice(source))
    assert request_seen["url"].endswith("/api/chat")
    assert request_seen["request"]["model"] == "qwen3:4b"
    assert request_seen["request"]["stream"] is False
    assert request_seen["request"]["think"] is False
    assert request_seen["request"]["options"]["num_predict"] == 512
    assert request_seen["request"]["options"]["num_ctx"] == 4096
    assert result.deadlines[0].evidence == "Submit applications by 2026-11-15."
