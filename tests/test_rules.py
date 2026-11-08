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


def test_gemini_retry_then_fallback(monkeypatch):
    """Fake Gemini: newest model busy (503) -> falls straight back to the next model."""
    from google.genai import errors as ge
    calls = []

    class FakeModels:
        def generate_content(self, model, contents, config):
            calls.append(model)
            if model == "gemini-9.0-flash":
                raise ge.ServerError(503, {"error": {"code": 503, "message": "busy", "status": "UNAVAILABLE"}})
            return "ok"

    class FakeClient:
        models = FakeModels()
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def close(self): pass

    monkeypatch.setattr(ai, "_client", lambda: FakeClient())
    monkeypatch.setattr(ai, "WAITS", (0, 0))
    monkeypatch.setattr(ai, "MODEL_OVERRIDE", None)
    ai._RESOLVED.clear()
    ai._RESOLVED.update(candidates=["gemini-9.0-flash", "gemini-8.5-flash"], available=[])
    assert ai._generate("x", None) == "ok"
    assert calls == ["gemini-9.0-flash", "gemini-8.5-flash"]   # 503 -> next model at once
    assert ai._RESOLVED["model"] == "gemini-8.5-flash"


def test_rank_flash_models():
    names = ["models/gemini-2.5-flash", "models/gemini-2.5-flash-lite", "models/gemini-3.8-flash",
             "models/gemini-3.8-flash-preview-09", "models/gemini-3.8-pro", "models/gemini-3.8-flash-image"]
    assert ai.rank_flash_models(names) == ["gemini-3.8-flash", "gemini-2.5-flash", "gemini-2.5-flash-lite"]


def test_gemini_timeout_moves_to_next_model(monkeypatch):
    calls = []

    class ReadTimeout(Exception):
        pass

    class FakeModels:
        def generate_content(self, model, contents, config):
            calls.append(model)
            if model == "gemini-9.0-flash":
                raise ReadTimeout("timed out")
            return "ok"

    class FakeClient:
        models = FakeModels()
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def close(self): pass

    monkeypatch.setattr(ai, "_client", lambda: FakeClient())
    monkeypatch.setattr(ai, "MODEL_OVERRIDE", None)
    ai._RESOLVED.clear()
    ai._RESOLVED.update(candidates=["gemini-9.0-flash", "gemini-8.5-flash"], available=[])
    assert ai._generate("x", None) == "ok"
    assert calls == ["gemini-9.0-flash", "gemini-8.5-flash"]   # no waiting on a slow model


def test_gemini_429_retries_same_model(monkeypatch):
    from google.genai import errors as ge
    calls = []

    class FakeModels:
        def generate_content(self, model, contents, config):
            calls.append(model)
            if len(calls) == 1:
                raise ge.ClientError(429, {"error": {"code": 429, "message": "quota", "status": "RESOURCE_EXHAUSTED"}})
            return "ok"

    class FakeClient:
        models = FakeModels()
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def close(self): pass

    monkeypatch.setattr(ai, "_client", lambda: FakeClient())
    monkeypatch.setattr(ai, "WAITS", (0, 0))
    monkeypatch.setattr(ai, "MODEL_OVERRIDE", None)
    ai._RESOLVED.clear()
    ai._RESOLVED.update(candidates=["gemini-9.0-flash", "gemini-8.5-flash"], available=[])
    assert ai._generate("x", None) == "ok"
    assert calls == ["gemini-9.0-flash", "gemini-9.0-flash"]


def test_gemini_all_busy_lists_models_tried(monkeypatch):
    from google.genai import errors as ge

    class FakeModels:
        def generate_content(self, model, contents, config):
            raise ge.ServerError(503, {"error": {"code": 503, "message": "busy", "status": "UNAVAILABLE"}})

    class FakeClient:
        models = FakeModels()
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def close(self): pass

    monkeypatch.setattr(ai, "_client", lambda: FakeClient())
    monkeypatch.setattr(ai, "MODEL_OVERRIDE", None)
    ai._RESOLVED.clear()
    ai._RESOLVED.update(candidates=["gemini-9.0-flash", "gemini-8.5-flash-lite"], available=[])
    with pytest.raises(RuntimeError, match="gemini-9.0-flash: 503.*gemini-8.5-flash-lite: 503"):
        ai._generate("x", None)


