"""Nurse view for the prior authorization review demo.

    streamlit run app.py

SYNTHETIC DATA ONLY. Criteria are illustrative. AI prepares the case; a
licensed clinician decides. There is no deny or partial-approval action.
"""

from __future__ import annotations

import json

import streamlit as st

from src.app_support import (FIELD_LABEL, STATUS_COLOR, STATUS_LABEL, STATUS_MEANING, LiveJob,
                             find_saved_run, format_hours, highlight_html)
from src.audit import AuditLog, verify_chain
from src.config import ROOT, load_settings
from src.criteria import load_criteria
from src.pipeline import run_case
from src.prompts import PROMPT_VERSION
from src.review import (CASE_ACTION_LABELS, ReviewError, approve_blockers, case_action,
                        draft_information_request, review_from_status)
from src.schemas import STATUSES

FALLBACK_AFTER = 45  # seconds before the "Use saved run" button appears
DATA = ROOT / "data" / "synthetic"
CASES = {
    "case_001": "Demo packet (case_001)",
    "case_002_missing": "Evaluation: PT dates removed",
    "case_003_not_met": "Evaluation: therapy worked",
}

st.set_page_config(page_title="PA Review Assistant (synthetic demo)", layout="wide")

# Keep the source panel in view while the nurse scrolls the criteria.
# Streamlit has no "sticky" option, so this pins the one column that contains
# the .source-anchor marker. Both test IDs are listed because Streamlit renamed
# "column" to "stColumn" in newer versions. On narrow screens the columns stack
# and the panel scrolls normally.
st.markdown("""
<style>
div[data-testid="stHorizontalBlock"]:has(.source-anchor) { align-items: flex-start; }
div[data-testid="stColumn"]:has(.source-anchor),
div[data-testid="column"]:has(.source-anchor) {
    position: sticky;
    top: 4rem;
    max-height: calc(100vh - 5rem);
    overflow-y: auto;
    z-index: 2;
}
/* Citation lines (tertiary buttons): wrap long text instead of cutting it off with "...",
   align left, and sit closer together. Two selectors cover older and newer Streamlit. */
button[data-testid="stBaseButton-tertiary"], button[kind="tertiary"] {
    justify-content: flex-start; text-align: left; min-height: 0; padding: 0.1rem 0; height: auto;
}
button[data-testid="stBaseButton-tertiary"] *, button[kind="tertiary"] * {
    white-space: normal !important; overflow: visible !important; text-overflow: clip !important;
    text-align: left !important;
}
/* Reviewer form: amber while the nurse still needs to act, green once reviewed.
   The marker span inside the form decides which style applies. */
div[data-testid="stForm"]:has(.review-pending) {
    background: #FFF8E1; border: 2px solid #F59E0B; border-radius: 0.6rem; padding: 0.9rem 1rem;
}
div[data-testid="stForm"]:has(.review-done) {
    background: #FFFFFF; border: 1px solid #D1D5DB; border-radius: 0.6rem; padding: 0.9rem 1rem;
}
@media (max-width: 640px) {
    div[data-testid="stColumn"]:has(.source-anchor),
    div[data-testid="column"]:has(.source-anchor) { position: static; max-height: none; }
}
</style>
""", unsafe_allow_html=True)

settings = load_settings()
audit = AuditLog(settings.runs_dir / "audit.jsonl")
criteria = load_criteria()
ss = st.session_state
for key, default in {"result": None, "reviews": {}, "case_actions": [], "view": None,
                     "view_n": 0, "job": None, "job_case": None, "notice": None}.items():
    ss.setdefault(key, default)


def set_result(result: dict | None) -> None:
    ss.result, ss.reviews, ss.case_actions, ss.view, ss.job = result, {}, [], None, None


def run_saved(case_id: str) -> None:
    path = find_saved_run(settings.runs_dir / "saved", case_id, PROMPT_VERSION)
    if path is None:
        ss.notice = f"No saved run for {case_id} under prompt version {PROMPT_VERSION}."
        return
    saved = settings.with_(provider="saved", saved_run=path)
    set_result(run_case(DATA / f"{case_id}.pdf", saved, audit=audit))


