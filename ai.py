"""
The only two places the AI is used:
  1. extract_intake: read a messy email/WhatsApp message (English or Hinglish) -> fixed JSON fields
  2. draft_agent_update: turn facts computed by code into a short, plain message to the agent

The AI never matches records, never calculates money and never decides a refund's state.
Provider: Google Gemini (free tier). API key comes from the GEMINI_API_KEY (or GOOGLE_API_KEY) environment
variable; the model can be changed with GEMINI_MODEL.
"""
from __future__ import annotations

import re
from typing import Literal, Optional

import os

from google import genai
from google.genai import types
from pydantic import BaseModel, Field

import re as _re

MODEL_OVERRIDE = os.environ.get("GEMINI_MODEL")  # optional; otherwise picked automatically
_RESOLVED: dict = {}
_SKIP = ("lite", "preview", "exp", "tts", "image", "live", "audio", "thinking", "embedding", "8b")


def pick_flash_model(names: list[str]) -> str | None:
    """Plain code: newest stable 'gemini-X.Y-flash' model from the list the API returns."""
    best, best_v = None, (-1.0,)
    for n in names:
        n = n.split("/")[-1]
        m = _re.fullmatch(r"gemini-(\d+(?:\.\d+)?)-flash(?:-(\d+))?", n)
        if not m or any(w in n for w in _SKIP):
            continue
        v = (float(m.group(1)), int(m.group(2) or 0))
        if v > best_v:
            best, best_v = n, v
    return best


def model_name() -> str:
    """GEMINI_MODEL if set, else ask the API which models this key can use and pick the newest Flash."""
    if MODEL_OVERRIDE:
        return MODEL_OVERRIDE
    if "model" not in _RESOLVED:
        with _client() as client:
            names = [mdl.name for mdl in client.models.list()
                     if not mdl.supported_actions or "generateContent" in mdl.supported_actions]
        chosen = pick_flash_model(names)
        if not chosen:
            raise RuntimeError("No Gemini Flash model available to this key. Set GEMINI_MODEL in Secrets. "
                               f"Available: {', '.join(n.split('/')[-1] for n in names[:15])}")
        _RESOLVED["model"] = chosen
    return _RESOLVED["model"]


APP_VERSION = "v4 (Gemini, auto model)"


def _client() -> genai.Client:
    """A fresh client per call, always used inside `with`, so it stays open for the whole request.
    (Using a throwaway client inline let Python close it mid-call: 'client has been closed'.)"""
    key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
    return genai.Client(api_key=key)


def api_key_set() -> bool:
    return bool(os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"))


# ---------------------------------------------------------------- 1. Intake
class Evidence(BaseModel):
    field: str = Field(description="Which output field this quote supports")
    quote: str = Field(description="Exact words copied from the message")


class IntakeFields(BaseModel):
    message_type: Literal["refund_request_from_agent", "internal_note", "other"]
    agent_name: Optional[str] = Field(description="Travel agency name, as written. Null if not stated.")
    route: Optional[str] = Field(description="Route as ORIGIN-DEST airport codes, e.g. DEL-DXB. Null if not stated.")
    amount_inr: Optional[int] = Field(description="Refund amount in INR if stated. Null if not stated. Never guess.")
    request_date: Optional[str] = Field(description="Explicit cancellation/request date as YYYY-MM-DD, only if a date is written. Null otherwise.")
    time_reference: Optional[str] = Field(description="Relative time phrase copied verbatim, e.g. 'last week', '2 hafte ho gaye'. Null if none.")
    booking_reference: Optional[str] = Field(description="Any ticket/refund/booking reference written in the text, e.g. RF-1099. Null if none.")
    language: str = Field(description="e.g. English, Hinglish")
    summary_english: str = Field(description="One-sentence plain-English summary of what the sender wants")
    evidence: list[Evidence] = Field(description="One exact quote for every non-null field above")


INTAKE_SYSTEM = """You read informal refund messages that reach BharatTrip, a B2B travel company, by email or WhatsApp.
Messages may be in English, Hindi written in Latin script, or a mix (Hinglish), e.g. "bhai refund ka kya hua" = "brother, what happened to my refund", "2 hafte ho gaye" = "it has been 2 weeks", "koi jawab nahi" = "no reply".

Extract only what is written. If a field is not in the message, return null; never infer or invent an amount, date or reference.
Do not convert relative times into dates; copy the phrase into time_reference. The software does the date maths.
For every field you fill, add an evidence item quoting the exact words you used. If the sender line (e.g. "from Peak Journeys") names the agency, that counts as written."""


def extract_intake(message: str, channel: str, sender: str, received_on: str) -> tuple[IntakeFields, str]:
    """Returns the parsed fields and the exact text that was sent to the model (the 'source')."""
    source = f"Channel: {channel}\nFrom: {sender}\nReceived: {received_on}\n\nMessage:\n{message}"
    model = model_name()
    with _client() as client:
        resp = client.models.generate_content(
            model=model,
            contents=source,
            config=types.GenerateContentConfig(
                system_instruction=INTAKE_SYSTEM,
                response_mime_type="application/json",
                response_schema=IntakeFields,   # Gemini must return JSON matching this schema
                temperature=0,
            ),
        )
    parsed = resp.parsed if isinstance(resp.parsed, IntakeFields) else None
    if parsed is None:
        if not resp.text:
            raise RuntimeError("Gemini returned no output (possibly blocked by a safety filter).")
        parsed = IntakeFields.model_validate_json(resp.text)  # raises if the JSON is invalid
    return parsed, source


# ---------------------------------------------------------------- 2. Agent update
UPDATE_SYSTEM = """You write short status updates from BharatTrip's refunds desk to a travel agent (a B2B customer).
Use ONLY the facts provided. Do not add amounts, dates, reasons or promises that are not in the facts.
Rules:
- 3 to 6 sentences, warm and plain. No jargon, no internal team names ("Finance tracker", "true state").
- Always quote the refund reference.
- If there is a deduction, state the requested amount, the deduction and the amount paid, and the reason if one is given. If no reason is given, say the team will confirm what it was for. Do not invent one.
- If the refund is not paid yet, say honestly where it is and what happens next. Never say it is paid when the facts say it is not.
- Write amounts exactly as given, in the form Rs 12,345.
- Sign off as "BharatTrip Refunds Team". Output only the message."""


def draft_agent_update(facts: dict) -> tuple[str, str]:
    source = "Facts (computed by code from both trackers):\n" + "\n".join(f"- {k}: {v}" for k, v in facts.items())
    model = model_name()
    with _client() as client:
        resp = client.models.generate_content(
            model=model,
            contents=source,
            config=types.GenerateContentConfig(system_instruction=UPDATE_SYSTEM, temperature=0.3),
        )
    if not resp.text:
        raise RuntimeError("Gemini returned no text (possibly blocked by a safety filter).")
    return resp.text.strip(), source


def numbers_not_in_facts(draft: str, facts: dict) -> list[str]:
    """Guardrail (plain code): every amount-like number in the draft must appear in the facts."""
    allowed = set()
    for v in facts.values():
        for n in re.findall(r"\d[\d,]*", str(v)):
            allowed.add(n.replace(",", ""))
    found = re.findall(r"\d[\d,]{2,}", draft)  # 3+ digit numbers (amounts, refs)
    return sorted({n for n in found if n.replace(",", "") not in allowed})