def test_candidate_view_payout_and_late_flag(m):
    r = matching.decide({"agent_name": "Peak Journeys", "route": "DEL-DXB", "time_reference": "last week",
                         "booking_reference": "RF-1099"}, m, pd.Timestamp("2026-06-05"), [])
    v = matching.candidate_view(r["candidates"], m, pd.Timestamp("2026-06-05")).set_index("refund_id")
    assert v.loc["RF-1145", "payout_inr"] == 21300 - 1700        # pending: requested minus deduction
    assert bool(v.loc["RF-1145", "logged_after_message"]) is True
    assert v.loc["RF-1023", "payout_inr"] == 11400                # paid: what Finance actually paid



def test_min_thinking_per_model_generation():
    from google.genai import types
    cfg = types.GenerateContentConfig(temperature=0)
    assert ai._with_min_thinking(cfg, "gemini-3.8-flash").thinking_config.thinking_level == types.ThinkingLevel.MINIMAL
    assert ai._with_min_thinking(cfg, "gemini-2.5-flash-lite").thinking_config.thinking_budget == 0
    assert ai._with_min_thinking(cfg, "gemini-2.0-flash").thinking_config is None


def test_drafting_tries_flash_lite_first(monkeypatch):
    monkeypatch.setattr(ai, "MODEL_OVERRIDE", None)
    ai._RESOLVED.clear()
    ai._RESOLVED.update(candidates=["gemini-3.8-flash", "gemini-2.5-flash", "gemini-3.8-flash-lite"], available=[])
    assert ai.model_candidates("draft")[0] == "gemini-3.8-flash-lite"
    assert ai.model_candidates("intake")[0] == "gemini-3.8-flash"


class _Chunk:
    def __init__(self, t): self.text = t


def _fake_client(behaviour, calls):
    class FakeModels:
        def generate_content_stream(self, model, contents, config):
            calls.append((model, getattr(config, "thinking_config", None) is not None))
            return behaviour(model, config)

    class FakeClient:
        models = FakeModels()
        def close(self): pass
    return lambda: FakeClient()


def test_streaming_falls_back_when_first_model_busy(monkeypatch):
    from google.genai import errors as ge
    from google.genai import types
    calls = []

    def behaviour(model, config):
        def gen():
            if model == "gemini-9.0-flash-lite":
                raise ge.ServerError(503, {"error": {"code": 503, "message": "busy", "status": "UNAVAILABLE"}})
            yield _Chunk("Hello ")
            yield _Chunk("agent.")
        return gen()

    monkeypatch.setattr(ai, "_client", _fake_client(behaviour, calls))
    monkeypatch.setattr(ai, "MODEL_OVERRIDE", None)
    ai._RESOLVED.clear()
    ai._RESOLVED.update(candidates=["gemini-9.0-flash", "gemini-9.0-flash-lite"], available=[])
    assert "".join(ai.draft_agent_update_stream({"Refund reference": "RF-1"})) == "Hello agent."
    assert [c[0] for c in calls] == ["gemini-9.0-flash-lite", "gemini-9.0-flash"]   # lite first, then fallback


def test_rejected_thinking_setting_retries_without_it(monkeypatch):
    from google.genai import errors as ge
    calls = []

    def behaviour(model, config):
        def gen():
            if config.thinking_config is not None:
                raise ge.ClientError(400, {"error": {"code": 400, "message": "thinking_level is not supported",
                                                     "status": "INVALID_ARGUMENT"}})
            yield _Chunk("ok")
        return gen()

    monkeypatch.setattr(ai, "_client", _fake_client(behaviour, calls))
    monkeypatch.setattr(ai, "MODEL_OVERRIDE", None)
    ai._RESOLVED.clear()
    ai._RESOLVED.update(candidates=["gemini-3.8-flash-lite"], available=[])
    assert "".join(ai.draft_agent_update_stream({"a": 1})) == "ok"
    assert calls == [("gemini-3.8-flash-lite", True), ("gemini-3.8-flash-lite", False)]
