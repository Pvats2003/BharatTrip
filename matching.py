"""
Plain-code matching for informal requests (no AI here).

Takes the fields the AI pulled out of a message and decides, with fixed rules,
whether it belongs to an existing refund or needs a new draft ticket.
"""
from __future__ import annotations

import re
from difflib import SequenceMatcher

import pandas as pd

import recon

# Score weights (out of 100). A booking reference that exists = certain match.
W_AGENT, W_ROUTE, W_DATE, W_AMOUNT = 40, 30, 20, 10
AUTO_LINK = 85        # >= this and clearly ahead of the next one: link automatically
SUGGEST = 60          # >= this: show as a possible match for a human to pick
DATE_WINDOW_DAYS = 10

_NUM_WORDS = {"ek": 1, "one": 1, "a": 1, "do": 2, "two": 2, "teen": 3, "three": 3,
              "char": 4, "chaar": 4, "four": 4}


def estimate_request_date(message_date: pd.Timestamp, explicit_date: str | None,
                          time_phrase: str | None) -> tuple[pd.Timestamp | None, str]:
    """Turn 'last week' / '2 hafte ho gaye' into an approximate date. Code, not AI."""
    if explicit_date:
        d = pd.to_datetime(explicit_date, errors="coerce", format="%Y-%m-%d")  # AI returns ISO
        if pd.isna(d):
            d = recon.parse_date(explicit_date)
        if pd.notna(d):
            return d, f"explicit date {d.date()}"
    if message_date is None or pd.isna(message_date):
        return None, "no message date"
    p = (time_phrase or "").lower()
    if "last week" in p or "pichle hafte" in p:
        return message_date - pd.Timedelta(days=7), "'last week' = message date minus 7 days"
    m = re.search(r"(\d+|ek|do|teen|chaa?r|one|two|three|four|a)\s*(hafte|hafta|weeks?|din|days?|mahina|months?)", p)
    if m:
        n = int(m.group(1)) if m.group(1).isdigit() else _NUM_WORDS.get(m.group(1), 1)
        unit = m.group(2)
        days = n * (7 if unit.startswith(("haft", "week")) else 30 if unit.startswith(("mahin", "month")) else 1)
        return message_date - pd.Timedelta(days=days), f"'{m.group(0)}' = message date minus {days} days"
    return None, "no usable time phrase"


def _name_sim(a, b) -> float:
    if not a or not b or pd.isna(a) or pd.isna(b):
        return 0.0
    k = lambda s: re.sub(r"[^a-z0-9]", "", str(s).lower())
    return SequenceMatcher(None, k(a), k(b)).ratio()


def _norm_route(r):
    if not r or pd.isna(r):
        return None
    codes = re.findall(r"[A-Za-z]{3}", str(r).upper())
    return "-".join(codes[:2]) if len(codes) >= 2 else None


def score_candidates(fields: dict, m: pd.DataFrame, message_date: pd.Timestamp) -> tuple[pd.DataFrame, dict]:
    """Return scored candidate refunds plus a note of how the date was estimated."""
    est, how = estimate_request_date(message_date, fields.get("request_date"), fields.get("time_reference"))
    route = _norm_route(fields.get("route"))
    amount = fields.get("amount_inr")
    agent = fields.get("agent_name")

    df = m.copy()
    df["agent_any"] = df["agent"].fillna(df["f_agent"])
    df["route_any"] = df["route"].fillna(df["f_route"])
    df["date_any"] = df["request_date"].fillna(df["f_received"])
    df["agent_sim"] = df["agent_any"].map(lambda a: _name_sim(agent, a))
    df["s_agent"] = (df["agent_sim"] >= 0.85) * W_AGENT
    df["s_route"] = (route is not None) * (df["route_any"] == route) * W_ROUTE
    if est is not None:
        df["date_gap_days"] = (df["date_any"] - est).dt.days.abs()
        df["s_date"] = (df["date_gap_days"] <= DATE_WINDOW_DAYS) * W_DATE
    else:
        df["date_gap_days"] = None
        df["s_date"] = 0
    if amount:
        amt_match = (df["s_amount"].sub(amount).abs() <= 1) | (df["f_paid"].sub(amount).abs() <= 1)
        df["s_amt"] = amt_match.fillna(False) * W_AMOUNT
    else:
        df["s_amt"] = 0
    df["score"] = df[["s_agent", "s_route", "s_date", "s_amt"]].sum(axis=1)
    # The agent must match at all for anything to be a candidate
    cands = df[df["s_agent"] > 0].sort_values("score", ascending=False)
    cols = ["refund_id", "agent_any", "route_any", "date_any", "s_amount", "true_state",
            "score", "s_agent", "s_route", "s_date", "s_amt", "date_gap_days"]
    return cands[cols].head(5).reset_index(drop=True), {"estimated_request_date": est, "how": how}


