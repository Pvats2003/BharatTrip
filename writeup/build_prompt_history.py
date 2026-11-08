"""Builds writeup/BharatTrip_Prompt_History.html (rendered to PDF separately)."""
import html
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import ai  # noqa: E402  (to quote the prototype's Gemini prompts exactly as shipped)

E = html.escape

INITIAL = """[Attached: BharatTrip_Refund_Data.xlsx and BharatTrip_Task_Brief.pdf] I'm doing a take-home for an "AI Operations Associate" role at BharatTrip, a B2B travel company. Attached: the task brief (PDF) and BharatTrip_Refund_Data.xlsx (tabs: Read_Me, Support_Tracker, Finance_Tracker, Escalations). Read both fully before doing anything.

Context: Support logs refund requests in one sheet, Finance logs payouts in another. They were never reconciled. Some requests come by email/WhatsApp and never get logged. Escalations rose for two months while refund volume stayed flat (~150/month). Leadership wants escalations down without adding headcount.

My first-pass hypothesis (verify or disprove, don't assume it's right):
- Support "Closed" doesn't mean paid. ~72 tickets are Closed in Support with no Finance record, jumping from ~3-6/month to ~22-25/month in May-June, mostly from the Portal channel.
- Escalation growth comes from new failure types (handoff breaks, never-logged informal requests, approval delays, unexplained deductions), not from the old "no status update" type.
- Most amount gaps are explained by Finance deductions that were never told to the agent.
- Finance pending payouts all arrived in June; payout time is rising; Approved By is mostly blank.

Phase 1: Clean and reconcile (Python/pandas, show me the code)
1. Normalise IDs (e.g. "RF 1750" -> "RF-1750"), parse mixed date formats (ISO, dd-mm-yyyy, dd/mm/yy), trim and standardise status values, standardise agent names (case and spelling), and remove exact duplicate rows. Log every cleaning rule and how many rows it affected.
2. Join Support and Finance on the ID. Give each refund one "true state": Paid / Pending in Finance / Declined / Closed in Support but missing in Finance / In Finance only / Open in Support. Flag amount mismatches and whether the Deduction column explains them.
3. Sort every escalation into a root-cause category and show the categories by month. Flag escalations whose ticket exists in neither tracker.
4. Find what changed in May: break the handoff failures down by channel, handler and month. Show handoff time (Support request -> Finance received) and payout time (received -> processed) by month.
Output: a short findings summary with numbers, plus a list of assumptions. Stop here and wait for my review before Phase 2.

Phase 2: Prototype (a Streamlit app I can host and link)
- Upload the two trackers -> the same rule-based reconciliation -> a daily problem-case list showing owner, age in days and the next action (e.g. "Closed in Support, not in Finance: send to Finance").
- AI intake: paste an informal email/WhatsApp message (handle Hinglish) -> the Claude API pulls out agent, route, amount, date and booking reference into JSON -> fuzzy-match to existing records -> either link to a ticket or create a new draft ticket with an ID. Test on the three informal messages in the brief.
- AI agent update: for any refund, draft a short status message to the travel agent from its true state, explaining any deduction plainly.
- Design rule: matching and money calculations must be plain code, never the AI. The AI only reads messy text and writes messages. Every AI output shows the source it was based on, and a human approves it before anything is sent.
- Keep it simple. Clear README with a one-line run command. API key from an environment variable.

Phase 3: Help me draft
- A 3-page write-up covering: problem diagnosis, analysis, solution design (single source of truth = one refund register keyed on refund ID with a status shared by both teams; what to automate and what to keep manual; how the teams stay in sync) and metrics. Metrics: (1) count of refunds Closed in Support but not paid in Finance for more than X days, target near zero, (2) escalations per 100 refunds, target back to March-April levels within a month.
- Plain language. Every claim backed by a number from Phase 1.

I'm not a developer. Explain decisions briefly as you go, and ask before making any judgement call that changes the conclusions."""

