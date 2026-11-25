"""ساخت گزارش Word (راست‌چین، فونت B Nazanin) برای هر تماس — مطابق قالب «گزارش پیاده‌سازی و تحلیل تماس»."""

import io

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Pt, RGBColor, Twips

FONT = "B Nazanin"
NAVY = RGBColor(0x1F, 0x4E, 0x78)
RED = RGBColor(0xC0, 0x00, 0x00)
BODY_PT = 15
TITLE_PT = 18
HEAD_PT = 16

ROLE_COLOR = {"کارشناس": NAVY, "مشتری": RED}
STATUS_FILL = {"رعایت شده": "E7F6EC", "رعایت نسبی": "FFF6E0", "رعایت نشده": "FDECEA", "قابل ارزیابی نیست": "EEF1F4"}


def _rtl_run(run, size=BODY_PT, bold=False, color=None):
    run.font.name = FONT
    run.font.size = Pt(size)
    run.font.bold = bold
    if color is not None:
        run.font.color.rgb = color
    rpr = run._element.get_or_add_rPr()
    fonts = rpr.find(qn("w:rFonts"))
    if fonts is None:
        fonts = OxmlElement("w:rFonts")
        rpr.insert(0, fonts)
    for attr in ("w:ascii", "w:hAnsi", "w:cs", "w:eastAsia"):
        fonts.set(qn(attr), FONT)
    for tag in ("w:bCs",) if bold else ():
        el = OxmlElement(tag)
        rpr.append(el)
    szcs = OxmlElement("w:szCs")
    szcs.set(qn("w:val"), str(int(size * 2)))
    rpr.append(szcs)
    rpr.append(OxmlElement("w:rtl"))
    return run


def _rtl_para(p, align=WD_ALIGN_PARAGRAPH.RIGHT, after=4, before=0, keep_next=False):
    ppr = p._element.get_or_add_pPr()
    ppr.insert(0, OxmlElement("w:bidi"))
    p.alignment = align
    p.paragraph_format.space_after = Pt(after)
    p.paragraph_format.space_before = Pt(before)
    p.paragraph_format.line_spacing = 1.15
    if keep_next:
        p.paragraph_format.keep_with_next = True
    return p


def _para(container, parts, **kw):
    """parts: لیست (متن، dict تنظیمات run)."""
    p = _rtl_para(container.add_paragraph(), **kw)
    for text, opts in parts:
        _rtl_run(p.add_run(text), **opts)
    return p


def _heading(doc, text):
    return _para(doc, [(text, {"size": HEAD_PT, "bold": True, "color": NAVY})], before=14, after=6, keep_next=True)


def _bullet(doc, label, text):
    parts = [("• ", {"bold": True})]
    if label:
        parts.append((label + ": ", {"bold": True}))
    parts.append((text, {}))
    return _para(doc, parts, after=4)


def _shade(cell, fill):
    tcpr = cell._element.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), fill)
    tcpr.append(shd)


def _table(doc, headers, rows, widths_twips, fills=None):
    """جدول راست‌به‌چپ: ستون اول در سمت راست قرار می‌گیرد."""
    t = doc.add_table(rows=1, cols=len(headers))
    t.style = "Table Grid"
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    tblpr = t._element.tblPr
    # ترتیب عناصر طبق استاندارد: bidiVisual بلافاصله بعد از tblStyle
    style_el = tblpr.find(qn("w:tblStyle"))
    bv = OxmlElement("w:bidiVisual")
    if style_el is not None:
        style_el.addnext(bv)
    else:
        tblpr.insert(0, bv)
    t.autofit = False
    for i, w in enumerate(widths_twips):
        t.columns[i].width = Twips(w)
    hdr = t.rows[0]
    trpr = hdr._tr.get_or_add_trPr()
    trpr.append(OxmlElement("w:tblHeader"))
    for i, h in enumerate(headers):
        c = hdr.cells[i]
        c.width = Twips(widths_twips[i])
        _shade(c, "1F4E78")
        p = c.paragraphs[0]
        _rtl_para(p, after=2)
        _rtl_run(p.add_run(h), size=BODY_PT - 1, bold=True, color=RGBColor(0xFF, 0xFF, 0xFF))
    for r_i, row in enumerate(rows):
        cells = t.add_row().cells
        for i, val in enumerate(row):
            c = cells[i]
            c.width = Twips(widths_twips[i])
            if fills and fills[r_i] and fills[r_i][i]:
                _shade(c, fills[r_i][i])
            lines = val if isinstance(val, list) else [val]
            first = True
            for line in lines:
                p = c.paragraphs[0] if first else c.add_paragraph()
                first = False
                _rtl_para(p, after=2)
                text, opts = line if isinstance(line, tuple) else (line, {})
                _rtl_run(p.add_run(text or "—"), size=BODY_PT - 1, **opts)
    for row in t.rows:
        row._tr.get_or_add_trPr().append(OxmlElement("w:cantSplit"))
    return t


