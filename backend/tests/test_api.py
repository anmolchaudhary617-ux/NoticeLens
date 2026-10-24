import json
import asyncio
from pathlib import Path

import httpx
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
from io import BytesIO
from pydantic import ValidationError

from app.main import app
from app import ollama_client
from app.config import Settings
from app.notice_facts import find_contextual_checklist_items, find_date_candidates, find_payment_requirements
from app.documents import extract_notice


SYNTHETIC_NOTICE = (Path(__file__).parent / "fixtures" / "generic_synthetic_notice.txt").read_text(encoding="utf-8")
SPIRIT_VOLLEYBALL_NOTICE = (Path(__file__).parent / "fixtures" / "spirit_volleyball_user_facts.txt").read_text(encoding="utf-8")
SPIRIT_VOLLEYBALL_RESPONSE = json.loads((Path(__file__).parent / "fixtures" / "spirit_volleyball_compact_response.json").read_text(encoding="utf-8"))


def mock_ollama_body(monkeypatch, body):
    class MockResponse:
        status_code = 200
        headers = {"content-type": "application/json"}

        def raise_for_status(self):
            return None

        def json(self):
            return body

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


def test_text_based_pdf_extraction_round_trip(client, monkeypatch):
    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    font = writer._add_object(DictionaryObject({
        NameObject("/Type"): NameObject("/Font"),
        NameObject("/Subtype"): NameObject("/Type1"),
        NameObject("/BaseFont"): NameObject("/Helvetica"),
        NameObject("/Encoding"): NameObject("/WinAnsiEncoding"),
    }))
    page[NameObject("/Resources")] = DictionaryObject({
        NameObject("/Font"): DictionaryObject({NameObject("/F1"): font}),
    })
    stream = DecodedStreamObject()
    stream.set_data(b"BT /F1 12 Tf 72 720 Td (PDF selectable text marker) Tj ET")
    page[NameObject("/Contents")] = writer._add_object(stream)
    pdf_bytes = BytesIO()
    writer.write(pdf_bytes)

    async def fake_analyze(source):
        assert "PDF selectable text marker" in source
        return ollama_client.Analysis(summary="PDF text extracted.", source_text=source)

    monkeypatch.setattr("app.main.analyze_notice", fake_analyze)
    response = client.post(
        "/api/analyze",
        files={"file": ("selectable.pdf", pdf_bytes.getvalue(), "application/pdf")},
    )
    assert response.status_code == 200
    assert "PDF selectable text marker" in response.json()["source_text"]


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
    assert not any("deadline was omitted" in item for item in response.json()["missing_information"])


def test_natural_language_date_is_normalized_only_when_quote_supports_same_date():
    data = {"deadlines": [{"title": "Registration", "date": "2026-11-15", "evidence": "Register by 15 November 2026."}], "checklist": [], "missing_information": []}
    ollama_client._verify_evidence(data, "Register by 15 November 2026.")
    assert data["deadlines"][0]["date"] == "2026-11-15"
    assert data["deadlines"][0]["day"] == "15"
    assert data["deadlines"][0]["month"] == "Nov"


def test_mismatched_model_date_is_replaced_by_deterministic_source_date():
    data = {"deadlines": [{"title": "Registration", "date": "2026-11-16", "evidence": "Register by 15 November 2026."}], "checklist": [], "missing_information": []}
    ollama_client._verify_evidence(data, "Register by 15 November 2026.")
    assert data["deadlines"][0]["date"] == "2026-11-15"
    assert data["deadlines"][0]["day"] == "15"


def test_model_connection_failure_becomes_readable_api_error(client, monkeypatch, caplog):
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
    assert "category=connection_failure" in caplog.text


def test_model_timeout_becomes_504(client, monkeypatch, caplog):
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
    assert "category=timeout" in caplog.text


def test_model_missing_fields_become_uncertainty_not_fabricated_results(monkeypatch):
    mock_ollama_body(monkeypatch, {"message": {"content": json.dumps({"title": "A brief notice", "summary_claims": []})}})
    result = asyncio.run(ollama_client.analyze_notice("A brief notice without a date."))
    assert result.deadlines == []
    assert result.checklist == []
    assert "no summary claims could be verified" in result.summary
    assert result.audience == "Not specified in the notice"


def test_compact_model_output_with_omitted_arrays_defaults_without_inventing_fields(monkeypatch):
    mock_ollama_body(monkeypatch, {"message": {"content": json.dumps({"t": "Brief notice", "s": []})}})
    result = asyncio.run(ollama_client.analyze_notice("A brief notice without explicit dates."))
    assert result.title == "Brief notice"
    assert result.deadlines == []
    assert result.checklist == []
    assert result.audience == "Not specified in the notice"
    assert result.source_text == "A brief notice without explicit dates."


