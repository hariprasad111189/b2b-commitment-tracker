import sys
sys.path.insert(0, ".")

import html
import re
import json

import streamlit as st
import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from data.mock_invoices import get_mock_invoices
from data.mock_ledger import get_mock_ledger
from data.mock_emails import get_mock_emails

API_BASE = "http://localhost:8000/api/v1"
_SAMPLE_EMAIL_LOOKUP = {e.email_id: e for e in get_mock_emails()}


def _relevant_sentence(body: str, commitment: dict) -> str | None:
    """Pick the most relevant sentence from the original email for the reviewer."""
    if not body:
        return None
    phrases = []
    raw_phrase = (commitment.get("raw_date_phrase") or "").strip()
    if raw_phrase:
        phrases.append(raw_phrase.lower())
    if commitment.get("claims_already_paid"):
        phrases.extend(["already been settled", "already paid", "already been processed", "settled"])
    if commitment.get("promised_amount") is not None:
        amount = commitment["promised_amount"]
        phrases.append(f"{amount:,.0f}".replace(",", ","))
        phrases.append(f"{amount:,.0f}".replace(",", ""))
    sentences = re.split(r"(?<=[.!?])\s+", body.strip())
    sentences = [s.strip() for s in sentences if s.strip()]
    for needle in phrases:
        for sentence in sentences:
            if needle and needle.lower() in sentence.lower():
                return sentence
    # Fallback: first non-greeting content line
    for sentence in sentences:
        lower = sentence.lower()
        if lower.startswith(("dear ", "hi", "hello", "regards", "best", "thanks")):
            continue
        if len(sentence) > 40:
            return sentence
    return sentences[0] if sentences else None


def _system_finding(commitment: dict, item: dict) -> str:
    if commitment.get("claims_already_paid"):
        return "Customer claims payment has already been made."
    if commitment.get("has_commitment"):
        parts = []
        if commitment.get("promised_amount") is not None:
            parts.append(f"promised amount ₹{commitment['promised_amount']:,.2f}")
        phrase = (commitment.get("raw_date_phrase") or "").strip()
        if phrase:
            parts.append(f"date phrase '{phrase}'")
        elif commitment.get("resolved_date"):
            parts.append(f"resolved date {commitment['resolved_date'][:10]}")
        if parts:
            return "Customer payment commitment extracted: " + "; ".join(parts) + "."
        return "A payment commitment was detected, but some details are incomplete."
    return "No clear payment commitment was extracted from this email."


def _human_decision_prompt(item: dict, commitment: dict) -> str:
    if commitment.get("claims_already_paid") and item.get("ledger_status") != "SETTLED":
        return "Please verify the payment before approving."
    if commitment.get("date_ambiguous"):
        return "Please confirm the intended payment date before approving."
    if item.get("action") == "NO_ACTION":
        return "Please confirm whether any follow-up is needed, or reject if no action is required."
    return "Please verify the details above, then Approve or Reject."


st.set_page_config(page_title="Payment Recovery Assistant", page_icon="💳", layout="centered")

