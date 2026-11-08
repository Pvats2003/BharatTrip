"""
BharatTrip Refund Desk: prototype.
Run:  streamlit run app.py      (set GEMINI_API_KEY for the two AI tabs)

Design rule: matching and money are plain code (recon.py, matching.py).
The AI (ai.py) only reads messy text and writes messages, every AI output shows
its source, and nothing counts as sent until a human clicks Approve.
"""
import io
import json
import os
from datetime import date, datetime

import pandas as pd
import streamlit as st

import matching
import recon

st.set_page_config(page_title="BharatTrip Refund Desk", page_icon="🧾", layout="wide")
SAMPLE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "BharatTrip_Refund_Data.xlsx")
try:  # Streamlit Cloud: values in the Secrets box are copied into environment variables
    for _k in ("GEMINI_API_KEY", "GEMINI_MODEL"):
        if _k in st.secrets and not os.environ.get(_k):
            os.environ[_k] = str(st.secrets[_k])
except Exception:
    pass
AI_READY = bool(os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"))

for k, v in {"drafts": [], "approved": []}.items():
    st.session_state.setdefault(k, v)

st.markdown("""<style>
.block-container {padding-top: 2rem;}
div[data-testid="stMetric"] {background: rgba(128,128,128,.07); border-radius: 10px; padding: 10px 14px;}
.case-box {border: 1px solid rgba(128,128,128,.3); border-radius: 10px; padding: 12px 16px; margin-bottom: 8px;}
.muted {color: gray; font-size: 0.9em;}
</style>""", unsafe_allow_html=True)

# Plain-language names for each problem type: (priority, short label, explanation, short next step)
PROBLEMS = {
    "Closed in Support, missing in Finance":
        (1, "🔴 'Done', not in Finance", "Support closed it and told the agent, but Finance has no record.",
         "Send to Finance; reopen ticket"),
    "Closed in Support, not yet paid (Finance pending)":
        (1, "🔴 'Done', still unpaid", "Support told the agent it was done, but Finance has not paid yet.",
         "Finance: pay · Support: correct the agent"),
    "Logged twice in Finance: check for double payout":
        (2, "🟠 Possible double payout", "Finance logged this refund twice. Check the bank statement.",
         "Finance: check bank for 2nd payout"),
    "Pending in Finance":
        (2, "🟠 Awaiting payout", "Finance has it but has not paid yet.", "Finance: sign off and pay"),
    "In Finance only":
        (3, "🟡 No Support ticket", "Finance handled it, but Support has no ticket, so the agent may not be updated.",
         "Support: create ticket, update agent"),
    "Open in Support":
        (3, "🟡 Open in Support", "Support has not sent it to Finance yet.", "Support: decide and send to Finance"),
    "Paid less than Support promised (deduction)":
        (4, "🔵 Explain deduction", "Paid, but less than requested. Tell the agent why.",
         "Support: explain deduction to agent"),
}


def problem(issue):
    if issue in PROBLEMS:
        return PROBLEMS[issue]
    return (3, f"🟡 {issue[:28]}", issue, "See case")


def lakh(x):
    """Indian-style short amount for headline cards."""
    if pd.isna(x):
        return "—"
    return f"₹{x / 1e5:.1f} lakh" if abs(x) >= 1e5 else f"₹{x:,.0f}"


def money(x):
    return f"₹{x:,.0f}" if pd.notna(x) else "—"


# ------------------------------------------------------------------ data
@st.cache_data(show_spinner=False)
def reconcile_bytes(sup_bytes, sup_name, fin_bytes, fin_name):
    def read(b, name, sheet):
        if name.lower().endswith(".csv"):
            return pd.read_csv(io.BytesIO(b))
        xl = pd.ExcelFile(io.BytesIO(b))
        return pd.read_excel(xl, sheet if sheet in xl.sheet_names else xl.sheet_names[0])
    s = read(sup_bytes, sup_name, "Support_Tracker")
    f = read(fin_bytes, fin_name, "Finance_Tracker")
    m, log, _, _ = recon.load_and_reconcile(s, f)
    return m, log


# ------------------------------------------------------------------ sidebar
with st.sidebar:
    st.markdown("### 🧾 Refund Desk")
    st.markdown("**📂 Data**")
    with st.expander("Use your own trackers"):
        up_s = st.file_uploader("Support tracker (.xlsx / .csv)", type=["xlsx", "csv"])
        up_f = st.file_uploader("Finance tracker (.xlsx / .csv)", type=["xlsx", "csv"])
    if up_s and up_f:
        m, cleanlog = reconcile_bytes(up_s.getvalue(), up_s.name, up_f.getvalue(), up_f.name)
        st.success("Using your uploaded trackers")
    else:
        b = open(SAMPLE, "rb").read()
        m, cleanlog = reconcile_bytes(b, SAMPLE, b, SAMPLE)
        st.info("Using sample data (snapshot 30 Jun 2026)")

    with st.expander("⚙️ Settings"):
        today = pd.Timestamp(st.date_input("Today's date (used for 'days waiting')", value=date(2026, 6, 30)))
        sla = st.number_input("Flag 'told done but not paid' after (days)", 1, 60, 7)

    st.markdown("**✅ Approvals this session**")
    n_appr = len(st.session_state.approved)
    if n_appr:
        st.download_button(f"⬇️ Download approval log ({n_appr})",
                           pd.DataFrame(st.session_state.approved).to_csv(index=False),
                           "approval_log.csv", width="stretch")
    else:
        st.caption("Nothing approved yet. Approved tickets and messages appear here for download.")

    st.markdown("---")
    import ai as _ai  # noqa: E402
    st.caption(("AI ready" if AI_READY else "AI off: set GEMINI_API_KEY") +
               f" · Build {_ai.APP_VERSION} · model: "
               f"{_ai.MODEL_OVERRIDE or _ai._RESOLVED.get('model', 'auto')}")


def log_download(key):
    """Download button for the approval log, shown right where the user approves."""
    if st.session_state.approved:
        n = len(st.session_state.approved)
        st.download_button(f"⬇️ Download approval log ({n} item{'s' if n != 1 else ''}, CSV)",
                           pd.DataFrame(st.session_state.approved).to_csv(index=False),
                           "approval_log.csv", key=key)


def reply_label(rid):
    """How a refund is shown in the 'Reply to agent' picker."""
    r = m[m.refund_id == rid].iloc[0]
    agent = r.agent if pd.notna(r.agent) else r.f_agent
    return f"{rid} · {agent} · {r.true_state}"


# ------------------------------------------------------------------ header
st.title("BharatTrip Refund Desk")
st.markdown("Every refund that needs action today, in one place. Built from the **Support** and **Finance** "
            "trackers. AI only reads messages and drafts replies; all numbers come from the trackers, "
            "and nothing is saved or sent until you approve it.")
with st.expander("How to use this (30 seconds)"):
    st.markdown("""
1. **📋 Today's worklist**: start here. Urgent cases (🔴) are at the top. Click a case to see what Support and Finance each say, and what to do next.
2. **📨 New message → ticket**: paste an email or WhatsApp from an agent (Hinglish is fine). The app finds the refund in the trackers, or creates a new ticket, with the amount and its proof.
3. **✉️ Reply to agent**: pick a refund and get a ready-to-send status message, explaining any deduction. Edit it, approve it, copy it.

Everything you approve goes into the **approval log** (left sidebar) for the next team.
""")

tab1, tab2, tab3 = st.tabs(["📋 Today's worklist", "📨 New message → ticket", "✉️ Reply to agent"])

# ------------------------------------------------------------------ tab 1
with tab1:
    pc = recon.problem_cases(m, today)
    pc["priority"], pc["problem"], pc["why"], pc["short_step"] = zip(*pc.issue.map(problem))
    cnp = recon.closed_not_paid(m, today, sla)
    dbl = pc[pc.issue.str.startswith("Logged twice")]

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Told 'done', unpaid", len(cnp),
              help=f"Support marked these Closed more than {sla} days ago, but Finance has not paid. Target: zero.")
    c1.caption(f"over {sla} days · {lakh(cnp.s_amount.sum())} owed · target 0")
    urgent = pc[pc.priority == 1]
    c2.metric("🔴 Urgent cases", len(urgent), help="Agent was told 'done' but the money has not gone out.")
    c2.caption(f"of {len(pc)} cases needing any action")
    fin_wait = pc[pc.owner == "Finance"]
    c3.metric("Waiting on Finance", len(fin_wait), help="Payout, sign-off or a bank check needed from Finance.")
    c3.caption(f"{lakh(m[m.true_state == 'Pending in Finance'].s_amount.sum())} not yet paid")
    c4.metric("Possible double payouts", len(dbl), help="Logged twice in Finance. Check the bank statement.")
    c4.caption(f"{lakh(dbl.finance_paid.sum())} to check")

    st.markdown("#### What needs action")
    f1, f2, f3 = st.columns([1.2, 1.6, 1])
    handlers = sorted(h for h in pc.owner.unique() if h not in ("Finance", "Support", "Unassigned"))
    owner_opts = ["Everyone", "Finance", "Support (all)"] + handlers + (["Unassigned"] if "Unassigned" in set(pc.owner) else [])
    who = f1.selectbox("Show cases for", owner_opts)
    order = pc.drop_duplicates("problem").sort_values("priority").problem.tolist()
    counts = pc.problem.value_counts()
    prob_opts = [f"All problems ({len(pc)})"] + [f"{p} ({counts[p]})" for p in order]
    pick = f2.selectbox("Problem", prob_opts)
    q = f3.text_input("Search", placeholder="Refund ID or agent")

    view = pc
    if who == "Finance":
        view = view[view.owner == "Finance"]
    elif who == "Support (all)":
        view = view[view.owner != "Finance"]
    elif who != "Everyone":
        view = view[view.owner == who]
    if not pick.startswith("All problems"):
        view = view[view.problem == pick.rsplit(" (", 1)[0]]
    if q.strip():
        ql = q.strip().lower()
        view = view[view.refund_id.str.lower().str.contains(ql, regex=False)
                    | view.agent.fillna("").str.lower().str.contains(ql, regex=False)]
    view = view.sort_values(["priority", "age_days"], ascending=[True, False])

    table = pd.DataFrame({
        "Problem": view.problem, "Refund": view.refund_id, "Agent": view.agent,
        "Days waiting": view.age_days, "Owner": view.owner, "Next step": view.short_step,
        "Amount": view.support_amount.fillna(view.finance_paid).map(money),
    })
    st.caption(f"Showing {len(table)} of {len(pc)} cases · most urgent and oldest first · "
               "tick a row to open the case below")
    sel = st.dataframe(
        table, hide_index=True, width="stretch", height=300, on_select="rerun", selection_mode="single-row",
        key="worklist",
        column_config={
            "Problem": st.column_config.TextColumn(width="medium"),
            "Days waiting": st.column_config.NumberColumn(format="%d d", help="Days since the last action on it"),
            "Next step": st.column_config.TextColumn(width="medium"),
            "Amount": st.column_config.TextColumn(width="small"),
        })
    st.download_button("⬇️ Download this list (CSV)", table.to_csv(index=False), "worklist.csv")

    # ---------- case detail
    rows = sel.selection.rows if sel and sel.selection else []
    if rows:
        case = view.iloc[rows[0]]
        r = m[m.refund_id == case.refund_id].iloc[0]
        st.markdown(f"#### Case {case.refund_id} · {case.agent}")
        st.markdown(f"**{case.problem}**: {case.why}")
        a, b = st.columns(2)
        with a:
            st.markdown("**What Support's tracker says**")
            if pd.notna(r.s_status):
                st.markdown(f"- Status: **{r.s_status}**, note: “{r.s_notes}”\n"
                            f"- Requested: **{money(r.s_amount)}** on {r.request_date:%d %b %Y}\n"
                            f"- Handled by {r.handler} · last updated {r.s_last_updated:%d %b %Y} · via {r.channel}")
            else:
                st.warning("No Support ticket at all.")
        with b:
            st.markdown("**What Finance's tracker says**")
            if pd.notna(r.f_status):
                ded = f", deduction **{money(r.f_deduction)}**" if r.f_deduction and r.f_deduction > 0 else ""
                paid = (f"Paid **{money(r.f_paid)}** on {r.f_processed:%d %b %Y}" if r.f_status == "Refund Done"
                        else f"Status: **{r.f_status}**")
                st.markdown(f"- {paid}{ded}\n"
                            f"- Remark: “{r.f_remarks}” · received {r.f_received:%d %b %Y}\n"
                            f"- Approved by: {r.approved_by if pd.notna(r.approved_by) else 'nobody recorded'}")
            else:
                st.error("No Finance record at all: this refund never reached Finance.")
        st.info(f"**Next step** (owner: **{case.owner}**): {case.next_action}")
        if st.button("✉️ Draft a reply to the agent for this case", type="primary"):
            st.session_state["reply_pick"] = reply_label(case.refund_id)
            st.success("Done: open the **✉️ Reply to agent** tab above. This refund is already selected there.")
    else:
        st.caption("👆 Click any row to see what Support and Finance each say about it.")

    with st.expander("How these numbers were worked out"):
        st.markdown("Both trackers are cleaned (IDs, dates, names, duplicates) and joined on the refund ID. "
                    "Each refund gets one true status. Finance decides whether money moved. No AI is used here.")
        x, y = st.columns(2)
        x.markdown("**True status of every refund**")
        x.dataframe(m.true_state.value_counts().rename_axis("Status").rename("Refunds"), width="stretch")
        y.markdown("**Cleaning rules applied**")
        y.dataframe(cleanlog.rename(columns={"sheet": "Sheet", "rule": "Rule", "rows_affected": "Rows"}),
                    hide_index=True, width="stretch")

