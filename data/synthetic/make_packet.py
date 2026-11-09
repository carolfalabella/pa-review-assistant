"""Build the synthetic prior authorization packets.

SYNTHETIC DATA ONLY. Every name, ID, date, and clinical detail is invented.

One base packet plus two evaluation variants. Each variant changes only the
pages it needs, so a result difference points at one cause.

  case_001            golden demo case   C1 met, C2 met,     C3 not met, C4 missing
  case_002_missing    PT dates removed   C1 met, C2 missing, C3 not met, C4 missing
  case_003_not_met    PT succeeded       C1 met, C2 not met, C3 not met, C4 missing

Run:  python data/synthetic/make_packet.py
"""

from pathlib import Path

from reportlab import rl_config
from reportlab.lib import colors
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

# Byte-identical output on every rebuild (no creation date or random ID), so
# the packet's hash stays stable and saved runs keep matching their packet.
rl_config.invariant = 1

HERE = Path(__file__).parent
TOTAL_PAGES = 8
BANNER = "SYNTHETIC TEST DATA - NOT A REAL PATIENT"

styles = getSampleStyleSheet()
H1 = ParagraphStyle("H1", parent=styles["Heading1"], fontSize=15, spaceAfter=6)
H2 = ParagraphStyle("H2", parent=styles["Heading2"], fontSize=12, spaceBefore=8, spaceAfter=4)
BODY = ParagraphStyle("Body", parent=styles["BodyText"], fontSize=10.5, leading=14, spaceAfter=6)

# ---------------------------------------------------------------------------
# Text that differs between variants. Everything else is shared.
# ---------------------------------------------------------------------------
BASE = {
    "letter_conservative": (
        "The patient has failed conservative management and continues to have pain. "
        "Please see the attached records for details."
    ),
    "hpi_radiation": (
        "Since early August 2026 the pain radiates from the right buttock down the lateral "
        "thigh and calf to the top of the right foot, with intermittent numbness of the right great toe."
    ),
    "hpi_pt": (
        "The patient completed a course of physical therapy and continues ibuprofen. "
        "Current pain is 6 out of 10 and worse with prolonged sitting."
    ),
    "exam_slr": "Straight-leg raise is positive on the right at 40 degrees and negative on the left.",
    "assessment_1": (
        "1. Lumbar radiculopathy in a right L5 distribution (M54.16), persistent despite "
        "physical therapy and NSAIDs."
    ),
    "plan_reason": None,
    "pt_episode": "Dates of care: 08/24/2026 to 10/16/2026. Total visits: 12.",
    "pt_col_initial": "Initial (08/24/2026)",
    "pt_col_discharge": "Discharge (10/16/2026)",
    "pt_rows": [
        ["Pain, numeric rating scale", "7/10", "6/10"],
        ["Oswestry Disability Index", "46%", "42%"],
        ["Right straight-leg raise", "35 degrees", "40 degrees"],
    ],
    "pt_assessment": [
        "The patient demonstrated minimal improvement in pain and function over the episode of care.",
        "Radicular symptoms in the right lower extremity persist.",
        "The minimal clinically important difference was not reached on the Oswestry Disability Index.",
    ],
    "pt_discharge": (
        "Discharged because progress plateaued. The patient is independent with the home "
        "exercise program and was referred back to the physician."
    ),
    "pt_signature": "Signed: Jamie Cole, PT, DPT, 10/16/2026",
}

VARIANTS = {
    "case_001": {},
    # Variant B: the PT summary no longer says when or how long therapy ran.
    # The only duration left is the page 8 PLAN for 6 to 8 weeks, which is
    # not proof of delivered treatment. Expect C2a missing, so C2 missing.
    "case_002_missing": {
        "pt_episode": "Episode of care completed. See interventions below.",
        "pt_col_initial": "Initial",
        "pt_col_discharge": "Discharge",
        "pt_signature": "Signed: Jamie Cole, PT, DPT",
    },
    # Variant C: therapy worked, and every document agrees. The physician
    # orders the MRI anyway. Expect C2d not met, so C2 not met.
    "case_003_not_met": {
        "letter_conservative": (
            "The patient has completed conservative management and continues to have "
            "intermittent symptoms. Please see the attached records for details."
        ),
        "hpi_radiation": (
            "From early August 2026 the pain radiated from the right buttock down the lateral "
            "thigh and calf to the top of the right foot, with intermittent numbness of the right great toe."
        ),
        "hpi_pt": (
            "The patient completed a course of physical therapy with substantial improvement. "
            "Current pain is 2 out of 10, with occasional tingling in the right foot."
        ),
        "exam_slr": "Straight-leg raise is negative bilaterally.",
        "assessment_1": (
            "1. Lumbar radiculopathy in a right L5 distribution (M54.16), substantially improved "
            "after physical therapy."
        ),
        "plan_reason": "The patient asks for imaging to understand the cause of the symptoms.",
        "pt_rows": [
            ["Pain, numeric rating scale", "7/10", "2/10"],
            ["Oswestry Disability Index", "46%", "14%"],
            ["Right straight-leg raise", "35 degrees", "Negative"],
        ],
        "pt_assessment": [
            "The patient demonstrated substantial improvement in pain and function over the episode of care.",
            "Radicular symptoms in the right lower extremity have largely resolved.",
            "The minimal clinically important difference was exceeded on the Oswestry Disability Index.",
        ],
        "pt_discharge": (
            "Discharged because treatment goals were met. The patient is independent with the "
            "home exercise program."
        ),
    },
}