st.markdown("""
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<style>
    html, body, [class*="css"] { font-family: 'Inter', sans-serif; }
    .stApp { background-color: #FAFBFF; }
    h1, h2, h3 { color: #0F172A !important; font-weight: 800 !important; }
    p, li, span, label { color: #1E293B; }

    div[data-testid="stButton"] button {
        border-radius: 10px; font-weight: 700; font-size: 1.02rem;
        padding: 0.85rem 1.4rem; border: none; width: 100%;
    }
    div[data-testid="stButton"] button[kind="primary"] { background-color: #2563EB; color: white; }
    div[data-testid="stButton"] button[kind="primary"]:hover { background-color: #1D4ED8; }
    div[data-testid="stButton"] button:not([kind="primary"]) {
        background-color: #FFFFFF; border: 1.5px solid #CBD5E1; color: #1E293B;
    }

    .hero {
        background: linear-gradient(135deg, #1E3A8A 0%, #2563EB 100%);
        border-radius: 18px; padding: 28px 32px; color: white; margin-bottom: 8px;
    }
    .hero h1 { color: white !important; margin: 0 0 6px 0; font-size: 1.8rem; }
    .hero p { color: #DBEAFE; margin: 0; font-size: 0.95rem; }

    @keyframes fadeInUp { from { opacity: 0; transform: translateY(10px); } to { opacity: 1; transform: translateY(0); } }

    .slide-card {
        background: white; border: 1px solid #E2E8F0; border-radius: 18px;
        padding: 30px 34px; margin: 14px 0; animation: fadeInUp 0.35s ease-out;
        min-height: 220px;
    }
    .slide-card h2 { margin-top: 0; }
    .slide-card .tag {
        display: inline-block; background: #DBEAFE; color: #1E40AF;
        padding: 4px 14px; border-radius: 20px; font-size: 0.78rem; font-weight: 700; margin-bottom: 12px;
    }
    .tech-grid { display: flex; flex-wrap: wrap; gap: 10px; margin-top: 14px; }
    .tech-chip {
        background: #F1F5F9; border: 1px solid #E2E8F0; border-radius: 10px;
        padding: 8px 14px; font-size: 0.85rem; font-weight: 600; color: #334155;
    }
    .dots { display: flex; gap: 8px; justify-content: center; margin-top: 6px; }
    .dot { width: 8px; height: 8px; border-radius: 50%; background: #CBD5E1; }
    .dot.active { background: #2563EB; width: 22px; border-radius: 4px; }

    .progress-track { display: flex; gap: 6px; margin: 18px 0 28px 0; }
    .progress-dot { flex: 1; height: 6px; border-radius: 4px; background: #E2E8F0; }
    .progress-dot.active { background: #2563EB; }
    .progress-dot.done { background: #10B981; }

    .step-header { display: flex; align-items: center; gap: 12px; margin-top: 34px; margin-bottom: 4px; }
    .step-number { width: 34px; height: 34px; border-radius: 50%; background: #2563EB; color: white;
        font-weight: 800; display: flex; align-items: center; justify-content: center; font-size: 0.95rem; }
    .step-number.locked { background: #CBD5E1; }
    .step-title { font-size: 1.25rem; font-weight: 800; color: #0F172A; }
    .step-sub { color: #64748B; font-size: 0.88rem; margin-left: 46px; margin-bottom: 12px; }

    .metric-tile { flex: 1; background: white; border: 1px solid #E2E8F0; border-radius: 12px;
        padding: 14px 12px; text-align: center; }
    .metric-tile .val { font-size: 1.5rem; font-weight: 800; }
    .metric-tile .lbl { font-size: 0.72rem; color: #64748B; margin-top: 2px; }

    .card { background: white; border: 1px solid #E2E8F0; border-radius: 14px; padding: 18px 20px; margin-bottom: 12px; }
    .card.review { border-left: 5px solid #F59E0B; }
    .card.ok { border-left: 5px solid #10B981; }
    .card.bad { border-left: 5px solid #EF4444; }
    .card.wait { border-left: 5px solid #3B82F6; }
    .card.none { border-left: 5px solid #CBD5E1; }

    .pill { display: inline-block; padding: 4px 12px; border-radius: 20px; font-size: 0.73rem; font-weight: 700; }
    .pill-green { background: #D1FAE5; color: #065F46; }
    .pill-red   { background: #FEE2E2; color: #991B1B; }
    .pill-amber { background: #FEF3C7; color: #92400E; }
    .pill-blue  { background: #DBEAFE; color: #1E40AF; }
    .pill-gray  { background: #F1F5F9; color: #475569; }

    .banner-ok   { background: #ECFDF5; border: 1.5px solid #34D399; border-radius: 12px; padding: 14px 18px; color: #065F46; }
    .banner-info { background: #EFF6FF; border: 1.5px solid #93C5FD; border-radius: 12px; padding: 14px 18px; color: #1E3A8A; }
    .banner-warn { background: #FFFBEB; border: 1.5px solid #FCD34D; border-radius: 12px; padding: 14px 18px; color: #92400E; }
    .banner-bad  { background: #FEF2F2; border: 1.5px solid #FCA5A5; border-radius: 12px; padding: 14px 18px; color: #991B1B; }

    .redact-box { background: #F8FAFC; border: 1px solid #E2E8F0; border-radius: 10px;
        padding: 14px 16px; font-family: monospace; font-size: 0.84rem; line-height: 1.6; }
    .pii-tag { background: #FEE2E2; color: #B91C1C; padding: 2px 6px; border-radius: 4px; font-weight: 700; }

    .draft-box { background: #F8FAFC; border: 1px solid #E2E8F0; border-radius: 10px;
        padding: 16px 18px; font-size: 0.9rem; line-height: 1.7; white-space: pre-wrap; }
</style>
""", unsafe_allow_html=True)


