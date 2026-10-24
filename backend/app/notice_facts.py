"""Deterministic date and payment cues used to audit local-model extraction."""
from __future__ import annotations

import re
from calendar import month_abbr, month_name
from datetime import date


MONTHS = {name.lower(): number for number, name in enumerate(month_name) if name}
MONTHS.update({name.lower(): number for number, name in enumerate(month_abbr) if name})
MONTH_PATTERN = "|".join(sorted((re.escape(value) for value in MONTHS), key=len, reverse=True))
DATE_PATTERNS = (
    re.compile(rf"\b(?P<day>\d{{1,2}})(?:st|nd|rd|th)?\s+(?P<month>{MONTH_PATTERN})[,]?\s+(?P<year>\d{{4}})\b", re.I),
    re.compile(rf"\b(?P<month>{MONTH_PATTERN})\s+(?P<day>\d{{1,2}})(?:st|nd|rd|th)?[,]?\s+(?P<year>\d{{4}})\b", re.I),
    re.compile(r"\b(?P<year>\d{4})-(?P<month>\d{1,2})-(?P<day>\d{1,2})\b"),
    re.compile(r"\b(?P<day>\d{1,2})[./-](?P<month>\d{1,2})[./-](?P<year>\d{4})\b"),
    re.compile(rf"\b(?P<day>\d{{1,2}})(?:st|nd|rd|th)?\s+(?P<month>{MONTH_PATTERN})\b", re.I),
    re.compile(r"\b(?P<day>\d{1,2})[./-](?P<month>\d{1,2})\b"),
)
DATE_RANGE_PATTERN = re.compile(
    rf"\b(?P<start_day>\d{{1,2}})(?:st|nd|rd|th)?\s*[-–—]\s*"
    rf"(?P<end_day>\d{{1,2}})(?:st|nd|rd|th)?\s+"
    rf"(?P<month>{MONTH_PATTERN})[,]?\s+(?P<year>\d{{4}})\b",
    re.I,
)
DEADLINE_CUES = re.compile(r"\b(deadline|last date|submit|submission|apply|application|register|registration|pay|payment|by|before|no later than|due)\b", re.I)
EVENT_CUES = re.compile(r"\b(event|festival|meeting|tournament|programme|program|held|scheduled|takes place|will be held|venue)\b", re.I)
HISTORICAL_CUES = re.compile(r"\b(previous|previously|former|prior|last year|past|was held|took place)\b", re.I)
PAYMENT_CUES = re.compile(r"\b(fee|fees|pay|payment|cash|amount|rupees?|rs\.?|inr)\b", re.I)
REQUIRED_ACTION_CUES = re.compile(r"\b(must|required|bring|pay|payable|deposit|submit|payment is due)\b", re.I)
TIME_PATTERN = re.compile(r"\b(?:[01]?\d|2[0-3])(?::[0-5]\d)?\s?(?:a\.?m\.?|p\.?m\.?)\b|\b(?:[01]?\d|2[0-3]):[0-5]\d\b", re.I)


def source_quote(source: str, quote: object) -> str | None:
    """Return an exact source slice, allowing only collapsed whitespace differences."""
    if not isinstance(quote, str) or not quote.strip():
        return None
    if quote in source:
        return quote
    normalized = " ".join(quote.split())
    pattern = re.compile(r"\s+".join(re.escape(part) for part in normalized.split()))
    match = pattern.search(source)
    return match.group(0) if match else None


