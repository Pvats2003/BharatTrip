"""
Phase 1: clean, reconcile and analyse the BharatTrip refund data.

Run:  python phase1_analysis.py
Writes CSVs + a markdown report of every table to ./output/
"""
from pathlib import Path

import pandas as pd

import recon

XLSX = Path("data/BharatTrip_Refund_Data.xlsx")
OUT = Path("output")
OUT.mkdir(exist_ok=True)
REPORT = []


def show(title, df):
    """Print a table and keep it for the markdown report."""
    print(f"\n=== {title} ===\n{df}")
    REPORT.append(f"\n### {title}\n\n{df.to_markdown()}\n")


# --------------------------------------------------------------------------
# 1. Clean + reconcile
# --------------------------------------------------------------------------
support_raw = pd.read_excel(XLSX, "Support_Tracker")
finance_raw = pd.read_excel(XLSX, "Finance_Tracker")
esc_raw = pd.read_excel(XLSX, "Escalations")

m, cleanlog, sup, fin = recon.load_and_reconcile(support_raw, finance_raw)

# Escalations cleaning (logged too)
e = esc_raw.copy()
e["refund_id"] = e["Related Ticket / Ref"].map(recon.norm_id)
no_ref = e["refund_id"].isna()
cleanlog = pd.concat([cleanlog, pd.DataFrame([
    {"sheet": "Escalations", "rule": "Rows read", "rows_affected": len(e)},
    {"sheet": "Escalations", "rule": "Related ref normalised to RF-####",
     "rows_affected": int((e["Related Ticket / Ref"].astype(str).str.strip() != e["refund_id"]).sum() - no_ref.sum())},
    {"sheet": "Escalations", "rule": "No usable ref ('no ref', 'not known', '-', blank) -> left blank",
     "rows_affected": int(no_ref.sum())},
    {"sheet": "Escalations", "rule": "Parsed text dates in Raised On / Resolved On (day-first)",
     "rows_affected": int(e["Raised On"].map(lambda v: isinstance(v, str)).sum()
                          + e["Resolved On"].map(lambda v: isinstance(v, str)).sum())},
])], ignore_index=True)
e["raised"] = e["Raised On"].map(recon.parse_date)
e["resolved"] = e["Resolved On"].map(recon.parse_date)
e["month"] = e["raised"].dt.to_period("M").astype(str)

show("Cleaning log", cleanlog)
cleanlog.to_csv(OUT / "cleaning_log.csv", index=False)

# --------------------------------------------------------------------------
# 2. True state + amounts
# --------------------------------------------------------------------------
show("True state of every refund", m["true_state"].value_counts().to_frame("refunds"))
show("Support status vs Finance status (raw cross-check)",
     pd.crosstab(m.s_status.fillna("(no Support row)"), m.f_status.fillna("(no Finance row)")))

closed = m[m.s_status == "Closed"]
show("What 'Closed' in Support actually means in Finance",
     closed.true_state.value_counts().to_frame("closed tickets"))
said_paid_not_paid = m[(m.s_status == "Closed") & m.f_status.isin(["Pending Payout"])]
show("Closed in Support + Finance still Pending (agent told it's done)",
     said_paid_not_paid[["refund_id", "s_notes", "f_remarks", "f_received", "approved_by"]].reset_index(drop=True))

show("Volume: refunds by request month", m.groupby("request_month").size().to_frame("refunds"))

mm = m[m.amount_mismatch]
show("Amount mismatches on paid refunds (Support amount vs Finance paid)",
     mm.mismatch_type.value_counts().to_frame("refunds"))
show("Amount mismatch detail",
     mm[["refund_id", "agent", "s_amount", "f_paid", "f_deduction", "amount_gap", "mismatch_type",
         "s_conflict", "s_conflict_amounts", "request_month"]].sort_values("mismatch_type").reset_index(drop=True))