def _session():
    if "_http" not in st.session_state:
        s = requests.Session()
        s.mount("http://", HTTPAdapter(max_retries=Retry(total=2, backoff_factor=0.5)))
        st.session_state["_http"] = s
    return st.session_state["_http"]


def api_get(path, timeout=15):
    try:
        r = _session().get(f"{API_BASE}{path}", timeout=timeout)
        r.raise_for_status()
        return r.json()
    except Exception:
        return None


def api_post(path, body=None, timeout=90):
    try:
        return _session().post(f"{API_BASE}{path}", json=body, timeout=timeout)
    except requests.exceptions.ReadTimeout:
        return "TIMEOUT"
    except Exception:
        return None


def render_redacted(text):
    escaped = html.escape(text or "")
    return re.sub(r"&lt;([A-Z_]+)&gt;", r'<span class="pii-tag">&lt;\1&gt;</span>', escaped)


ACTION_STYLE = {
    "MARK_RESOLVED": ("ok", "pill-green", "✅ Payment Confirmed"),
    "FLAG_BROKEN_PROMISE": ("bad", "pill-red", "🔴 Promise Not Kept"),
    "ESCALATE_TO_MANAGER": ("review", "pill-amber", "⚠️ Needs Your Review"),
    "PAUSE_DUNNING": ("wait", "pill-blue", "⏸️ Not Due Yet"),
    "DRAFT_REMINDER": ("wait", "pill-blue", "✉️ Reminder Suggested"),
    "NO_ACTION": ("none", "pill-gray", "⚪ Nothing To Do"),
}

# ============================================================================
# ABOUT THIS PROJECT — slide deck, visible on open
# ============================================================================
SLIDES = [
    {
        "tag": "THE PROBLEM",
        "title": "🧾 B2B invoices go unpaid, and nobody tracks the promises",
        "body": "When a business customer replies to a payment reminder with something like "
                "\"we'll pay by next Friday,\" that promise usually lives in someone's inbox — "
                "not in any system. Nobody automatically checks if it was kept. Multiply that across "
                "hundreds of invoices, and real money quietly slips through the cracks.",
    },
    {
        "tag": "THE SOLUTION",
        "title": "🤖 An AI assistant that reads, verifies, and never guesses with money",
        "body": "This system reads incoming emails, strips out personal details before any AI sees them, "
                "extracts what was promised, and — critically — checks that promise against real payment "
                "records using plain deterministic code, not AI. If a customer claims \"already paid\" but "
                "the records disagree, a human is alerted immediately instead of the claim being trusted blindly.",
    },
    {
        "tag": "HOW IT WORKS",
        "title": "🔄 Five steps, every one of them auditable",
        "body": "① Email arrives → ② personal details are redacted → ③ AI extracts the payment promise → "
                "④ plain Python code checks it against the ledger (never AI) → ⑤ a human approves or rejects, "
                "which then auto-drafts a professional reply. Every single step is permanently logged with a "
                "tamper-proof cryptographic chain.",
    },
    {
        "tag": "TECH STACK",
        "title": "🛠️ Built entirely on free, production-grade tools",
        "body": "",
        "chips": ["FastAPI", "LangGraph", "Pydantic v2", "SQLite", "Groq (gpt-oss-120b)",
                  "Presidio (PII redaction)", "SHA-256 audit chain", "Streamlit", "IMAP live email"],
    },
]

if "slide_idx" not in st.session_state:
    st.session_state["slide_idx"] = 0

st.markdown("## ℹ️ About This Project")

slide = SLIDES[st.session_state["slide_idx"]]
chips_html = ""
if slide.get("chips"):
    chips_html = '<div class="tech-grid">' + "".join(f'<div class="tech-chip">{c}</div>' for c in slide["chips"]) + '</div>'

st.markdown(f"""
<div class="slide-card">
    <span class="tag">{slide['tag']}</span>
    <h2>{slide['title']}</h2>
    <p style="color:#475569; font-size:0.98rem; line-height:1.7;">{slide['body']}</p>
    {chips_html}
</div>
""", unsafe_allow_html=True)

nav1, nav2, nav3 = st.columns([1, 3, 1])
with nav1:
    if st.button("← Back", key="slide_back", disabled=(st.session_state["slide_idx"] == 0)):
        st.session_state["slide_idx"] -= 1
        st.rerun()
