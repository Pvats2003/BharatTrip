"""Render the intake tab with hand-written stand-ins for the AI output (no API call) and check what a user sees."""
from datetime import date

from streamlit.testing.v1 import AppTest

SRC = "Channel: Email\nFrom: Peak Journeys\nReceived: 2026-06-05\n\nMessage:\n..."
PEAK = {"message_type": "refund_request_from_agent", "agent_name": "Peak Journeys", "route": "DEL-DXB",
        "amount_inr": None, "request_date": None, "time_reference": "last week", "booking_reference": "RF-1099",
        "language": "English", "summary_english": "Agent wants an update on a refund for a cancelled DEL-DXB booking.",
        "evidence": [{"field": "agent_name", "quote": "Peak Journeys"}, {"field": "route", "quote": "DEL-DXB"},
                     {"field": "time_reference", "quote": "last week"}, {"field": "booking_reference", "quote": "RF-1099"}]}
NOTE = {"message_type": "internal_note", "agent_name": None, "route": None, "amount_inr": None, "request_date": None,
        "time_reference": "last month", "booking_reference": None, "language": "English",
        "summary_english": "Support agent says Finance never received refunds they closed.", "evidence": []}


def run(fields):
    at = AppTest.from_file("../app.py", default_timeout=60)
    at.session_state["intake"] = {"fields": fields, "source": SRC, "received": date(2026, 6, 5), "channel": "Email"}
    at.run()
    assert not at.exception, at.exception
    return at


def text(at):
    return " ".join([e.value for e in at.markdown] + [e.value for e in at.success] + [e.value for e in at.error]
                    + [e.value for e in at.warning] + [e.value for e in at.info])


def test_peak_journeys_plain_view():
    at = run(PEAK)
    t = text(at)
    assert "not in our records" in t and "never logged" in t
    assert "DRAFT-001" in " ".join(at.radio[0].options)
    assert "Amount not stated in the message" in t          # default = new ticket, no amount guessed


def test_linking_rf1145_shows_amount_with_proof():
    at = run(PEAK)
    opt = next(o for o in at.radio[0].options if "RF-1145" in o)
    at.radio[0].set_value(opt).run()
    t = text(at)
    assert "₹21,300" in t and "₹1,700" in t and "₹19,600" in t
    assert "Support tracker" in t and "Finance tracker" in t
    next(b for b in at.button if "Approve and send" in b.label).click().run()   # approve
    assert any("Download approval log" in b.label for b in at.get("download_button")), "no download button after approve"
    log = at.session_state["approved"][-1]
    assert log["refund_id"] == "RF-1145" and log["payout_inr"] == 19600 and log["owner"] == "Finance"


def test_internal_note_shows_records_not_ticket():
    at = run(NOTE)
    t = text(at)
    assert "not a refund request" in t and "69 refunds" in t



def test_saved_draft_shows_instantly_without_ai():
    import json
    import pandas as pd
    import recon
    m = recon.load_and_reconcile(pd.read_excel("data/BharatTrip_Refund_Data.xlsx", "Support_Tracker"),
                                 pd.read_excel("data/BharatTrip_Refund_Data.xlsx", "Finance_Tracker"))[0]
    pc = recon.problem_cases(m, recon.SNAPSHOT)
    rid = pc.refund_id.iloc[0]                                  # first refund in tab 3's list
    facts = recon.refund_facts(m[m.refund_id == rid].iloc[0])
    at = AppTest.from_file("../app.py", default_timeout=60)
    at.session_state["draft_cache"] = {(rid, json.dumps(facts, sort_keys=True, default=str)):
                                       {"text": "Hello", "source": "s", "flags": [], "call": ""}}
    at.run()
    assert not at.exception, at.exception
    assert any("Saved draft (instant)" in c.value for c in at.caption)
    assert any(b.label == "Redraft with AI" for b in at.button)
