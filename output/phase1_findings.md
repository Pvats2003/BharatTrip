# Phase 1 findings: BharatTrip refund reconciliation

Source: `phase1_analysis.py` (all tables in `output/phase1_tables.md`). Snapshot date 30 June 2026.
After cleaning: 733 Support refunds and 680 Finance refunds, giving **749 unique refund IDs**.

## Headline
Refund volume is flat (144 / 152 / 147 / 148 / 142 requests, Feb–Jun). Escalations per 100 refunds went
**15.1 (Mar) → 17.7 (Apr) → 20.9 (May) → 52.8 (Jun)**. All of the growth comes from new failure types that
began in May. Each one is a break *between* the two teams, or between a team and the agent.

## 1. "Closed" in Support does not mean paid
| What a Support "Closed" ticket really is in Finance | Tickets |
|---|---|
| Paid | 571 |
| **Not in Finance at all** | **69** |
| Still pending in Finance (Support notes say "refund given") | 12 |
| Declined by Finance | 6 |

- 69 unique tickets are closed with no Finance record. (The raw count is 72; 3 of those rows are duplicates.)
- The failure rate jumped in May: **2.9% / 2.1% / 4.1% of closed tickets (Feb–Apr) → 18.7% (May) → 33.0% (Jun)**.
  In counts that is 4 / 3 / 6 → 26 / 30.
- Every one of them carries a Support note telling the agent it was done ("refund processed, informed agent", "refund given").
- Median age since Support closed them: 32 days. **61 are older than 7 days, 55 older than 14, 36 older than 30.**
  Together they are worth ₹10.8 lakh by Support amount.
- Hand-offs that *do* reach Finance arrive in a steady ~2.5 days in every month. The handoff doesn't slow down.
  Either the ticket reaches Finance or it never does.

## 2. What changed in May (handoff failures)
- **Not a Portal-specific problem.** Portal has the most failures (32 of 56 in May–Jun), but Portal is 51% of all
  requests in every month. Failure *rates* rose on every channel, Feb–Apr → May–Jun:
  Portal 2.7% → 28.1%, WhatsApp 0% → 37.5%, Phone 5.6% → 19.1%, Email 2.6% → 15.4%.
- **Partly concentrated in two handlers.** In May–Jun, Rakesh N. failed 44% of closed tickets (23 of 52, which is 41% of all
  failures) and Vikram T. failed 36% (10 of 28). Every other handler also rose, from 0–2% to 11–23%.
  So the process broke for everyone in May, and two people's queues were hit hardest.
- Most likely cause, which the data cannot prove: a change in May to how Support passes tickets to Finance, with no
  check that Finance actually received them. The internal note on 11 June describes exactly this.

## 3. Escalations by root cause (keyword rules on the complaint text)
| Root cause | Mar | Apr | May | Jun | Total |
|---|---|---|---|---|---|
| No status update (old type) | 18 | 21 | 11 | 11 | 61 |
| Handoff break (closed, never reached Finance) | 2 | 2 | 6 | 22 | 32 |
| Informal request never logged | 1 | 3 | 2 | 20 | 26 |
| Amount / deduction not explained | 0 | 0 | 8 | 11 | 19 |
| Approval / payout delay | 0 | 0 | 2 | 10 | 12 |
| Decline not explained | 2 | 0 | 2 | 1 | 5 |
| **Total** | **23** | **26** | **31** | **75** | **155** |

- The old type is flat or falling (18 → 21 → 11 → 11). The new types went 5 → 5 → 20 → 64.
- The categories hold up against the trackers. All 31 handoff-break escalations with a ref point to a ticket that
  really is Closed-but-missing. All 18 amount complaints with a ref point to a refund where a deduction exactly
  explains the gap.
- Surprise: **54 of the 61 "no status update" complaints are on refunds that were already paid.** The money
  went out and nobody told the agent.
- **29 escalations have no ticket in either tracker**: 10 quote a ref that exists nowhere (including RF-1098 and
  RF-1099 from the brief), and 19 have no ref at all. 20 of the 26 informal-request escalations came in June.
  These requests never entered any system.

## 4. Amount gaps = deductions nobody explained
- 51 paid refunds have Support amount ≠ Finance amount paid. **50 of them are exactly explained by the Deduction column.**
  The remaining one (RF-1847) is a Support double entry (₹23,500 vs ₹24,500), not a real gap.