with nav2:
    dots_html = "".join(
        f'<div class="dot{" active" if i == st.session_state["slide_idx"] else ""}"></div>'
        for i in range(len(SLIDES))
    )
    st.markdown(f'<div class="dots">{dots_html}</div>', unsafe_allow_html=True)
with nav3:
    if st.button("Next →", key="slide_next", disabled=(st.session_state["slide_idx"] == len(SLIDES) - 1)):
        st.session_state["slide_idx"] += 1
        st.rerun()

st.markdown("---")

# ============================================================================
st.markdown("""
<div class="hero">
    <h1>💳 Payment Recovery Assistant</h1>
    <p>Now let's actually run it — follow the numbered steps below.</p>
</div>
""", unsafe_allow_html=True)

backend_ok = api_get("/commitments/pending") is not None
if not backend_ok:
    st.markdown('<div class="banner-bad">🔴 <b>Backend is not running.</b> Start it, then refresh this page.</div>', unsafe_allow_html=True)
    st.code("uvicorn app.api:app --reload --port 8000")
    st.stop()

pending = api_get("/commitments/pending") or []
recovery = api_get("/recovery/summary") or {"total_exposure": 0, "recovered": 0, "at_risk": 0, "pending_review": 0, "total_items": 0}
drafts = api_get("/drafts/pending") or []

# ============================================================================
# RECOVERY IMPACT
# ============================================================================
st.markdown("### 📊 Recovery Impact")
st.caption("This is the business result — how much money is confirmed, at risk, or still needs a decision.")

m1, m2, m3, m4 = st.columns(4)
tiles = [
    (m1, f"₹{recovery['total_exposure']:,.0f}", "Total Invoiced", "#0F172A"),
    (m2, f"₹{recovery['recovered']:,.0f}", "Confirmed Recovered", "#10B981"),
    (m3, f"₹{recovery['at_risk']:,.0f}", "At Risk (Broken Promises)", "#EF4444"),
    (m4, f"₹{recovery['pending_review']:,.0f}", "Awaiting Your Decision", "#F59E0B"),
]
for col, val, lbl, color in tiles:
    col.markdown(f'<div class="metric-tile"><div class="val" style="color:{color}">{val}</div><div class="lbl">{lbl}</div></div>', unsafe_allow_html=True)

# ============================================================================
# STEP 1 — INGEST
# ============================================================================
st.markdown('<div class="step-header"><div class="step-number">1</div><div class="step-title">Bring in the emails</div></div>', unsafe_allow_html=True)
st.markdown('<div class="step-sub">Choose one option, click its button.</div>', unsafe_allow_html=True)

c1, c2 = st.columns(2)
with c1:
    st.markdown("**📁 Sample Emails**")
    st.caption("5 practice emails already in this project. Safe, repeatable demo.")
    if st.button("▶️ Run 5 Sample Emails", type="primary", key="btn_demo"):
        with st.spinner("Starting fresh and processing the 5 sample emails..."):
            resp = api_post("/commitments/ingest-fresh")
        if resp == "TIMEOUT":
            st.session_state["step1_result"] = ("error", "This took too long and timed out. Click Refresh below, "
                                                          "then check Step 2 — it may have finished anyway.")
        elif resp is None:
            st.session_state["step1_result"] = ("error", "Could not reach the backend server at all. "
                                                          "Make sure `uvicorn app.api:app --reload --port 8000` is running.")
        elif resp.status_code == 200:
            st.session_state["step1_result"] = ("demo", resp.json())
        else:
            st.session_state["step1_result"] = ("error", f"Backend returned an error (status {resp.status_code}): {resp.text[:200]}")

with c2:
    st.markdown("**📬 My Real Inbox**")
    st.caption("Connects to your actual email for new invoice-related messages.")
    if st.button("🔍 Test My Connection First", key="btn_test"):
        st.session_state["conn_test"] = api_get("/live/test-connection")

    if "conn_test" in st.session_state and st.session_state["conn_test"]:
        r = st.session_state["conn_test"]
        if r.get("success"):
            st.success("✅ " + r["message"])
        else:
            st.error("❌ " + r["message"])

    if st.button("📬 Fetch Live Real Emails", type="primary", key="btn_live"):
        with st.spinner("Connecting to your inbox..."):
            resp = api_post("/commitments/ingest-live")
        if resp == "TIMEOUT":
            st.session_state["step1_result"] = ("error", "Connecting to your inbox timed out. Try again.")
        elif resp is None:
            st.session_state["step1_result"] = ("error", "Could not reach the backend server. Make sure it's running.")
        elif resp.status_code == 200:
            st.session_state["step1_result"] = ("live", resp.json())
        else:
            detail = resp.json().get("detail", resp.text[:200]) if resp.headers.get("content-type", "").startswith("application/json") else resp.text[:200]
            st.session_state["step1_result"] = ("live_error", detail)