# ------------------------------------------------------------------ tab 2
SAMPLES = {
    "Email: Peak Journeys, 5 June": ("Email", "Peak Journeys", date(2026, 6, 5),
        "Hi, I cancelled booking for DEL-DXB last week and was told I'd get a refund. I haven't received "
        "anything and I don't have any reference number. Please help, my client is asking. "
        "(This is the case later referenced as RF-1099.)"),
    "WhatsApp: Nomad Travel, 8 June": ("WhatsApp", "Nomad Travel", date(2026, 6, 8),
        "Bhai refund ka kya hua? BLR-MAA wala. 2 hafte ho gaye, koi jawab nahi. (Later referenced as RF-1098.)"),
    "Email: internal Support note, 11 June": ("Email", "Support agent (internal)", date(2026, 6, 11),
        "Finance says they never received several of the refunds I closed last month. I marked them done "
        "on my side. Not sure where they went."),
    "(paste your own)": ("Email", "", date(2026, 6, 30), ""),
}

with tab2:
    st.markdown("#### Turn an email or WhatsApp into a ticket")
    st.caption("Paste an email or WhatsApp message. AI reads it; every amount and match below comes from "
               "our trackers, not the AI. Nothing is saved until you approve.")
    pick = st.selectbox("Try an example, or choose '(paste your own)'", list(SAMPLES))
    ch, snd, rcv, txt = SAMPLES[pick]
    a, b_, c_ = st.columns(3)
    channel = a.selectbox("Channel", ["Email", "WhatsApp", "Phone note"], index=["Email", "WhatsApp", "Phone note"].index(ch))
    sender = b_.text_input("From", snd)
    received = c_.date_input("Received on", rcv)
    message = st.text_area("Message, pasted exactly as received", txt, height=120)

    if not AI_READY:
        st.warning("AI is switched off (no GEMINI_API_KEY). The worklist still works.")
    if st.button("🔍 Read message and check our records", type="primary", disabled=not (AI_READY and message.strip())):
        import ai
        with st.spinner("Reading the message and checking both trackers…"):
            try:
                fields, source = ai.extract_intake(message, channel, sender, str(received))
                st.session_state.pop("flash_intake", None)
                st.session_state.intake = {"fields": fields.model_dump(), "source": source,
                                           "received": received, "channel": channel,
                                           "call": ai._RESOLVED.get("last_call", "")}
            except Exception as e:  # show the error rather than crash the app
                st.error(f"AI call failed: {e}")

    it = st.session_state.get("intake")
    if it:
        fx = it["fields"]
        ev = {e["field"]: e["quote"] for e in fx.get("evidence", [])}
        msg_date = pd.Timestamp(it["received"])
        known = set(m.refund_id.dropna())

        def proof(field):
            return f" <span style='color:gray'>— from the message: “{ev[field]}”</span>" if field in ev else ""

        # ---------- 1. What the message says
        st.markdown("### 1. What the message says")
        st.markdown(f"> {fx['summary_english']}")
        if fx.get("language", "").lower() != "english":
            st.caption(f"Message language: {fx['language']} (summary translated to English)")

        if fx["message_type"] != "refund_request_from_agent":
            closed_missing = m[m.true_state == "Closed in Support, missing in Finance"]
            st.warning("**This is not a refund request from a travel agent**, so no ticket is created.")
            if fx["message_type"] == "internal_note":
                st.markdown("### 2. What our records show")
                st.error(f"**{len(closed_missing)} refunds** are marked Closed by Support but **never reached Finance**, "
                         f"worth **₹{closed_missing.s_amount.sum():,.0f}**. This matches what the note describes.")
                by_h = (closed_missing.groupby("handler")
                        .agg(refunds=("refund_id", "size"), amount=("s_amount", "sum"))
                        .sort_values("refunds", ascending=False).reset_index()
                        .rename(columns={"handler": "Closed by", "refunds": "Refunds", "amount": "Amount"}))
                st.dataframe(by_h, hide_index=True, column_config={"Amount": st.column_config.NumberColumn(format="₹%d")})
                st.markdown("### 3. Next step")
                st.info("Open tab ① and filter Issue = *Closed in Support, missing in Finance*. Each row has an owner "
                        "and the next action (send to Finance, reopen the ticket).")
        else:
            est, how = matching.estimate_request_date(msg_date, fx.get("request_date"), fx.get("time_reference"))
            ref = recon.norm_id(fx.get("booking_reference"))
            rows = [
                ("Travel agent", fx.get("agent_name") or "Not stated", proof("agent_name")),
                ("Route", fx.get("route") or "Not stated", proof("route")),
                ("When cancelled", (f"about {est:%d %b %Y}" if est is not None else "Not stated"),
                 proof("time_reference") or proof("request_date")),
                ("Amount", f"₹{fx['amount_inr']:,}" if fx.get("amount_inr") else "Not stated in the message",
                 proof("amount_inr")),
                ("Reference quoted", (ref or "None") + ("" if not ref else
                 (" ✅ found in our records" if ref in known else " ❌ not in our records")), proof("booking_reference")),
            ]
            st.markdown("\n".join(f"- **{k}:** {v}{p}" for k, v, p in rows), unsafe_allow_html=True)

            # ---------- 2. What our records show
            st.markdown("### 2. What our records show")
            if "res" not in it:  # decide once, so the draft number doesn't change on every click
                it["res"] = matching.decide(fx, m, msg_date, st.session_state.drafts)
            res = it["res"]
            view = matching.candidate_view(res["candidates"], m, msg_date)
            if res["decision"] == "LINK":
                st.success(f"✅ **Found in our records: {res['refund_id']}.** {res['reason']}")
            elif ref:
                st.error(f"❌ **Not in Support or Finance records.** {ref} is not in either tracker, so this "
                         f"request was never logged.")
            else:
                st.warning("⚠️ **No exact match in our records.** No reference was given and no record matches "
                           "agent, route and date closely enough to be sure.")
            if len(view):
                st.markdown("**Refunds for the same agent that might be this one:**")
                friendly = pd.DataFrame({
                    "Refund": view.refund_id,
                    "Requested on": view.requested_on,
                    "Requested": view.requested_inr,
                    "Deduction": view.deduction_inr,
                    "Payout": view.payout_inr,
                    "Status": view.status,
                    "How close": view.match_score.map(lambda s: "High" if s >= 85 else "Medium" if s >= 60 else "Low"),
                    "Note": [("Logged AFTER the message: may be this request, logged late"
                              if r.logged_after_message else
                              f"{int(r.days_from_estimate)} days from the cancellation date"
                              if pd.notna(r.days_from_estimate) else "") for r in view.itertuples()],
                })
                money = {c: st.column_config.NumberColumn(format="₹%d") for c in ("Requested", "Deduction", "Payout")}
                st.dataframe(friendly, hide_index=True, width="stretch", column_config=money)

            # ---------- 3. Decide and send to the next stage
            st.markdown("### 3. Decide what goes to the next stage")
            if res["decision"] == "LINK":
                labels = {f"This is {res['refund_id']} (found in our records)": ("LINK", res["refund_id"])}
            else:
                labels = {f"Create a new ticket {res['refund_id']}: request was never logged": ("NEW_DRAFT", res["refund_id"])}
            for r in view.itertuples():
                if r.refund_id != res["refund_id"]:
                    hint = ", logged later by Support" if r.logged_after_message else ""
                    labels[f"It is {r.refund_id} ({r.status}, requested {r.requested_on}{hint})"] = ("LINK", r.refund_id)
            choice = st.radio("Your decision", list(labels), key=f"choice_{it['source'][:40]}")
            action, rid = labels[choice]

            st.markdown("**Amount to carry forward, with proof**")
            if action == "LINK":
                rec = m[m.refund_id == rid].iloc[0]
                pf = recon.payout_proof(rec)
                for label, amt, src in pf["lines"]:
                    st.markdown(f"- {label}: **₹{amt:,.0f}** <span style='color:gray'>({src})</span>", unsafe_allow_html=True)
                if pf["amount"] is not None:
                    st.success(f"**{pf['kind']}: ₹{pf['amount']:,.0f}**" + (f"  ·  check: {pf['check']}" if pf["check"] else ""))
                else:
                    st.warning(pf["kind"])
                agent = rec.agent if pd.notna(rec.agent) else rec.f_agent
                route = rec.route if pd.notna(rec.route) else rec.f_route
                amount, payout = rec.s_amount, pf["amount"]
                owner, next_step = (("Finance", f"Release the payout of ₹{payout:,.0f}. Support: tell the agent the "
                                     f"reference {rid} and explain any deduction.")
                                    if rec.true_state in ("Pending in Finance", "Closed in Support, missing in Finance",
                                                          "Open in Support") else
                                    ("Support", f"Tell the agent the status of {rid} using tab ③."))
            else:
                agent, route = fx.get("agent_name"), fx.get("route")
                if fx.get("amount_inr"):
                    st.success(f"**Amount: ₹{fx['amount_inr']:,}**, stated in the message: “{ev.get('amount_inr', '')}”")
                    amount = fx["amount_inr"]
                else:
                    st.warning("**Amount not stated in the message, and there is no tracker record to take it from.** "
                               "Ask the agent to confirm the booking amount before sending this to Finance.")
                    amount = st.number_input("Amount confirmed with the agent (₹), leave 0 if not yet confirmed",
                                             0, step=100, key=f"amt_{it['source'][:40]}") or None
                payout = None
                owner, next_step = ("Support", f"Reply to {agent or 'the agent'} with ticket {rid}"
                                    + ("" if amount else ", confirm the amount") + ", then send it to Finance.")

            st.markdown(f"**Next stage:** owner **{owner}**. {next_step}")
            if st.button("✅ Approve and send to next stage", type="primary", key=f"approve_{it['source'][:40]}"):
                if action == "NEW_DRAFT" and rid not in st.session_state.drafts:
                    st.session_state.drafts.append(rid)
                st.session_state.approved.append({
                    "approved_at": datetime.now().isoformat(timespec="seconds"), "type": "intake",
                    "action": action, "refund_id": rid, "agent_reference": ref,
                    "agent": agent, "route": route, "amount_inr": amount, "payout_inr": payout,
                    "owner": owner, "next_step": next_step,
                    "channel": it["channel"], "received_on": str(it["received"]), "source_text": it["source"]})
                st.session_state.flash_intake = (f"Saved: {'linked to' if action == 'LINK' else 'new ticket'} "
                                                 f"**{rid}** · owner {owner} · {next_step}")
                st.rerun()
            if st.session_state.get("flash_intake"):
                st.success(st.session_state.flash_intake)
                log_download("dl_intake")

        with st.expander("Technical details (audit trail)"):
            if it.get("call"):
                st.caption(it["call"])
            st.markdown("**Exactly what the AI was given**")
            st.code(it["source"], language=None)
            st.markdown("**AI output (structured fields and quotes)**")
            st.json(fx)
            if "res" in it:
                st.markdown("**Matching scores (plain code, matching.py)**")
                st.caption(it["res"]["date_note"]["how"])
                st.dataframe(it["res"]["candidates"], hide_index=True)