# (stage, prompt text exactly as typed, what came out of it)
ENTRIES = [
    ("Brief and plan", INITIAL,
     "Read the brief and every tab of the workbook first. Built the cleaning and reconciliation code and the Phase 1 "
     "analysis. Results: 69 unique Closed-but-missing refunds (72 raw rows, 3 duplicates); failure rate jumped from "
     "2-4% to 19% in May and 33% in June; escalations per 100 refunds went 15.1 to 52.8. Hypothesis checked point by "
     "point: 'mostly Portal' was misleading (every channel rose; two handlers' queues hit hardest), and blank "
     "Approved By was not new. Stopped for review with three questions."),
    ("Phase 1 review", "1. add the 12 pending in finance, as technically its a wrong assumption\n"
                       "2. Fix is the process, but i guess we should keep the names in for visibility, suggest your reasonings\n"
                       "3. Yes lets keep 7 days",
     "Metric 1 redefined to 81 refunds (69 missing + 12 still pending in Finance); 63 older than 7 days. Names kept, "
     "always shown with rates and the fact that every handler rose. Built the Streamlit prototype (worklist, AI intake, "
     "AI agent update) and drafted the 3-page write-up."),
    ("Hosting and AI provider", "lets connect vercel and deploy there , make the url live also API key change it to gemini, for a free tier plan",
     "Explained that Vercel cannot host a Streamlit app and asked me to choose. My answers: host on Streamlit "
     "Community Cloud; use Gemini Flash. Switched the AI layer from Claude to Gemini; key read from GEMINI_API_KEY."),
    ("Live testing", "[Screenshot of the hosted app: 'AI call failed: Cannot send a request, as the client has been closed.']",
     "Reproduced the error locally: a temporary Gemini client was being closed mid-call. Fixed and pushed."),
    ("Live testing", "AI call failed: Cannot send a request, as the client has been closed.",
     "Made the fix robust (one client per call, kept open for the whole request), pinned the Gemini library and added "
     "a build label so I could confirm the live app had updated."),
    ("Live testing", "AI call failed: 404 NOT_FOUND. {'error': {'code': 404, 'message': 'models/gemini-flash-latest is not "
                     "found for API version v1, or is not supported for generateContent. Call ModelService.ListModels to "
                     "see the list of available models and their supported methods.', 'status': 'NOT_FOUND'}}",
     "Replaced the guessed model name with code that asks Google which models the key can use and picks the newest "
     "stable Flash model."),
    ("Live testing", "AI call failed: 503 UNAVAILABLE. {'error': {'code': 503, 'message': 'This model is currently "
                     "experiencing high demand. Spikes in demand are usually temporary. Please try again later.', "
                     "'status': 'UNAVAILABLE'}}",
     "Added retries and automatic fallback to other Flash models, with tests that simulate a busy model."),
    ("Live testing", "[Screenshot: 'Drafting…' spinner on the agent update screen] it has been drafting and buffereing from past 2 mins",
     "Found there was no time limit on requests. Added a 30-second limit per request and a 75-second overall cap, "
     "verified against a server that never replies."),
    ("Live testing", "AI call failed: Gemini is busy right now (no answer within 75s). Please try again in a minute. "
                     "Last error: 503 UNAVAILABLE. {'error': {'code': 503, 'message': 'This model is currently experiencing "
                     "high demand. Spikes in demand are usually temporary. Please try again later.', 'status': 'UNAVAILABLE'}}",
     "Changed strategy: a busy model is skipped at once instead of retried; up to six Flash and Flash-Lite models are "
     "tried; the last working model is remembered; the error lists every model tried."),
    ("Live testing", "[Screenshot: drafted message for RF-1042 with 'Number check passed'] msg draafted , but took around ~1 min",
     "Checked the draft against the facts (accurate, honest, no invented numbers). Added a line showing which model "
     "answered and how long it took, and shortened the per-model limit to 20 seconds."),
    ("Checking the matching", "[Two screenshots: the Peak Journeys email and the 'Create DRAFT-001' decision with candidate refunds] "
                              "the two windows compare each other, and the final payout amount should be 21300?",
     "Explained why not: the email states no amount and the AI may not guess one. RF-1145 (Rs 21,300) is a possible "
     "match logged after the email, but Finance recorded a Rs 1,700 deduction, so its payout would be Rs 19,600. Added "
     "a comparison table with payouts worked out by code and a 'logged after the message' flag."),
    ("Designing for the user", "[Screenshot: the raw JSON output on the intake screen] a non tech guy would use the dashboard, he "
                               "doesnt need to know the JSON and all, he need the analysis, coparison and accurate amount with "
                               "proof to be entered for the next stage",
     "Redesigned the intake screen in three plain steps: what the message says (with quotes as proof), what our records "
     "show, and what goes to the next stage, with the amount and its source (Rs 21,300 - Rs 1,700 = Rs 19,600). JSON "
     "moved to a collapsed audit section."),
    ("Designing for the user", "[Screenshot: 'Saved: linked to RF-1145' with no download button visible] no download button?",
     "Found the cause (the sidebar was drawn before the approval was processed). Added a download button right under the "
     "confirmation and made the sidebar refresh."),
    ("Speed", "the draft msg with AI takes too long, suggest ways to improve",
     "Gave seven ranked options with effort and effect, and recommended the first four."),
    ("Speed", "lets go with 1-4 for the time being",
     "Implemented: minimal 'thinking', Flash-Lite first for drafting, message streamed as it is written, and saved "
     "drafts per refund. Each change covered by a test."),
    ("Polish", "great, now lets polish the prototype, enhance the UI/UX and build it operations friendly simple to use and not "
               "confusing to a first time viewer",
     "Reworked the app for first-time users: purpose and 'how to use' at the top, task-named tabs, plain-language "
     "worklist ranked by priority, a case view showing what Support and Finance each recorded, and step-by-step reply."),
    ("Enterprise readiness", "good, now go through the site, remove the emoji's, work as a senior UI/UX developer and designer,access "
                             "the tool enhance it, act like a tester fix the bugs and then make it a production ready enterprise level tool",
     "Tested every path and fixed eight bugs (including two crashes). Removed all emojis and applied one design system. "
     "Added upload validation, named approvals with an append-only log and its own tab, plain-language AI errors, a "
     "locked-down configuration, pinned libraries and automatic tests on every push. Listed the remaining gaps "
     "(single sign-on, database, live data feed) honestly in the README."),
    ("Submission", "make a pdf for the prompt history submission", "This document."),
]