def test_nested_compact_audience_pair_is_expanded_then_evidence_verified(monkeypatch):
    source = "Interested students are encouraged to participate."
    compact_response = {
        "t": "Participation notice",
        "s": [["Students are encouraged to participate.", source]],
        "a": [["Interested students", source]],
        "d": [],
        "c": [],
        "m": [],
    }
    mock_ollama_body(monkeypatch, {"message": {"content": json.dumps(compact_response)}})

    result = asyncio.run(ollama_client.analyze_notice(source))

    assert result.audience == "Interested students"
    assert result.audience_evidence == source


def test_null_optional_compact_arrays_become_empty_without_inventing_facts(monkeypatch):
    mock_ollama_body(monkeypatch, {
        "message": {
            "content": json.dumps({"t": None, "s": None, "a": None, "d": None, "c": None, "m": None}),
        },
    })
    result = asyncio.run(ollama_client.analyze_notice("A short notice without listed details."))

    assert result.title == "Notice analysis"
    assert result.audience == "Not specified in the notice"
    assert result.summary_claims == []
    assert result.deadlines == []
    assert result.checklist == []
    assert result.missing_information == []


def test_nullable_schema_fields_accept_null_without_schema_error(monkeypatch):
    source = "The meeting takes place on 12 November 2026."
    response = {
        "title": "Brief notice",
        "summary": "A short notice.",
        "summary_evidence": None,
        "audience": None,
        "audience_evidence": None,
        "deadlines": [{
            "title": "Meeting date",
            "date": None,
            "time": None,
            "evidence": source,
        }],
        "missing_information": None,
    }
    mock_ollama_body(monkeypatch, {"message": {"content": json.dumps(response)}})
    result = asyncio.run(ollama_client.analyze_notice(source))

    assert result.title == "Brief notice"
    assert result.audience == "Not specified in the notice"
    assert result.deadlines[0].date == "2026-11-12"
    assert result.deadlines[0].time is None
    assert result.checklist == []
    assert result.missing_information == []


def test_spirit_volleyball_compact_response_preserves_separate_dates_and_requirements(monkeypatch):
    mock_ollama_body(monkeypatch, {
        "message": {
            "content": json.dumps(SPIRIT_VOLLEYBALL_RESPONSE),
            "thinking": "private model reasoning must never be returned",
        },
        "done": True,
        "done_reason": "stop",
        "eval_count": 128,
    })

    result = asyncio.run(ollama_client.analyze_notice(SPIRIT_VOLLEYBALL_NOTICE))
    tournament_date = next(item for item in result.deadlines if item.date == "2026-08-13")
    entry_deadline = next(item for item in result.deadlines if item.date == "2026-08-10")
    assert result.source_text == SPIRIT_VOLLEYBALL_NOTICE
    assert tournament_date.title == "Tournament date"
    assert tournament_date.date != entry_deadline.date
    assert tournament_date.time == "07:30 AM"
    assert entry_deadline.title == "Entry deadline"
    assert tournament_date.evidence in SPIRIT_VOLLEYBALL_NOTICE
    assert entry_deadline.evidence in SPIRIT_VOLLEYBALL_NOTICE
    assert result.audience == "Not specified in the notice"
    assert any("GIDC Degree Engineering College" in claim.text for claim in result.summary_claims)
    assert "forms.gle" not in " ".join(task.text + task.evidence for task in result.checklist)
    checklist_text = "\n".join(task.text for task in result.checklist)
    for expected in ("email", "Google Form", "college ID", "passport-size photos", "latest fee receipt", "leaving certificate", "mark sheets", "eligibility proforma", "signed by the principal", "lodging and boarding", "TA/DA"):
        assert expected.lower() in checklist_text.lower()
    assert all(task.evidence in SPIRIT_VOLLEYBALL_NOTICE for task in result.checklist)
    assert "private model reasoning" not in result.model_dump_json()


def test_source_time_overrides_model_24_hour_variant(monkeypatch):
    response = json.loads(json.dumps(SPIRIT_VOLLEYBALL_RESPONSE))
    tournament = next(item for item in response["d"] if item[0] == "Tournament date")
    tournament[3] = "19:30"
    mock_ollama_body(monkeypatch, {"message": {"content": json.dumps(response)}})

    result = asyncio.run(ollama_client.analyze_notice(SPIRIT_VOLLEYBALL_NOTICE))
    assert next(item for item in result.deadlines if item.date == "2026-08-13").time == "07:30 AM"