if "step1_result" in st.session_state:
    kind, payload = st.session_state["step1_result"]
    if kind == "demo":
        st.markdown(f'<div class="banner-ok">✅ Processed {payload["ingested"]} email(s). Scroll down to Step 2.</div>', unsafe_allow_html=True)
    elif kind == "live":
        if payload["ingested"] == 0:
            st.markdown('<div class="banner-warn">📭 Connected fine, no new emails found yet. Send a test email and click again.</div>', unsafe_allow_html=True)
        else:
            st.markdown(f'<div class="banner-ok">✅ Found and processed {payload["ingested"]} new email(s)! Scroll down to Step 2.</div>', unsafe_allow_html=True)
    elif kind in ("live_error", "error"):
        st.markdown(f'<div class="banner-bad">❌ {payload}</div>', unsafe_allow_html=True)

with st.expander("📋 Reference Card — invoice IDs in this system"):
    invoices = get_mock_invoices()
    ledger_map = {l.invoice_id: l for l in get_mock_ledger()}
    rows = [{"Invoice ID": i.invoice_id, "Client": i.client_name, "Amount": f"₹{i.amount_due:,.0f}",
             "Status": ledger_map[i.invoice_id].status.value} for i in invoices]
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

with st.expander("🧹 Start over completely"):
    st.caption("Clears commitments and sample state. Keeps live-email markers so old inbox messages are not re-fetched.")
    if st.button("Clear All Data", key="btn_reset"):
        resp = api_post("/dev/reset-demo-data", timeout=15)
        if resp not in (None, "TIMEOUT") and resp.status_code == 200:
            body = resp.json()
            st.success(
                f"Cleared. Pending = {body.get('pending_count', 0)}. "
                f"Preserved {body.get('preserved_live_markers', 0)} live email marker(s). Run Step 1 again."
            )
            st.session_state.pop("step1_result", None)
        else:
            st.error("Could not clear data — check the backend is running.")

# ============================================================================
# STEP 2 — REVIEW & APPROVE
# ============================================================================
locked = len(pending) == 0 and recovery["total_items"] == 0
st.markdown(f'<div class="step-header"><div class="step-number {"locked" if locked else ""}">2</div><div class="step-title">Review and approve each one</div></div>', unsafe_allow_html=True)
st.markdown('<div class="step-sub">Nothing has happened yet — you decide. Approving will also draft a reply email (Step 3).</div>', unsafe_allow_html=True)

if locked:
    st.info("Complete Step 1 above first.")
elif not pending:
    st.markdown('<div class="banner-ok">✅ All caught up — nothing waiting for review right now.</div>', unsafe_allow_html=True)