STAGE_CSS = """
@page { size: A4; margin: 15mm 16mm; }
body { font-family: Helvetica, Arial, sans-serif; font-size: 9.6pt; line-height: 1.4; color: #101828; }
h1 { font-size: 16pt; color: #1F3A5F; margin: 0 0 2px; }
h2 { font-size: 11.5pt; color: #1F3A5F; margin: 14px 0 6px; border-bottom: 1px solid #E4E7EC; padding-bottom: 3px; }
.sub { color: #667085; margin-bottom: 10px; }
.entry { border: 1px solid #E4E7EC; border-radius: 6px; padding: 8px 12px; margin: 0 0 9px; page-break-inside: avoid; }
.entry.long { page-break-inside: auto; }
.head { font-size: 8.5pt; color: #667085; text-transform: uppercase; letter-spacing: .04em; margin-bottom: 4px; }
.head b { color: #1F3A5F; }
.prompt { background: #F5F7FA; border-left: 3px solid #1F3A5F; padding: 6px 10px; white-space: pre-wrap;
          font-family: "Courier New", monospace; font-size: 8.6pt; margin: 0 0 6px; }
.out { margin: 0; }
.out b { color: #344054; }
ul { margin: 4px 0; padding-left: 18px; } li { margin: 2px 0; }
.sys { white-space: pre-wrap; font-family: "Courier New", monospace; font-size: 8.4pt; background: #F5F7FA;
       padding: 8px 10px; border-radius: 4px; }
"""


def build():
    parts = [f"<!doctype html><html><head><meta charset='utf-8'><style>{STAGE_CSS}</style></head><body>",
             "<h1>BharatTrip take-home: prompt history</h1>",
             "<div class='sub'>AI Operations Associate · every prompt I gave the AI coding assistant (Claude Code), in order, "
             "copied exactly as typed, with a one-line note on what came out of it. Screenshots I sent are described in "
             "[brackets]. Attached file paths are replaced by the file names.</div>",
             "<h2>How I worked with AI</h2><ul>"
             "<li><b>Hypothesis first, then verify.</b> I gave my own first-pass diagnosis and asked the AI to prove or disprove "
             "each point with the data, and to stop for my review before building anything.</li>"
             "<li><b>Clear division of labour.</b> Matching and money are plain code; AI only reads messy text and writes "
             "messages; a person approves every output.</li>"
             "<li><b>I made the judgement calls.</b> Metric definition, whether to name handlers, the 7-day threshold, hosting "
             "and AI provider were my decisions, after the AI laid out the options.</li>"
             "<li><b>Tested live and fed back real errors.</b> I deployed the app, used it as an operations user would, and "
             "sent back exact error messages and screenshots until it worked.</li>"
             "<li><b>Designed for the end user.</b> I pushed back when the screen was built for a developer rather than an "
             "operations user.</li></ul>",
             f"<h2>Prompts ({len(ENTRIES)})</h2>"]
    for i, (stage, prompt, out) in enumerate(ENTRIES, 1):
        cls = "entry long" if len(prompt) > 1500 else "entry"
        parts.append(f"<div class='{cls}'><div class='head'><b>Prompt {i}</b> · {E(stage)}</div>"
                     f"<div class='prompt'>{E(prompt)}</div><p class='out'><b>Outcome:</b> {E(out)}</p></div>")
    parts.append("<h2>Appendix: prompts the prototype sends to Gemini</h2>"
                 "<p>These are the system prompts inside the app (ai.py). The app also forces Gemini's reply into a fixed "
                 "JSON schema for message reading, and checks every amount in a drafted message against the facts in code.</p>"
                 "<p><b>1. Reading an email or WhatsApp message</b></p>"
                 f"<div class='sys'>{E(ai.INTAKE_SYSTEM)}</div>"
                 "<p><b>2. Drafting a status message to the agent</b> (the facts are computed by code and sent with it)</p>"
                 f"<div class='sys'>{E(ai.UPDATE_SYSTEM)}</div>")
    parts.append("</body></html>")
    out = os.path.join(os.path.dirname(__file__), "BharatTrip_Prompt_History.html")
    open(out, "w", encoding="utf-8").write("".join(parts))
    print(out)


if __name__ == "__main__":
    build()
