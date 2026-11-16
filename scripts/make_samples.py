"""Build the demo documents in samples/ (a PDF handbook and a Word policy) with the standard library only.

Usage: python scripts/make_samples.py
The Markdown FAQ in samples/ is written by hand and not touched by this script.
"""
from __future__ import annotations

import zipfile
import zlib
from pathlib import Path
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parent.parent
SAMPLES = ROOT / "samples"

# --- PDF: Employee Handbook -------------------------------------------------------------------------

HANDBOOK = [
    [
        ("title", "Northwind Analytics"),
        ("subtitle", "Employee Handbook"),
        ("small", "Version 2026.1, effective 1 January 2026. Owned by the People team."),
        ("h1", "About this handbook"),
        ("p", "This handbook explains how we work together at Northwind Analytics Ltd, a reporting software company "
              "of about 60 people based in London, with colleagues across the UK and Europe. It covers working hours, "
              "time off, expenses, equipment and what to do when something goes wrong."),
        ("p", "The handbook is a guide, not a contract. Where your employment contract says something different, "
              "the contract applies. We review the handbook every January and announce changes in the company channel."),
        ("p", "Questions about anything in here go to the People team at people@northwind.test."),
    ],
    [
        ("h1", "1. Working hours and flexible time"),
        ("p", "Our standard working week is 37.5 hours, Monday to Friday. Core collaboration hours are 10:00 to 16:00 "
              "UK time, and we ask everyone to be reachable during that window. Outside core hours you can plan your "
              "day the way that suits you, as long as your team knows when you are around."),
        ("p", "Part-time arrangements are welcome. Agree your pattern with your manager, and the People team will "
              "update your contract within two weeks."),
        ("p", "Overtime is not expected. If a launch or an incident means you work more than 45 hours in a week, take "
              "the extra time back within the next month and record it in the HR system so your manager can see it."),
        ("h1", "2. Remote and hybrid work"),
        ("p", "Northwind is remote first. You can work from home, from our London office at 14 Clerkenwell Road, or "
              "from a coworking space that we pay for (see section 6)."),
        ("p", "Working from another country: you may work from abroad for up to 20 working days in any 12 month "
              "period. Ask your manager at least two weeks before you travel and tell IT through the service portal, "
              "because some countries need extra security settings on your laptop. Stays longer than 20 working days "
              "need approval from the People team, as they can affect tax and right to work rules."),
        ("p", "We meet in person for a company offsite twice a year. Travel and accommodation for offsites are booked "
              "and paid for centrally."),
    ],
    [
        ("h1", "3. Paid time off"),
        ("p", "Vacation allowance: full-time employees get 25 days of paid vacation per calendar year, plus UK bank "
              "holidays. Part-time allowances are calculated pro rata."),
        ("p", "Your first year: if you join during the year, your allowance for that year is prorated by the number of "
              "full months you work. For example, someone who starts on 1 April gets 18.75 days, rounded up to 19 days. "
              "During the first three months, which are your probation period, you can take up to 5 of those days."),
        ("p", "Long service: after three full years with Northwind you get 2 extra vacation days per year, and after "
              "five years you get 5 extra days per year."),
        ("p", "Carrying days over: you can carry up to 5 unused days into the next year. Carried days must be used by "
              "31 March, after which they expire. Unused days are not paid out, except when you leave the company."),
        ("p", "Booking time off: request time off in the HR system. For up to 3 days, give at least one week of "
              "notice. For longer breaks, give at least four weeks. Managers reply within three working days."),
        ("p", "Company closure: the company closes between 25 December and 1 January. These days do not count "
              "against your vacation allowance."),
    ],
    [
        ("h1", "4. Sick leave"),
        ("p", "If you are ill, tell your manager before 10:00 on the first day, by phone or chat, and record the "
              "absence in the HR system when you are back."),
        ("p", "You can self-certify for up to 7 calendar days. From the eighth day we need a fit note from a doctor."),
        ("p", "Northwind pays full salary for up to 15 working days of sick leave in any 12 month period. After that, "
              "Statutory Sick Pay applies. Longer or repeated absences are handled individually with the People team, "
              "and we always look at adjustments to your work first."),
        ("p", "Medical appointments: you do not need to use vacation days for short appointments. Let your team know "
              "and make up the time where that is reasonable."),
        ("p", "Mental health days count as sick leave. You do not need to give a reason beyond saying that you are "
              "unwell."),
        ("h1", "5. Family leave"),
        ("p", "Birth parents get 26 weeks of full pay followed by 13 weeks of statutory pay. Partners get 6 weeks of "
              "full pay, which can be taken in up to three blocks within the first year. Adoptive parents follow the "
              "same rules."),
        ("p", "You can take up to 5 days of paid compassionate leave when a close family member dies. More time can "
              "be agreed with your manager."),
    ],
    [
        ("h1", "6. Expenses and travel"),
        ("p", "Submit expense claims in the finance app within 30 days of spending the money. Approved claims are paid "
              "with the next monthly salary."),
        ("bullet", "Receipts: attach a receipt for every item over £25. For smaller items, a photo of the card "
                   "statement line is enough."),
        ("bullet", "Meals while travelling for work are covered up to £40 per day. Alcohol is not reimbursed, except "
                   "at team events approved in advance."),
        ("bullet", "Trains: book standard class. First class is allowed only when it is cheaper than standard on the day."),
        ("bullet", "Flights: book economy class for flights under 6 hours. For longer flights you can book premium "
                   "economy. Always book through the travel tool so we can reach you if plans change."),
        ("bullet", "Coworking: if you prefer not to work from home, Northwind pays up to £150 per month for a "
                   "coworking membership. Claim it as an expense each month."),
        ("bullet", "Mileage for using your own car on company business is paid at 45p per mile."),
        ("p", "Anything not covered here needs approval from your manager before you spend the money."),
    ],
    [
        ("h1", "7. Equipment and home office"),
        ("p", "Every employee gets a laptop (a MacBook Pro or a Windows laptop of their choice), a monitor and a "
              "headset. Laptops are replaced every three years, or sooner if they fail."),
        ("p", "Home office budget: when you join, you get a one-off budget of £300 to set up your workspace at home, "
              "for example for a chair, a desk or a keyboard. Items bought with the budget are yours to keep."),
        ("p", "Lost or stolen equipment: report it to IT straight away through the service portal or the IT helpline, "
              "and to the police if it was stolen. The IT Security Policy explains the steps in detail. You will not "
              "be charged for an honest loss."),
        ("p", "When you leave Northwind, return your laptop and monitor within 10 working days. We send prepaid "
              "packaging to your home."),
        ("h1", "8. Learning and development"),
        ("p", "Each employee has a learning budget of £1,000 per calendar year for courses, books, conferences and "
              "certifications, and up to 3 working days per year can be taken as learning days. Ask your manager "
              "before booking anything that costs more than £300."),
        ("p", "Unused learning budget does not carry over to the next year."),
    ],
    [
        ("h1", "9. Conduct and raising concerns"),
        ("p", "We expect everyone to treat colleagues, customers and partners with respect. Harassment, "
              "discrimination and bullying are not tolerated."),
        ("p", "If something worries you, talk to your manager or the People team. If you would rather stay "
              "anonymous, use the confidential speak-up form on the intranet. Reports are read by the Head of People "
              "and an external adviser, and nobody is ever penalised for raising a concern in good faith."),
        ("p", "Conflicts of interest, such as a side business or a close relationship with a supplier, must be "
              "declared to your manager in writing."),
        ("h1", "10. Leaving Northwind"),
        ("p", "The notice period is one month during probation and two months after it, unless your contract says "
              "otherwise. Remaining vacation days are paid out with your final salary."),
        ("p", "We hold a short exit conversation with everyone who leaves, so we can keep improving Northwind as a "
              "place to work."),
    ],
]

