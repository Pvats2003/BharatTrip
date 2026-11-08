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
import time

from google.genai import errors as genai_errors

MODEL_OVERRIDE = os.environ.get("GEMINI_MODEL")  # optional; otherwise picked automatically
_RESOLVED: dict = {}   # remembers the model list and which model last answered
_SKIP = ("preview", "exp", "tts", "image", "live", "audio", "thinking", "embedding", "8b")
RETRY_CODES = (429, 500, 503, 504)   # busy / rate-limited / temporary server errors
WAITS = (2, 5)                       # seconds between attempts on the same model
REQUEST_TIMEOUT_S = 20               # one request may take at most this long
TOTAL_BUDGET_S = 75                  # the whole button click gives up after this long


def rank_flash_models(names: list[str]) -> list[str]:
    """Plain code: stable Flash models newest first, then Flash-Lite models newest first."""
    flash, lite = [], []
    for n in names:
        n = n.split("/")[-1]
        m = _re.fullmatch(r"gemini-(\d+(?:\.\d+)?)-flash(-lite)?(?:-(\d+))?", n)
        if not m or any(w in n for w in _SKIP):
            continue
        (lite if m.group(2) else flash).append(((float(m.group(1)), int(m.group(3) or 0)), n))
    return [n for _, n in sorted(flash, reverse=True)] + [n for _, n in sorted(lite, reverse=True)]


def pick_flash_model(names: list[str]) -> str | None:
    r = [n for n in rank_flash_models(names) if "lite" not in n]
    return r[0] if r else None


def model_candidates(task: str = "intake") -> list[str]:
    """Order: GEMINI_MODEL (if set), the model that last worked for this task, then usable Flash models.
    Intake (reading messy text): Flash first, Flash-Lite last. Drafting (short message): Flash-Lite first,
    because it is faster and usually less busy. The model list is fetched once."""
    if "candidates" not in _RESOLVED:
        with _client() as client:
            names = [mdl.name for mdl in client.models.list()
                     if not mdl.supported_actions or "generateContent" in mdl.supported_actions]
        _RESOLVED["candidates"] = rank_flash_models(names)
        _RESOLVED["available"] = [n.split("/")[-1] for n in names]
    ranked = _RESOLVED["candidates"]
    if task == "draft":
        ranked = [c for c in ranked if "lite" in c] + [c for c in ranked if "lite" not in c]
    order = [MODEL_OVERRIDE, _RESOLVED.get(f"model_{task}")] + ranked
    cands = list(dict.fromkeys(m for m in order if m))
    if not cands:
        raise RuntimeError("No Gemini Flash model available to this key. Set GEMINI_MODEL in Secrets. "
                           f"Available: {', '.join(_RESOLVED['available'][:15])}")
    return cands[:6]


def _with_min_thinking(config: types.GenerateContentConfig, model: str):
    """Turn the model's private 'thinking' down to the minimum: these tasks need no reasoning.
    Gemini 3+ takes a thinking level; Gemini 2.5 takes a token budget (0 = off)."""
    if config is None or model in _RESOLVED.get("no_thinking_cfg", set()):
        return config
    m = _re.match(r"gemini-(\d+(?:\.\d+)?)", model)
    if not m:
        return config
    v = float(m.group(1))
    if v >= 3:
        tc = types.ThinkingConfig(thinking_level=types.ThinkingLevel.MINIMAL)
    elif v >= 2.5:
        tc = types.ThinkingConfig(thinking_budget=0)
    else:
        return config
    return config.model_copy(update={"thinking_config": tc})