# ------------------------------------------------------------------ sidebar
with st.sidebar:
    st.header("Case")
    busy = ss.job is not None
    case_id = st.selectbox("Packet", list(CASES), format_func=CASES.get, disabled=busy)
    mode = st.radio("Model", ["Live: Gemini", "Saved run"], disabled=busy,
                    help="Saved run replays a recorded Gemini response. Quote checks still run live.")
    if st.button("Run review", type="primary", disabled=busy):
        ss.notice = None
        if mode.startswith("Live"):
            set_result(None)
            ss.job = LiveJob(DATA / f"{case_id}.pdf", settings.with_(provider="gemini"), audit).start()
            ss.job_case = case_id
        else:
            run_saved(case_id)
        st.rerun()
    if st.button("Clear", disabled=busy):
        set_result(None)
        st.rerun()
    st.divider()
    st.caption(f"Live model: `{settings.gemini_model}` (Gemini API)")
    st.caption(f"Prompt version: `{PROMPT_VERSION}`")
    st.caption(f"Criteria: `{criteria['criteria_set_id']}@{criteria['version']}`")
    st.caption("Synthetic data only. Never send real patient data to this demo.")

# ------------------------------------------------------------------- header
st.title("Prior Authorization Review Assistant")
st.info(
    "**Synthetic data only.** Criteria are illustrative: not a coverage policy, MCG, or InterQual "
    "content, and not clinically validated. **AI prepares the case; a licensed clinician decides.** "
    "There is no deny or partial-approval action."
)
if ss.notice:
    st.error(ss.notice)


# --------------------------------------------------------------- live run
@st.fragment(run_every=1.0)
def live_monitor() -> None:
    job = ss.get("job")
    if job is None:
        return
    if job.done():
        if job.error:
            ss.notice = f"The run stopped unexpectedly: {job.error}"
            ss.job = None
        else:
            set_result(job.result)
        st.rerun()
    elapsed = job.elapsed()
    with st.status(f"Running live on {settings.gemini_model}: {elapsed:.0f}s", expanded=True):
        st.write("Two model calls run in parallel: extract the clinical details, and check the four rules.")
        for event in job.events:
            st.write(f"Busy response. {event}")
    if elapsed >= FALLBACK_AFTER:
        st.warning(f"The live model has taken more than {FALLBACK_AFTER} seconds.")
        if st.button("Use saved run instead", key="fallback"):
            case = ss.job_case
            ss.job = None  # the live thread finishes in the background and is still audited
            run_saved(case)
            st.rerun()


live_monitor()

r = ss.result
if r is None:
    if ss.job is None:
        st.write("Choose a packet and a model in the sidebar, then click **Run review**.")
    st.stop()

# ------------------------------------------------------------- run summary
if r["saved_run_label"]:
    st.warning(f"**{r['saved_run_label']}**")

d, dl = r["details"], r["deadline"]
c = st.columns(5)
c[0].metric("Member (synthetic)", d["member_id"])
c[1].metric("Requested service", f"CPT {d['cpt']}", help=d["service"])
c[2].metric("Diagnosis code", d["diagnosis_code"])
c[3].metric("Line of business", "MA · Standard", help="Medicare Advantage, standard pre-service request")
if dl.get("configured"):
    c[4].metric(f"Decision due ({dl['limit']})", format_hours(dl["remaining_hours"]), help=f"Due {dl['due_at']}")
else:
    c[4].metric("Decision due", "Not set", help=dl.get("problem"))
st.caption(f"Model `{r['provider']}/{r['model']}` · prompt `{r['prompt_version']}` · "
           f"criteria `{r['criteria_version']}` · run `{r['run_id']}` · {r['seconds']}s")

