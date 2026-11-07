"""
Live test of the two AI features on the three informal messages from the brief.
Needs ANTHROPIC_API_KEY.   Run:  python test_ai.py
Prints the AI's JSON, the evidence quotes, and the plain-code matching decision for each.
"""
import pandas as pd

import ai
import matching
import recon

f = "data/BharatTrip_Refund_Data.xlsx"
m, _, _, _ = recon.load_and_reconcile(pd.read_excel(f, "Support_Tracker"), pd.read_excel(f, "Finance_Tracker"))

MESSAGES = [
    ("Email", "Peak Journeys", "2026-06-05",
     "Hi, I cancelled booking for DEL-DXB last week and was told I'd get a refund. I haven't received anything "
     "and I don't have any reference number. Please help, my client is asking. (This is the case later referenced as RF-1099.)"),
    ("WhatsApp", "Nomad Travel", "2026-06-08",
     "Bhai refund ka kya hua? BLR-MAA wala. 2 hafte ho gaye, koi jawab nahi. (Later referenced as RF-1098.)"),
    ("Email", "Support agent (internal)", "2026-06-11",
     "Finance says they never received several of the refunds I closed last month. I marked them done on my side. "
     "Not sure where they went."),
]

drafts = []
for ch, sender, day, text in MESSAGES:
    print("=" * 80, f"\n{ch} from {sender}, {day}\n{text}\n")
    fields, _ = ai.extract_intake(text, ch, sender, day)
    print(fields.model_dump_json(indent=2))
    if fields.message_type == "refund_request_from_agent":
        res = matching.decide(fields.model_dump(), m, pd.Timestamp(day), drafts)
        if res["decision"] == "NEW_DRAFT":
            drafts.append(res["refund_id"])
        print(f"\nDECISION: {res['decision']} {res['refund_id']}\n{res['reason']}\n{res['date_note']['how']}")
        print(res["candidates"][["refund_id", "date_any", "true_state", "score"]].to_string(index=False))
    else:
        print("\nNot an agent refund request: no ticket created. Points to the Closed-in-Support-missing-in-Finance list.")

print("=" * 80, "\nAgent update for RF-1197 (paid with a Rs 1,500 deduction)\n")
facts = recon.refund_facts(m[m.refund_id == "RF-1197"].iloc[0])
draft, _ = ai.draft_agent_update(facts)
print(draft, "\n\nNumbers not in facts:", ai.numbers_not_in_facts(draft, facts) or "none")
