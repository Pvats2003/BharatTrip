"""Offline tests of the plain-code rules (no AI, no API key).  Run:  python -m pytest -q"""
import pandas as pd
import pytest

import ai
import matching
import recon

F = "data/BharatTrip_Refund_Data.xlsx"


@pytest.fixture(scope="module")
def m():
    return recon.load_and_reconcile(pd.read_excel(F, "Support_Tracker"), pd.read_excel(F, "Finance_Tracker"))[0]


def test_ids_and_dates():
    assert recon.norm_id("RF 1750") == recon.norm_id("rf-1750") == recon.norm_id("RF1750 (revised) ") == "RF-1750"
    assert recon.parse_date("09-06-2026") == pd.Timestamp("2026-06-09")
    assert recon.parse_date("30/05/26") == pd.Timestamp("2026-05-30")


def test_phase1_numbers(m):
    vc = m.true_state.value_counts()
    assert vc["Closed in Support, missing in Finance"] == 69
    assert len(recon.closed_not_paid(m, days=-1)) == 81
    assert len(recon.closed_not_paid(m, days=7)) == 63


def test_brief_messages_create_drafts(m):
    for fx, day in [({"agent_name": "Peak Journeys", "route": "DEL-DXB", "time_reference": "last week",
                      "booking_reference": "RF-1099"}, "2026-06-05"),
                    ({"agent_name": "Nomad Travel", "route": "BLR-MAA", "time_reference": "2 hafte ho gaye",
                      "booking_reference": "RF-1098"}, "2026-06-08")]:
        r = matching.decide(fx, m, pd.Timestamp(day), [])
        assert r["decision"] == "NEW_DRAFT"          # neither ref exists in any tracker


def test_hinglish_time_phrase():
    d, _ = matching.estimate_request_date(pd.Timestamp("2026-06-08"), None, "2 hafte ho gaye")
    assert d == pd.Timestamp("2026-05-25")


def test_known_ref_links(m):
    assert matching.decide({"agent_name": "GoFly", "booking_reference": "rf 1197"}, m,
                           pd.Timestamp("2026-05-20"), [])["decision"] == "LINK"


def test_ambiguous_match_is_not_auto_linked(m):
    # Two GoFly BOM-DXB refunds on the same day -> a human must pick
    r = matching.decide({"agent_name": "GoFly Holidays", "route": "BOM-DXB", "request_date": "2026-05-04"},
                        m, pd.Timestamp("2026-05-20"), [])
    assert r["decision"] == "NEW_DRAFT"


def test_number_guardrail(m):
    facts = recon.refund_facts(m[m.refund_id == "RF-1197"].iloc[0])
    assert ai.numbers_not_in_facts("Requested Rs 17,700, deduction Rs 1,500, paid Rs 16,200.", facts) == []
    assert ai.numbers_not_in_facts("We paid Rs 17,000.", facts) == ["17,000"]