else:
    # Show only the most recent item per invoice — if the same invoice appears from
    # two different emails, that's real data, but showing both as separate cards is confusing.
    seen_invoices = {}
    for item in pending:
        inv_id = item["commitment"]["invoice_id"]
        if inv_id not in seen_invoices:
            seen_invoices[inv_id] = item
    deduped_pending = list(seen_invoices.values())

    if len(deduped_pending) < len(pending):
        st.caption(f"ℹ️ {len(pending) - len(deduped_pending)} additional message(s) for an invoice "
                  f"already shown above were grouped together — showing the most recent one per invoice.")

    for item in deduped_pending:
        css, pill, label = ACTION_STYLE.get(item["action"], ("none", "pill-gray", item["action"]))
        commitment = item["commitment"]

        live_tag = '&nbsp;·&nbsp;<span class="pill pill-blue">📬 Live</span>' if commitment.get('source') == 'live' else ''
        st.markdown(f"""
        <div class="card {css}">
            <span class="pill {pill}">{label}</span> &nbsp; <b>Invoice {commitment['invoice_id']}</b>
            &nbsp;·&nbsp;<span style="color:#94A3B8">{commitment['email_id']}</span>{live_tag}
        </div>
        """, unsafe_allow_html=True)

        with st.expander("See why"):
            raw_email = _SAMPLE_EMAIL_LOOKUP.get(commitment["email_id"])
            relevant = _relevant_sentence(raw_email.body, commitment) if raw_email else None

            st.markdown(f"**Invoice:** {commitment['invoice_id']}  \n**Email:** {commitment['email_id']}")

            st.markdown("**Customer email:**")
            if raw_email:
                st.text(raw_email.body)
                if relevant:
                    st.caption(f"Exact relevant sentence: “{relevant}”")
            elif commitment.get("source") == "live":
                st.info("Live email — original body is not stored in the dashboard (privacy). Review uses the extracted fields below.")
            else:
                st.info("Original email text is not available for this item.")

            st.markdown("**System finding:**")
            st.write(_system_finding(commitment, item))

            st.markdown("**What the system extracted:**")
            amount_txt = (
                f"₹{commitment['promised_amount']:,.2f}"
                if commitment.get("promised_amount") is not None
                else "Not found"
            )
            extracted_lines = [
                f"• Commitment detected: {'Yes' if commitment.get('has_commitment') else 'No'}",
                f"• Amount: {amount_txt}",
                f"• Date phrase: {(commitment.get('raw_date_phrase') or 'Not found')}",
                f"• Resolved date: {(commitment.get('resolved_date') or 'Not resolved')}",
                f"• Claims already paid: {'Yes' if commitment.get('claims_already_paid') else 'No'}",
                f"• AI confidence: {commitment.get('confidence', 0):.0%}",
            ]
            st.markdown("\n".join(extracted_lines))

            st.markdown("**Ledger:**")
            st.write(
                f"Payment status: {item['ledger_status'].title()}  \n"
                f"Recorded as paid: ₹{item['amount_settled']:,.2f}  \n"
                f"Still owed vs promise: ₹{item['amount_shortfall']:,.2f}"
            )

            st.markdown("**Why review is required:**")
            st.write(item["reasoning"])

            st.markdown("**Human decision:**")
            st.write(_human_decision_prompt(item, commitment))

            if commitment.get("claims_already_paid"):
                st.warning("⚠️ Customer says they already paid — verified against our records above.")
            st.progress(commitment["confidence"])
            st.caption(f"AI confidence: {commitment['confidence']:.0%}")

            b1, b2, _ = st.columns([1, 1, 2])
            with b1:
                if st.button("✅ Approve", key=f"a{item['id']}"):
                    r = api_post(f"/commitments/{item['id']}/approve", {"approved_by": "user", "decision": "APPROVED"})
                    if r not in (None, "TIMEOUT") and r.status_code == 200:
                        st.toast("Approved! Check Step 3 for the drafted reply.", icon="✅")
                        st.rerun()
                    else:
                        st.error("Could not approve — try again.")
            with b2:
                if st.button("❌ Reject", key=f"r{item['id']}"):
                    r = api_post(f"/commitments/{item['id']}/approve", {"approved_by": "user", "decision": "REJECTED"})
                    if r not in (None, "TIMEOUT") and r.status_code == 200:
                        st.toast("Rejected.", icon="❌")
                        st.rerun()
                    else:
                        st.error("Could not reject — try again.")

# ============================================================================
# STEP 3 — AUTO-DRAFTED REPLIES
# ============================================================================
locked = len(drafts) == 0
st.markdown(f'<div class="step-header"><div class="step-number {"locked" if locked else ""}">3</div><div class="step-title">Send the reply</div></div>', unsafe_allow_html=True)
st.markdown('<div class="step-sub">Every approval drafts a professional reply automatically. Nothing sends without you clicking.</div>', unsafe_allow_html=True)

if locked:
    st.info("Approve an item in Step 2 to see a drafted reply appear here.")