# Helvetica character widths (per 1000 units of font size) for the characters used here.
WIDTHS = dict(zip(
    " !\"#$%&'()*+,-./0123456789:;<=>?@ABCDEFGHIJKLMNOPQRSTUVWXYZ[\\]^_`abcdefghijklmnopqrstuvwxyz{|}~",
    [278, 278, 355, 556, 556, 889, 667, 191, 333, 333, 389, 584, 278, 333, 278, 278]
    + [556] * 10
    + [278, 278, 584, 584, 584, 556, 1015, 667, 667, 722, 722, 667, 611, 778, 722, 278, 500, 667, 556, 833,
       722, 778, 667, 778, 722, 667, 611, 722, 667, 944, 667, 667, 611, 278, 278, 278, 469, 556, 333, 556, 556,
       500, 556, 556, 278, 556, 556, 222, 222, 500, 222, 833, 556, 556, 556, 556, 333, 500, 278, 556, 500, 722,
       500, 500, 500, 334, 260, 334, 584],
))
WIDTHS.update({"£": 556, "•": 350})

PAGE_W, PAGE_H = 595.28, 841.89
MARGIN_X, TOP, BOTTOM = 70, 768, 86
STYLES = {  # size, bold, leading, space after
    "title": (26, True, 32, 4),
    "subtitle": (15, False, 22, 6),
    "small": (9.5, False, 14, 18),
    "h1": (14, True, 20, 4),
    "p": (10.5, False, 15.5, 8),
    "bullet": (10.5, False, 15.5, 4),
}


