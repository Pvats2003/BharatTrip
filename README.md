# BharatTrip Refund Desk

Take-home for the AI Operations Associate role. Reconciles the Support and Finance refund trackers, builds a daily
problem-case list, and uses Google Gemini (free tier) for two narrow jobs: reading informal messages and drafting agent updates.

## Run it (one line)

```bash
pip install -r requirements.txt && GEMINI_API_KEY=your-key streamlit run app.py
```

Without a key, tab ① (the reconciliation and problem list) works fully, and the two AI buttons stay disabled.

## Host it (free link on Streamlit Community Cloud)
1. Go to share.streamlit.io and sign in with GitHub.
2. Choose **New app**, pick repo `pvats2003/bharattrip`, the branch, and main file `app.py`.
3. Under **Advanced settings → Secrets**, paste `GEMINI_API_KEY = "your-key"` (free key from aistudio.google.com), then click **Deploy**.

## What it does
| Tab | For | What happens |
|---|---|---|
| 📋 Today's worklist | Support and Finance leads, every morning | Every refund needing action, most urgent first (🔴 agent told "done" but not paid). Filter by person or problem, search, and tick a case to see **what Support says vs what Finance says**, the next step and its owner. All plain code (`recon.py`). |
| 📨 New message → ticket | Whoever reads the inbox or WhatsApp | Paste a message (Hinglish OK). Gemini reads it into facts with exact quotes; code checks both trackers and either links to the refund (amount and payout worked out by code, with source) or creates a new ticket. You approve. |
| ✉️ Reply to agent | Support | Pick a refund and get a short status message built only from tracker facts, explaining any deduction. A number check flags any amount not in the facts. Edit, approve, copy. |

**Design rule:** matching and money are never done by the AI. Every AI output is shown next to the exact source it was given, and nothing counts as sent until a human clicks Approve (approvals download as a CSV log). The prototype never sends anything itself.

Model: Gemini Flash. The app asks the API which models the key can use and picks the newest stable Flash; set `GEMINI_MODEL` to override. Free-tier note: Google may use free-tier prompts to improve its models, which is fine here because the data is synthetic. Do not use real customer data on the free tier.

## Files
- `recon.py`: cleaning, reconciliation, true state, problem cases, metric 1, agent-update facts
- `matching.py`: rule-based link-or-create for informal requests
- `ai.py`: the two Gemini calls and the number guardrail
- `app.py`: the Streamlit app
- `phase1_analysis.py`: Phase 1 analysis; writes `output/` (findings, tables, cleaning log)
- `tests/test_rules.py`: offline tests of the rules (`python -m pytest -q`)
- `test_ai.py`: live test of the AI on the three brief messages (`python test_ai.py`, needs a key)