def build_report(job: dict) -> bytes:
    an = job.get("analysis") or {}
    ev = job.get("evaluation")
    doc = Document()

    # تنظیمات پایه: حاشیه‌ها مثل نمونه (۰٫۷۵ اینچ)، سبک Normal راست‌چین با B Nazanin
    for s in doc.sections:
        s.top_margin = s.bottom_margin = s.left_margin = s.right_margin = Twips(1080)
    zoom = doc.settings.element.find(qn("w:zoom"))
    if zoom is not None and zoom.get(qn("w:percent")) is None:
        zoom.set(qn("w:percent"), "100")
    normal = doc.styles["Normal"]
    normal.font.name = FONT
    normal.font.size = Pt(BODY_PT)
    rpr = normal.element.get_or_add_rPr()
    fonts = rpr.find(qn("w:rFonts"))
    if fonts is None:
        fonts = OxmlElement("w:rFonts")
        rpr.insert(0, fonts)
    for attr in ("w:ascii", "w:hAnsi", "w:cs", "w:eastAsia"):
        fonts.set(qn(attr), FONT)

    title = an.get("report_title") or "گزارش پیاده‌سازی و تحلیل تماس"
    _para(doc, [(title, {"size": TITLE_PT, "bold": True, "color": NAVY})], align=WD_ALIGN_PARAGRAPH.CENTER, after=4)
    _para(doc, [(f"فایل: {job.get('filename', '')}", {"size": BODY_PT - 3, "color": RGBColor(0x6B, 0x77, 0x85)})],
          align=WD_ALIGN_PARAGRAPH.CENTER, after=10)

    # ۱. متن کامل
    _heading(doc, "۱. پیاده‌سازی متن کامل تماس و تفکیک گویندگان")
    turns = an.get("transcript") or []
    if turns:
        for t in turns:
            role = t.get("speaker") or "نامشخص"
            _para(doc, [(role + ": ", {"bold": True, "color": ROLE_COLOR.get(role, RGBColor(0x55, 0x55, 0x55))}),
                        (t.get("text", ""), {})], after=5)
    else:
        for line in (job.get("text") or "").split("\n"):
            if line.strip():
                _para(doc, [(line, {})], after=5)

    if an:
        # ۲. تفکیک
        _heading(doc, "۲. تفکیک مشتری و کارشناس")
        agent = an.get("agent_role") or "کارشناس"
        cust = an.get("customer_role") or "مشتری"
        _para(doc, [("در پیاده‌سازی فوق، نقش‌های مکالمه به صورت دقیق تفکیک شده‌اند: ", {}),
                    (agent, {"bold": True}), (" با رنگ سرمه‌ای و ", {}),
                    (cust, {"bold": True}), (" با رنگ قرمز و با برچسب‌های واضح در ابتدای هر عبارت مشخص گردیده‌اند.", {})])

        # ۳. مشکل
        _heading(doc, "۳. مشکل یا درخواست اصلی مشتری")
        mi = an.get("main_issue") or {}
        _bullet(doc, "موضوع اصلی", mi.get("topic", "—"))
        _bullet(doc, "شرح مشکل", mi.get("description", "—"))
        _bullet(doc, "سؤال مشتری", mi.get("customer_question", "—"))

        # ۴. راه حل
        _heading(doc, "۴. راه حل ارائه شده توسط کارشناس")
        sol = an.get("solution") or {}
        if sol.get("summary"):
            _para(doc, [(sol["summary"], {})], after=6)
        methods = sol.get("methods") or []
        if methods:
            rows = [[(f"{_fa(i)}. {m.get('method', '')}", {"bold": True}), m.get("details", "")] for i, m in enumerate(methods, 1)]
            rows = [[[r[0]], r[1]] for r in rows]
            _table(doc, ["روش / راهکار", "شرح نحوه اجرا و نتیجه"], rows, [3600, 6480])
        elif not sol.get("summary"):
            _para(doc, [("کارشناس راهکار مشخصی ارائه نکرد.", {})])

        # ۵. احساسات
        _heading(doc, "۵. تحلیل احساسات مشتری (Sentiment Analysis)")
        se = an.get("sentiment") or {}
        for key, label in (("start", "ابتدای تماس"), ("middle", "میانه تماس"), ("end", "پایان تماس")):
            part = se.get(key) or {}
            lab = f"{label} ({part['label']})" if part.get("label") else label
            _bullet(doc, lab, part.get("description", "—"))

    # ۶. ارزیابی
    if ev:
        _heading(doc, "۶. ارزیابی انطباق با استانداردهای پاسخگویی")
        _para(doc, [("امتیاز کلی: ", {"bold": True}), (f"{_fa(ev.get('overall_score', 0))} از ۱۰۰", {"bold": True, "color": NAVY}),
                    ("   |   نتیجه: ", {"bold": True}), (ev.get("verdict", ""), {"bold": True})])
        _para(doc, [(f"استاندارد مرجع: {job.get('standards_name', '')}", {"size": BODY_PT - 3, "color": RGBColor(0x6B, 0x77, 0x85)})])
        if ev.get("summary"):
            _para(doc, [(ev["summary"], {})], after=6)
        crit = ev.get("criteria") or []
        if crit:
            rows, fills = [], []
            for i, c in enumerate(crit, 1):
                detail = [c.get("comment") or "—"]
                if c.get("evidence"):
                    detail.append((f"«{c['evidence']}»", {"color": RGBColor(0x4A, 0x55, 0x63)}))
                rows.append([[f"{_fa(i)}. {c.get('title', '')}"], c.get("status", ""), detail])
                fills.append([None, STATUS_FILL.get(c.get("status")), None])
            _table(doc, ["معیار", "وضعیت", "توضیح و شاهد از متن"], rows, [3400, 1700, 4980], fills)
        for title_, key in (("موارد رعایت‌نشده", "violations"), ("نقاط قوت", "strengths"), ("پیشنهادهای بهبود", "recommendations")):
            items = ev.get(key) or []
            if items:
                _para(doc, [(title_, {"bold": True, "color": NAVY})], before=8, after=3, keep_next=True)
                for x in items:
                    _bullet(doc, "", x)

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def _fa(n) -> str:
    return str(n).translate(str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹"))