def text_width(text: str, size: float, bold: bool) -> float:
    width = sum(WIDTHS.get(ch, 556) for ch in text) * size / 1000
    return width * (1.06 if bold else 1.0)


def wrap(text: str, size: float, max_width: float, bold: bool) -> list[str]:
    lines, current = [], ""
    for word in text.split():
        trial = f"{current} {word}".strip()
        if not current or text_width(trial, size, bold) <= max_width:
            current = trial
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def pdf_string(text: str) -> str:
    out = []
    for ch in text:
        if ch in "\\()":
            out.append("\\" + ch)
        elif ch == "£":
            out.append("\\243")  # WinAnsi pound sign
        elif ch == "•":
            out.append("\\225")  # WinAnsi bullet
        elif 32 <= ord(ch) < 127:
            out.append(ch)
        else:
            raise ValueError(f"character {ch!r} is not supported by the sample PDF writer")
    return "(" + "".join(out) + ")"


def layout(pages: list[list[tuple[str, str]]]) -> list[list[tuple[float, float, float, bool, str]]]:
    out = []
    for blocks in pages:
        lines = []
        y = TOP
        for kind, text in blocks:
            size, bold, leading, after = STYLES[kind]
            if kind == "h1" and lines:
                y -= 10
            indent = 12 if kind == "bullet" else 0
            for i, line in enumerate(wrap(text, size, PAGE_W - 2 * MARGIN_X - indent, bold)):
                if kind == "bullet" and i == 0:
                    lines.append((MARGIN_X, y, size, False, "• " + line))
                else:
                    lines.append((MARGIN_X + indent, y, size, bold, line))
                y -= leading
            y -= after
            if y < BOTTOM:
                raise ValueError(f"page {len(out) + 1} is too long")
        out.append(lines)
    return out


def build_pdf(path: Path, pages, title: str, author: str, footer: str) -> None:
    laid_out = layout(pages)
    total = len(laid_out)
    objects: list[bytes] = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"",  # page tree, filled in below
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>",
        f"<< /Title {pdf_string(title)} /Author {pdf_string(author)} /CreationDate (D:20260105090000Z) >>".encode(),
    ]
    kids = []
    for number, lines in enumerate(laid_out, start=1):
        ops = []
        for x, y, size, bold, text in lines:
            ops.append(f"BT /{'F2' if bold else 'F1'} {size} Tf {x:.2f} {y:.2f} Td {pdf_string(text)} Tj ET")
        ops.append(f"BT /F1 8.5 Tf {MARGIN_X} 48 Td {pdf_string(f'{footer} | Page {number} of {total}')} Tj ET")
        stream = zlib.compress("\n".join(ops).encode("latin-1"))
        objects.append(b"<< /Length %d /Filter /FlateDecode >>\nstream\n" % len(stream) + stream + b"\nendstream")
        content_ref = len(objects)
        objects.append(
            (
                f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {PAGE_W} {PAGE_H}] "
                f"/Resources << /Font << /F1 3 0 R /F2 4 0 R >> >> /Contents {content_ref} 0 R >>"
            ).encode()
        )
        kids.append(f"{len(objects)} 0 R")
    objects[1] = f"<< /Type /Pages /Kids [{' '.join(kids)}] /Count {total} >>".encode()

    data = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(data))
        data += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(data)
    data += f"xref\n0 {len(objects) + 1}\n".encode()
    data += b"0000000000 65535 f \n"
    for offset in offsets:
        data += f"{offset:010d} 00000 n \n".encode()
    data += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R /Info 5 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    path.write_bytes(bytes(data))


# --- Word: IT Security Policy -------------------------------------------------------------------

