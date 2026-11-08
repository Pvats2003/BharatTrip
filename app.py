"""
BharatTrip Refund Desk.
Run:  streamlit run app.py      (set GEMINI_API_KEY for the two AI screens)

Design rule: matching and money are plain code (recon.py, matching.py).
The AI (ai.py) only reads messy text and writes messages. Every AI output shows its source,
and nothing is saved or sent until a named person approves it (approvals.py keeps the log).
"""
import html
import io
import json
import logging
import os
from datetime import date

import pandas as pd
import streamlit as st

import approvals
import matching
import recon

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("refund_desk")

st.set_page_config(page_title="BharatTrip Refund Desk", layout="wide", initial_sidebar_state="expanded")
SAMPLE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "BharatTrip_Refund_Data.xlsx")
try:  # Streamlit Cloud: values in the Secrets box are copied into environment variables
    for _k in ("GEMINI_API_KEY", "GEMINI_MODEL", "APPROVAL_LOG_PATH"):
        if _k in st.secrets and not os.environ.get(_k):
            os.environ[_k] = str(st.secrets[_k])
except Exception:
    pass
AI_READY = bool(os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"))
st.session_state.setdefault("drafts", [])

# ------------------------------------------------------------------ design system
TONES = {  # text colour, background
    "urgent": ("#B42318", "#FEF3F2"), "high": ("#B54708", "#FFFAEB"), "medium": ("#8A6100", "#FEF7C3"),
    "low": ("#175CD3", "#EFF8FF"), "ok": ("#067647", "#ECFDF3"), "neutral": ("#344054", "#F2F4F7"),
}
st.markdown("""<style>
:root { --bt-navy:#1F3A5F; --bt-border:#E4E7EC; --bt-muted:#667085; }
.block-container { padding-top: 1.2rem; padding-bottom: 3rem; max-width: 1400px; }
header[data-testid="stHeader"] { background: transparent; }
.bt-header { display:flex; justify-content:space-between; align-items:center; border-bottom:1px solid var(--bt-border);
             padding: 0 0 14px 0; margin-bottom: 6px; gap: 16px; flex-wrap: wrap; }
.bt-title { font-size: 1.55rem; font-weight: 700; color: var(--bt-navy); letter-spacing: -0.01em; margin: 0; }
.bt-sub { color: var(--bt-muted); font-size: 0.92rem; margin-top: 2px; max-width: 900px; }
.bt-pill { display:inline-block; padding: 3px 10px; border-radius: 999px; font-size: 0.78rem; font-weight: 600;
           border: 1px solid var(--bt-border); color: #344054; background: #F9FAFB; margin: 2px 0 2px 6px; }
.bt-kpi { border:1px solid var(--bt-border); border-left: 4px solid var(--tone); border-radius: 10px;
          padding: 12px 16px; background: #FFFFFF; height: 100%; }
.bt-kpi .l { color: var(--bt-muted); font-size: 0.78rem; font-weight: 600; text-transform: uppercase; letter-spacing: .03em; }
.bt-kpi .v { font-size: 1.9rem; font-weight: 700; color: #101828; line-height: 1.2; margin-top: 4px; }
.bt-kpi .s { color: var(--bt-muted); font-size: 0.85rem; margin-top: 2px; }
.bt-badge { display:inline-block; padding: 2px 9px; border-radius: 6px; font-size: 0.78rem; font-weight: 700;
            vertical-align: middle; }
.bt-card { border:1px solid var(--bt-border); border-radius: 10px; padding: 12px 18px; background:#FFFFFF; margin: 6px 0 10px; }
.bt-card p { margin: 0 0 6px 0; }
.bt-card h4 { margin: 0 0 8px 0; font-size: 0.95rem; color: var(--bt-navy); }
.bt-section { font-size: 1.1rem; font-weight: 700; color: #101828; margin: 18px 0 2px; }
.bt-hint { color: var(--bt-muted); font-size: 0.88rem; margin-bottom: 8px; }
.bt-quote { color: var(--bt-muted); }
.bt-step { display:inline-block; width:22px; height:22px; border-radius:50%; background: var(--bt-navy); color:#fff;
           text-align:center; font-size:0.8rem; font-weight:700; line-height:22px; margin-right:8px; }
div[data-testid="stTabs"] button p { font-size: 0.98rem; font-weight: 600; }
</style>""", unsafe_allow_html=True)


def esc(x) -> str:
    return html.escape("" if x is None or (isinstance(x, float) and pd.isna(x)) else str(x))


def badge(text, tone):
    fg, bg = TONES[tone]
    return f"<span class='bt-badge' style='color:{fg};background:{bg}'>{esc(text)}</span>"


def kpi(col, label, value, sub, tone):
    col.markdown(f"<div class='bt-kpi' style='--tone:{TONES[tone][0]}'><div class='l'>{esc(label)}</div>"
                 f"<div class='v'>{esc(value)}</div><div class='s'>{esc(sub)}</div></div>", unsafe_allow_html=True)


def section(title, hint=None, step=None):
    num = f"<span class='bt-step'>{step}</span>" if step else ""
    st.markdown(f"<div class='bt-section'>{num}{esc(title)}</div>", unsafe_allow_html=True)
    if hint:
        st.markdown(f"<div class='bt-hint'>{esc(hint)}</div>", unsafe_allow_html=True)


def money(x):
    return f"₹{x:,.0f}" if x is not None and pd.notna(x) else "—"


def lakh(x):
    if x is None or pd.isna(x):
        return "—"
    return f"₹{x / 1e5:.1f} lakh" if abs(x) >= 1e5 else f"₹{x:,.0f}"


def fdate(x):
    return x.strftime("%d %b %Y") if x is not None and pd.notna(x) else "not recorded"


# Problem types in plain language: (priority, label, explanation, short next step)
PRIORITY = {1: ("Urgent", "urgent"), 2: ("High", "high"), 3: ("Medium", "medium"), 4: ("Low", "low")}
PROBLEMS = {
    "Closed in Support, missing in Finance":
        (1, "Told done, not in Finance", "Support closed it and told the agent, but Finance has no record.",
         "Send to Finance; reopen ticket"),
    "Closed in Support, not yet paid (Finance pending)":
        (1, "Told done, still unpaid", "Support told the agent it was done, but Finance has not paid yet.",
         "Finance: pay. Support: correct agent"),
    "Logged twice in Finance: check for double payout":
        (2, "Possible double payout", "Finance logged this refund twice. Check the bank statement.",
         "Finance: check bank for 2nd payout"),
    "Pending in Finance":
        (2, "Awaiting payout", "Finance has it but has not paid yet.", "Finance: sign off and pay"),
    "In Finance only":
        (3, "No Support ticket", "Finance handled it, but Support has no ticket, so the agent may not be updated.",
         "Support: create ticket, update agent"),
    "Open in Support":
        (3, "Open in Support", "Support has not sent it to Finance yet.", "Support: decide, send to Finance"),
    "Paid less than Support promised (deduction)":
        (4, "Deduction to explain", "Paid, but less than requested. Tell the agent why.",
         "Support: explain deduction"),
}


def problem(issue):
    return PROBLEMS.get(issue, (3, str(issue)[:40], str(issue), "See case"))


# ------------------------------------------------------------------ data loading
@st.cache_data(show_spinner=False)
def reconcile_frames(sup_bytes, sup_name, sup_sheet, fin_bytes, fin_name, fin_sheet):
    def read(b, name, sheet):
        if name.lower().endswith(".csv"):
            return pd.read_csv(io.BytesIO(b))
        xl = pd.ExcelFile(io.BytesIO(b))
        if sheet not in xl.sheet_names:
            if len(xl.sheet_names) == 1:
                sheet = xl.sheet_names[0]
            else:
                raise recon.TrackerFormatError(f"Could not find a sheet named '{sheet}' in {name}. "
                                               f"Sheets found: {', '.join(xl.sheet_names)}.")
        return pd.read_excel(xl, sheet)
    s = read(sup_bytes, sup_name, sup_sheet)
    f = read(fin_bytes, fin_name, fin_sheet)
    m, cleanlog, _, _ = recon.load_and_reconcile(s, f)
    return m, cleanlog


def load_data(up_wb, up_s, up_f):
    """Returns (merged, cleaning log, source label, error message or None). Falls back to the sample on error."""
    err = None
    try:
        if up_wb is not None:
            b = up_wb.getvalue()
            m, cl = reconcile_frames(b, up_wb.name, "Support_Tracker", b, up_wb.name, "Finance_Tracker")
            return m, cl, f"Uploaded: {up_wb.name}", None
        if up_s is not None and up_f is not None:
            m, cl = reconcile_frames(up_s.getvalue(), up_s.name, "Support_Tracker",
                                     up_f.getvalue(), up_f.name, "Finance_Tracker")
            return m, cl, "Uploaded: two files", None
    except recon.TrackerFormatError as e:
        err = str(e)
    except Exception as e:  # unreadable file
        log.exception("upload failed")
        err = f"The file could not be read ({type(e).__name__}). Please upload the original .xlsx or .csv."
    b = open(SAMPLE, "rb").read()
    m, cl = reconcile_frames(b, SAMPLE, "Support_Tracker", b, SAMPLE, "Finance_Tracker")
    return m, cl, "Sample data (snapshot 30 Jun 2026)", err


# ------------------------------------------------------------------ sidebar
with st.sidebar:
    st.markdown("<div class='bt-title' style='font-size:1.15rem'>Refund Desk</div>"
                "<div class='bt-sub'>BharatTrip operations</div>", unsafe_allow_html=True)
    st.write("")
    approver = st.text_input("Your name", key="approver", placeholder="Required to approve",
                             help="Recorded against every approval in the log.").strip()

    st.markdown("**Data**")
    with st.expander("Upload trackers"):
        up_wb = st.file_uploader("One workbook with both tabs (Support_Tracker, Finance_Tracker)", type=["xlsx"])
        st.caption("Or upload two separate files:")
        up_s = st.file_uploader("Support tracker", type=["xlsx", "csv"])
        up_f = st.file_uploader("Finance tracker", type=["xlsx", "csv"])
    m, cleanlog, data_label, data_err = load_data(up_wb, up_s, up_f)
    if data_err:
        st.error(f"Upload not used. {data_err} Showing the sample data instead.")
    st.caption(data_label)

    with st.expander("Settings"):
        today = pd.Timestamp(st.date_input("Today's date (used for days waiting)", value=date(2026, 6, 30)))
        sla = st.number_input("Flag 'told done but unpaid' after (days)", 1, 60, 7)

    st.divider()
    import ai as _ai  # noqa: E402
    st.caption(("AI: connected" if AI_READY else "AI: not configured (set GEMINI_API_KEY)") +
               f"  ·  Build {_ai.APP_VERSION}")

# ------------------------------------------------------------------ header
st.markdown(
    "<div class='bt-header'><div><div class='bt-title'>BharatTrip Refund Desk</div>"
    "<div class='bt-sub'>One view of every refund that needs action, built from the Support and Finance trackers. "
    "AI reads messages and drafts replies; all numbers come from the trackers; nothing is saved without approval."
    f"</div></div><div><span class='bt-pill'>{esc(data_label)}</span>"
    f"<span class='bt-pill'>As of {today:%d %b %Y}</span></div></div>", unsafe_allow_html=True)
with st.expander("How to use this desk"):
    st.markdown("""
1. **Worklist**: start here each morning. Urgent cases are at the top. Select a case to see what Support and Finance each recorded, and the next step.
2. **New message**: paste an email or WhatsApp from an agent (Hinglish is fine). The desk finds the refund in the trackers, or prepares a new ticket, with the amount and its source.
3. **Agent reply**: pick a refund and get a ready-to-send status message. Edit, approve, copy.
4. **Approval log**: every approval, with who approved it and the source it was based on. Download it for the next team.

Enter **your name** in the left panel before approving anything.
""")


def require_name() -> bool:
    if not approver:
        st.caption("Enter your name in the left panel to approve.")
        return False
    return True


def show_ai_error(e):
    import ai
    msg, detail = ai.friendly_error(e)
    st.error(msg)
    with st.expander("Technical detail"):
        st.code(detail, language=None)


def reply_label(rid):
    r = m[m.refund_id == rid].iloc[0]
    agent = r.agent if pd.notna(r.agent) else r.f_agent
    return f"{rid}  ·  {agent if pd.notna(agent) else 'Unknown agent'}  ·  {r.true_state}"


def safe(render):
    """Show a clear message instead of a crash if a screen fails unexpectedly."""
    try:
        render()
    except Exception:
        log.exception("screen failed: %s", render.__name__)
        st.error("Something went wrong on this screen. Your approvals are safe. Refresh the page; if it happens "
                 "again, report it with the time shown in the server log.")


tab_work, tab_msg, tab_reply, tab_log = st.tabs(["Worklist", "New message", "Agent reply", "Approval log"])


# ================================================================== Worklist
def render_worklist():
    pc = recon.problem_cases(m, today)
    if not len(pc):
        st.success("No refunds need action. Both trackers agree.")
        return
    pc["priority"], pc["problem"], pc["why"], pc["short_step"] = zip(*pc.issue.map(problem))
    pc["priority_label"] = pc.priority.map(lambda p: PRIORITY[p][0])
    cnp = recon.closed_not_paid(m, today, sla)
    dbl = pc[pc.issue.str.startswith("Logged twice")]
    urgent = pc[pc.priority == 1]
    fin = pc[pc.owner == "Finance"]

    c1, c2, c3, c4 = st.columns(4)
    kpi(c1, f"Told done, unpaid > {sla} days", len(cnp), f"{lakh(cnp.s_amount.sum())} owed  ·  target 0", "urgent")
    kpi(c2, "Urgent cases", len(urgent), f"of {len(pc)} cases needing action", "urgent" if len(urgent) else "ok")
    kpi(c3, "Waiting on Finance", len(fin),
        f"{lakh(m[m.true_state == 'Pending in Finance'].s_amount.sum())} not yet paid", "high")
    kpi(c4, "Possible double payouts", len(dbl), f"{lakh(dbl.finance_paid.sum())} to check with bank", "high")

    section("Cases needing action", "Most urgent and longest waiting first. Select a row to open the case.")
    f1, f2, f3 = st.columns([1.1, 1.5, 1])
    named = sorted(h for h in pc.owner.unique() if h not in ("Finance", "Support", "Unassigned"))
    owner_opts = ["Everyone", "Finance", "Support (all)"] + named + (["Unassigned"] if "Unassigned" in set(pc.owner) else [])
    who = f1.selectbox("Owner", owner_opts)
    order = pc.drop_duplicates("problem").sort_values("priority").problem.tolist()
    counts = pc.problem.value_counts()
    prob_opts = ["All problems"] + order
    pick = f2.selectbox("Problem", prob_opts,
                        format_func=lambda p: f"{p} ({len(pc)})" if p == "All problems" else f"{p} ({counts[p]})")
    q = f3.text_input("Search", placeholder="Refund ID or agent name")

    view = pc
    if who == "Finance":
        view = view[view.owner == "Finance"]
    elif who == "Support (all)":
        view = view[view.owner != "Finance"]
    elif who != "Everyone":
        view = view[view.owner == who]
    if pick != "All problems":
        view = view[view.problem == pick]
    if q.strip():
        ql = q.strip().lower()
        view = view[view.refund_id.str.lower().str.contains(ql, regex=False)
                    | view.agent.fillna("").str.lower().str.contains(ql, regex=False)]
    view = view.sort_values(["priority", "age_days"], ascending=[True, False]).reset_index(drop=True)

    if not len(view):
        st.info("No cases match these filters.")
        return
    table = pd.DataFrame({
        "Priority": view.priority_label, "Problem": view.problem, "Refund": view.refund_id,
        "Agent": view.agent.fillna("—"), "Days waiting": view.age_days, "Owner": view.owner,
        "Next step": view.short_step, "Amount": view.support_amount.fillna(view.finance_paid).map(money),
    })
    tone_by_label = {v[0]: v[1] for v in PRIORITY.values()}
    styled = table.style.apply(
        lambda col: [f"color:{TONES[tone_by_label[v]][0]};background-color:{TONES[tone_by_label[v]][1]};font-weight:600"
                     for v in col], subset=["Priority"])
    st.caption(f"{len(view)} of {len(pc)} cases")
    # key includes the filters, so a selection never points at a row from a different filter
    sel = st.dataframe(
        styled, hide_index=True, width="stretch", height=320, on_select="rerun", selection_mode="single-row",
        key=f"worklist_{who}_{pick}_{q}",
        column_config={
            "Priority": st.column_config.TextColumn(width="small"),
            "Problem": st.column_config.TextColumn(width="medium"),
            "Days waiting": st.column_config.NumberColumn(format="%d", help="Days since the last action"),
            "Next step": st.column_config.TextColumn(width="medium"),
            "Amount": st.column_config.TextColumn(width="small"),
        })
    st.download_button("Download this list (CSV)", table.to_csv(index=False), "worklist.csv")

    rows = sel.selection.rows if sel and sel.selection else []
    if not rows or rows[0] >= len(view):
        st.caption("Select a row above to see what Support and Finance each recorded.")
    else:
        case = view.iloc[rows[0]]
        r = m[m.refund_id == case.refund_id].iloc[0]
        pr, tone = PRIORITY[case.priority]
        st.markdown(f"<div class='bt-section'>Case {esc(case.refund_id)}  ·  {esc(case.agent)}  "
                    f"{badge(pr, tone)}</div><div class='bt-hint'><b>{esc(case.problem)}.</b> {esc(case.why)}</div>",
                    unsafe_allow_html=True)
        a, b = st.columns(2)
        if pd.notna(r.s_status):
            sup = (f"<p>Status <b>{esc(r.s_status)}</b>  ·  note <span class='bt-quote'>“{esc(r.s_notes)}”</span></p>"
                   f"<p>Requested <b>{money(r.s_amount)}</b> on {fdate(r.request_date)}</p>"
                   f"<p>Handled by {esc(r.handler)}  ·  last updated {fdate(r.s_last_updated)}  ·  via {esc(r.channel)}</p>")
        else:
            sup = f"<p>{badge('No Support ticket', 'high')}</p>"
        a.markdown(f"<div class='bt-card'><h4>Support tracker</h4>{sup}</div>", unsafe_allow_html=True)
        if pd.notna(r.f_status):
            paid = (f"Paid <b>{money(r.f_paid)}</b> on {fdate(r.f_processed)}" if r.f_status == "Refund Done"
                    else f"Status <b>{esc(r.f_status)}</b>")
            ded = f"  ·  deduction <b>{money(r.f_deduction)}</b>" if r.f_deduction and r.f_deduction > 0 else ""
            fin_html = (f"<p>{paid}{ded}</p><p>Remark <span class='bt-quote'>“{esc(r.f_remarks)}”</span>  ·  "
                        f"received {fdate(r.f_received)}</p><p>Approved by "
                        f"{esc(r.approved_by) if pd.notna(r.approved_by) else 'nobody recorded'}</p>")
        else:
            fin_html = f"<p>{badge('No Finance record', 'urgent')}</p><p>This refund never reached Finance.</p>"
        b.markdown(f"<div class='bt-card'><h4>Finance tracker</h4>{fin_html}</div>", unsafe_allow_html=True)
        st.info(f"Next step  ·  owner {case.owner}:  {case.next_action}")
        if st.button("Draft a reply to the agent", type="primary", key=f"to_reply_{case.refund_id}"):
            st.session_state["reply_pick"] = reply_label(case.refund_id)
            st.success("Prepared. Open the **Agent reply** tab; this refund is already selected.")

    with st.expander("How these numbers are calculated"):
        st.markdown("Both trackers are cleaned (IDs, dates, names, duplicates) and joined on the refund ID. Each refund "
                    "gets one true status, and Finance decides whether money moved. No AI is used in this screen.")
        x, y = st.columns(2)
        x.markdown("**True status of every refund**")
        x.dataframe(m.true_state.value_counts().rename_axis("Status").rename("Refunds"), width="stretch")
        y.markdown("**Cleaning rules applied**")
        y.dataframe(cleanlog.rename(columns={"sheet": "Sheet", "rule": "Rule", "rows_affected": "Rows"}),
                    hide_index=True, width="stretch")


# ================================================================== New message
SAMPLES = {
    "Email from Peak Journeys, 5 June": ("Email", "Peak Journeys", date(2026, 6, 5),
        "Hi, I cancelled booking for DEL-DXB last week and was told I'd get a refund. I haven't received "
        "anything and I don't have any reference number. Please help, my client is asking. "
        "(This is the case later referenced as RF-1099.)"),
    "WhatsApp from Nomad Travel, 8 June": ("WhatsApp", "Nomad Travel", date(2026, 6, 8),
        "Bhai refund ka kya hua? BLR-MAA wala. 2 hafte ho gaye, koi jawab nahi. (Later referenced as RF-1098.)"),
    "Internal note from a Support agent, 11 June": ("Email", "Support agent (internal)", date(2026, 6, 11),
        "Finance says they never received several of the refunds I closed last month. I marked them done "
        "on my side. Not sure where they went."),
    "Paste a new message": ("Email", "", date(2026, 6, 30), ""),
}


def render_message():
    section("Turn an email or WhatsApp into a ticket",
            "AI reads the message. Every match and amount below comes from the trackers, not the AI. "
            "Nothing is saved until you approve.")
    pick = st.selectbox("Message", list(SAMPLES), help="Choose an example from the brief, or paste a new one.")
    ch, snd, rcv, txt = SAMPLES[pick]
    a, b_, c_ = st.columns(3)
    channel = a.selectbox("Channel", ["Email", "WhatsApp", "Phone note"], index=["Email", "WhatsApp", "Phone note"].index(ch))
    sender = b_.text_input("From", snd)
    received = c_.date_input("Received on", rcv)
    message = st.text_area("Message text, exactly as received", txt, height=110,
                           max_chars=5000, placeholder="Paste the email or WhatsApp text here")

    if not AI_READY:
        st.warning("AI is not configured on this server, so messages cannot be read. The Worklist still works.")
    if st.button("Read message and check records", type="primary", disabled=not (AI_READY and message.strip())):
        import ai
        with st.spinner("Reading the message and checking both trackers"):
            try:
                fields, source = ai.extract_intake(message, channel, sender, str(received))
                st.session_state.intake = {"fields": fields.model_dump(), "source": source,
                                           "received": received, "channel": channel,
                                           "skey": approvals.dedupe_key(source),
                                           "call": ai._RESOLVED.get("last_call", "")}
            except Exception as e:
                show_ai_error(e)

    it = st.session_state.get("intake")
    if not it:
        return
    fx = it["fields"]
    skey = it.get("skey") or approvals.dedupe_key(it["source"])
    ev = {e["field"]: e["quote"] for e in fx.get("evidence", [])}
    msg_date = pd.Timestamp(it["received"])
    known = set(m.refund_id.dropna())

    def proof(field):
        return f" <span class='bt-quote'>· from the message: “{esc(ev[field])}”</span>" if field in ev else ""

    section("What the message says", step=1)
    lang = fx.get("language", "")
    st.markdown(f"<div class='bt-card'>{esc(fx['summary_english'])}"
                + (f"<div class='bt-hint' style='margin:6px 0 0'>Language: {esc(lang)} (summary translated)</div>"
                   if lang and lang.lower() != "english" else "") + "</div>", unsafe_allow_html=True)

    if fx["message_type"] != "refund_request_from_agent":
        st.warning("This is not a refund request from a travel agent, so no ticket is created.")
        if fx["message_type"] == "internal_note":
            cm = m[m.true_state == "Closed in Support, missing in Finance"]
            section("What our records show", step=2)
            st.error(f"{len(cm)} refunds are marked Closed by Support but never reached Finance, worth "
                     f"{money(cm.s_amount.sum())}. This matches what the note describes.")
            by_h = (cm.groupby("handler").agg(refunds=("refund_id", "size"), amount=("s_amount", "sum"))
                    .sort_values("refunds", ascending=False).reset_index())
            by_h["amount"] = by_h.amount.map(money)
            st.dataframe(by_h.rename(columns={"handler": "Closed by", "refunds": "Refunds", "amount": "Amount"}),
                         hide_index=True)
            section("Next step", step=3)
            st.info("Open the Worklist and set Problem to 'Told done, not in Finance'. Each row has an owner and a "
                    "next step.")
        return

    est, _ = matching.estimate_request_date(msg_date, fx.get("request_date"), fx.get("time_reference"))
    ref = recon.norm_id(fx.get("booking_reference"))
    ref_html = esc(ref or "None")
    if ref:
        ref_html += " " + (badge("Found in our records", "ok") if ref in known else badge("Not in our records", "urgent"))
    rows = [
        ("Travel agent", esc(fx.get("agent_name") or "Not stated"), proof("agent_name")),
        ("Route", esc(fx.get("route") or "Not stated"), proof("route")),
        ("Cancelled", f"about {est:%d %b %Y}" if est is not None else "Not stated",
         proof("time_reference") or proof("request_date")),
        ("Amount", money(fx["amount_inr"]) if fx.get("amount_inr") else "Not stated in the message", proof("amount_inr")),
        ("Reference quoted", ref_html, proof("booking_reference")),
    ]
    st.markdown("<div class='bt-card'>" + "".join(f"<p><b>{k}:</b> {v}{p}</p>" for k, v, p in rows) + "</div>",
                unsafe_allow_html=True)

    section("What our records show", step=2)
    if "res" not in it:  # decide once, so the draft number is stable
        logged = approvals.load()
        taken = [x for x in logged.get("refund_id", pd.Series(dtype=str)) if str(x).startswith("DRAFT-")]
        it["res"] = matching.decide(fx, m, msg_date, sorted(set(taken + st.session_state.drafts)))
    res = it["res"]
    view = matching.candidate_view(res["candidates"], m, msg_date)
    if res["decision"] == "LINK":
        st.success(f"Found in our records: {res['refund_id']}. {res['reason']}")
    elif ref:
        st.error(f"Not in the Support or Finance trackers. {ref} is in neither, so this request was never logged.")
    else:
        st.warning("No exact match. No reference was given, and no record matches agent, route and date closely enough.")
    if len(view):
        st.markdown("**Refunds for the same agent that might be this one**")
        friendly = pd.DataFrame({
            "Refund": view.refund_id, "Requested on": view.requested_on,
            "Requested": view.requested_inr.map(money), "Deduction": view.deduction_inr.map(money),
            "Payout": view.payout_inr.map(money), "Status": view.status,
            "Match": view.match_score.map(lambda s: "High" if s >= 85 else "Medium" if s >= 60 else "Low"),
            "Note": [("Logged after the message; may be this request" if r.logged_after_message else
                      f"{int(r.days_from_estimate)} days from cancellation" if pd.notna(r.days_from_estimate) else "")
                     for r in view.itertuples()],
        })
        st.dataframe(friendly, hide_index=True, width="stretch")

    section("Decide what goes to the next stage", step=3)
    if res["decision"] == "LINK":
        labels = {f"This is {res['refund_id']} (found in our records)": ("LINK", res["refund_id"])}
    else:
        labels = {f"Create new ticket {res['refund_id']} (request was never logged)": ("NEW_DRAFT", res["refund_id"])}
    for r in view.itertuples():
        if r.refund_id != res["refund_id"]:
            hint = ", logged later by Support" if r.logged_after_message else ""
            labels[f"It is {r.refund_id} ({r.status}, requested {r.requested_on}{hint})"] = ("LINK", r.refund_id)
    choice = st.radio("Decision", list(labels), key=f"choice_{skey}")
    action, rid = labels[choice]

    if action == "LINK":
        rec = m[m.refund_id == rid].iloc[0]
        pf = recon.payout_proof(rec)
        lines = "".join(f"<p>{esc(lbl)}: <b>{money(amt)}</b> <span class='bt-quote'>({esc(src)})</span></p>"
                        for lbl, amt, src in pf["lines"])
        total = (f"<p style='margin-top:8px'><b>{esc(pf['kind'])}: {money(pf['amount'])}</b>"
                 + (f" <span class='bt-quote'>· check: {esc(pf['check'])}</span>" if pf["check"] else "") + "</p>"
                 if pf["amount"] is not None else f"<p><b>{esc(pf['kind'])}</b>: confirm the amount with the agent.</p>")
        st.markdown(f"<div class='bt-card'><h4>Amount to carry forward</h4>{lines}{total}</div>", unsafe_allow_html=True)
        agent = rec.agent if pd.notna(rec.agent) else rec.f_agent
        route = rec.route if pd.notna(rec.route) else rec.f_route
        amount, payout = rec.s_amount, pf["amount"]
        if rec.true_state in ("Pending in Finance", "Closed in Support, missing in Finance", "Open in Support"):
            owner = "Finance"
            pay_txt = f"Release the payout of {money(payout)}" if payout is not None else "Confirm the amount, then pay"
            next_step = f"{pay_txt}. Support: tell the agent the reference {rid} and explain any deduction."
        else:
            owner, next_step = "Support", f"Tell the agent the status of {rid} using the Agent reply tab."
    else:
        agent, route, payout = fx.get("agent_name"), fx.get("route"), None
        if fx.get("amount_inr"):
            st.markdown(f"<div class='bt-card'><h4>Amount to carry forward</h4><p><b>{money(fx['amount_inr'])}</b> "
                        f"<span class='bt-quote'>· stated in the message: “{esc(ev.get('amount_inr', ''))}”</span></p></div>",
                        unsafe_allow_html=True)
            amount = fx["amount_inr"]
        else:
            st.warning("The amount is not in the message and there is no tracker record to take it from. "
                       "Confirm it with the agent before this goes to Finance.")
            amount = st.number_input("Amount confirmed with the agent (₹), 0 if not yet confirmed", 0, step=100,
                                     key=f"amt_{skey}") or None
        owner = "Support"
        next_step = (f"Reply to {agent or 'the agent'} with ticket {rid}" + ("" if amount else " and confirm the amount")
                     + ", then send it to Finance.")

    st.markdown(f"**Next stage:** owner **{owner}**. {next_step}")
    key = approvals.dedupe_key("intake", skey, action, rid)
    if approvals.already_approved(key):
        st.success(f"Approved and logged. Owner {owner}: {next_step}")
    elif require_name() and st.button("Approve and send to next stage", type="primary", key=f"approve_{skey}"):
        ok, apr = approvals.append({
            "approved_by": approver, "type": "intake", "action": action, "refund_id": rid, "agent_reference": ref,
            "agent": agent, "route": route, "amount_inr": amount, "payout_inr": payout, "owner": owner,
            "next_step": next_step, "channel": it["channel"], "received_on": str(it["received"]),
            "source_text": it["source"]}, key)
        if action == "NEW_DRAFT" and rid not in st.session_state.drafts:
            st.session_state.drafts.append(rid)
        log.info("approval %s intake %s %s by %s", apr, action, rid, approver)
        st.rerun()

    with st.expander("Technical details (audit trail)"):
        if it.get("call"):
            st.caption(it["call"])
        st.markdown("**Exactly what the AI was given**")
        st.code(it["source"], language=None)
        st.markdown("**AI output (structured fields with quotes)**")
        st.json(fx)
        st.markdown("**Matching scores (plain code)**")
        st.caption(res["date_note"]["how"])
        st.dataframe(res["candidates"], hide_index=True)


# ================================================================== Agent reply
def render_reply():
    section("Send a status update to a travel agent",
            "Facts come from both trackers. AI only turns them into a short, polite message. "
            "You review and approve it before anything is sent.")
    pc_ids = recon.problem_cases(m, today).refund_id.tolist()
    order = list(dict.fromkeys(pc_ids + m.refund_id.dropna().sort_values().tolist()))
    options = [reply_label(x) for x in order]
    if st.session_state.get("reply_pick") not in options:
        st.session_state.pop("reply_pick", None)
    label = st.selectbox("Refund (cases needing action first; type to search)", options, key="reply_pick")
    rid = label.split("  ·  ")[0]
    row = m[m.refund_id == rid].iloc[0]
    facts = recon.refund_facts(row)
    left, right = st.columns([1, 1.25], gap="large")
    with left:
        section("Check the facts", step=1)
        st.markdown("<div class='bt-card'>" + "".join(
            f"<p><b>{esc(k)}:</b> {esc(str(v).replace('Rs ', '₹'))}</p>" for k, v in facts.items()) + "</div>",
            unsafe_allow_html=True)
        st.caption("Worked out by code from both trackers. The message may only use these facts.")
    with right:
        section("Draft the message", step=2)
        if not AI_READY:
            st.warning("AI is not configured on this server.")
        cache = st.session_state.setdefault("draft_cache", {})
        ckey = (rid, json.dumps(facts, sort_keys=True, default=str))
        d = cache.get(ckey)
        if st.button("Redraft with AI" if d else "Draft message with AI", type="secondary" if d else "primary",
                     disabled=not AI_READY, key=f"draft_{rid}"):
            import ai
            try:
                st.caption("Writing")
                text = st.write_stream(ai.draft_agent_update_stream(facts))
                if isinstance(text, list):
                    text = "".join(map(str, text))
                if not text.strip():
                    raise RuntimeError("Gemini returned no text (blocked by a safety filter).")
                cache[ckey] = {"text": text.strip(), "source": ai.update_source(facts),
                               "flags": ai.numbers_not_in_facts(text, facts), "call": ai._RESOLVED.get("last_call", "")}
                st.rerun()
            except Exception as e:
                show_ai_error(e)
        if not d:
            return
        st.caption(("Saved draft. Use Redraft for a new version.  ·  " + d.get("call", "")).strip(" ·"))
        if d["flags"]:
            st.error(f"Numbers in the draft that are not in the facts: {', '.join(d['flags'])}. Edit before approving.")
        else:
            st.success("Number check passed: every amount in the draft appears in the facts.")
        section("Review and approve", step=3)
        edited = st.text_area("Message to the agent (edit freely)", d["text"], height=230,
                              key=f"edit_{rid}_{approvals.dedupe_key(d['text'])}")
        key = approvals.dedupe_key("update", rid, edited.strip())
        if approvals.already_approved(key):
            st.success("Approved and logged. Copy the text below into email or WhatsApp. The desk does not send anything.")
            st.code(edited, language=None)
        elif require_name() and st.button("Approve message", type="primary", key=f"approve_upd_{rid}"):
            ok, apr = approvals.append({
                "approved_by": approver, "type": "agent_update", "refund_id": rid, "true_state": row.true_state,
                "message": edited.strip(), "source_text": d["source"]}, key)
            log.info("approval %s agent_update %s by %s", apr, rid, approver)
            st.rerun()


# ================================================================== Approval log
def render_log():
    section("Approval log", "Every approved ticket and agent message, who approved it, and the source it was based on.")
    df = approvals.load()
    if not len(df):
        st.info("Nothing approved yet. Approvals from the New message and Agent reply tabs appear here.")
        return
    kinds = {"All": None, "Tickets from messages": "intake", "Agent messages": "agent_update"}
    k = st.radio("Show", list(kinds), horizontal=True)
    view = df if kinds[k] is None else df[df.type == kinds[k]]
    view = view.sort_values("approved_at", ascending=False)

    def num(x):
        try:
            return money(float(x)) if str(x).strip() else "—"
        except ValueError:
            return "—"
    show = pd.DataFrame({
        "Approval": view.approval_id,
        "When": pd.to_datetime(view.approved_at, errors="coerce").dt.strftime("%d %b %Y, %H:%M"),
        "Approved by": view.approved_by,
        "Type": view.type.map({"intake": "Ticket from message", "agent_update": "Agent message"}).fillna(view.type),
        "Decision": view.action.map({"LINK": "Linked to refund", "NEW_DRAFT": "New ticket"}).fillna(""),
        "Refund": view.refund_id, "Agent": view.agent,
        "Amount": view.amount_inr.map(num), "Payout": view.payout_inr.map(num), "Owner": view.owner,
        "Next step / message": view.next_step.where(view.next_step != "", view.message),
    })
    st.dataframe(show, hide_index=True, width="stretch", height=min(400, 40 + 35 * len(show)),
                 column_config={"Next step / message": st.column_config.TextColumn(width="large")})
    st.download_button("Download full log (CSV, includes source text)",
                       view.drop(columns=["dedupe_key"]).to_csv(index=False), "approval_log.csv", type="primary")
    st.caption("Stored on the server as an append-only file. In production this would be a database with user sign-in.")


with tab_work:
    safe(render_worklist)
with tab_msg:
    safe(render_message)
with tab_reply:
    safe(render_reply)
with tab_log:
    safe(render_log)
