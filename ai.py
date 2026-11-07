"""
The only two places the AI is used:
  1. extract_intake: read a messy email/WhatsApp message (English or Hinglish) -> fixed JSON fields
  2. draft_agent_update: turn facts computed by code into a short, plain message to the agent

The AI never matches records, never calculates money and never decides a refund's state.
API key comes from the ANTHROPIC_API_KEY environment variable.
"""
from __future__ import annotations

import re
from typing import Literal, Optional

import anthropic
from pydantic import BaseModel, Field

MODEL = "claude-opus-5-5"
# If the model declines a request, the API retries it on a fallback model automatically.
FALLBACK = dict(betas=["server-side-fallback-2026-07-01"], fallbacks="default")


def _client() -> anthropic.Anthropic:
    return anthropic.Anthropic()  # reads ANTHROPIC_API_KEY


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
    resp = _client().beta.messages.parse(
        model=MODEL,
        max_tokens=4000,
        output_config={"effort": "low"},
        system=INTAKE_SYSTEM,
        messages=[{"role": "user", "content": source}],
        output_format=IntakeFields,
        **FALLBACK,
    )
    if resp.stop_reason == "refusal" or resp.parsed_output is None:
        raise RuntimeError("The model declined or returned no structured output.")
    return resp.parsed_output, source


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
    resp = _client().beta.messages.create(
        model=MODEL,
        max_tokens=2000,
        output_config={"effort": "low"},
        system=UPDATE_SYSTEM,
        messages=[{"role": "user", "content": source}],
        **FALLBACK,
    )
    if resp.stop_reason == "refusal":
        raise RuntimeError("The model declined to draft this message.")
    text = "".join(b.text for b in resp.content if b.type == "text").strip()
    return text, source


def numbers_not_in_facts(draft: str, facts: dict) -> list[str]:
    """Guardrail (plain code): every amount-like number in the draft must appear in the facts."""
    allowed = set()
    for v in facts.values():
        for n in re.findall(r"\d[\d,]*", str(v)):
            allowed.add(n.replace(",", ""))
    found = re.findall(r"\d[\d,]{2,}", draft)  # 3+ digit numbers (amounts, refs)
    return sorted({n for n in found if n.replace(",", "") not in allowed})