POLICY = [
    ("title", "Northwind Analytics IT Security Policy"),
    ("p", "Version 3.2, last reviewed on 12 January 2026. Owner: the IT and Security team (it-help@northwind.test)."),
    ("h1", "1. Purpose and scope"),
    ("p", "This policy explains how we keep Northwind's systems, customer data and devices safe. It applies to every "
          "employee, contractor and intern, on any device used for Northwind work."),
    ("h1", "2. Passwords and sign-in"),
    ("p", "Use the company password manager for every work account. Passwords must be at least 14 characters long "
          "and unique to each service. Never share a password, not even with IT."),
    ("p", "Multi-factor authentication (MFA) is required for email, the code repository, the cloud console and the "
          "HR and finance systems. Use the authenticator app or a hardware security key. Text message codes are only "
          "allowed as a backup."),
    ("p", "Your laptop must lock automatically after 5 minutes without activity."),
    ("h1", "3. Devices"),
    ("p", "Only laptops managed by Northwind may be used to access customer data. Personal phones may be used for "
          "email and chat if they have a screen lock and the latest system updates."),
    ("p", "Laptops are encrypted (FileVault on Mac, BitLocker on Windows) and managed remotely by IT. Do not turn off "
          "encryption, the firewall or the endpoint protection agent."),
    ("p", "Install software through the self-service portal. If something you need is missing, ask IT. They usually "
          "reply within one working day."),
    ("p", "USB storage devices are blocked. Share files through the company drive instead."),
    ("h1", "4. Lost or stolen devices"),
    ("p", "If a laptop, phone or security key is lost or stolen, report it to IT within 1 hour of noticing, through "
          "the service portal or by calling the IT helpline on +44 20 7946 0999, which is answered day and night. IT "
          "will lock the device remotely and wipe it if needed."),
    ("p", "If the device was stolen, also report it to the police and send the crime reference number to IT. You "
          "will get a replacement laptop within two working days."),
    ("list", "Do not try to track down or recover a stolen device yourself."),
    ("list", "Change your password manager master password if you think someone may have seen it."),
    ("list", "Tell your manager if customer data was stored on the device."),
    ("h1", "5. Phishing and suspicious messages"),
    ("p", "Report suspicious emails with the Report Phishing button in the mail app. Do not click links or open "
          "attachments you were not expecting. If you clicked something by mistake, tell IT straight away. Quick "
          "reports limit the damage, and nobody gets into trouble for reporting."),
    ("h1", "6. Data classification"),
    ("p", "Every document and dataset belongs to one of four classes. Handle it according to the table below."),
    ("table", [
        ["Class", "Examples", "Rules"],
        ["Public", "Website text, published blog posts", "No restrictions"],
        ["Internal", "Handbook, team plans, meeting notes", "Share inside Northwind only"],
        ["Confidential", "Customer data, contracts, salaries", "Named people only, never on personal devices"],
        ["Restricted", "Passwords, encryption keys, security reports", "Only in the password manager or the secrets vault"],
    ]),
    ("h1", "7. Working while travelling"),
    ("p", "Before working from another country, request travel mode through the service portal at least five working "
          "days before you leave. IT will check that your laptop can be used safely there. A few countries require a "
          "loan laptop instead of your own."),
    ("p", "Avoid public Wi-Fi unless the company VPN is on. Keep your laptop with you, and never leave it visible in "
          "a car."),
    ("h1", "8. Reporting security incidents"),
    ("p", "A security incident is anything that may put company or customer data at risk, for example a lost device, "
          "an unexpected login alert or data sent to the wrong person. Report it to security@northwind.test or "
          "through the service portal straight away. When customer data is involved, the Security team decides "
          "within 24 hours whether customers or the regulator must be told."),
    ("h1", "9. Breaking this policy"),
    ("p", "Breaking this policy on purpose can lead to disciplinary action. Honest mistakes that are reported quickly "
          "are treated as a chance to learn."),
]

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def _run(text: str, bold: bool = False) -> str:
    props = "<w:rPr><w:b/></w:rPr>" if bold else ""
    return f'<w:r>{props}<w:t xml:space="preserve">{escape(text)}</w:t></w:r>'


def _para(text: str, style: str | None = None, bold: bool = False) -> str:
    ppr = f'<w:pPr><w:pStyle w:val="{style}"/></w:pPr>' if style else ""
    return f"<w:p>{ppr}{_run(text, bold)}</w:p>"