else:
    for d in drafts:
        method_pill = 'pill-blue' if d['generation_method'] == 'AI_DRAFTED' else 'pill-gray'
        method_label = '🤖 AI Drafted' if d['generation_method'] == 'AI_DRAFTED' else '📋 Template'
        st.markdown(f"""
        <div class="card wait">
            <b>To:</b> {d['recipient_name'] or 'Customer'} ({d['recipient_email'] or 'no address on file'})
            &nbsp;·&nbsp; Invoice {d['invoice_id']}
            &nbsp;·&nbsp;<span class="pill {method_pill}">{method_label}</span>
        </div>
        """, unsafe_allow_html=True)

        with st.expander(f"Preview: {d['subject']}"):
            st.markdown(f'<div class="draft-box"><b>Subject:</b> {html.escape(d["subject"])}\n\n{html.escape(d["body"])}</div>', unsafe_allow_html=True)
            if d["source"] == "stored":
                st.caption("⚠️ This came from a sample email with a fake address — use Copy, not Send.")

            st.code(f"{d['subject']}\n\n{d['body']}", language=None)
            if st.button("📤 Send Email Now", key=f"send{d['id']}"):
                r = api_post(f"/drafts/{d['id']}/send", timeout=20)
                if r not in (None, "TIMEOUT") and r.status_code == 200:
                    st.success("Sent!")
                    st.rerun()
                elif r not in (None, "TIMEOUT"):
                    st.error(r.json().get("detail", "Could not send."))
                else:
                    st.error("Could not reach the backend.")

# ============================================================================
# STEP 4 — PRIVACY CHECK
# ============================================================================
chain = api_get("/audit/chain") or []
redacted_map = {}
for e in chain:
    if e["event_type"] == "PII_REDACTED":
        p = json.loads(e["payload_json"])
        redacted_map[p["email_id"]] = p

locked = len(redacted_map) == 0
st.markdown(f'<div class="step-header"><div class="step-number {"locked" if locked else ""}">4</div><div class="step-title">See how personal details are protected</div></div>', unsafe_allow_html=True)
st.markdown('<div class="step-sub">Names, phone numbers, and ID numbers are removed before the AI ever reads the email.</div>', unsafe_allow_html=True)

if locked:
    st.info("Complete Step 1 above first.")
else:
    from data.mock_emails import get_mock_emails
    lookup = {e.email_id: e for e in get_mock_emails()}
    choice = st.selectbox("Pick an email:", options=list(redacted_map.keys()), key="privacy_pick")

    col1, col2 = st.columns(2)
    with col1:
        st.markdown("**📄 Original**")
        raw = lookup.get(choice)
        if raw:
            st.markdown(f'<div class="redact-box">{render_redacted(raw.body)}</div>', unsafe_allow_html=True)
        else:
            st.markdown('<div class="redact-box">(Live email — original not stored, for privacy.)</div>', unsafe_allow_html=True)
    with col2:
        st.markdown("**🛡️ What AI Sees**")
        st.markdown(f'<div class="redact-box">{render_redacted(redacted_map[choice]["redacted_text"])}</div>', unsafe_allow_html=True)

# ============================================================================
# STEP 5 — TAMPER-PROOF CHECK
# ============================================================================
st.markdown('<div class="step-header"><div class="step-number">5</div><div class="step-title">Prove nothing can be secretly changed</div></div>', unsafe_allow_html=True)
st.markdown('<div class="step-sub">Every action is permanently recorded. Try to break it, then watch it get caught.</div>', unsafe_allow_html=True)

b1, b2, b3 = st.columns(3)
with b1:
    if st.button("🔍 Check Everything", key="btn_verify"):
        st.session_state["verify"] = api_get("/audit/verify")
with b2:
    if st.button("🧪 Try To Break It", key="btn_tamper"):
        api_post("/audit/tamper-demo")
        st.toast("A record was just secretly altered!", icon="🧪")
with b3:
    if st.button("♻️ Undo & Fix It", key="btn_restore"):
        r = api_post("/audit/restore-demo")
        if r not in (None, "TIMEOUT") and r.json().get("restored"):
            st.toast("Restored.", icon="♻️")
            st.session_state.pop("verify", None)
        else:
            st.info("Nothing to restore right now.")

if "verify" in st.session_state and st.session_state["verify"]:
    v = st.session_state["verify"]
    if v.get("valid"):
        st.markdown(f'<div class="banner-ok">✅ All clear! Checked {v.get("total_events")} records.</div>', unsafe_allow_html=True)
    else:
        st.markdown(f'<div class="banner-bad">🚨 Tampering detected at record #{v["broken_at_id"]}. Click "Undo & Fix It".</div>', unsafe_allow_html=True)

st.markdown("---")
st.caption("Read emails → verify against real records → human approves → reply drafted automatically → everything tamper-proof.")