def next_draft_id(existing_drafts: list[str]) -> str:
    n = len(existing_drafts) + 1
    return f"DRAFT-{n:03d}"


def decide(fields: dict, m: pd.DataFrame, message_date: pd.Timestamp, existing_drafts: list[str]) -> dict:
    """Rule-based decision: link to an existing refund, or create a draft ticket."""
    ref = recon.norm_id(fields.get("booking_reference"))
    cands, date_note = score_candidates(fields, m, message_date)
    known_ids = set(m["refund_id"].dropna())

    if ref and ref in known_ids:
        row = m[m.refund_id == ref].iloc[0]
        return {"decision": "LINK", "refund_id": ref,
                "reason": f"Reference {ref} exists in the trackers (true state: {row.true_state}).",
                "candidates": cands, "date_note": date_note}

    top = cands.iloc[0] if len(cands) else None
    second = cands.iloc[1]["score"] if len(cands) > 1 else 0
    if not ref and top is not None and top.score >= AUTO_LINK and top.score - second >= 15:
        return {"decision": "LINK", "refund_id": top.refund_id,
                "reason": f"Agent, route and date all match {top.refund_id} (score {top.score}/100).",
                "candidates": cands, "date_note": date_note}

    draft_id = next_draft_id(existing_drafts)
    if ref:
        reason = (f"Reference {ref} is quoted but exists in NEITHER tracker, so this request was never "
                  f"logged. Create draft {draft_id} (keeps {ref} as the agent's reference).")
    elif top is not None and top.score >= AUTO_LINK:
        reason = (f"No reference. {top.refund_id} scores {top.score}/100 but another record scores {second}/100, "
                  f"too close to choose safely. Pick the right one below, or create draft {draft_id}.")
    elif top is not None and top.score >= SUGGEST:
        reason = (f"No reference. Closest record is {top.refund_id} (score {top.score}/100), which is below the "
                  f"auto-link bar of {AUTO_LINK}. Default: create draft {draft_id}. A human can link it instead.")
    else:
        reason = f"No reference and no close match in the trackers. Create draft {draft_id}."
    return {"decision": "NEW_DRAFT", "refund_id": draft_id, "agent_reference": ref,
            "reason": reason, "candidates": cands, "date_note": date_note}


def candidate_view(cands: pd.DataFrame, m: pd.DataFrame, message_date: pd.Timestamp) -> pd.DataFrame:
    """Side-by-side comparison of candidate refunds for the human (plain code, incl. expected payout)."""
    if not len(cands):
        return cands
    rows = []
    for _, c in cands.iterrows():
        r = m[m.refund_id == c.refund_id].iloc[0]
        ded = r.f_deduction if pd.notna(r.f_deduction) else 0
        if r.true_state == "Paid" or r.f_status == "Refund Done":
            payout, payout_note = r.f_paid, "paid"
        elif r.true_state == "Declined":
            payout, payout_note = 0, "declined"
        elif pd.notna(r.s_amount):
            payout, payout_note = r.s_amount - ded, "expected (requested − deduction)"
        else:
            payout, payout_note = None, "unknown"
        rows.append({
            "refund_id": c.refund_id,
            "requested_on": c.date_any.date() if pd.notna(c.date_any) else None,
            "logged_after_message": bool(pd.notna(c.date_any) and c.date_any > message_date),
            "requested_inr": r.s_amount, "deduction_inr": ded, "payout_inr": payout, "payout_is": payout_note,
            "status": r.true_state, "days_from_estimate": c.date_gap_days, "match_score": c.score,
        })
    return pd.DataFrame(rows)


def option_label(row) -> str:
    amt = f"₹{row.requested_inr:,.0f}" if pd.notna(row.requested_inr) else "amount unknown"
    flag = " · logged AFTER the message" if row.logged_after_message else ""
    return f"LINK: {row.refund_id} · requested {row.requested_on} · {amt} · {row.status}{flag}"