route = r["route"]
box = {"nurse_review_ai_failed": st.error, "nurse_review_needs_verification": st.warning}.get(route["queue"], st.info)
suggested = ", ".join(CASE_ACTION_LABELS[a] for a in route["suggested_actions"]) or "none; review the source"
box("**Routed to nurse review.** " + " ".join(route["reasons"]) + f"\n\n**Suggested next steps:** {suggested}")


def cite(page: int, quote: str, verified: bool, key: str) -> None:
    """One citation row: a button that opens the page, and the quote."""
    b, q = st.columns([1, 6])
    if b.button(f"{'✅' if verified else '❌'} p.{page}", key=key,
                help="Open this page with the quote highlighted"):
        ss.view = {"page": page, "quote": quote}
        ss.view_n += 1
    q.markdown(f"_{quote}_" + ("" if verified else "  \n:red[Not found on the cited page]"))


def cite_line(page: int, quote: str, verified: bool, text: str, key: str) -> None:
    """Compact citation: one clickable line with the summary. Hover shows the exact quote;
    click opens the page with the quote highlighted. No nested columns, so it can sit
    inside a column."""
    label = f"{'✅' if verified else '❌'} p.{page} · {text}"
    if not verified:
        label += " (quote not found on page)"
    if st.button(label, key=key, type="tertiary", help=f"Source quote: “{quote}”. Click to open the page."):
        ss.view = {"page": page, "quote": quote}
        ss.view_n += 1


left, right = st.columns([3, 2], gap="large")