def _run(task: str, config, start):
    """Find a model that answers. `start(client, model, config)` makes the call and returns its result.
    'Busy' (503) or a timeout -> next model at once. Rate limit (429) -> brief wait, same model.
    A rejected thinking setting -> same model without it. Anything else (bad key, bad request) -> stop.
    Returns (result, client); the caller closes the client when done (streaming keeps it open)."""
    tried = []
    t0 = time.monotonic()
    deadline = t0 + TOTAL_BUDGET_S
    for model in model_candidates(task):
        attempt = 0
        while attempt <= len(WAITS) and time.monotonic() <= deadline:
            client = _client()
            try:
                result = start(client, model, _with_min_thinking(config, model))
                _RESOLVED["model"] = _RESOLVED[f"model_{task}"] = model
                _RESOLVED["last_call"] = (f"Answered by {model} in {time.monotonic() - t0:.0f}s"
                                          + (f" · skipped: {'; '.join(tried)}" if tried else ""))
                return result, client
            except genai_errors.APIError as e:
                client.close()
                if e.code == 400 and "think" in str(e).lower() and model not in _RESOLVED.get("no_thinking_cfg", set()):
                    _RESOLVED.setdefault("no_thinking_cfg", set()).add(model)
                    continue                            # same model, without the thinking setting
                tried.append(f"{model}: {e.code} {e.status or ''}".strip())
                if e.code == 429 and attempt < len(WAITS):
                    time.sleep(WAITS[attempt])
                    attempt += 1
                    continue
                if e.code in RETRY_CODES or e.code == 404:
                    break                               # busy / unavailable / not found: next model
                raise
            except Exception as e:
                client.close()
                if "timeout" not in type(e).__name__.lower() and "timed out" not in str(e).lower():
                    raise
                tried.append(f"{model}: timed out after {REQUEST_TIMEOUT_S}s")
                break
    raise RuntimeError("Gemini is busy right now on every Flash model this key can use. Please try again in a "
                       "few minutes. Models tried: " + "; ".join(tried))


def _generate(contents: str, config: types.GenerateContentConfig, task: str = "intake"):
    resp, client = _run(task, config,
                        lambda c, model, cfg: c.models.generate_content(model=model, contents=contents, config=cfg))
    client.close()
    return resp


APP_VERSION = "v10 (polished UI)"


def _client() -> genai.Client:
    """A fresh client per call, always used inside `with`, so it stays open for the whole request.
    (Using a throwaway client inline let Python close it mid-call: 'client has been closed'.)"""
    key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
    # Hard time limit per request (ms), and no hidden SDK retries: _generate() owns retrying.
    return genai.Client(api_key=key, http_options=types.HttpOptions(timeout=REQUEST_TIMEOUT_S * 1000))


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
    resp = _generate(source, types.GenerateContentConfig(
            system_instruction=INTAKE_SYSTEM,
            response_mime_type="application/json",
            response_schema=IntakeFields,   # Gemini must return JSON matching this schema
            temperature=0,
        ))
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


def update_source(facts: dict) -> str:
    return "Facts (computed by code from both trackers):\n" + "\n".join(f"- {k}: {v}" for k, v in facts.items())


def draft_agent_update_stream(facts: dict):
    """Yields the message piece by piece as Gemini writes it, so the user sees words immediately."""
    source = update_source(facts)
    config = types.GenerateContentConfig(system_instruction=UPDATE_SYSTEM, temperature=0.3)

    def start(client, model, cfg):
        stream = client.models.generate_content_stream(model=model, contents=source, config=cfg)
        first = next(stream)          # busy/timeout errors surface here, so fallback still works
        return first, stream

    (first, stream), client = _run("draft", config, start)
    try:
        if first.text:
            yield first.text
        for chunk in stream:
            if chunk.text:
                yield chunk.text
    finally:
        client.close()


def draft_agent_update(facts: dict) -> tuple[str, str]:
    text = "".join(draft_agent_update_stream(facts)).strip()
    if not text:
        raise RuntimeError("Gemini returned no text (possibly blocked by a safety filter).")
    return text, update_source(facts)


def numbers_not_in_facts(draft: str, facts: dict) -> list[str]:
    """Guardrail (plain code): every amount-like number in the draft must appear in the facts."""
    allowed = set()
    for v in facts.values():
        for n in re.findall(r"\d[\d,]*", str(v)):
            allowed.add(n.replace(",", ""))
    found = re.findall(r"\d[\d,]{2,}", draft)  # 3+ digit numbers (amounts, refs)
    return sorted({n for n in found if n.replace(",", "") not in allowed})