def test_json_code_fence_is_accepted(monkeypatch):
    fenced = "```JSON\n" + json.dumps(SPIRIT_VOLLEYBALL_RESPONSE) + "\n```"
    mock_ollama_body(monkeypatch, {"message": {"content": fenced}})

    result = asyncio.run(ollama_client.analyze_notice(SPIRIT_VOLLEYBALL_NOTICE))
    assert any(item.date == "2026-08-10" for item in result.deadlines)


def test_harmless_text_around_json_is_recovered():
    parsed = ollama_client._parse_json('Analysis follows:\n' + json.dumps({"summary_claims": []}) + "\nDone.")
    assert parsed == {"summary_claims": []}


def test_invalid_model_evidence_is_dropped_individually(monkeypatch):
    invalid_response = {
        "t": "Unsupported claims",
        "s": [["The venue is GIDC Degree Engineering College, Abrama, Navsari.", "Venue: GIDC Degree Engineering College, Abrama, Navsari."], ["Free accommodation is provided.", "Free accommodation is provided."]],
        "d": [["Invented deadline", "2027-12-01", "", "", "Last date for sending entry: 10/08/2026."]],
        "c": [["The organizer will pay for lodging.", "Teams must arrange their own lodging and boarding."]],
    }
    mock_ollama_body(monkeypatch, {"message": {"content": json.dumps(invalid_response)}})

    result = asyncio.run(ollama_client.analyze_notice(SPIRIT_VOLLEYBALL_NOTICE))
    assert all("free accommodation" not in claim.text.lower() for claim in result.summary_claims)
    assert any("GIDC Degree Engineering College" in claim.text for claim in result.summary_claims)
    assert all(item.date != "2027-12-01" for item in result.deadlines)
    assert any(item.date == "2026-08-13" for item in result.deadlines)
    assert not any("organizer will pay" in item.text.lower() for item in result.checklist)


@pytest.mark.parametrize(
    ("response", "error_location", "error_type"),
    [
        (
            {"summary_claims": [{"text": "This nested field is required"}]},
            "('summary_claims', 0, 'evidence')",
            "missing",
        ),
        (
            {"summary_claims": [], "deadlines": "not an array"},
            "('deadlines',)",
            "list_type",
        ),
    ],
)
def test_invalid_schema_output_is_classified_and_logged_safely(
    monkeypatch, caplog, response, error_location, error_type
):
    mock_ollama_body(monkeypatch, {
        "message": {"content": json.dumps(response)},
        "done": True,
        "done_reason": "stop",
        "eval_count": 84,
    })

    with pytest.raises(HTTPException) as error:
        asyncio.run(ollama_client.analyze_notice("A brief notice."))

    assert error.value.status_code == 502
    assert "analysis schema" in error.value.detail
    assert "category=schema_validation" in caplog.text
    assert error_location in caplog.text
    assert error_type in caplog.text
    assert "expected_field_names" in caplog.text
    assert "actual_field_names" in caplog.text
    assert "'json_output_length':" in caplog.text
    assert "'done_reason': 'stop'" in caplog.text
    assert "'eval_count': 84" in caplog.text
    assert "This nested field is required" not in caplog.text


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
    assert request_seen["request"]["options"]["num_predict"] == 768
    assert request_seen["request"]["options"]["num_ctx"] == 4096
    assert result.deadlines[0].evidence == "Submit applications by 2026-11-15."


def test_individually_supported_summary_claims_are_preserved():
    data = {
        "summary": "A combined summary that should be replaced by verified claims.",
        "summary_claims": [
            {"text": "Registered student teams attend a coordination meeting.", "evidence": "All registered student teams must attend the coordination meeting"},
            {"text": "The meeting is on 12 November 2026.", "evidence": "coordination meeting on 12 November 2026 at 10:30 AM"},
        ],
        "audience": "Registered student teams",
        "audience_evidence": "All registered student teams must attend",
        "deadlines": [], "checklist": [], "missing_information": [],
    }
    ollama_client._verify_evidence(data, SYNTHETIC_NOTICE)
    result = ollama_client._normalize_response(data, SYNTHETIC_NOTICE)
    assert "Registered student teams attend" in result["summary"]
    assert "meeting is on 12 November 2026" in result["summary"]
    assert len(result["summary_claims"]) == 2
    assert all(claim["evidence"] in SYNTHETIC_NOTICE for claim in result["summary_claims"])


def test_unsupported_summary_claim_is_dropped_individually():
    data = {
        "summary_claims": [
            {"text": "Teams attend a coordination meeting.", "evidence": "All registered student teams must attend the coordination meeting"},
            {"text": "The university provides free transport.", "evidence": "free transport is provided"},
        ],
        "audience": "Not specified in the notice", "deadlines": [], "checklist": [], "missing_information": [],
    }
    ollama_client._verify_evidence(data, SYNTHETIC_NOTICE)
    assert len(data["summary_claims"]) == 1
    assert data["summary"] == "Teams attend a coordination meeting."
    assert any("Could not verify one summary claim" in item for item in data["missing_information"])


