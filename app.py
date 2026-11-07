"""
BharatTrip Refund Desk: prototype.
Run:  streamlit run app.py      (set GEMINI_API_KEY for the two AI tabs)

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
st.sidebar.write("AI features:", "✅ ready" if AI_READY else "⚠️ set `GEMINI_API_KEY`")
import ai as _ai  # noqa: E402
st.sidebar.caption(f"Build {_ai.APP_VERSION} · model: {_ai.MODEL_OVERRIDE or _ai._RESOLVED.get('model', 'auto (picked on first AI call)')}")
st.sidebar.write(f"Approved items this session: **{len(st.session_state.approved)}**")
if st.session_state.approved:
    st.sidebar.download_button("Download approval log (CSV)",
                               pd.DataFrame(st.session_state.approved).to_csv(index=False),
                               "approval_log.csv")



def log_download(key):
    """Download button for the approval log, shown right where the user approves."""
    if st.session_state.approved:
        n = len(st.session_state.approved)
        st.download_button(f"⬇️ Download approval log ({n} item{'s' if n != 1 else ''}, CSV)",
                           pd.DataFrame(st.session_state.approved).to_csv(index=False),
                           "approval_log.csv", key=key)


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
    st.dataframe(view, width="stretch", hide_index=True,
                 column_config={"age_days": st.column_config.NumberColumn("age (days)"),
                                "support_amount": st.column_config.NumberColumn(format="₹%d"),
                                "finance_paid": st.column_config.NumberColumn(format="₹%d"),
                                "deduction": st.column_config.NumberColumn(format="₹%d")})
    st.download_button("Download worklist (CSV)", view.to_csv(index=False), "problem_cases.csv")

    with st.expander("Summary by owner"):
        st.dataframe(pc.pivot_table(index="owner", columns="issue", values="refund_id",
                                    aggfunc="count", fill_value=0), width="stretch")
    with st.expander("True state of every refund"):
        st.dataframe(m.true_state.value_counts().rename("refunds"))
    with st.expander("Cleaning log (every rule and rows affected)"):
        st.dataframe(cleanlog, width="stretch", hide_index=True)

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
    st.caption("Paste an email or WhatsApp message. AI reads it; every amount and match below comes from "
               "our trackers, not the AI. Nothing is saved until you approve.")
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
                                                     "flags": ai.numbers_not_in_facts(text, facts),
                                                     "call": ai._RESOLVED.get("last_call", "")}
                except Exception as e:
                    st.error(f"AI call failed: {e}")
        d = st.session_state.get("update_draft")
        if d and d["rid"] == rid:
            if d.get("call"):
                st.caption(d["call"])
            if d["flags"]:
                st.error(f"⚠️ Numbers in the draft that are NOT in the facts: {', '.join(d['flags'])}. Edit before approving.")
            else:
                st.success("Number check passed: every amount in the draft appears in the facts.")
            edited = st.text_area("Draft (edit freely)", d["text"], height=220)
            if st.button("✅ Approve message"):
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