def _date_value(match: re.Match[str], pattern_index: int, numeric_order: str | None = None) -> tuple[str | None, str]:
    day_text, month_text, year_text = match.group("day"), match.group("month"), match.groupdict().get("year")
    day = int(day_text)
    month_num: int
    if month_text.isdigit():
        first, second = int(day_text), int(month_text)
        if pattern_index == 3 and numeric_order == "mdy":
            day, month_num = second, first
        elif pattern_index == 3 and numeric_order == "dmy":
            day, month_num = first, second
        else:
            month_num = second
            if pattern_index == 3 and month_num <= 12 and day <= 12:
                return None, "Numeric date order is ambiguous; confirm the intended day and month."
    else:
        month_num = MONTHS[month_text.lower()]
    if year_text is None:
        return None, "The notice gives a day and month but no year. Confirm the year before acting."
    try:
        return date(int(year_text), month_num, day).isoformat(), ""
    except ValueError:
        return None, "The date in the notice is not a valid calendar date; confirm it in the source."


def find_date_candidates(source: str) -> list[dict[str, str | None]]:
    """Find distinct date mentions and classify their nearby role without guessing."""
    candidates: list[dict[str, str | None]] = []
    seen: set[tuple[int, int]] = set()
    numeric_matches = list(DATE_PATTERNS[3].finditer(source))
    has_dmy = any(int(item.group("day")) > 12 and int(item.group("month")) <= 12 for item in numeric_matches)
    has_mdy = any(int(item.group("month")) > 12 and int(item.group("day")) <= 12 for item in numeric_matches)
    numeric_order = "dmy" if has_dmy and not has_mdy else "mdy" if has_mdy and not has_dmy else None
    for match in DATE_RANGE_PATTERN.finditer(source):
        start, end = match.span()
        seen.add((start, end))
        context_start, context_end = max(0, start - 42), min(len(source), end + 42)
        context = source[context_start:context_end]
        before = source[max(0, start - 50):start]
        after = source[end:min(len(source), end + 50)]
        is_deadline = bool(DEADLINE_CUES.search(before)) or bool(re.search(r"\b(by|before|deadline|last date|due)\b", after, re.I))
        is_event = bool(EVENT_CUES.search(before + " " + after))
        try:
            month_num = MONTHS[match.group("month").lower()]
            start_date = date(int(match.group("year")), month_num, int(match.group("start_day")))
            end_date = date(int(match.group("year")), month_num, int(match.group("end_day")))
            if start_date > end_date:
                raise ValueError
            start_value, end_value = start_date.isoformat(), end_date.isoformat()
            ambiguity = None
        except ValueError:
            start_value = end_value = None
            ambiguity = "The date range in the notice is not a valid calendar range; confirm it in the source."
        if is_deadline:
            title = "Possible deadline range"
            ambiguity = "; ".join(filter(None, (ambiguity, "Confirm that this range applies to the stated action.")))
        elif is_event:
            title = "Event date range"
        else:
            title = "Date range to review"
            ambiguity = "; ".join(filter(None, (ambiguity, "The notice includes this date range, but its role is unclear from nearby text.")))
        candidates.append({
            "title": title,
            "date": start_value,
            "end_date": end_value,
            "time": None,
            "evidence": context.strip(),
            "ambiguity": ambiguity,
        })

    for pattern_index, pattern in enumerate(DATE_PATTERNS):
        for match in pattern.finditer(source):
            span = match.span()
            if any(span[0] < end and span[1] > start for start, end in seen):
                continue
            seen.add(span)
            start, end = span
            context_start, context_end = max(0, start - 42), min(len(source), end + 42)
            context = source[context_start:context_end]
            before = source[max(0, start - 50):start]
            after = source[end:min(len(source), end + 50)]
            is_deadline = bool(DEADLINE_CUES.search(before)) or bool(re.search(r"\b(by|before|deadline|last date|due)\b", after, re.I))
            is_event = bool(EVENT_CUES.search(before + " " + after))
            is_historical = bool(HISTORICAL_CUES.search(before + " " + after))
            if is_historical:
                title = "Historical reference date"
                ambiguity = "This date is described as historical, not as an upcoming action date."
            elif is_deadline:
                title = "Possible deadline"
                ambiguity = "Confirm that this date applies to the stated action; nearby wording suggests a deadline." if is_event else None
            elif is_event:
                title = "Event or meeting date"
                ambiguity = None
            else:
                title = "Date to review"
                ambiguity = "The notice includes this date, but its role is unclear from nearby text."
            normalized_date, date_note = _date_value(match, pattern_index, numeric_order)
            time_match = TIME_PATTERN.search(context)
            if date_note:
                ambiguity = "; ".join(filter(None, (ambiguity, date_note)))
            candidates.append({
                "title": title,
                "date": normalized_date,
                "time": time_match.group(0) if time_match else None,
                "evidence": context.strip(),
                "ambiguity": ambiguity,
            })
    return candidates