show("Paid refunds with a deduction, by month (paid month)",
     m[(m.true_state == "Paid")].assign(ded=lambda d: d.f_deduction > 0,
                                        pm=lambda d: d.f_processed.dt.to_period("M").astype(str))
     .groupby("pm").agg(paid=("refund_id", "size"), with_deduction=("ded", "sum")))
show("Deduction recorded but Support amount already equals paid amount",
     m[m.deduction_without_gap][["refund_id", "s_amount", "f_paid", "f_deduction"]].reset_index(drop=True))
show("Possible double payouts (same ref entered twice in Finance)",
     m[m.f_double_entry.fillna(False)][["refund_id", "f_agent", "f_paid", "f_processed", "approved_by"]].reset_index(drop=True))
show("Support IDs logged twice with different values (kept one)",
     m[m.s_conflict.fillna(False)][["refund_id", "s_amount", "s_conflict_amounts", "s_status", "true_state", "f_paid"]].reset_index(drop=True))
show("In Finance only (no Support ticket)",
     m[m.true_state == "In Finance only"][["refund_id", "f_agent", "f_status", "f_paid", "f_received", "f_remarks"]].reset_index(drop=True))

# --------------------------------------------------------------------------
# 3. Escalations -> root cause (keyword rules on the complaint text)
# --------------------------------------------------------------------------
RULES = [  # order matters: first match wins
    ("Handoff break: closed in Support, never reached Finance",
     ["finance has no record", "marked complete on support", "support says refund is done",
      "finance says they never received"]),
    ("Informal request never logged",
     ["ignored entirely", "never got a ticket number", "no reference number", "ignored for two weeks"]),
    ("Approval / payout delay", ["approval queue", "still sitting unpaid", "no one owns it"]),
    ("Amount or deduction not explained", ["less than the amount", "short payment", "two different refund figures"]),
    ("Decline not explained", ["rejected, but no reason", "decline communicated"]),
    ("No status update (old type)", ["status update", "follow-ups on refund status"]),
]


def categorise(text):
    t = str(text).lower()
    for cat, keys in RULES:
        if any(k in t for k in keys):
            return cat
    return "Uncategorised"


e["category"] = e["Complaint"].map(categorise)
assert (e.category != "Uncategorised").all()
e = e.merge(m[["refund_id", "true_state", "channel", "handler", "mismatch_type", "f_deduction"]],
            on="refund_id", how="left")
e["tracker_match"] = "In tracker(s)"
e.loc[e.refund_id.notna() & e.true_state.isna(), "tracker_match"] = "Ref given, in NEITHER tracker"
e.loc[e.refund_id.isna(), "tracker_match"] = "No ref at all"

show("Complaint text -> category mapping",
     e.groupby(["category", "Complaint"]).size().to_frame("n"))
by_month = pd.crosstab(e.category, e.month, margins=True, margins_name="Total")
show("Escalations by root cause and month", by_month)
vol = m.groupby("request_month").size()
rate = (e.groupby("month").size() / vol * 100).dropna().round(1)
show("Escalations per 100 refunds (by month)",
     pd.DataFrame({"escalations": e.groupby("month").size(), "refunds": vol}).dropna()
     .assign(per_100=rate))
old = "No status update (old type)"
show("Old vs new failure types by month",
     pd.crosstab(e.category.eq(old).map({True: "Old: no status update", False: "New types"}), e.month, margins=True))
show("Category vs tracker state (does the data back up the complaint?)",
     pd.crosstab(e.category, e.true_state.fillna(e.tracker_match)))
show("Escalations whose ticket is in NEITHER tracker",
     e[e.tracker_match != "In tracker(s)"][["Escalation ID", "Related Ticket / Ref", "raised", "Agent / Team",
                                             "Channel", "Complaint", "tracker_match"]].reset_index(drop=True))
show("Escalation status: still open at snapshot, by category",
     pd.crosstab(e.category, e.Status))
show("Amount-complaints: what the data says",
     e[e.category.str.startswith("Amount")][["Escalation ID", "refund_id", "true_state", "mismatch_type", "f_deduction"]].reset_index(drop=True))
