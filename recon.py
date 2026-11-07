"""
BharatTrip refund reconciliation — plain, rule-based code (no AI).

Used by both the Phase 1 analysis script and the Streamlit app, so the
numbers in the write-up and the numbers in the app come from the same rules.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

import pandas as pd

SNAPSHOT = pd.Timestamp("2026-06-30")

CANONICAL_AGENTS = [
    "Anand Travels", "BlueJet Tours", "Coral Voyages", "DeccanFly", "Global Wings",
    "GoFly Holidays", "Himalaya Holidays", "Kaveri Tours", "Lotus Travel Co",
    "Metro Yatra", "Nomad Travel", "Orbit Travels", "Peak Journeys",
    "Pinnacle Getaways", "SafarNama Travel", "Skyline Travels", "Sunrise Trips",
    "TripHub", "Voyage Desk", "Wander Agency", "Yatri Junction", "ZipTrip",
]
_AGENT_KEY = {re.sub(r"\s+", "", a).lower(): a for a in CANONICAL_AGENTS}


# --------------------------------------------------------------------------
# Cleaning log
# --------------------------------------------------------------------------
@dataclass
class CleanLog:
    rows: list = field(default_factory=list)

    def add(self, sheet: str, rule: str, n: int):
        self.rows.append({"sheet": sheet, "rule": rule, "rows_affected": int(n)})

    def df(self) -> pd.DataFrame:
        return pd.DataFrame(self.rows, columns=["sheet", "rule", "rows_affected"])


# --------------------------------------------------------------------------
# Field normalisers
# --------------------------------------------------------------------------
def norm_id(x) -> str | None:
    """'RF 1750', 'rf-1750', 'RF1750 ', 'RF-1750 (revised)' -> 'RF-1750'."""
    if pd.isna(x):
        return None
    m = re.search(r"rf\s*-?\s*(\d{3,5})", str(x), flags=re.I)
    return f"RF-{m.group(1)}" if m else None


def parse_date(x) -> pd.Timestamp:
    """Handles real Excel dates, ISO text, dd-mm-yyyy and dd/mm/yy. Day-first always."""
    if pd.isna(x) or str(x).strip() == "":
        return pd.NaT
    if isinstance(x, (pd.Timestamp,)) or hasattr(x, "year"):
        return pd.Timestamp(x).normalize()
    s = str(x).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%d-%m-%Y", "%d/%m/%y", "%d/%m/%Y", "%d-%m-%y"):
        try:
            return pd.to_datetime(s, format=fmt)
        except ValueError:
            pass
    return pd.NaT


def norm_agent(x) -> str | None:
    if pd.isna(x):
        return None
    key = re.sub(r"\s+", "", str(x)).lower()
    return _AGENT_KEY.get(key, re.sub(r"\s+", " ", str(x)).strip().title())


def _count_changed(before: pd.Series, after: pd.Series) -> int:
    b = before.astype("string").fillna("<NA>")
    a = after.astype("string").fillna("<NA>")
    return int((b != a).sum())


# --------------------------------------------------------------------------
# Sheet cleaners
# --------------------------------------------------------------------------
SUPPORT_COLS = {
    "Ticket ID": "refund_id", "Agent": "agent", "Route": "route",
    "Refund Amount (INR)": "s_amount", "Request Date": "request_date",
    "Last Updated": "s_last_updated", "Status": "s_status",
    "Handled By": "handler", "Channel": "channel", "Notes": "s_notes",
}
FINANCE_COLS = {
    "Ref No": "refund_id", "Agent Name": "f_agent", "Sector": "f_route",
    "Amount Paid (INR)": "f_paid", "Deduction (INR)": "f_deduction",
    "Received On": "f_received", "Processed On": "f_processed",
    "Payout Status": "f_status", "Approved By": "approved_by", "Remarks": "f_remarks",
}
SUPPORT_STATUS = {"closed": "Closed", "working": "Working",
                  "not eligible": "Not Eligible", "escalated": "Escalated"}
FINANCE_STATUS = {"refund done": "Refund Done", "pending payout": "Pending Payout",
                  "declined": "Declined"}
STATUS_RANK = {"Closed": 3, "Not Eligible": 3, "Escalated": 2, "Working": 1}


def clean_support(raw: pd.DataFrame, log: CleanLog) -> pd.DataFrame:
    sh = "Support"
    df = raw.rename(columns=SUPPORT_COLS)[list(SUPPORT_COLS.values())].copy()
    log.add(sh, "Rows read", len(df))

    n = len(df)
    df = df.drop_duplicates()
    log.add(sh, "Removed exact duplicate rows (row pasted twice)", n - len(df))

    new = df["refund_id"].map(norm_id)
    log.add(sh, "Normalised ticket ID to RF-#### (spaces, case, missing hyphen, trailing space)",
            _count_changed(df["refund_id"], new))
    df["refund_id"] = new

    for c in ["request_date", "s_last_updated"]:
        txt = df[c].map(lambda v: isinstance(v, str))
        log.add(sh, f"Parsed text date in '{c}' (dd-mm-yyyy or dd/mm/yy, day-first)", txt.sum())
        df[c] = df[c].map(parse_date)

    new = df["s_status"].astype(str).str.strip().str.lower().map(SUPPORT_STATUS)
    log.add(sh, "Trimmed whitespace from Status", _count_changed(df["s_status"], df["s_status"].astype(str).str.strip()))
    df["s_status"] = new

    new = df["agent"].map(norm_agent)
    log.add(sh, "Standardised agent name (case, extra/leading/trailing spaces)", _count_changed(df["agent"], new))
    df["agent"] = new

    log.add(sh, "Blank 'Handled By' set to 'Unassigned'", df["handler"].isna().sum())
    df["handler"] = df["handler"].fillna("Unassigned").str.strip()
    log.add(sh, "Blank 'Channel' set to 'Unknown'", df["channel"].isna().sum())
    df["channel"] = df["channel"].fillna("Unknown").str.strip()
    log.add(sh, "Blank refund amount left blank (not guessed)", df["s_amount"].isna().sum())
    df["s_amount"] = pd.to_numeric(df["s_amount"], errors="coerce")

    # Exact dupes only became visible after ID/name normalisation for some rows
    n = len(df)
    df = df.drop_duplicates()
    log.add(sh, "Removed rows that became exact duplicates after normalisation", n - len(df))

    # Same ID twice with different values: keep the most advanced status, then the
    # latest update; flag it so the conflict stays visible.
    dup = df["refund_id"].duplicated(keep=False)
    df["s_conflict"] = dup
    df["_rank"] = df["s_status"].map(STATUS_RANK).fillna(0)
    alt = (df[dup].groupby("refund_id")["s_amount"]
           .apply(lambda s: ", ".join(f"{v:,.0f}" for v in sorted(s.dropna().unique()))))
    n = len(df)
    df = (df.sort_values(["refund_id", "_rank", "s_last_updated"])
            .drop_duplicates("refund_id", keep="last").drop(columns="_rank"))
    df["s_conflict_amounts"] = df["refund_id"].map(alt)
    log.add(sh, "Same ticket ID logged twice with different amount/status: kept one "
                "(most advanced status, then latest update), flagged as conflict", n - len(df))
    log.add(sh, "Rows after cleaning (one per refund ID)", len(df))
    return df.reset_index(drop=True)


def clean_finance(raw: pd.DataFrame, log: CleanLog) -> pd.DataFrame:
    sh = "Finance"
    df = raw.rename(columns=FINANCE_COLS)[list(FINANCE_COLS.values())].copy()
    log.add(sh, "Rows read", len(df))

    n = len(df)
    df = df.drop_duplicates()
    log.add(sh, "Removed exact duplicate rows", n - len(df))

    df["f_revised"] = df["refund_id"].astype(str).str.contains("revised", case=False)
    log.add(sh, "Stripped '(revised)' suffix from Ref No (kept a flag)", df["f_revised"].sum())
    new = df["refund_id"].map(norm_id)
    log.add(sh, "Normalised Ref No to RF-#### (all variants incl. revised)", _count_changed(df["refund_id"], new))
    df["refund_id"] = new

    for c in ["f_received", "f_processed"]:
        txt = df[c].map(lambda v: isinstance(v, str))
        log.add(sh, f"Parsed text date in '{c}' (day-first)", txt.sum())
        df[c] = df[c].map(parse_date)

    log.add(sh, "Trimmed whitespace from Payout Status",
            _count_changed(df["f_status"], df["f_status"].astype(str).str.strip()))
    df["f_status"] = df["f_status"].astype(str).str.strip().str.lower().map(FINANCE_STATUS)

    new = df["f_agent"].map(norm_agent)
    log.add(sh, "Standardised agent name (case, extra/leading/trailing spaces)", _count_changed(df["f_agent"], new))
    df["f_agent"] = new

    for c in ["f_paid", "f_deduction"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    log.add(sh, "Blank Deduction treated as 0 for maths (blank != confirmed zero; kept a flag)",
            df["f_deduction"].isna().sum())
    df["f_deduction_blank"] = df["f_deduction"].isna()
    df["f_deduction"] = df["f_deduction"].fillna(0)

    # Same Ref No twice, identical except Remarks ('re-entry', 'duplicate check pending')
    key = [c for c in df.columns if c not in ("f_remarks",)]
    dupmask = df.duplicated(subset=key, keep=False)
    dup_ids = df.loc[dupmask, "refund_id"].unique()
    df["f_double_entry"] = df["refund_id"].isin(dup_ids)
    marker = df["f_remarks"].str.contains("re-entry|duplicate", case=False, na=False)
    n = len(df)
    df = df[~(dupmask & marker)]
    df = df.drop_duplicates(subset=key)
    log.add(sh, "Same Ref No entered twice, identical apart from Remarks ('re-entry'/'duplicate "
                "check pending'): kept one, flagged as possible double payout", n - len(df))
    log.add(sh, "Rows after cleaning (one per refund ID)", len(df))
    assert df["refund_id"].is_unique, "Finance still has duplicate IDs"
    return df.reset_index(drop=True)


# --------------------------------------------------------------------------
# Reconciliation
# --------------------------------------------------------------------------
TRUE_STATES = [
    "Paid", "Pending in Finance", "Declined",
    "Closed in Support, missing in Finance", "In Finance only", "Open in Support",
]


def _true_state(r) -> str:
    in_s, in_f = pd.notna(r["s_status"]), pd.notna(r["f_status"])
    if in_f and not in_s:
        return "In Finance only"
    if in_f:
        if r["f_status"] == "Refund Done":
            return "Paid"
        if r["f_status"] == "Pending Payout":
            return "Pending in Finance"
        if r["f_status"] == "Declined":
            return "Declined"
    if in_s and not in_f:
        if r["s_status"] == "Closed":
            return "Closed in Support, missing in Finance"
        if r["s_status"] == "Not Eligible":
            return "Declined"
        return "Open in Support"
    return "In Finance only"


def reconcile(sup: pd.DataFrame, fin: pd.DataFrame) -> pd.DataFrame:
    m = sup.merge(fin, on="refund_id", how="outer", indicator="source")
    m["source"] = m["source"].map({"both": "Both", "left_only": "Support only", "right_only": "Finance only"})
    m["true_state"] = m.apply(_true_state, axis=1)
    m["declined_by"] = None
    m.loc[(m.true_state == "Declined") & m.f_status.eq("Declined"), "declined_by"] = "Finance"
    m.loc[(m.true_state == "Declined") & m.f_status.isna(), "declined_by"] = "Support"

    # Amount check: only meaningful for Paid rows that exist in both sheets
    paid_both = (m.source == "Both") & (m.true_state == "Paid") & m.s_amount.notna()
    m["amount_gap"] = (m.s_amount - m.f_paid).where(paid_both)
    m["amount_mismatch"] = paid_both & (m.amount_gap.abs() > 0)
    gap, ded = m.amount_gap, m.f_deduction
    m["mismatch_type"] = None
    m.loc[m.amount_mismatch & (gap == ded), "mismatch_type"] = "Explained by deduction"
    m.loc[m.amount_mismatch & (gap != ded) & (ded > 0), "mismatch_type"] = "Deduction present but doesn't match gap"
    m.loc[m.amount_mismatch & (gap != ded) & (ded == 0), "mismatch_type"] = "Unexplained (no deduction)"
    m["deduction_without_gap"] = paid_both & (gap == 0) & (ded > 0)

    # Timings
    m["handoff_days"] = (m.f_received - m.request_date).dt.days
    m["payout_days"] = (m.f_processed - m.f_received).dt.days
    m["request_month"] = m.request_date.dt.to_period("M").astype("string")
    m["finance_month"] = m.f_received.dt.to_period("M").astype("string")

    # Agent name agreement (a sanity check that the ID join is right)
    both = m.source == "Both"
    m["agent_disagree"] = both & (m.agent != m.f_agent)
    m["route_disagree"] = both & (m.route != m.f_route)
    return m


# --------------------------------------------------------------------------
# Daily problem-case list (used by the app)
# --------------------------------------------------------------------------
def problem_cases(m: pd.DataFrame, today: pd.Timestamp = SNAPSHOT) -> pd.DataFrame:
    rows = []
    for _, r in m.iterrows():
        st = r.true_state
        issue = action = owner = None
        since = r.request_date
        if st == "Closed in Support, missing in Finance":
            issue, owner = st, r.handler
            action = "Send to Finance with booking details; reopen ticket until Finance confirms payout"
            since = r.s_last_updated
        elif st == "Pending in Finance":
            issue, owner = st, "Finance"
            action = ("Get manager sign-off and release payout" if pd.isna(r.approved_by)
                      else "Release payout")
            since = r.f_received
        elif st == "In Finance only":
            issue, owner = st, "Support"
            action = "Create the missing Support ticket and confirm the request with the agent"
            since = r.f_received
        elif st == "Open in Support":
            issue, owner = st, r.handler
            action = "Raise to Finance or decide eligibility; update the agent"
        elif r.amount_mismatch and r.mismatch_type != "Explained by deduction":
            issue, owner = f"Amount mismatch: {r.mismatch_type}", "Finance"
            action = "Confirm the correct amount and explain the difference to the agent"
            since = r.f_processed
        elif r.amount_mismatch:
            issue, owner = "Paid less than Support promised (deduction)", r.handler
            action = "Tell the agent about the deduction and why"
            since = r.f_processed
        elif r.get("f_double_entry", False):
            issue, owner = "Logged twice in Finance: check for double payout", "Finance"
            action = "Check bank statement for a second payout"
            since = r.f_processed
        if issue:
            rows.append({
                "refund_id": r.refund_id, "agent": r.agent if pd.notna(r.agent) else r.f_agent,
                "issue": issue, "owner": owner if pd.notna(owner) else "Unassigned",
                "age_days": (today - since).days if pd.notna(since) else None,
                "next_action": action,
                "support_amount": r.s_amount, "finance_paid": r.f_paid,
                "deduction": r.f_deduction, "channel": r.channel,
            })
    out = pd.DataFrame(rows)
    if len(out):
        out = out.sort_values("age_days", ascending=False, na_position="last").reset_index(drop=True)
    return out


def load_and_reconcile(support_raw: pd.DataFrame, finance_raw: pd.DataFrame):
    log = CleanLog()
    sup = clean_support(support_raw, log)
    fin = clean_finance(finance_raw, log)
    return reconcile(sup, fin), log.df(), sup, fin