def _table(rows: list[list[str]]) -> str:
    border = '<w:{0} w:val="single" w:sz="4" w:space="0" w:color="B8C0CC"/>'
    borders = "".join(border.format(side) for side in ("top", "left", "bottom", "right", "insideH", "insideV"))
    grid = "".join('<w:gridCol w:w="3000"/>' for _ in rows[0])
    body = []
    for r, row in enumerate(rows):
        cells = "".join(
            f'<w:tc><w:tcPr><w:tcW w:w="3000" w:type="dxa"/></w:tcPr>{_para(cell, bold=r == 0)}</w:tc>' for cell in row
        )
        body.append(f"<w:tr>{cells}</w:tr>")
    return (
        f'<w:tbl><w:tblPr><w:tblW w:w="9000" w:type="dxa"/><w:tblBorders>{borders}</w:tblBorders></w:tblPr>'
        f"<w:tblGrid>{grid}</w:tblGrid>{''.join(body)}</w:tbl>"
    )


STYLES_XML = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles xmlns:w="{W_NS}">
  <w:docDefaults>
    <w:rPrDefault><w:rPr><w:rFonts w:ascii="Calibri" w:hAnsi="Calibri" w:cs="Calibri"/><w:sz w:val="22"/></w:rPr></w:rPrDefault>
    <w:pPrDefault><w:pPr><w:spacing w:after="160" w:line="276" w:lineRule="auto"/></w:pPr></w:pPrDefault>
  </w:docDefaults>
  <w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/></w:style>
  <w:style w:type="paragraph" w:styleId="Title"><w:name w:val="Title"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/>
    <w:pPr><w:spacing w:after="240"/></w:pPr><w:rPr><w:b/><w:sz w:val="44"/><w:color w:val="1F2A44"/></w:rPr></w:style>
  <w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/>
    <w:pPr><w:keepNext/><w:spacing w:before="320" w:after="120"/><w:outlineLvl w:val="0"/></w:pPr>
    <w:rPr><w:b/><w:sz w:val="28"/><w:color w:val="2F4BBF"/></w:rPr></w:style>
  <w:style w:type="paragraph" w:styleId="ListParagraph"><w:name w:val="List Paragraph"/><w:basedOn w:val="Normal"/>
    <w:pPr><w:spacing w:after="80"/><w:ind w:left="720" w:hanging="360"/></w:pPr></w:style>
</w:styles>
"""


def build_docx(path: Path, blocks, title: str, author: str) -> None:
    body = []
    for kind, content in blocks:
        if kind == "title":
            body.append(_para(content, "Title"))
        elif kind == "h1":
            body.append(_para(content, "Heading1"))
        elif kind == "list":
            body.append(_para("•\t" + content, "ListParagraph"))
        elif kind == "table":
            body.append(_table(content))
        else:
            body.append(_para(content))
    section = (
        '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/>'
        '<w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440" w:header="708" w:footer="708" w:gutter="0"/>'
        "</w:sectPr>"
    )
    document = (
        f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<w:document xmlns:w="{W_NS}"><w:body>'
        + "".join(body) + section + "</w:body></w:document>"
    )
    content_types = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
  <Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>
  <Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>
</Types>
"""
    rels = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>
</Relationships>
"""
    doc_rels = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
</Relationships>
"""
    core = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <dc:title>{escape(title)}</dc:title>
  <dc:creator>{escape(author)}</dc:creator>
  <dcterms:created xsi:type="dcterms:W3CDTF">2026-01-12T09:00:00Z</dcterms:created>
</cp:coreProperties>
"""
    fixed = (2026, 1, 12, 9, 0, 0)  # fixed timestamps keep the file identical between runs
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in (
            ("[Content_Types].xml", content_types),
            ("_rels/.rels", rels),
            ("word/document.xml", document),
            ("word/_rels/document.xml.rels", doc_rels),
            ("word/styles.xml", STYLES_XML),
            ("docProps/core.xml", core),
        ):
            info = zipfile.ZipInfo(name, date_time=fixed)
            info.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(info, data)


def main() -> None:
    SAMPLES.mkdir(exist_ok=True)
    build_pdf(
        SAMPLES / "Northwind-Employee-Handbook.pdf",
        HANDBOOK,
        title="Northwind Analytics Employee Handbook",
        author="Northwind Analytics People Team",
        footer="Northwind Analytics Employee Handbook",
    )
    build_docx(
        SAMPLES / "Northwind-IT-Security-Policy.docx",
        POLICY,
        title="Northwind Analytics IT Security Policy",
        author="Northwind Analytics IT and Security Team",
    )
    print("Wrote the sample PDF and Word documents to", SAMPLES)


if __name__ == "__main__":
    main()