def footer(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica-Bold", 8)
    canvas.setFillColor(colors.HexColor("#B00020"))
    canvas.drawString(0.75 * inch, 0.5 * inch, BANNER)
    canvas.setFillColor(colors.black)
    canvas.setFont("Helvetica", 8)
    canvas.drawRightString(
        LETTER[0] - 0.75 * inch, 0.5 * inch, f"Packet page {doc.page} of {TOTAL_PAGES}"
    )
    canvas.restoreState()


def p(text, style=BODY):
    return Paragraph(text, style)


def grid(rows, widths, header=False):
    t = Table(rows, colWidths=widths)
    style = [
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]
    style.append(("FONTNAME", (0, 0), (-1, 0) if header else (0, -1), "Helvetica-Bold"))
    t.setStyle(TableStyle(style))
    return t


def build_story(v):
    s = []

    # Page 1: request form
    s += [
        p("Prior Authorization Request Form", H1),
        p("Synthetic Medicare Advantage Plan - Utilization Management Department"),
        grid(
            [
                ["Date submitted", "11/02/2026"],
                ["Request type", "Standard (non-urgent), pre-service"],
                ["Member name", "Alex Q. Sample"],
                ["Date of birth", "03/15/1958"],
                ["Member ID", "SYN-MA-0001234"],
                ["Requesting provider", "Morgan Ellis, MD, Riverbend Family Medicine"],
                ["Provider NPI", "1000000000 (synthetic)"],
                ["Requested service", "MRI lumbar spine without contrast"],
                ["CPT code", "72148, 1 unit"],
                ["Diagnosis", "M54.16 Radiculopathy, lumbar region"],
                ["Servicing facility", "Lakeview Imaging Center (synthetic)"],
            ],
            [2.0 * inch, 4.6 * inch],
        ),
        Spacer(1, 10),
        p("Attachments", H2),
        p("Letter of medical necessity (page 2)"),
        p("Office visit note, 10/28/2026 (pages 3-5)"),
        p("Physical therapy discharge summary (pages 6-7)"),
        p("Office visit note, 08/20/2026 (page 8)"),
        PageBreak(),
    ]

    # Page 2: letter of medical necessity
    s += [
        p("Riverbend Family Medicine", H1),
        p("November 2, 2026"),
        p("To: Utilization Management, Synthetic Medicare Advantage Plan"),
        p("Re: Alex Q. Sample, Member ID SYN-MA-0001234"),
        Spacer(1, 6),
        p("Letter of Medical Necessity", H2),
        p(
            "I am requesting authorization for an MRI of the lumbar spine without contrast "
            "for my patient, Alex Q. Sample, who has lumbar radiculopathy."
        ),
        p(v["letter_conservative"]),
        p("I believe this study is medically necessary for further evaluation."),
        Spacer(1, 12),
        p("Sincerely,"),
        p("Morgan Ellis, MD"),
        p("Riverbend Family Medicine"),
        PageBreak(),
    ]

    # Page 3: office note 10/28, history
    s += [
        p("Office Visit Note", H1),
        p("Riverbend Family Medicine. Date of service: 10/28/2026. Provider: Morgan Ellis, MD."),
        p("Patient: Alex Q. Sample. Age: 68."),
        p("Chief complaint", H2),
        p("Low back pain radiating to the right leg."),
        p("History of present illness", H2),
        p("The patient reports low back pain that began in the spring of 2026. " + v["hpi_radiation"]),
        p(v["hpi_pt"]),
        p("Past medical history", H2),
        p("Hypertension. Hyperlipidemia."),
        p("Imaging history", H2),
        p(
            "Lumbar spine MRI without contrast on 06/18/2026 at Lakeview Imaging Center showed "
            "a mild L4-L5 disc bulge without significant canal stenosis. The report is not attached."
        ),
        p("Red flag review", H2),
        p(
            "The patient denies bowel or bladder changes, saddle anesthesia, fever, unexplained "
            "weight loss, history of cancer, or recent trauma. No red flags identified."
        ),
        PageBreak(),
    ]

    # Page 4: office note 10/28, exam
    s += [
        p("Office Visit Note, continued (10/28/2026)", H1),
        p("Medications", H2),
        p("Lisinopril 10 mg daily. Atorvastatin 20 mg daily. Ibuprofen 600 mg up to three times daily with food."),
        p("Allergies", H2),
        p("No known drug allergies."),
        p("Vital signs", H2),
        p("Blood pressure 132/78. Heart rate 72. Temperature 98.4 F. BMI 27.1."),
        p("Physical examination", H2),
        p("Tenderness of the right lumbar paraspinal muscles at L4-L5."),
        p(v["exam_slr"]),
        p(
            "Strength is 4+/5 for right great toe extension, unchanged since 08/20/2026, "
            "and 5/5 elsewhere in both lower extremities."
        ),
        p("Light touch sensation is decreased over the top of the right foot."),
        p("Reflexes are 2+ and symmetric at the knees and ankles. Gait is mildly antalgic."),
        PageBreak(),
    ]

    # Page 5: office note 10/28, assessment and plan
    plan = []
    if v["plan_reason"]:
        plan.append(p(v["plan_reason"]))
    plan += [
        p("Order MRI lumbar spine without contrast."),
        p("Continue the home exercise program and ibuprofen as needed."),
        p("Follow up in 3 weeks."),
    ]
    s += [
        p("Office Visit Note, continued (10/28/2026)", H1),
        p("Assessment", H2),
        p(v["assessment_1"]),
        p("2. Hypertension, controlled."),
        p("Plan", H2),
        *plan,
        Spacer(1, 12),
        p("Electronically signed: Morgan Ellis, MD, 10/28/2026"),
        PageBreak(),
    ]

    # Page 6: PT discharge summary
    s += [
        p("Physical Therapy Discharge Summary", H1),
        p("Riverbend Physical Therapy (synthetic). Therapist: Jamie Cole, PT, DPT."),
        p("Patient: Alex Q. Sample. Referring provider: Morgan Ellis, MD."),
        p("Referral diagnosis: lumbar radiculopathy, right."),
        p("Episode of care", H2),
        p(v["pt_episode"]),
        p("Interventions", H2),
        p("Therapeutic exercise including core stabilization and directional preference exercises."),
        p("Neural mobilization (nerve glides) for the right lower extremity."),
        p("Manual therapy to the lumbar spine."),
        p("Home exercise program issued at the first visit and progressed through the episode."),
        PageBreak(),
    ]

    # Page 7: PT outcomes and assessment
    s += [
        p("Physical Therapy Discharge Summary, continued", H1),
        p("Outcome measures", H2),
        grid(
            [["Measure", v["pt_col_initial"], v["pt_col_discharge"]], *v["pt_rows"]],
            [2.4 * inch, 2.0 * inch, 2.2 * inch],
            header=True,
        ),
        Spacer(1, 8),
        p("Assessment", H2),
        *[p(line) for line in v["pt_assessment"]],
        p("Discharge", H2),
        p(v["pt_discharge"]),
        p(v["pt_signature"]),
        PageBreak(),
    ]

    # Page 8: earlier office note 08/20. Weakness documented here too, so the
    # deficit on page 4 is stable, not progressive (a progressive deficit
    # would be a red flag and contradict page 3).
    s += [
        p("Office Visit Note", H1),
        p("Riverbend Family Medicine. Date of service: 08/20/2026. Provider: Morgan Ellis, MD."),
        p("History of present illness", H2),
        p(
            "The patient strained the low back in May 2026 and was seen at urgent care. "
            "A lumbar MRI was obtained in June 2026 and the back pain later improved."
        ),
        p(
            "About two weeks ago new right leg pain began, radiating below the knee, "
            "with tingling in the right foot."
        ),
        p("Examination", H2),
        p("Straight-leg raise is positive on the right at 35 degrees."),
        p("Strength is 4+/5 for right great toe extension and 5/5 elsewhere. Reflexes are normal."),
        p("Assessment and plan", H2),
        p("Right lumbar radiculopathy, new onset."),
        p("Referral to physical therapy, 2 visits per week for 6 to 8 weeks."),
        p("Ibuprofen 600 mg up to three times daily with food."),
        p("Will reassess after physical therapy."),
        p("Electronically signed: Morgan Ellis, MD, 08/20/2026"),
    ]
    return s


def build(case_id: str) -> Path:
    v = {**BASE, **VARIANTS[case_id]}
    out = HERE / f"{case_id}.pdf"
    doc = SimpleDocTemplate(
        str(out),
        pagesize=LETTER,
        title=f"{case_id} synthetic prior authorization packet",
        author="Synthetic test data",
        leftMargin=0.75 * inch,
        rightMargin=0.75 * inch,
        topMargin=0.75 * inch,
        bottomMargin=0.9 * inch,
    )
    doc.build(build_story(v), onFirstPage=footer, onLaterPages=footer)
    return out


def main():
    for case_id in VARIANTS:
        print(f"Wrote {build(case_id)}")


if __name__ == "__main__":
    main()