e.to_csv(OUT / "escalations_categorised.csv", index=False)

# --------------------------------------------------------------------------
# 4. What changed in May
# --------------------------------------------------------------------------
ho = m[m.s_status == "Closed"].assign(missing=lambda d: d.true_state.str.startswith("Closed in Support"))


def rate_table(col):
    t = ho.groupby(col).agg(closed=("refund_id", "size"), missing_in_finance=("missing", "sum"))
    t["pct_missing"] = (t.missing_in_finance / t.closed * 100).round(1)
    return t


show("Handoff failures by request month", rate_table("request_month"))
show("Handoff failures by channel (all months)", rate_table("channel"))
for period, months in [("Feb-Apr", ["2026-02", "2026-03", "2026-04"]), ("May-Jun", ["2026-05", "2026-06"])]:
    sub = ho[ho.request_month.isin(months)]
    t = sub.groupby("channel").agg(closed=("refund_id", "size"), missing=("missing", "sum"))
    t["pct"] = (t.missing / t.closed * 100).round(1)
    show(f"Handoff failure rate by channel, {period}", t)
show("Handoff failures: channel x month (counts)",
     pd.crosstab(ho[ho.missing].channel, ho[ho.missing].request_month, margins=True))
show("Handoff failures by handler (all months)", rate_table("handler"))
show("Handoff failures: handler x month (counts)",
     pd.crosstab(ho[ho.missing].handler, ho[ho.missing].request_month, margins=True))
show("Portal share of all requests by month",
     pd.crosstab(m.request_month, m.channel, normalize="index").round(2))

paid = m[m.f_received.notna()]
show("Handoff time (Support request -> Finance received), days, by request month",
     paid.groupby("request_month").handoff_days.describe()[["count", "mean", "50%", "max"]].round(1))
done = m[m.f_processed.notna()]
show("Payout time (Finance received -> processed), days, by Finance-received month",
     done.groupby("finance_month").payout_days.describe()[["count", "mean", "50%", "max"]].round(1))
show("Payout time by month and whether 'Approved By' is filled",
     done.assign(approved=done.approved_by.notna()).pivot_table(
         index="finance_month", columns="approved", values="payout_days", aggfunc="mean").round(1))
fm = m[m.f_status.notna()]
show("Finance: pending payouts and blank 'Approved By', by received month",
     fm.groupby("finance_month").agg(rows=("refund_id", "size"),
                                     pending=("f_status", lambda s: (s == "Pending Payout").sum()),
                                     approved_blank=("approved_by", lambda s: s.isna().sum()))
     .assign(pct_blank=lambda d: (d.approved_blank / d.rows * 100).round(0)))
pend = m[m.f_status == "Pending Payout"]
show("Pending payouts: age at snapshot and reason",
     pend.assign(age=(recon.SNAPSHOT - pend.f_received).dt.days)
     .groupby("f_remarks").agg(n=("refund_id", "size"), mean_age_days=("age", "mean"), max_age=("age", "max")).round(1))

age = m[m.true_state.str.startswith("Closed in Support")]
age = (recon.SNAPSHOT - age.s_last_updated).dt.days
show("Closed-but-missing: days since Support closed it (at 30 June)",
     age.describe().round(1).to_frame("days"))
show("Closed-but-missing older than X days", pd.DataFrame(
    {"older_than_days": [7, 14, 30], "refunds": [(age > x).sum() for x in (7, 14, 30)]}).set_index("older_than_days"))
show("Money: total value at stake by true state (Support amount)",
     m.groupby("true_state").s_amount.agg(["count", "sum"]).rename(columns={"sum": "INR"}))

# --------------------------------------------------------------------------
m.to_csv(OUT / "reconciled_refunds.csv", index=False)
recon.problem_cases(m).to_csv(OUT / "problem_cases.csv", index=False)
(OUT / "phase1_tables.md").write_text("# Phase 1 tables (generated by phase1_analysis.py)\n" + "".join(REPORT))
print("\nWrote output/ files.")
