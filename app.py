"""
BharatTrip Refund Desk: prototype.
Run:  streamlit run app.py      (set ANTHROPIC_API_KEY for the two AI tabs)

Design rule: matching and money are plain code (recon.py, matching.py).
The AI (ai.py) only reads messy text and writes messages, every AI output shows
its source, and nothing counts as sent until a human clicks Approve.
"""
import io
import os
from datetime import date, datetime

import pandas as pd
import streamlit as st

import matching
import recon

st.set_page_config(page_title="BharatTrip Refund Desk", layout="wide")
SAMPLE = "data/BharatTrip_Refund_Data.xlsx"
AI_READY = bool(os.environ.get("ANTHROPIC_API_KEY"))

for k, v in {"drafts": [], "approved": []}.items():
    st.session_state.setdefault(k, v)


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


st.sidebar.title("BharatTrip Refund Desk")
st.sidebar.caption("Upload both trackers, or use the sample extract.")
up_s = st.sidebar.file_uploader("Support tracker (.xlsx / .csv)", type=["xlsx", "csv"])
up_f = st.sidebar.file_uploader("Finance tracker (.xlsx / .csv)", type=["xlsx", "csv"])
if up_s and up_f:
    m, cleanlog = reconcile_bytes(up_s.getvalue(), up_s.name, up_f.getvalue(), up_f.name)
    st.sidebar.success("Using uploaded trackers")
else:
    b = open(SAMPLE, "rb").read()
    m, cleanlog = reconcile_bytes(b, SAMPLE, b, SAMPLE)
    st.sidebar.info("Using sample extract (snapshot 30 Jun 2026)")
today = pd.Timestamp(st.sidebar.date_input("Today's date (for ages)", value=date(2026, 6, 30)))
sla = st.sidebar.number_input("Closed-but-unpaid alert after (days)", 1, 60, 7)
st.sidebar.markdown("---")
st.sidebar.write("AI features:", "✅ ready" if AI_READY else "⚠️ set `ANTHROPIC_API_KEY`")
st.sidebar.write(f"Approved items this session: **{len(st.session_state.approved)}**")
if st.session_state.approved:
    st.sidebar.download_button("Download approval log (CSV)",
                               pd.DataFrame(st.session_state.approved).to_csv(index=False),
                               "approval_log.csv")

tab1, tab2, tab3 = st.tabs(["① Daily problem cases", "② AI intake (email / WhatsApp)", "③ AI agent update"])