def find_payment_requirements(source: str) -> list[dict[str, str]]:
    """Return explicit fee/payment sentences as evidence candidates for model audit."""
    results = []
    # ``Rs.`` is a currency marker, not a sentence boundary.
    protected_source = re.sub(r"\bRs\.", "Rs<dot>", source, flags=re.I)
    for sentence in (part.replace("Rs<dot>", "Rs.") for part in re.split(r"(?<=[.!?])\s+|\n+", protected_source)):
        if PAYMENT_CUES.search(sentence) and REQUIRED_ACTION_CUES.search(sentence):
            evidence = sentence.strip()
            if evidence and not any(item["evidence"] == evidence for item in results):
                results.append({"text": "Complete the stated payment requirement: " + evidence, "evidence": evidence})
    return results


def find_contextual_checklist_items(source: str) -> list[dict[str, str]]:
    """Recover explicitly stated entry flows without manufacturing web links."""
    results: list[dict[str, str]] = []
    registration_link = re.search(
        r"(?im)^\s*registration\s+link\s*:\s*[^\r\n]*https?://[^\s)]+[^\r\n]*",
        source,
    )
    registration_deadline = re.search(
        r"(?im)^.*\b(?:last\s+date|deadline)\b[^\r\n]{0,60}\b(?:registration|entries?|entry)\b[^\r\n]*$",
        source,
    )
    entry_by_email = re.search(
        r"(?im)^.*\b(?:send|sending|submit|submitting)\b[^\r\n]*\bentr(?:y|ies)\b[^\r\n]*\bemail\b[^\r\n]*$",
        source,
    )
    form_by_email = re.search(
        r"(?im)^.*\bGoogle\s+Form\b[^\r\n]*\b(?:link\s+(?:is\s+)?provided\s+in|provided\s+in\s+the\s+email)\b[^\r\n]*$",
        source,
    )
    email_addresses = list(re.finditer(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", source, re.I))
    email_contact = min(email_addresses, key=lambda item: abs(item.start() - entry_by_email.start())) if entry_by_email and email_addresses else None
    if registration_link and registration_deadline:
        evidence_ranges = [registration_link, registration_deadline]
        task_text = "Register using the provided registration link before the registration deadline."
    elif registration_deadline and entry_by_email and form_by_email:
        evidence_ranges = [registration_deadline, entry_by_email, form_by_email]
        if email_contact and abs(email_contact.start() - entry_by_email.start()) <= 400:
            evidence_ranges.append(email_contact)
            task_text = f"Send the entry by email to {email_contact.group(0)} and complete the Google Form link provided in the email before the deadline."
        else:
            task_text = "Send the entry by email and complete the Google Form link provided in the email before the deadline."
    else:
        evidence_ranges = []
        task_text = ""
    if evidence_ranges:
        evidence_start = min(item.start() for item in evidence_ranges)
        evidence_end = max(item.end() for item in evidence_ranges)
        evidence = source[evidence_start:evidence_end].strip()
        results.append({"text": task_text, "evidence": evidence})

    encouraged = re.search(r"(?im)^.*\bencouraged\s+to\s+participate\b.*$", source)
    if encouraged:
        evidence = encouraged.group(0).strip()
        results.append({
            "text": "Optional: Participate and represent your college.",
            "evidence": evidence,
        })
    return results