- **Deductions did not exist before May**: 0 in Feb–Apr, 41 in May, 40 in June (81 refunds, ₹1.47 lakh in total, mostly ₹1,500).
  This looks like a new fee or policy that Support was never told about.
- Support notes on those refunds say "refund given" or "done". None mentions a deduction. 27 of the 81 have already escalated.

## 5. Finance: approvals stalled
- **All 58 pending payouts arrived in June** (4–30 June), and none has an approver.
  Reasons: supplier not confirmed 14, amount-mismatch hold 14, awaiting approval 13, in queue 10, manager sign-off 7.
- Payout time (received → processed): 2.9 / 2.9 / 2.7 days in Feb–Apr → **6.2 in May** → 4.6 in June (June looks lower only because slow cases
  are still pending). Payouts taking more than 7 days: 0 in Feb–Apr, 28 in May.
- The slowdown is in sign-off. Payouts *with* an approver took 3.2–3.9 days in Feb–Apr, then **15.6 days in May and 19.0 in June**.
  Approvals fell from 41–46 a month to 29 in May and **1 in June**.
- Correction to the hypothesis: a blank "Approved By" is not new. It was 71–73% blank in Feb–Apr. What changed is that
  sign-offs slowed sharply in May and nearly stopped in June.

## 6. Other data issues worth validating
- 9 refunds appear twice in Finance, identical apart from remarks like "re-entry" or "duplicate check pending". These are
  **possible double payouts worth ₹2.05 lakh**, to check against bank statements.
- 16 refunds are in Finance with no Support ticket (12 paid, 3 pending, 1 declined). Someone handled these outside the tracker.
- 10 Support ticket IDs were logged twice with different amounts or statuses.

## Hypothesis check
| Your hypothesis | Verdict |
|---|---|
| ~72 Closed with no Finance record, 3–6/month → 22–25/month in May–Jun | **Mostly right.** 69 unique (72 raw rows); 4/3/6 → 26/30 |
| ...mostly from Portal | **Misleading.** Largest count, but every channel's rate rose (Phone ~3×, Email ~6×, Portal ~10×, WhatsApp from 0%). Two handlers are the stronger concentration |
| Growth is new failure types, not "no status update" | **Confirmed.** Old type 18→11/month; new 5→64 |
| Amount gaps explained by deductions never told to agent | **Confirmed** (50 of 51). "Never told" is inferred from notes and complaints; we can't see the messages |
| Pending payouts all arrived in June | **Confirmed** (58 of 58) |
| Payout time rising | **Confirmed**, driven by sign-off delays |
| Approved By mostly blank | **True but not new** (~72% blank all along); approvals collapsed in June |

## Assumptions
1. Text dates are day-first (dd-mm-yyyy, dd/mm/yy). Checked: no text date has a second part above 12.
2. IDs are compared on their digits only: `RF 1750`, `rf-1750`, `RF1750` and `RF-1750 (revised)` are the same refund.
3. Where both sheets have a refund, Finance decides whether money moved (Paid / Pending / Declined).
4. Support "Not Eligible" counts as Declined. All 27 also show Declined in Finance.
5. Support ID logged twice with different values: kept the row with the most advanced status, then the latest update, and flagged it (10 IDs).
6. Finance ID entered twice, identical except remarks: counted once and flagged as a possible double payout (9 IDs).
7. A blank Deduction counts as ₹0 for the maths.
8. Escalations per 100 refunds = escalations raised in the month ÷ refunds requested in the month.
9. Escalation categories come from fixed keyword rules on the complaint text, not AI. "No reference number given" counts as
   an informal/unlogged request. The single "no one owns it" case counts as approval/payout delay.
10. Ages are measured to the 30 June snapshot. The brief and the data give no SLA, so 7/14/30-day cut-offs are shown.
11. Unlogged email/WhatsApp requests are invisible in this data except where an escalation mentions them, so their true volume is unknown.

## What I'd validate with more access
Bank statements (the 9 possible double payouts, and whether "Paid" really landed); what changed in the Support→Finance handoff in May;
the deduction policy and when it started; why sign-offs stopped in June (approver absence?); the shared inbox and WhatsApp log for unlogged requests.