with left:
    # --------------------------------------------------------- extraction
    st.subheader("1. Extracted clinical details")
    if r["extraction"] is None:
        st.warning("Extraction did not complete. Rule results below are still shown; review the source directly.")
    else:
        st.caption("Each line opens its source page with the quote highlighted. Hover to see the exact quote.")
        fields = list(FIELD_LABEL.items())
        for row in (fields[:2], fields[2:]):
            for col, (field, label) in zip(st.columns(2, gap="medium"), row):
                with col:
                    f = r["extraction"][field]
                    flag = "" if f["verified"] else " :red[(some quotes failed verification)]"
                    st.markdown(f"**{label}**{flag}")
                    if not f["items"]:
                        st.caption("Not found in the packet.")
                    for j, item in enumerate(f["items"]):
                        cite_line(item["page"], item["quote"], item["verified"], item["text"],
                                  key=f"x_{field}_{j}_{r['run_id']}")

    # ----------------------------------------------------------- rules
    st.subheader("2. Criteria check")
    st.caption("C1 to C4 are the four sample criteria; C1a, C1b, and so on are the parts of each. "
               + criteria["label"])
    if r["rules"] is None:
        st.error("No criteria results. The AI step failed, so nothing was marked met, not met, or missing. "
                 "Review the packet directly.")
    for rule in r["rules"] or []:
        with st.container(border=True):
            status = rule["status"]
            verified = ":green[Verified citations]" if rule["verified"] else ":violet[**Unverified: check the source**]"
            st.markdown(f"#### Criterion {rule['id']} · {rule['title']}")
            st.markdown(f":{STATUS_COLOR[status]}-background[**{STATUS_LABEL[status]}**] · {verified}")
            st.caption(STATUS_MEANING[status])
            for e in rule["elements"]:
                st.markdown(f"**{e['element_id']}** {e['text']}  \n"
                            f"→ :{STATUS_COLOR[e['status']]}[**{STATUS_LABEL[e['status']]}**]")
                if e["rationale"]:
                    st.caption(e["rationale"])
                for k, ev in enumerate(e["evidence"]):
                    cite(ev["page"], ev["quote"], ev["verified"], key=f"e_{e['element_id']}_{k}_{r['run_id']}")
                for problem in e["problems"]:
                    st.markdown(f":red[Check failed: {problem}]")

            fk = f"{rule['id']}_{r['run_id']}"
            reviewed = rule["id"] in ss.reviews
            with st.form(f"review_{fk}", border=False):
                if reviewed:
                    st.markdown(f'<span class="review-done"></span>**✅ Reviewed.** You can change your review '
                                f'of {rule["id"]} below; every change is kept in the audit record.',
                                unsafe_allow_html=True)
                else:
                    st.markdown(f'<span class="review-pending"></span>**✍️ Your review is needed.** Keep the AI '
                                f'result for {rule["id"]} to confirm it, or choose a different status and give '
                                f'a reason to override it.', unsafe_allow_html=True)
                # One control, so the form can't hold two answers that disagree. Starts at the
                # nurse's saved decision if there is one, otherwise at the AI's status.
                previous = ss.reviews.get(rule["id"])
                start = previous["final_status"] if previous else (rule["status"] or STATUSES[0])
                final_status = st.selectbox(
                    f"Your decision for {rule['id']} (AI result: {STATUS_LABEL[rule['status']]})",
                    STATUSES, index=STATUSES.index(start), key=f"to_{fk}", format_func=STATUS_LABEL.get)
                reason = st.text_input(
                    "Reason (required if your decision differs from the AI result, changes a saved review, "
                    "or confirms an unverified result)", key=f"why_{fk}")
                if st.form_submit_button("Save review", type="primary"):
                    try:
                        rec = review_from_status(rule, final_status, reason, previous=previous)
                    except ReviewError as exc:
                        st.error(str(exc))
                    else:
                        ss.reviews[rule["id"]] = rec
                        audit.append("rule_review", {"run_id": r["run_id"], "case_id": r["case_id"], **rec},
                                     actor=rec["actor"], role="nurse")
                        st.rerun()
            # Shown under the Save review button, so the confirmation appears where the nurse just clicked.
            rev = ss.reviews.get(rule["id"])
            if rev:
                verb = "Confirmed" if rev["action"] == "confirm" else "Overridden"
                st.success(f"{verb} by {rev['actor']}: **{STATUS_LABEL[rev['final_status']]}**"
                           + (f". Reason: {rev['reason']}" if rev["reason"] else ""))

    # ------------------------------------------------------- case action
    st.subheader("3. Case action")
    st.caption("Allowed: Approve, Request information, Refer to medical director. There is no deny or "
               "partial-approval action. Only a licensed clinician can make an adverse determination.")
    rules = r["rules"] or []

    def record(action: str, note: str = "") -> None:
        try:
            rec = case_action(rules, ss.reviews, action, note)
        except ReviewError as exc:
            st.error(str(exc))
            return
        ss.case_actions.append(rec)
        audit.append("case_action", {"run_id": r["run_id"], "case_id": r["case_id"], **rec},
                     actor=rec["actor"], role="nurse")
        st.rerun()

    t_approve, t_info, t_refer = st.tabs(["Approve", "Request information", "Refer to medical director"])
    with t_approve:
        blockers = approve_blockers(rules, ss.reviews)
        if blockers:
            st.markdown("Approve is unavailable until every criterion is reviewed and met:")
            for b in blockers:
                st.markdown(f"- {b}")
        if st.button("Approve", disabled=bool(blockers), key=f"approve_{r['run_id']}"):
            record("approve")
    with t_info:
        draft = draft_information_request(rules, criteria, d, ss.reviews)
        text = st.text_area("Draft request (edit before recording)", value=draft, height=240,
                            key=f"info_{r['run_id']}")
        if st.button("Record information request", key=f"info_btn_{r['run_id']}"):
            record("request_information", text)
    with t_refer:
        note = st.text_area("Reason for the medical director", key=f"refer_{r['run_id']}",
                            placeholder="Example: C3 not met. Lumbar MRI on 06/18/2026; radicular symptoms "
                                        "began after it, which may justify repeat imaging.")
        if st.button("Refer to medical director", key=f"refer_btn_{r['run_id']}"):
            record("refer_to_medical_director", note)

    for rec in ss.case_actions:
        st.success(f"Recorded: **{CASE_ACTION_LABELS[rec['action']]}** by {rec['actor']} at {rec['at']}"
                   + (f"  \n{rec['note']}" if rec["note"] and rec["action"] != "request_information" else ""))
    st.caption("In production, these actions update the plan's UM system, which stays the system of record. "
               "Letters are sent only after a person approves them.")

