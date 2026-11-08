# BharatTrip Refund Desk

An operations tool that reconciles the Support and Finance refund trackers, gives both teams one prioritised
worklist, turns informal emails and WhatsApp messages into tickets, and drafts status updates to travel agents.

**Design rule:** matching and money are plain, tested code. The AI (Google Gemini) only reads messy text and
writes messages. Every AI output is shown next to the source it used, and nothing is saved or sent until a named
person approves it.

## Run it

```bash
pip install -r requirements.txt && GEMINI_API_KEY=your-key streamlit run app.py
```

Without a key, the Worklist and Approval log work fully, and the two AI screens are disabled with a clear notice.

## Screens

| Screen | Who uses it | What it does |
|---|---|---|
| Worklist | Support and Finance leads, each morning | Every refund needing action, ranked Urgent / High / Medium / Low, then by days waiting. Filter by owner or problem, search, and open a case to see what Support recorded next to what Finance recorded, with the next step and owner. |
| New message | Whoever reads the inbox or WhatsApp | Paste a message (English or Hinglish). Gemini extracts the facts with exact quotes; code checks both trackers and either links to the refund (amount and payout worked out by code, with their source) or prepares a new ticket. Approve to send it to the next stage. |
| Agent reply | Support | Pick a refund and get a short status message built only from tracker facts, explaining any deduction. A number check flags any amount not in the facts. Edit, approve, copy. |
| Approval log | Team leads, audit | Every approval: who, when, what was decided, amounts, and the source text. Downloadable CSV. |

## Configuration

| Setting | Where | Purpose |
|---|---|---|
| `GEMINI_API_KEY` | environment variable or Streamlit Secrets | Enables the AI screens (free key: aistudio.google.com) |
| `GEMINI_MODEL` | optional | Pin a model. By default the desk picks the newest stable Flash model the key can use and falls back to others if one is busy |
| `APPROVAL_LOG_PATH` | optional | Where the append-only approval log is written (default `approvals/approval_log.csv`) |
| `.streamlit/config.toml` | repository | Fixed light theme, viewer-only toolbar, no stack traces shown to users, 20 MB upload limit |

**Deploy on Streamlit Community Cloud:** New app, choose this repository, branch and `app.py`, then add
`GEMINI_API_KEY` under Advanced settings, Secrets.

## Reliability and safety
- **Uploads:** tracker files are validated. Missing columns or unreadable files produce a clear message, and the desk keeps showing the last good data. Rows with no usable refund ID are dropped and listed in the cleaning log.
- **AI calls:** 20-second timeout per request, retry on rate limits, automatic fallback to the next Flash model when one is busy, minimal "thinking" for speed, and plain-language error messages (technical detail kept in an expander and the server log).
- **Approvals:** a name is required; each approval gets an ID; approving the same item twice is ignored; the log is append-only, with a file lock for concurrent users.
- **Screens:** an unexpected error on one screen shows a message instead of breaking the app, and is logged.
- **Tests:** `python -m pytest -q` (23 tests: cleaning rules, matching, payout maths, AI fallback paths with a fake Gemini, and the screens themselves). Run automatically by GitHub Actions on every push.

## Known limits (next steps for a full production rollout)
- **Sign-in:** the approver types their name. Production needs company single sign-on, so names cannot be faked.
- **Storage:** the approval log is a file on the server. On Streamlit Community Cloud it is reset when the app restarts, so download it daily. Production should write to a database, and push linked or new tickets straight into the refund register.
- **Data feed:** trackers are uploaded by hand. Production should read the shared refund register directly.
- **AI tier:** the free Gemini tier is sometimes slow or busy. Use a paid tier in production, and do not send real customer data to a free tier.

## Files
- `recon.py`: cleaning, reconciliation, true status, problem cases, metric 1, agent-update facts, payout proof
- `matching.py`: rule-based link-or-create for informal requests, candidate comparison
- `ai.py`: the two Gemini calls, model fallback, error messages, number guardrail
- `approvals.py`: append-only approval log
- `app.py`: the Streamlit interface
- `phase1_analysis.py`: Phase 1 analysis, writes `output/` (findings, tables, cleaning log)
- `tests/`: automated tests; `test_ai.py`: live test of the AI on the three brief messages (needs a key)