# ------------------------------------------------------------------ tab 3
with tab3:
    st.markdown("#### Send a status update to a travel agent")
    st.caption("Pick a refund. The facts come from both trackers; AI only turns them into a short, polite message. "
               "You edit and approve it before anything is sent.")
    pc_ids = recon.problem_cases(m, today).refund_id.tolist()
    order = list(dict.fromkeys(pc_ids + m.refund_id.dropna().sort_values().tolist()))
    options = [reply_label(x) for x in order]
    if st.session_state.get("reply_pick") not in options:
        st.session_state.pop("reply_pick", None)
    label = st.selectbox("Which refund? (cases needing action are listed first; type to search)", options,
                         key="reply_pick")
    rid = label.split(" · ")[0]
    row = m[m.refund_id == rid].iloc[0]
    facts = recon.refund_facts(row)
    left, right = st.columns([1, 1.2])
    with left:
        st.markdown("**Step 1 · Check the facts**")
        st.markdown("\n".join(f"- **{k}:** {str(v).replace('Rs ', '₹')}" for k, v in facts.items()))
        st.caption("Worked out by code from both trackers. The message may only use these facts.")
    with right:
        st.markdown("**Step 2 · Draft the message**")
        if not AI_READY:
            st.warning("AI is switched off (no GEMINI_API_KEY).")
        cache = st.session_state.setdefault("draft_cache", {})
        ckey = (rid, json.dumps(facts, sort_keys=True, default=str))   # same refund + same facts = same draft
        d = cache.get(ckey)
        if st.button("🔄 Redraft with AI" if d else "✍️ Draft message with AI", type="secondary" if d else "primary",
                     disabled=not AI_READY):
            import ai
            try:
                st.caption("Writing…")
                text = st.write_stream(ai.draft_agent_update_stream(facts))   # words appear as they are written
                if isinstance(text, list):
                    text = "".join(map(str, text))
                cache[ckey] = {"text": text.strip(), "source": ai.update_source(facts),
                               "flags": ai.numbers_not_in_facts(text, facts),
                               "call": ai._RESOLVED.get("last_call", "")}
                st.rerun()
            except Exception as e:
                st.error(f"AI call failed: {e}")
        if d:
            st.caption(("Saved draft (instant). Click *Redraft with AI* for a new version.  ·  " + d.get("call", "")).strip(" ·"))
            if d["flags"]:
                st.error(f"⚠️ Numbers in the draft that are NOT in the facts: {', '.join(d['flags'])}. Edit before approving.")
            else:
                st.success("Number check passed: every amount in the draft appears in the facts.")
            st.markdown("**Step 3 · Edit if needed, then approve**")
            edited = st.text_area("Message to the agent (edit freely)", d["text"], height=220, key=f"edit_{rid}_{hash(d['text'])}")
            if st.button("✅ Approve message", type="primary"):
                st.session_state.approved.append({
                    "approved_at": datetime.now().isoformat(timespec="seconds"), "type": "agent_update",
                    "refund_id": rid, "true_state": row.true_state, "message": edited, "source_text": d["source"]})
                st.session_state.flash_update = {"rid": rid, "text": edited}
                st.rerun()
            fu = st.session_state.get("flash_update")
            if fu and fu["rid"] == rid:
                st.success("Approved. Copy the text below into email / WhatsApp. The prototype does not send anything.")
                st.code(fu["text"], language=None)
                log_download("dl_update")