# ------------------------------------------------------------------ tab 1
with tab1:
    pc = recon.problem_cases(m, today)
    cnp = recon.closed_not_paid(m, today, sla)
    c1, c2, c3, c4 = st.columns(4)
    c1.metric(f"Closed, unpaid > {sla} days", len(cnp), help="Target: near zero")
    c2.metric("Open problem cases", len(pc))
    c3.metric("Pending in Finance", int((m.true_state == "Pending in Finance").sum()))
    c4.metric("Refunds reconciled", len(m))

    st.subheader("Today's worklist")
    st.caption("Every row comes from rules in recon.py. No AI is involved in this list.")
    f1, f2 = st.columns(2)
    issues = f1.multiselect("Issue", sorted(pc.issue.unique()), default=sorted(pc.issue.unique()))
    owners = f2.multiselect("Owner", sorted(pc.owner.unique()), default=sorted(pc.owner.unique()))
    view = pc[pc.issue.isin(issues) & pc.owner.isin(owners)]
    st.dataframe(view, use_container_width=True, hide_index=True,
                 column_config={"age_days": st.column_config.NumberColumn("age (days)"),
                                "support_amount": st.column_config.NumberColumn(format="₹%d"),
                                "finance_paid": st.column_config.NumberColumn(format="₹%d"),
                                "deduction": st.column_config.NumberColumn(format="₹%d")})
    st.download_button("Download worklist (CSV)", view.to_csv(index=False), "problem_cases.csv")

    with st.expander("Summary by owner"):
        st.dataframe(pc.pivot_table(index="owner", columns="issue", values="refund_id",
                                    aggfunc="count", fill_value=0), use_container_width=True)
    with st.expander("True state of every refund"):
        st.dataframe(m.true_state.value_counts().rename("refunds"))
    with st.expander("Cleaning log (every rule and rows affected)"):
        st.dataframe(cleanlog, use_container_width=True, hide_index=True)

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
    st.subheader("Turn an informal message into a ticket")
    st.caption("The AI only reads the message into fields and quotes its evidence. "
               "Matching and the link-or-create decision are plain code (matching.py).")
    pick = st.selectbox("Load a message from the brief", list(SAMPLES))
    ch, snd, rcv, txt = SAMPLES[pick]
    a, b_, c_ = st.columns(3)
    channel = a.selectbox("Channel", ["Email", "WhatsApp", "Phone note"], index=["Email", "WhatsApp", "Phone note"].index(ch))
    sender = b_.text_input("From", snd)
    received = c_.date_input("Received on", rcv)
    message = st.text_area("Message (paste as received)", txt, height=120)

    if st.button("Read message with AI", disabled=not (AI_READY and message.strip())):
        import ai
        with st.spinner("Reading message…"):
            try:
                fields, source = ai.extract_intake(message, channel, sender, str(received))
                st.session_state.intake = {"fields": fields.model_dump(), "source": source,
                                           "received": received, "channel": channel}
            except Exception as e:  # show the error rather than crash the app
                st.error(f"AI call failed: {e}")

    it = st.session_state.get("intake")
    if it:
        fx = it["fields"]
        left, right = st.columns(2)
        with left:
            st.markdown("**Source: exactly what the AI was given**")
            st.code(it["source"], language=None)
            st.markdown("**Evidence the AI quoted for each field**")
            st.dataframe(pd.DataFrame(fx["evidence"]), hide_index=True, use_container_width=True)
        with right:
            st.markdown("**Extracted fields (JSON from the AI; edit before approving)**")
            st.json({k: v for k, v in fx.items() if k != "evidence"})

        if fx["message_type"] != "refund_request_from_agent":
            closed_missing = m[m.true_state == "Closed in Support, missing in Finance"]
            st.warning(f"This is **not a refund request from an agent** ({fx['message_type']}). "
                       f"No ticket is created. Summary: {fx['summary_english']}")
            if fx["message_type"] == "internal_note":
                st.info(f"Related check (plain code): **{len(closed_missing)}** refunds are Closed in Support "
                        f"but missing in Finance. See tab ① and filter Issue = 'Closed in Support, missing in Finance'.")
                by_h = closed_missing.groupby("handler").size().sort_values(ascending=False).rename("closed, missing in Finance")
                st.dataframe(by_h)
        else:
            st.markdown("**Matching (plain code)**")
            res = matching.decide(fx, m, pd.Timestamp(it["received"]), st.session_state.drafts)
            st.caption(f"Date estimate: {res['date_note']['how']}")
            if len(res["candidates"]):
                st.dataframe(res["candidates"], hide_index=True, use_container_width=True)
            if res["decision"] == "LINK":
                st.success(f"🔗 **Link to {res['refund_id']}**: {res['reason']}")
            else:
                st.warning(f"🆕 **Create {res['refund_id']}**: {res['reason']}")

            with st.form("approve_intake"):
                st.markdown("**Human check before anything is saved**")
                options = [f"{res['decision']}: {res['refund_id']}"] + \
                          [f"LINK: {r}" for r in res["candidates"].refund_id if r != res["refund_id"]]
                choice = st.radio("Action", options)
                e1, e2, e3 = st.columns(3)
                agent = e1.text_input("Agent", fx.get("agent_name") or "")
                route = e2.text_input("Route", fx.get("route") or "")
                amount = e3.number_input("Amount (INR, 0 = unknown)", 0, value=int(fx.get("amount_inr") or 0))
                if st.form_submit_button("✅ Approve"):
                    action, rid = choice.split(": ")
                    if action == "NEW_DRAFT":
                        st.session_state.drafts.append(rid)
                    st.session_state.approved.append({
                        "approved_at": datetime.now().isoformat(timespec="seconds"), "type": "intake",
                        "action": action, "refund_id": rid, "agent_reference": res.get("agent_reference"),
                        "agent": agent, "route": route, "amount_inr": amount or None,
                        "channel": it["channel"], "received_on": str(it["received"]),
                        "source_text": it["source"]})
                    st.success(f"Saved: {action} {rid}. Owner: Support, next action: acknowledge to agent with this ticket ID.")

# ------------------------------------------------------------------ tab 3
with tab3:
    st.subheader("Draft a status message to the travel agent")
    st.caption("Facts are computed by code from both trackers. The AI only turns them into a short message. "
               "A number check flags any amount in the draft that is not in the facts.")
    pc_ids = recon.problem_cases(m, today).refund_id.tolist()
    order = pc_ids + [r for r in m.refund_id.dropna().sort_values() if r not in set(pc_ids)]
    rid = st.selectbox("Refund (problem cases listed first)", order)
    row = m[m.refund_id == rid].iloc[0]
    facts = recon.refund_facts(row)
    left, right = st.columns(2)
    with left:
        st.markdown(f"**True state:** {row.true_state}")
        st.markdown("**Source: facts the AI will be given**")
        st.table(pd.Series(facts, name="value"))
    with right:
        if st.button("Draft message with AI", disabled=not AI_READY):
            import ai
            with st.spinner("Drafting…"):
                try:
                    text, source = ai.draft_agent_update(facts)
                    st.session_state.update_draft = {"rid": rid, "text": text, "source": source,
                                                     "flags": ai.numbers_not_in_facts(text, facts)}
                except Exception as e:
                    st.error(f"AI call failed: {e}")
        d = st.session_state.get("update_draft")
        if d and d["rid"] == rid:
            if d["flags"]:
                st.error(f"⚠️ Numbers in the draft that are NOT in the facts: {', '.join(d['flags'])}. Edit before approving.")
            else:
                st.success("Number check passed: every amount in the draft appears in the facts.")
            edited = st.text_area("Draft (edit freely)", d["text"], height=220)
            if st.button("✅ Approve message"):
                st.session_state.approved.append({
                    "approved_at": datetime.now().isoformat(timespec="seconds"), "type": "agent_update",
                    "refund_id": rid, "true_state": row.true_state, "message": edited, "source_text": d["source"]})
                st.success("Approved. Copy the text below into email / WhatsApp. The prototype does not send anything.")
                st.code(edited, language=None)
