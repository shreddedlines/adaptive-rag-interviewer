"""
PDF report generator for interview sessions.
Uses ReportLab to produce a clean, branded A4 report.
"""
from __future__ import annotations

import io
from datetime import datetime
from typing import Any


def generate_pdf_report(summary: dict[str, Any], contact_email: str | None, contact_phone: str | None) -> bytes:
    """Returns raw PDF bytes for the given session summary."""
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import mm
        from reportlab.platypus import (
            SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
            HRFlowable, KeepTogether,
        )
        from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT
    except ImportError:
        raise RuntimeError("reportlab is not installed. Run: pip install reportlab")

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=20*mm, rightMargin=20*mm,
        topMargin=18*mm, bottomMargin=18*mm,
    )

    # ── Colour palette ────────────────────────────────────────────────────────
    DARK    = colors.HexColor("#0f172a")
    MID     = colors.HexColor("#475569")
    LIGHT   = colors.HexColor("#94a3b8")
    ACCENT  = colors.HexColor("#2563eb")
    GREEN   = colors.HexColor("#16a34a")
    ROSE    = colors.HexColor("#dc2626")
    AMBER   = colors.HexColor("#d97706")
    BG_CARD = colors.HexColor("#f8fafc")
    LINE    = colors.HexColor("#e2e8f0")

    W = A4[0] - 40*mm   # usable width

    # ── Styles ────────────────────────────────────────────────────────────────
    ss = getSampleStyleSheet()
    def S(name, **kw):
        return ParagraphStyle(name, **kw)

    title_s   = S("title",   fontSize=22, textColor=DARK,   fontName="Helvetica-Bold",   spaceAfter=2)
    sub_s     = S("sub",     fontSize=11, textColor=MID,    fontName="Helvetica",         spaceAfter=2)
    label_s   = S("label",   fontSize=8,  textColor=LIGHT,  fontName="Helvetica-Bold",    spaceAfter=1, leading=10)
    body_s    = S("body",    fontSize=10, textColor=DARK,   fontName="Helvetica",         spaceAfter=4, leading=14)
    bold_s    = S("bold",    fontSize=10, textColor=DARK,   fontName="Helvetica-Bold",    spaceAfter=3)
    small_s   = S("small",   fontSize=8,  textColor=MID,    fontName="Helvetica",         spaceAfter=2, leading=11)
    italic_s  = S("italic",  fontSize=9,  textColor=MID,    fontName="Helvetica-Oblique", spaceAfter=2, leading=12)
    q_s       = S("q",       fontSize=10, textColor=DARK,   fontName="Helvetica-Bold",    spaceAfter=4, leading=14)
    ans_s     = S("ans",     fontSize=9,  textColor=MID,    fontName="Helvetica",         spaceAfter=3, leading=13)
    fb_s      = S("fb",      fontSize=9,  textColor=DARK,   fontName="Helvetica-Oblique", spaceAfter=3, leading=13)
    chip_s    = S("chip",    fontSize=8,  textColor=GREEN,  fontName="Helvetica-Bold",    spaceAfter=1, leading=10)
    gap_s     = S("gap",     fontSize=8,  textColor=ROSE,   fontName="Helvetica-Bold",    spaceAfter=1, leading=10)

    insights  = summary.get("insights", {})
    questions = summary.get("questions", [])
    _avg_raw  = insights.get("average_score")
    avg       = round(float(_avg_raw)) if _avg_raw is not None else 0
    answered  = insights.get("questions_answered", 0)
    skipped   = insights.get("skipped_count", 0)
    rec       = insights.get("recommendation", "")
    name      = summary.get("candidate_name") or "Candidate"
    role      = summary.get("role", "").replace("-", " ").title()

    # Score colour
    score_color = GREEN if avg >= 75 else AMBER if avg >= 50 else ROSE
    verdict     = "Strong Candidate" if avg >= 75 else "Adequate" if avg >= 60 else "Needs Development" if avg >= 40 else "Not Recommended"

    story = []

    # ── HEADER ────────────────────────────────────────────────────────────────
    header_data = [[
        Paragraph(name, title_s),
        Paragraph(f"<font color='#{score_color.hexval()[2:]}' size=26><b>{avg}</b></font><br/><font size=8 color='#94a3b8'>/ 100</font>", S("sc", fontSize=10, textColor=DARK, fontName="Helvetica", alignment=TA_RIGHT)),
    ]]
    header_table = Table(header_data, colWidths=[W*0.75, W*0.25])
    header_table.setStyle(TableStyle([
        ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
        ("ALIGN",  (1,0), (1,0),  "RIGHT"),
        ("BOTTOMPADDING", (0,0), (-1,-1), 4),
    ]))
    story.append(header_table)
    story.append(Paragraph(role, sub_s))

    # Contact line
    contact_parts = []
    if contact_email: contact_parts.append(f"✉ {contact_email}")
    if contact_phone: contact_parts.append(f"✆ {contact_phone}")
    if contact_parts:
        story.append(Paragraph("   ·   ".join(contact_parts), S("ct", fontSize=9, textColor=ACCENT, fontName="Helvetica")))

    story.append(Paragraph(verdict, S("vd", fontSize=9, textColor=score_color, fontName="Helvetica-Bold", spaceAfter=8)))
    story.append(HRFlowable(width=W, color=LINE, thickness=1, spaceAfter=8))

    # ── STATS ROW ─────────────────────────────────────────────────────────────
    stats_data = [
        [Paragraph("ANSWERED", label_s),  Paragraph("SKIPPED", label_s),  Paragraph("OVERALL SCORE", label_s)],
        [Paragraph(str(answered), S("sv", fontSize=22, fontName="Helvetica-Bold", textColor=DARK)),
         Paragraph(str(skipped),  S("sv", fontSize=22, fontName="Helvetica-Bold", textColor=DARK)),
         Paragraph(f"{avg}%",     S("sv", fontSize=22, fontName="Helvetica-Bold", textColor=score_color))],
    ]
    stats_t = Table(stats_data, colWidths=[W/3]*3)
    stats_t.setStyle(TableStyle([
        ("ALIGN",         (0,0), (-1,-1), "LEFT"),
        ("VALIGN",        (0,0), (-1,-1), "MIDDLE"),
        ("TOPPADDING",    (0,0), (-1,-1), 6),
        ("BOTTOMPADDING", (0,0), (-1,-1), 6),
        ("LINEBELOW",     (0,0), (-1,0),  0.8, LINE),   # gray line under labels
    ]))
    story.append(stats_t)
    story.append(Spacer(1, 8))

    # ── RECOMMENDATION ────────────────────────────────────────────────────────
    if rec:
        rec_data = [[Paragraph("RECOMMENDATION", label_s)], [Paragraph(rec, body_s)]]
        rec_t = Table(rec_data, colWidths=[W])
        rec_t.setStyle(TableStyle([
            ("LEFTPADDING",   (0,0), (-1,-1), 0),
            ("RIGHTPADDING",  (0,0), (-1,-1), 0),
            ("TOPPADDING",    (0,0), (-1,-1), 4),
            ("BOTTOMPADDING", (0,0), (-1,-1), 4),
        ]))
        story.append(rec_t)
        story.append(Spacer(1, 12))

    # ── Q&A BREAKDOWN ─────────────────────────────────────────────────────────
    story.append(Paragraph("Question Breakdown", S("bh", fontSize=13, fontName="Helvetica-Bold", textColor=DARK, spaceAfter=6)))
    story.append(HRFlowable(width=W, color=LINE, thickness=1, spaceAfter=8))

    for i, item in enumerate(questions):
        analysis = item.get("analysis") or {}
        score    = analysis.get("score")
        level    = analysis.get("level", "skipped" if item.get("skipped") else "")
        feedback = analysis.get("feedback", "")
        strengths = analysis.get("strengths", [])
        gaps      = analysis.get("gaps", [])
        sc_color  = GREEN if (score or 0) >= 75 else AMBER if (score or 0) >= 50 else ROSE

        topic_tag = f"Q{i+1}  ·  {item.get('topic','').upper()}  ·  {item.get('difficulty','').upper()}"

        rows = []
        # Header row: topic tags + score
        score_str = f"{score}/100  {level.upper()}" if score is not None else "SKIPPED"
        rows.append([
            Paragraph(topic_tag, S("tag", fontSize=8, fontName="Helvetica-Bold", textColor=ACCENT)),
            Paragraph(score_str, S("sc2", fontSize=8, fontName="Helvetica-Bold", textColor=sc_color, alignment=TA_RIGHT)),
        ])
        # Question
        rows.append([Paragraph(item.get("question",""), q_s), ""])
        # Answer
        ans = item.get("answer") or "No answer recorded."
        rows.append([Paragraph(f"<i>Your answer:</i> {ans[:600]}{'…' if len(ans)>600 else ''}", ans_s), ""])
        # Feedback
        if feedback:
            rows.append([Paragraph(feedback, fb_s), ""])
        # Strengths
        if strengths:
            rows.append([Paragraph("✓ STRENGTHS: " + "   ·   ".join(strengths), chip_s), ""])
        # Gaps
        if gaps:
            rows.append([Paragraph("✗ GAPS: " + "   ·   ".join(gaps), gap_s), ""])

        # Merge second column for all rows except header
        card_t = Table(rows, colWidths=[W*0.78, W*0.22])
        style = [
            ("LEFTPADDING",   (0,0), (-1,-1), 0),
            ("RIGHTPADDING",  (0,0), (-1,-1), 0),
            ("TOPPADDING",    (0,0), (-1,-1), 4),
            ("BOTTOMPADDING", (0,0), (-1,-1), 4),
            ("VALIGN",        (0,0), (-1,-1), "TOP"),
            ("ALIGN",         (1,0), (1,0),   "RIGHT"),
        ]
        for r in range(1, len(rows)):
            style.append(("SPAN", (0,r), (1,r)))
        card_t.setStyle(TableStyle(style))

        story.append(KeepTogether([card_t, HRFlowable(width=W, color=LINE, thickness=0.5, spaceAfter=10)]))


    # ── FOOTER ────────────────────────────────────────────────────────────────
    story.append(Spacer(1, 10))
    story.append(HRFlowable(width=W, color=LINE, thickness=0.5))
    ts = datetime.utcnow().strftime("%d %b %Y, %H:%M UTC")
    story.append(Paragraph(f"Interview Report · Generated on {ts}", S("ft", fontSize=7, textColor=LIGHT, alignment=TA_CENTER)))

    doc.build(story)
    return buf.getvalue()