with right:
    # ------------------------------------------------------- source view
    st.markdown('<span class="source-anchor"></span>', unsafe_allow_html=True)
    st.subheader("Source packet")
    pages = r["pages"]
    numbers = sorted(pages)
    view = ss.view or {"page": numbers[0], "quote": None}
    page = st.selectbox("Page", numbers, index=numbers.index(view["page"]),
                        format_func=lambda p: f"Page {p} of {len(numbers)}", key=f"page_{ss.view_n}")
    quote = view["quote"] if page == view["page"] else None
    body, found = highlight_html(pages[page], quote)
    if quote and found:
        st.caption("Highlighted: the cited quote.")
    elif quote:
        st.error("The cited quote is not on this page. This citation failed verification.")
    # No fixed height here: the pinned column itself scrolls, so there is one scroll bar, not two.
    with st.container(border=True):
        st.markdown(f"<div style='font-size:0.92rem;line-height:1.5'>{body}</div>", unsafe_allow_html=True)

# --------------------------------------------------------- audit and raw
st.divider()
t_audit, t_raw, t_details, t_prod = st.tabs(["Audit record", "Raw model output", "Run details", "Demo vs production"])
with t_audit:
    ok, problems = verify_chain(audit.path)
    st.markdown("Audit chain integrity: " + (":green[**intact**]" if ok else f":red[**broken**: {'; '.join(problems[:3])}]"))
    for rec in audit.records(r["run_id"]):
        p = rec["payload"]
        st.markdown(f"**#{rec['seq']} {rec['event']}** · {rec['at']} · {rec['actor']} ({rec['role']})")
        if rec["event"] == "pipeline_run":
            st.json({"model": f"{p['provider']}/{p['model']}", "saved_run": p.get("saved_run_label"),
                     "prompt_version": p["prompt_version"], "criteria_version": p["criteria_version"],
                     "packet_sha256": p["packet_sha256"][:16] + "…",
                     "rules": {x["id"]: x["status"] for x in (p["rules"] or [])},
                     "route": p["route"]["queue"], "failures": p["call_failures"]})
        else:
            st.json({k: v for k, v in p.items() if k not in ("run_id", "rule_reviews")})
    st.caption("Each record stores the hash of the one before it, so a changed or deleted record is detected. "
               "This demo logs synthetic text; production logs metadata, not PHI.")
with t_raw:
    for name, raw in r["raw"].items():
        st.markdown(f"**{name}** call")
        try:
            st.json(json.loads(raw))
        except (TypeError, ValueError):
            st.code(raw or "(no output)")
with t_details:
    st.json(r["calls"])
    st.json({"route": r["route"], "deadline": r["deadline"], "details": r["details"]})
with t_prod:
    st.markdown(
        "| Step | This demo | Production |\n|---|---|---|\n"
        "| Intake | One local text PDF | Fax, portal, EDI 278, FHIR (Da Vinci PAS); receipt time saved at arrival |\n"
        "| Parsing | PDF text | OCR with a page-quality check; poor pages go to a person |\n"
        "| Member and clock | Fixed synthetic member, 7-day clock | Read-only query to the plan's core system; deadline table owned by Compliance |\n"
        "| Rules | Four illustrative rules in a JSON file | Versioned registry, exact lookup; licensed content stays under its license |\n"
        "| Model | Gemini API free tier, synthetic data only | Approved model in a private cloud boundary under BAAs; no training on PHI |\n"
        "| Guardrails | Schema check, quote check, rule rollup in code | Same, plus an evaluation set, drift monitoring, and calibrated escalation thresholds |\n"
        "| Decisions | Nurse actions in this page | Plan's UM system stays the system of record |\n"
        "| Audit | Local hash-chained file | Protected audit store feeding the plan's security monitoring; no PHI in logs |"
    )
