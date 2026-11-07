# BharatTrip refunds: why escalations doubled, and how to bring them down

*AI Operations Associate take-home · Data: Support and Finance trackers and escalation log, Feb–Jun 2026 (snapshot 30 June)*

## 1. Problem diagnosis

**Escalations are not rising because of volume.** Refund requests were flat at 142–152 a month, but escalations per 100 refunds went
**15.1 (Mar) → 17.7 (Apr) → 20.9 (May) → 52.8 (Jun)**.

**The real problem: no one owns the refund end to end, and the two teams' records never meet.** Support and Finance each keep their own
sheet with their own statuses. Nothing checks one against the other, and some requests never enter either. That gap was always there. In May, four new
failures started flowing through it at once:

1. **Support "Closed" stopped meaning "paid".** 81 refunds are Closed in Support but not paid: 69 never reached Finance, 12 are still pending there.
   Every one carries a note telling the agent it was done. The share of closed tickets missing in Finance went from 2–4% (Feb–Apr) to **19% in May and 33% in June**.
2. **Informal requests are lost.** Email and WhatsApp requests that nobody logs. 29 escalations point to a refund in *neither* tracker (including RF-1098 and RF-1099 from the brief), 20 of them in June.
3. **A new deduction nobody explains.** Deductions did not exist before May. Since then 81 refunds have had one (₹1.47 lakh, mostly ₹1,500), and no Support note mentions it.
4. **Finance approvals stalled.** Sign-offs fell from 41–46 a month to 1 in June, and all 58 pending payouts arrived in June.

The old complaint type ("no status update") is flat or falling, but it shows the same root cause: **54 of its 61 cases were already paid**. Nobody told the agent.

## 2. Analysis

**Method.** I cleaned both trackers in Python (fixed 58 malformed IDs, parsed 345 hand-typed dates, standardised 95 agent names, removed 12 duplicate rows),
joined them on refund ID, and gave each of 749 refunds one "true state": Paid 571, Closed in Support but missing in Finance 69, Pending in Finance 55, Declined 38,
In Finance only 16. Escalations were sorted into root causes with fixed keyword rules, then checked against the trackers. For example, all 31 "closed but not received"
complaints with a ref sit on refunds that really are Closed-but-missing.

| Escalations by root cause | Mar | Apr | May | Jun |
|---|---|---|---|---|
| No status update (old type) | 18 | 21 | 11 | 11 |
| Handoff break: closed in Support, never reached Finance | 2 | 2 | 6 | 22 |
| Informal request never logged | 1 | 3 | 2 | 20 |
| Amount / deduction not explained | 0 | 0 | 8 | 11 |
| Approval / payout delay | 0 | 0 | 2 | 10 |
| Decline not explained | 2 | 0 | 2 | 1 |
| **Total** | **23** | **26** | **31** | **75** |

**Where the trackers agree, disagree, or fall silent.**

- **They agree** on 571 paid refunds. Agent and route match on every refund found in both sheets.
- **They disagree** on 51 amounts. In 50 of them, Support's amount minus Finance's deduction is exactly what was paid; the last is a Support double entry.
- **They fall silent** on 69 Support-only closures, 16 Finance-only refunds (no ticket at all), and every unlogged email or WhatsApp request.

**What changed in May.**

- **Not one channel.** Portal has the most handoff failures (32 of 56 in May–June) only because it carries half of all requests. Failure rates rose on every channel:
  Portal 2.7% → 28%, WhatsApp 0% → 38%, Phone 6% → 19%, Email 3% → 15%.
- **Two queues hit hardest.** Rakesh N. (44% of his May–June closures went missing, 23 tickets) and Vikram T. (36%, 10 tickets) account for 59% of failures. But every handler rose from 0–2% to 11–23%, so this is a process break, not two individuals.
- **Handoff time didn't change.** Refunds that did reach Finance still arrived in about 2.5 days in every month. A ticket either reached Finance or it never did.
- **Payouts slowed at sign-off.** Received-to-paid time rose from 2.9 days (Feb–Mar) to 6.2 in May. Signed-off payouts took 15.6 days in May and 19.0 in June, against about 3.5 before.
  A blank "Approved By" is *not* new: it was 71–73% blank in Feb–Apr too.

**What I'd validate with more access.**

- What changed in the Support→Finance handoff in May (a new form, a new inbox, a staff change?).
- The deduction policy and when it started.
- Why approvals stopped in June (is the approver away?).
- The shared inbox and WhatsApp, for the true volume of unlogged requests.
- **9 refunds entered twice in Finance (₹2.05 lakh), to check against bank statements for double payouts.**

## 3. Solution design

**Single source of truth: one refund register, keyed on refund ID, with one status both teams share.** Every request gets an ID the day it arrives,
whatever the channel. Both teams update the same row, and Support can no longer "close" a refund on its own.

| Status | Set by | Meaning, and what the agent is told |
|---|---|---|
| Requested | Support | Logged with ID. Agent gets the ID the same day |
| With Finance | Support | Sent to Finance; the register records who and when |
| On hold (reason) | Finance | Supplier, approval or amount check. The reason is required |
| Paid (amount, deduction + reason) | **Finance only** | Only now is the agent told "done", with any deduction explained |
| Declined (policy reason) | Finance | The reason is required and goes to the agent |

**What to automate (the prototype does all four):**

- A daily reconciliation of the two sheets that produces a problem list with owner, age in days and next action.
- AI intake of email and WhatsApp (including Hinglish) into a draft ticket, matched to existing refunds by rules.
- AI-drafted agent updates built from the true state, with the deduction explained.
- Number checks on every draft.

**What to keep manual, and why:**

- Approving every AI output before it goes out. These are customer messages about money.
- Linking a message to a refund when the match is ambiguous. In the data, the same agent can have two refunds on the same route on the same day.
- Finance sign-off and declines, which are policy and money decisions.
- Setting the deduction policy, a business decision. The register only forces a reason to be recorded.

**How the teams stay in sync, with no new headcount:**

- A 10-minute daily huddle between the Support lead and the Finance lead, working through the problem list.
- A backup approver, so sign-off never sits with one person.
- A one-line rule: *no "done" message until Finance marks it Paid.*

The time comes from work that disappears. Each of the 155 escalations meant repeated chasing. Automating logging, reconciliation and message drafting removes that rework instead of adding people.

## 4. Metrics

| Metric | Baseline (30 June) | Good result after one month |
|---|---|---|
| **1. Refunds Closed in Support but not paid in Finance for more than 7 days** (missing in Finance + still pending there) | **63** (of 81 closed-but-unpaid; ₹12.7 lakh) | **Near zero (≤ 5)**, and none older than 14 days |
| **2. Escalations per 100 refunds** | **52.8** (June) | **Back to the Mar–Apr level of 16.4** (49 escalations / 299 refunds) |

**Guardrails to watch alongside them:**

- Median payout time back to 3 days or less.
- No pending payout older than 7 days.
- Zero escalations for refunds that are in no tracker.

*Key assumptions:*

- Text dates are day-first (checked: no text date has a second part above 12).
- Where both sheets hold a refund, Finance decides whether money moved.
- Duplicates were kept once and flagged.
- Escalations per 100 refunds = escalations raised in a month ÷ refunds requested that month.
- No SLA exists in the data, so 7 days was chosen: successful handoffs take about 2.5 days.
- The true volume of informal requests is unknown beyond what the escalations show.

*Prototype:* a Streamlit app (link / repo `pvats2003/bharattrip`). Run it with `pip install -r requirements.txt && streamlit run app.py`.