def test_currency_payment_requirement_is_kept_with_source_evidence():
    payments = find_payment_requirements(SYNTHETIC_NOTICE)
    assert len(payments) == 1
    assert "Rs. 150/-" in payments[0]["evidence"]
    data = {"summary_claims": [], "summary": "", "deadlines": [], "checklist": [], "missing_information": []}
    ollama_client._verify_evidence(data, SYNTHETIC_NOTICE)
    assert any("Rs. 150/-" in task["evidence"] for task in data["checklist"])


def test_registration_action_requires_both_registration_link_and_deadline():
    items = find_contextual_checklist_items(SPIRIT_VOLLEYBALL_NOTICE)
    submission = next(item for item in items if "Google Form" in item["text"])
    assert submission["evidence"] in SPIRIT_VOLLEYBALL_NOTICE
    assert "Last date for sending entry:" in submission["evidence"]
    assert "Google Form link provided in the email" in submission["evidence"]
    assert "sports110@gdec.in" in submission["text"]
    without_deadline = SPIRIT_VOLLEYBALL_NOTICE.replace("Last date for sending entry: 10/08/2026.", "Entry information is available from the office.")
    assert not any("Google Form" in item["text"] for item in find_contextual_checklist_items(without_deadline))


def test_encouraged_participation_is_never_upgraded_to_mandatory():
    data = {
        "summary_claims": [], "summary": "", "deadlines": [],
        "checklist": [{
            "text": "Students must participate in the festival.",
            "evidence": "Interested students are encouraged to participate and represent our college.",
        }],
        "missing_information": [],
    }
    ollama_client._verify_evidence(data, "Interested students are encouraged to participate and represent the team.")
    assert not any("must participate" in item.get("text", "").lower() for item in data["checklist"])
    assert any(item["text"].startswith("Optional:") for item in data["checklist"])


def test_deterministic_dates_keep_deadline_event_and_historical_context():
    data = {"summary_claims": [], "summary": "", "deadlines": [], "checklist": [], "missing_information": []}
    ollama_client._verify_evidence(data, SYNTHETIC_NOTICE)
    dates = data["deadlines"]
    assert any(item["title"] == "Possible deadline" and item["date"] == "2026-11-08" for item in dates)
    assert any(item["title"] == "Event or meeting date" and item["date"] == "2026-11-12" for item in dates)
    assert any(item["title"] == "Historical reference date" and item["date"] == "2025-11-04" for item in dates)


def test_date_without_year_is_shown_for_review_without_invented_normalization():
    candidates = find_date_candidates("Submit the form by 8 November. The meeting will be held on 10 November.")
    assert len(candidates) == 2
    assert all(item["date"] is None for item in candidates)
    assert all("no year" in item["ambiguity"] for item in candidates)


def test_evidence_whitespace_is_normalized_but_unrelated_quote_is_rejected():
    data = {"summary_claims": [{"text": "Teams attend the meeting.", "evidence": "All registered student teams must attend\n the coordination meeting"}], "summary": "", "deadlines": [], "checklist": [], "missing_information": []}
    ollama_client._verify_evidence(data, SYNTHETIC_NOTICE)
    assert len(data["summary_claims"]) == 1
    bad = {"summary_claims": [{"text": "Teams get transport.", "evidence": "All registered student teams must attend the coordination meeting"}], "summary": "", "deadlines": [], "checklist": [], "missing_information": []}
    ollama_client._verify_evidence(bad, SYNTHETIC_NOTICE)
    assert bad["summary_claims"] == []


def test_malformed_model_json_has_specific_diagnostic(monkeypatch, caplog):
    mock_ollama_body(monkeypatch, {"message": {"content": "not json"}, "done": True, "done_reason": "stop"})
    with pytest.raises(HTTPException, match="malformed JSON"):
        asyncio.run(ollama_client.analyze_notice("A brief notice."))
    assert "category=malformed_json" in caplog.text
    assert "not json" not in caplog.text


def test_truncated_model_json_has_specific_diagnostic(monkeypatch, caplog):
    mock_ollama_body(monkeypatch, {
        "message": {"content": '{"c":[["Bring all eligibility documents signed by'},
        "done": True,
        "done_reason": "length",
        "eval_count": 768,
    })
    with pytest.raises(HTTPException, match="truncated"):
        asyncio.run(ollama_client.analyze_notice("A brief notice."))
    assert "category=truncated_json" in caplog.text
    assert "content_length" in caplog.text
    assert "'eval_count': 768" in caplog.text
    assert "Unterminated string starting at" in caplog.text
