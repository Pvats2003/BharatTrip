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
| Tab | What happens | Who does the work |
|---|---|---|
| ① Daily problem cases | Upload both trackers → clean → join on refund ID → one true state per refund → worklist with owner, age in days and next action | Plain code (`recon.py`) |
| ② AI intake | Paste an email/WhatsApp (Hinglish OK) → Gemini returns fixed JSON fields plus an exact quote for each → code matches to existing refunds and links or creates a draft ticket → a human approves | AI reads the text; code does matching and dates (`matching.py`) |
| ③ AI agent update | Pick a refund → code builds the facts (state, amounts, deduction) → Gemini drafts a short message → code checks every ₹ figure is in the facts → a human edits and approves | AI writes; code supplies and checks the numbers |

**Design rule:** matching and money are never done by the AI. Every AI output is shown next to the exact source it was given, and nothing counts as sent until a human clicks Approve (approvals download as a CSV log). The prototype never sends anything itself.

Model: Gemini Flash (`gemini-flash-latest` by default; set `GEMINI_MODEL` to change it). Free-tier note: Google may use free-tier prompts to improve its models, which is fine here because the data is synthetic. Do not use real customer data on the free tier.

## Files
- `recon.py`: cleaning, reconciliation, true state, problem cases, metric 1, agent-update facts
- `matching.py`: rule-based link-or-create for informal requests
- `ai.py`: the two Gemini calls and the number guardrail
- `app.py`: the Streamlit app
- `phase1_analysis.py`: Phase 1 analysis; writes `output/` (findings, tables, cleaning log)
- `tests/test_rules.py`: offline tests of the rules (`python -m pytest -q`)
- `test_ai.py`: live test of the AI on the three brief messages (`python test_ai.py`, needs a key)
