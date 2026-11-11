"""
PDF report generation for the Waste Sales Management module.

Every report function below takes the SAME filter parameters the
corresponding list/view page already uses, fetches data through the
SAME existing fetch_* functions in oracle_data.py, and renders it into
a landscape PDF -- so "Export PDF" always reflects exactly the filtered
view currently on screen (division, month, status, etc.), never a
separate, unfiltered dump of the whole table.
"""
import os
from io import BytesIO
from datetime import datetime
from xml.sax.saxutils import escape as _xml_escape

from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT
from reportlab.pdfgen import canvas as _canvas
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, KeepTogether,
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

from .oracle_data import (
    fetch_all_receiving, fetch_all_sales_headers, fetch_all_quotation_headers,
    fetch_all_gate_passes, build_comparison_rows,
    fetch_quotation_header_by_id, fetch_quotation_lines,
    fetch_sales_header_by_id, fetch_sales_lines,
    fetch_gate_pass_by_id, fetch_gate_pass_lines,
    fetch_ledger_report,
)

PRIMARY = colors.HexColor('#047857')
HEADER_BG = colors.HexColor('#F3F4F6')
BORDER = colors.HexColor('#E2E8F0')
MUTED = colors.HexColor('#6B7280')
ZEBRA = colors.HexColor('#FAFBFC')
LOCKED_RED = colors.HexColor('#A32D2D')
PENDING_AMBER = colors.HexColor('#B45309')

# Lifted verbatim from quotation_comparison.html so the export matches the
# grid on screen rather than approximating it.
INK = colors.HexColor('#334155')
TINT_HEADER = colors.HexColor('#ECFDF5')   # green header band on ranked vendor groups
TINT_BODY = colors.HexColor('#F8FDFB')     # the paler body tint under those same groups
BEST_BID_RING = colors.HexColor('#10B981')  # UI's inset box-shadow on the winning vendor cell
LOCKED_BADGE_BG = colors.HexColor('#FDE8E8')
PENDING_BADGE_BG = colors.HexColor('#FFF7ED')

# Where to look for the company logo, relative to the app's static dirs.
# First hit wins; if none exist the masthead silently falls back to text,
# so a missing asset can never 500 an export.
_LOGO_CANDIDATES = (
    'img/soorty-logo.png', 'img/logo.png', 'images/logo.png',
    'wastage/img/logo.png', 'logo.png',
)

# Footer approval blocks. Edit this tuple to change the sign-off columns.
SIGNATURE_BLOCKS = ('Prepared By', 'Checked By', 'Approved By')


def _find_logo():
    """Resolve the logo through Django's staticfiles finders. Returns a
    filesystem path or None -- never raises, because a report must still
    generate on a box where the asset hasn't been collected."""
    try:
        from django.contrib.staticfiles import finders
    except Exception:
        return None
    for candidate in _LOGO_CANDIDATES:
        try:
            hit = finders.find(candidate)
        except Exception:
            continue
        if hit and os.path.exists(hit):
            return hit
    return None


class _NumberedCanvas(_canvas.Canvas):
    """'Page X of Y' needs a total that isn't known until layout has
    finished, so every page is buffered on the first pass and the
    header/footer furniture is stamped on a second pass once the count is
    final. Pass a `page_furniture(canvas, page_num, page_count)` callable
    in via the class attribute set by _make_numbered_canvas()."""
    _furniture = None

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_states = []

    def showPage(self):
        self._saved_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        total = len(self._saved_states)
        for state in self._saved_states:
            self.__dict__.update(state)
            if self._furniture:
                self._furniture(self, self._pageNumber, total)
            super().showPage()
        self._saved_states = []
        super().save()


def _make_numbered_canvas(furniture):
    """Bind a furniture-drawing callable to a fresh _NumberedCanvas
    subclass -- one per document, so concurrent exports can't stamp each
    other's headers."""
    return type('_BoundNumberedCanvas', (_NumberedCanvas,), {'_furniture': staticmethod(furniture)})


def _signature_block(page_width, styles, blocks=None):
    """Approval strip rendered once, at the end of the document. Kept as a
    flowable rather than drawn into the page footer so it appears exactly
    once instead of on every page. blocks defaults to SIGNATURE_BLOCKS
    (the office-approval set used by the tabular reports) -- Gate Pass
    passes its own ('Waste Incharge', 'Accounts', 'Security Incharge')
    since that's the actual sign-off chain printed on the physical slip."""
    blocks = blocks or SIGNATURE_BLOCKS
    label_style = ParagraphStyle('SigLabel', parent=styles['Normal'], fontSize=8,
                                 textColor=INK, alignment=TA_CENTER)
    cells = [Paragraph(f'<b>{_xml_escape(label)}</b>', label_style) for label in blocks]
    col_w = page_width / len(blocks)
    table = Table([[''] * len(blocks), cells],
                  colWidths=[col_w] * len(blocks), rowHeights=[16 * mm, None])
    table.setStyle(TableStyle([
        ('LINEBELOW', (0, 0), (-1, 0), 0.6, colors.HexColor('#94A3B8')),
        ('LEFTPADDING', (0, 0), (-1, -1), 10),
        ('RIGHTPADDING', (0, 0), (-1, -1), 10),
        ('TOPPADDING', (0, 1), (-1, 1), 4),
        ('VALIGN', (0, 0), (-1, -1), 'BOTTOM'),
    ]))
    return KeepTogether([Spacer(1, 12 * mm), table])


def _build_report_pdf(report_title, filter_lines, headers, rows, col_widths=None,
                       generated_by=None, align_right_cols=None, total_row=None):
    """Shared report shell: masthead, filter-context line, generated
    timestamp, a styled table, and a page-number footer. Returns raw PDF
    bytes, ready to hand straight to an HttpResponse.

    total_row: optional list, same length as headers -- appended as a
    visually distinct final row (bold, divider line above it) rather
    than styled like a normal data row. Pass '' for any column that
    shouldn't show a total (e.g. a label column)."""
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4),
                             topMargin=15 * mm, bottomMargin=15 * mm,
                             leftMargin=12 * mm, rightMargin=12 * mm)
    styles = getSampleStyleSheet()
    masthead_style = ParagraphStyle('Masthead', parent=styles['Normal'], fontSize=9,
                                     textColor=MUTED, spaceAfter=2)
    title_style = ParagraphStyle('ReportTitle', parent=styles['Title'], fontSize=17,
                                  textColor=PRIMARY, spaceAfter=4, leading=20, alignment=TA_LEFT)
    filter_style = ParagraphStyle('FilterContext', parent=styles['Normal'], fontSize=9.5,
                                   textColor=colors.HexColor('#334155'), spaceAfter=14)
    empty_style = ParagraphStyle('EmptyState', parent=styles['Normal'], fontSize=10,
                                  textColor=MUTED, spaceBefore=20)

    story = [
        Paragraph("Waste Sales Management, Mill Division", masthead_style),
        Paragraph(report_title, title_style),
        Paragraph(" &nbsp;&nbsp;|&nbsp;&nbsp; ".join(filter_lines), filter_style),
    ]

    if rows:
        table_data = [headers] + rows
        data_row_count = len(rows)
        if total_row:
            table_data = table_data + [total_row]
        col_count = len(headers)
        align_right_cols = align_right_cols or []
        t = Table(table_data, colWidths=col_widths, repeatRows=1, hAlign='LEFT')
        style_cmds = [
            ('BACKGROUND', (0, 0), (-1, 0), HEADER_BG),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.HexColor('#334155')),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 0), (-1, -1), 8),
            ('GRID', (0, 0), (-1, -1), 0.5, BORDER),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('ROWBACKGROUNDS', (0, 1), (-1, data_row_count), [colors.white, ZEBRA]),
            ('TOPPADDING', (0, 0), (-1, -1), 5),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
            ('LEFTPADDING', (0, 0), (-1, -1), 6),
            ('RIGHTPADDING', (0, 0), (-1, -1), 6),
        ]
        for c in align_right_cols:
            style_cmds.append(('ALIGN', (c, 0), (c, -1), 'RIGHT'))
        if total_row:
            style_cmds += [
                ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
                ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor('#ECFDF5')),
                ('LINEABOVE', (0, -1), (-1, -1), 1, PRIMARY),
            ]
        t.setStyle(TableStyle(style_cmds))
        story.append(t)
    else:
        story.append(Paragraph("No records found for the selected filters.", empty_style))

    stamp = f"Generated {datetime.now().strftime('%d-%b-%Y %H:%M')}"
    if generated_by:
        stamp += f" by {generated_by}"

    def _footer(canvas, page_num, page_count):
        canvas.saveState()
        canvas.setFont('Helvetica', 7)
        canvas.setFillColor(MUTED)
        canvas.drawString(12 * mm, 10 * mm, stamp)
        canvas.drawRightString(landscape(A4)[0] - 12 * mm, 10 * mm,
                               f"Page {page_num} of {page_count}")
        canvas.restoreState()

    doc.build(story, canvasmaker=_make_numbered_canvas(_footer))
    buf.seek(0)
    return buf.getvalue()


def _fmt(v, default='\u2014'):
    return default if v is None or v == '' else str(v)


def _fmt_num(v, default='\u2014'):
    if v is None:
        return default
    try:
        return f'{float(v):,.2f}'
    except (TypeError, ValueError):
        return str(v)


def _fmt_display_date(iso_str):
    """RECEIVE_DATE/VALID_UNTIL come back from fetch_quotation_header_by_id
    as plain 'YYYY-MM-DD' (that function formats for round-tripping into
    HTML date inputs, not for display) -- reformat to 'DD-Mon-YYYY' for
    the printed document. Falls back to the raw string rather than raising
    if it's ever something unexpected."""
    if not iso_str:
        return None
    try:
        from datetime import date as _date_cls
        return _date_cls.fromisoformat(str(iso_str)[:10]).strftime('%d-%b-%Y')
    except (ValueError, TypeError):
        return iso_str


# ─── Stock Receiving ─────────────────────────────────────────────────
def build_receiving_pdf(division_label, month_label, search, division, month, year, generated_by=None,
                         department_ids=None, department_labels=None, item_ids=None, item_labels=None,
                         date_from=None, date_to=None):
    records = fetch_all_receiving(search=search, division=division, month=month, year=year,
                                   department_ids=department_ids, item_ids=item_ids,
                                   date_from=date_from, date_to=date_to)
    headers = ['Item', 'Department', 'UOM', 'Qty Received', 'Receive Date', 'Division', 'Remarks']
    rows = [[
        _fmt(r.get('ITEM_NAME')), _fmt(r.get('DEPT_NAME')), _fmt(r.get('UOM')),
        _fmt_num(r.get('QTY_RECEIVED')), _fmt(r.get('RECEIVE_DATE')),
        _fmt(r.get('DIVISION')), _fmt(r.get('REMARKS')),
    ] for r in records]

    filter_lines = [f'Division: {division_label}']
    if date_from and date_to:
        filter_lines.append(f'Date Range: {_fmt_display_date(date_from)} to {_fmt_display_date(date_to)}')
    else:
        filter_lines.append(f'Period: {month_label}')
    if department_labels:
        filter_lines.append(f'Department: {", ".join(department_labels)}')
    if item_labels:
        filter_lines.append(f'Item: {", ".join(item_labels)}')
    if search:
        filter_lines.append(f'Search: "{search}"')
    filter_lines.append(f'{len(records)} entries')

    total_qty = sum(float(r.get('QTY_RECEIVED') or 0) for r in records)
    total_row = ['', '', 'TOTAL', _fmt_num(total_qty), '', '', ''] if records else None

    return _build_report_pdf(
        'Stock Receiving Report', filter_lines, headers, rows,
        col_widths=[65 * mm, 40 * mm, 20 * mm, 30 * mm, 32 * mm, 22 * mm, None],
        generated_by=generated_by, align_right_cols=[3], total_row=total_row,
    )


# ─── Stock Ledger (month-wise) ───────────────────────────────────────
# Column names below are the ones fetch_ledger_report() returns (oracle_data.py).
_LEDGER_TYPE_SHORT = {'RECEIVE': 'IN', 'SALE': 'OUT'}          # anything else -> ADJ
_LEDGER_TYPE_SOURCE = {'RECEIVE': 'Receiving', 'SALE': 'Sales'}  # anything else -> Manual
_LEDGER_TYPE_FILTER_LABEL = {'RECEIVE': 'Receiving (IN)', 'SALE': 'Sales (OUT)', 'ADJUST': 'Adjustment'}


def build_ledger_pdf(division_label, month_label, division, month, year,
                      item_id=None, item_label=None, txn_type=None,
                      show_division=False, generated_by=None):
    records = fetch_ledger_report(division, month, year,
                                  item_id=item_id or None, txn_type=txn_type or None)
    cell = ParagraphStyle('LedgerCell', fontName='Helvetica', fontSize=8, leading=9.5)

    headers = ['Date']
    weights = [1.5]
    if show_division:
        headers.append('Division'); weights.append(1.0)
    headers += ['Voucher Ref', 'Type', 'Item', 'Template', 'IN (+)', 'OUT (\u2212)', 'Running Bal.', 'Posted By']
    weights += [2.4, 0.9, 4.0, 1.4, 1.4, 1.4, 1.7, 1.8]

    rows = []
    total_in = total_out = 0.0
    for r in records:
        r = {str(k).upper(): v for k, v in r.items()}
        ttype = (r.get('TRANSACTION_TYPE') or '').upper()
        qty_in, qty_out = r.get('QTY_IN'), r.get('QTY_OUT')
        total_in += float(qty_in or 0)
        total_out += float(qty_out or 0)
        row = [_fmt(r.get('TXN_DATE_DISP'))]
        if show_division:
            row.append(_fmt(r.get('DIVISION')))
        row += [
            Paragraph(_xml_escape(_fmt(r.get('SOURCE_REF'))), cell),
            _LEDGER_TYPE_SHORT.get(ttype, 'ADJ'),
            Paragraph(_xml_escape(_fmt(r.get('ITEM_NAME'))), cell),
            _LEDGER_TYPE_SOURCE.get(ttype, 'Manual'),
            _fmt_num(qty_in) if qty_in else '\u2014',
            _fmt_num(qty_out) if qty_out else '\u2014',
            _fmt_num(r.get('BALANCE')),
            Paragraph(_xml_escape(_fmt(r.get('POSTED_BY'), 'System')), cell),
        ]
        rows.append(row)

    usable = landscape(A4)[0] - 24 * mm
    col_widths = [usable * w / sum(weights) for w in weights]
    n = len(headers)
    in_idx = headers.index('IN (+)')
    right_cols = [in_idx, in_idx + 1, in_idx + 2]

    total_row = None
    if rows:
        total_row = [''] * n
        total_row[0] = 'TOTAL'
        total_row[in_idx] = _fmt_num(total_in)
        total_row[in_idx + 1] = _fmt_num(total_out)

    filter_lines = [f'Division: {division_label}', f'Month: {month_label}']
    if item_label:
        filter_lines.append(f'Item: {item_label}')
    if txn_type:
        filter_lines.append(f'Type: {_LEDGER_TYPE_FILTER_LABEL.get(txn_type, txn_type)}')
    filter_lines.append(f'{len(records)} entries')

    return _build_report_pdf(
        'Stock Ledger Report', filter_lines, headers, rows,
        col_widths=col_widths, generated_by=generated_by,
        align_right_cols=right_cols, total_row=total_row,
    )


# ─── Sales Order ─────────────────────────────────────────────────────
def build_sales_pdf(division_label, month_label, search, division, month, generated_by=None):
    records = fetch_all_sales_headers(division=division, search=search, month=month)
    headers = ['Doc ID', 'Division', 'Party', 'Doc Date', 'Invoice No', 'Status', 'Total Amount', 'Lines']
    rows = [[
        _fmt(r.get('DOC_ID')), _fmt(r.get('DIVISION')), _fmt(r.get('VENDOR_NAME')),
        _fmt(r.get('DOC_DATE')), _fmt(r.get('INVOICE_NO')), _fmt(r.get('STATUS')),
        _fmt_num(r.get('TOTAL_AMOUNT')), _fmt(r.get('LINE_COUNT')),
    ] for r in records]
    filter_lines = [f'Division: {division_label}', f'Month: {month_label}']
    if search:
        filter_lines.append(f'Search: "{search}"')
    filter_lines.append(f'{len(records)} entries')
    return _build_report_pdf(
        'Sales Order Report', filter_lines, headers, rows,
        col_widths=[32 * mm, 22 * mm, 45 * mm, 28 * mm, 30 * mm, 25 * mm, 32 * mm, 18 * mm],
        generated_by=generated_by, align_right_cols=[6, 7],
    )


# ─── Sales Order Detail (single document, row-level PDF) ─────────────
# Same idea as the Quotation Detail export below: build_sales_pdf() above
# is the flat filtered-summary grid; this is the row-level "PDF" action
# on one document -- full header + every line item, landscape (rather
# than Quotation Detail's portrait) because a sales line carries two more
# columns (Shipped Qty, Line Status) that Quotation lines don't have.
def build_sales_detail_pdf(doc_id, division=None, generated_by=None):
    """division is the same IDOR guard fetch_sales_header_by_id() uses
    everywhere else in this module. Returns None (never raises) if the
    doc doesn't exist or belongs to a different division, so the calling
    view can redirect with a friendly message instead of a 500."""
    header = fetch_sales_header_by_id(doc_id, division=division)
    if not header:
        return None
    lines = fetch_sales_lines(doc_id)

    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4),
                             topMargin=15 * mm, bottomMargin=15 * mm,
                             leftMargin=12 * mm, rightMargin=12 * mm)
    styles = getSampleStyleSheet()
    masthead_style = ParagraphStyle('Masthead', parent=styles['Normal'], fontSize=9,
                                     textColor=MUTED, spaceAfter=2)
    title_style = ParagraphStyle('ReportTitle', parent=styles['Title'], fontSize=17,
                                  textColor=PRIMARY, spaceAfter=10, leading=20, alignment=TA_LEFT)
    label_style = ParagraphStyle('FieldLabel', parent=styles['Normal'], fontSize=8,
                                  textColor=MUTED, leading=10)
    value_style = ParagraphStyle('FieldValue', parent=styles['Normal'], fontSize=10,
                                  textColor=INK, leading=13)
    lines_title_style = ParagraphStyle('LinesTitle', parent=styles['Normal'], fontSize=11,
                                        textColor=INK, spaceAfter=6, fontName='Helvetica-Bold')
    empty_style = ParagraphStyle('EmptyState', parent=styles['Normal'], fontSize=10,
                                  textColor=MUTED, spaceBefore=8)
    item_desc_style = ParagraphStyle('ItemDesc', parent=styles['Normal'], fontSize=8, leading=10, textColor=INK)

    story = [
        Paragraph("Waste Sales Management, Mill Division", masthead_style),
        Paragraph(f"Sales Order &mdash; {_xml_escape(_fmt(header.get('DOC_ID')))}", title_style),
    ]

    def _cell(label, value):
        return [Paragraph(_xml_escape(label), label_style),
                Paragraph(_xml_escape(_fmt(value)), value_style)]

    field_rows = [
        _cell('Doc ID', header.get('DOC_ID')) + _cell('Status', header.get('STATUS')),
        _cell('Party', header.get('VENDOR_NAME')) + _cell('Division', header.get('DIVISION')),
        _cell('Doc Date', _fmt_display_date(header.get('DOC_DATE'))) + _cell('Invoice No', header.get('INVOICE_NO')),
        _cell('Total Amount', _fmt_num(header.get('TOTAL_AMOUNT'))) + _cell('Created By', header.get('CREATED_BY')),
    ]
    if header.get('POSTED_BY'):
        field_rows.append(_cell('Posted By', header.get('POSTED_BY')) + _cell('Posted Date', header.get('POSTED_DATE')))
    if header.get('CANCELLED_BY'):
        field_rows.append(_cell('Cancelled By', header.get('CANCELLED_BY')) + _cell('Cancelled Date', header.get('CANCELLED_DATE')))

    field_table = Table(field_rows, colWidths=[28 * mm, 90 * mm, 28 * mm, 90 * mm])
    field_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), HEADER_BG),
        ('GRID', (0, 0), (-1, -1), 0.5, BORDER),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ('LEFTPADDING', (0, 0), (-1, -1), 6),
        ('RIGHTPADDING', (0, 0), (-1, -1), 6),
    ]))
    story += [field_table, Spacer(1, 10 * mm)]

    story.append(Paragraph(
        f"Sales Order Lines &nbsp; ({len(lines)} item{'s' if len(lines) != 1 else ''})",
        lines_title_style))

    headers2 = ['Line #', 'Item Code', 'Item Description', 'UOM', 'Quantity',
                'Unit Price', 'Line Total', 'Shipped Qty', 'Line Status']
    # Item Description is a Paragraph (wraps within its column) for the same
    # reason as Quotation Detail: a plain-string cell doesn't wrap and would
    # silently push later columns off the page for any long item name.
    rows2 = [[
        _fmt(l.get('LINE_NO')), _fmt(l.get('ITEM_CODE')),
        Paragraph(_xml_escape(_fmt(l.get('ITEM_NAME'))), item_desc_style),
        _fmt(l.get('UOM')), _fmt_num(l.get('QUANTITY')),
        _fmt_num(l.get('UNIT_PRICE')), _fmt_num(l.get('LINE_TOTAL')),
        _fmt_num(l.get('SHIPPED_QTY')), _fmt(l.get('LINE_STATUS')),
    ] for l in lines]

    if rows2:
        total_row_idx = len(rows2) + 1  # +1 for the header row at index 0
        rows2.append(['Total', '', '', '', '', '', _fmt_num(header.get('TOTAL_AMOUNT')), '', ''])
        t = Table([headers2] + rows2,
                   colWidths=[10 * mm, 20 * mm, None, 12 * mm, 20 * mm, 24 * mm, 24 * mm, 20 * mm, 24 * mm],
                   repeatRows=1, hAlign='LEFT')
        t.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), HEADER_BG),
            ('TEXTCOLOR', (0, 0), (-1, 0), INK),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 0), (-1, -1), 8),
            ('GRID', (0, 0), (-1, -1), 0.5, BORDER),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, ZEBRA]),
            ('TOPPADDING', (0, 0), (-1, -1), 5),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
            ('LEFTPADDING', (0, 0), (-1, -1), 6),
            ('RIGHTPADDING', (0, 0), (-1, -1), 6),
            ('ALIGN', (4, 0), (7, -1), 'RIGHT'),
            # Total row: spans the label across the identity columns, bold,
            # ruled off from the line items above it.
            ('SPAN', (0, total_row_idx), (5, total_row_idx)),
            ('ALIGN', (0, total_row_idx), (5, total_row_idx), 'RIGHT'),
            ('FONTNAME', (0, total_row_idx), (-1, total_row_idx), 'Helvetica-Bold'),
            ('LINEABOVE', (0, total_row_idx), (-1, total_row_idx), 0.75, INK),
            ('BACKGROUND', (0, total_row_idx), (-1, total_row_idx), HEADER_BG),
        ]))
        story.append(t)
    else:
        story.append(Paragraph("No line items on this sale document.", empty_style))

    story.append(_signature_block(doc.width, styles))

    stamp = f"Generated {datetime.now().strftime('%d-%b-%Y %H:%M')}"
    if generated_by:
        stamp += f" by {generated_by}"

    def _footer(canvas, page_num, page_count):
        canvas.saveState()
        canvas.setFont('Helvetica', 7)
        canvas.setFillColor(MUTED)
        canvas.drawString(12 * mm, 10 * mm, stamp)
        canvas.drawRightString(landscape(A4)[0] - 12 * mm, 10 * mm, f"Page {page_num} of {page_count}")
        canvas.restoreState()

    doc.build(story, canvasmaker=_make_numbered_canvas(_footer))
    buf.seek(0)
    return buf.getvalue()


# ─── Quotation ────────────────────────────────────────────────────────
def build_quotation_pdf(division_label, month_label, division, month, generated_by=None):
    records = fetch_all_quotation_headers(division=division, month=month)
    headers = ['Doc ID', 'Status', 'Division', 'Party', 'Month', 'Reference No', 'Receive Date', 'Valid Until', 'Lines']
    rows = [[
        _fmt(r.get('QUOTE_DOC_ID')), _fmt(r.get('STATUS')), _fmt(r.get('DIVISION')),
        _fmt(r.get('VENDOR_NAME')), _fmt(r.get('TARGET_MONTH_DISPLAY')), _fmt(r.get('REFERENCE_NO')),
        _fmt(r.get('RECEIVE_DATE')), _fmt(r.get('VALID_UNTIL')), _fmt(r.get('LINE_COUNT')),
    ] for r in records]
    filter_lines = [f'Division: {division_label}', f'Month: {month_label}', f'{len(records)} entries']
    return _build_report_pdf(
        'Quotation Report', filter_lines, headers, rows,
        col_widths=[30 * mm, 20 * mm, 20 * mm, 38 * mm, 22 * mm, 32 * mm, 28 * mm, 28 * mm, 16 * mm],
        generated_by=generated_by, align_right_cols=[8],
    )


# ─── Quotation Detail (single vendor / doc, row-level PDF) ───────────
# Distinct from build_quotation_pdf() above, which exports the flat
# summary grid across every vendor for a month. This is the row-level
# "PDF" action on one record: full header fields + every line item bid
# by that vendor, laid out as a standalone document rather than a report
# table row.
def build_quotation_detail_pdf(doc_id, division=None, generated_by=None):
    """division is the same IDOR guard fetch_quotation_header_by_id()
    uses everywhere else in this module -- pass the caller's own division
    (or None for a sees-all user) and this returns None, not someone
    else's data, if doc_id belongs to a different division. Returns None
    (never raises) if the doc doesn't exist at all either, so the calling
    view can redirect with a friendly message instead of a 500."""
    header = fetch_quotation_header_by_id(doc_id, division=division)
    if not header:
        return None
    lines = fetch_quotation_lines(doc_id, division=header['DIVISION'], target_month=header['TARGET_MONTH'])

    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
                             topMargin=15 * mm, bottomMargin=15 * mm,
                             leftMargin=15 * mm, rightMargin=15 * mm)
    styles = getSampleStyleSheet()
    masthead_style = ParagraphStyle('Masthead', parent=styles['Normal'], fontSize=9,
                                     textColor=MUTED, spaceAfter=2)
    title_style = ParagraphStyle('ReportTitle', parent=styles['Title'], fontSize=17,
                                  textColor=PRIMARY, spaceAfter=10, leading=20, alignment=TA_LEFT)
    label_style = ParagraphStyle('FieldLabel', parent=styles['Normal'], fontSize=8,
                                  textColor=MUTED, leading=10)
    value_style = ParagraphStyle('FieldValue', parent=styles['Normal'], fontSize=10,
                                  textColor=INK, leading=13)
    lines_title_style = ParagraphStyle('LinesTitle', parent=styles['Normal'], fontSize=11,
                                        textColor=INK, spaceAfter=6, fontName='Helvetica-Bold')
    empty_style = ParagraphStyle('EmptyState', parent=styles['Normal'], fontSize=10,
                                  textColor=MUTED, spaceBefore=8)

    # Oracle's 'Month YYYY' TO_CHAR format pads short month names with
    # trailing spaces inside the string (not just at the ends), which
    # .strip() alone doesn't catch -- collapse to single spaces for print.
    month_display = ' '.join(str(header.get('TARGET_MONTH_DISPLAY') or '').split())

    story = [
        Paragraph("Waste Sales Management, Mill Division", masthead_style),
        Paragraph(f"Quotation &mdash; {_xml_escape(_fmt(header.get('QUOTE_DOC_ID')))}", title_style),
    ]

    def _cell(label, value):
        return [Paragraph(_xml_escape(label), label_style),
                Paragraph(_xml_escape(_fmt(value)), value_style)]

    field_rows = [
        _cell('Doc ID', header.get('QUOTE_DOC_ID')) + _cell('Status', header.get('STATUS')),
        _cell('Party', header.get('VENDOR_NAME')) + _cell('Division', header.get('DIVISION')),
        _cell('Reference No', header.get('REFERENCE_NO')) + _cell('Month', month_display),
        _cell('Receive Date', _fmt_display_date(header.get('RECEIVE_DATE')))
            + _cell('Valid Until', _fmt_display_date(header.get('VALID_UNTIL'))),
    ]
    field_style_cmds = [
        ('BACKGROUND', (0, 0), (-1, -1), HEADER_BG),
        ('GRID', (0, 0), (-1, -1), 0.5, BORDER),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ('LEFTPADDING', (0, 0), (-1, -1), 6),
        ('RIGHTPADDING', (0, 0), (-1, -1), 6),
    ]
    if header.get('REMARKS'):
        remarks_row = len(field_rows)
        field_rows.append(_cell('Remarks', header.get('REMARKS')) + ['', ''])
        field_style_cmds.append(('SPAN', (1, remarks_row), (3, remarks_row)))

    field_table = Table(field_rows, colWidths=[28 * mm, 57 * mm, 28 * mm, 57 * mm])
    field_table.setStyle(TableStyle(field_style_cmds))
    story += [field_table, Spacer(1, 10 * mm)]

    story.append(Paragraph(
        f"Quotation Lines &nbsp; ({len(lines)} item{'s' if len(lines) != 1 else ''})",
        lines_title_style))

    # Item Description is a Paragraph, not a plain string, so it WRAPS
    # inside its column -- a plain-string cell has no wrapping and sizes
    # to its own natural width, which silently pushed every column after
    # it (including Offered Price) off the right edge of the page for any
    # long item name. This is the same fix already applied to the
    # Comparison PDF for the same reason.
    item_desc_style = ParagraphStyle('ItemDesc', parent=styles['Normal'], fontSize=8, leading=10, textColor=INK)
    headers = ['Line #', 'Item Code', 'Item Description', 'UOM', 'Quantity', 'Last Month Price', 'Offered Price']
    rows = [[
        _fmt(l.get('LINE_NO')), _fmt(l.get('ITEM_CODE')),
        Paragraph(_xml_escape(_fmt(l.get('ITEM_NAME'))), item_desc_style),
        _fmt(l.get('UOM')), _fmt_num(l.get('OFFERED_QTY')),
        _fmt_num(l.get('LAST_MONTH_PRICE')), _fmt_num(l.get('CURRENT_OFFERED_PRICE')),
    ] for l in lines]

    if rows:
        t = Table([headers] + rows,
                   colWidths=[10 * mm, 22 * mm, None, 14 * mm, 22 * mm, 28 * mm, 28 * mm],
                   repeatRows=1, hAlign='LEFT')
        t.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), HEADER_BG),
            ('TEXTCOLOR', (0, 0), (-1, 0), INK),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 0), (-1, -1), 8),
            ('GRID', (0, 0), (-1, -1), 0.5, BORDER),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, ZEBRA]),
            ('TOPPADDING', (0, 0), (-1, -1), 5),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
            ('LEFTPADDING', (0, 0), (-1, -1), 6),
            ('RIGHTPADDING', (0, 0), (-1, -1), 6),
            ('ALIGN', (4, 0), (6, -1), 'RIGHT'),
        ]))
        story.append(t)
    else:
        story.append(Paragraph("No line items on this quotation.", empty_style))

    story.append(_signature_block(doc.width, styles))

    stamp = f"Generated {datetime.now().strftime('%d-%b-%Y %H:%M')}"
    if generated_by:
        stamp += f" by {generated_by}"

    def _footer(canvas, page_num, page_count):
        canvas.saveState()
        canvas.setFont('Helvetica', 7)
        canvas.setFillColor(MUTED)
        canvas.drawString(15 * mm, 10 * mm, stamp)
        canvas.drawRightString(A4[0] - 15 * mm, 10 * mm, f"Page {page_num} of {page_count}")
        canvas.restoreState()

    doc.build(story, canvasmaker=_make_numbered_canvas(_footer))
    buf.seek(0)
    return buf.getvalue()


# ─── Quotation Comparison ────────────────────────────────────────────
# The comparison grid is a pivot, not a flat list: a two-tier header with
# grouped vendor bands, tinted rank columns and a highlight on the winning
# bid. _build_report_pdf()'s single-row shell can't express any of that, so
# this report builds its own document. The other four are untouched.

_CMP_HEADER_TOP = [
    'Item', 'UOM', 'Party 1 (Rank 1)', '', 'Party 2 (Rank 2)', '',
    'Party 3 (Rank 3)', '', 'Last Month Winner', '', 'Yearly High',
    'Best Bid (System)', '', 'Manual Selection',
]
_CMP_HEADER_SUB = [
    '', '', 'Name', 'Cost', 'Name', 'Cost', 'Name', 'Cost',
    'Winner', 'Price', '', 'Name', 'Price', '',
]
# Columns that hold a formatted number or a short code and must never wrap.
_CMP_RIGID_COLS = (1, 3, 5, 7, 9, 10, 12)
# Columns whose text wraps onto as many lines as it needs.
_CMP_WRAP_COLS = (0, 2, 4, 6, 8, 11, 13)
# The green-tinted rank bands, mirroring the UI's #ECFDF5 / #F8FDFB.
_CMP_TINTED_COLS = (2, 3, 6, 7, 11, 12)
# Vendor-name cells that get the winner ring when they hold the Best Bid.
_CMP_RING_COLS = (2, 4, 6)
_CMP_EM_DASH = '\u2014'


def _hex(color):
    """reportlab's own hexval() returns '0xrrggbb', which its Paragraph
    markup parser rejects -- <font color='...'> needs a leading '#'."""
    return '#' + color.hexval()[2:]


def _longest_word_width(text, font, size):
    """Widest unbreakable token in a string. A wrapping column narrower
    than this will spill its text past the cell edge, which is exactly the
    overlap this report had before -- so this is the hard floor for any
    auto-fitted column."""
    return max((stringWidth(w, font, size) for w in str(text).split()), default=0.0)


# Platypus's own line-breaking pass (Paragraph.wrap) doesn't reproduce raw
# stringWidth() to the last decimal -- a column sized to exactly
# stringWidth + padding measured 22.935pt of usable text width for
# "125.50" and still wrapped it into two lines. A few points of slack
# absorbs that gap; this was found empirically, not derived.
_WRAP_SAFETY_MARGIN = 3.0


def _autofit_comparison_widths(plain_rows, budget, body_size, header_size, padding):
    """Distribute a fixed page budget across the 14 columns from the actual
    cell contents rather than hardcoded millimetres.

    Rigid columns take precisely the width their longest value needs.
    Whatever is left goes to the wrapping columns: any column that fits
    naturally gets its natural width, and the columns that don't share the
    remainder in proportion to how much they asked for -- never dropping
    below their longest single word. Returns None if even the floors don't
    fit, which tells the caller to retry a size down."""
    all_rows = [_CMP_HEADER_TOP, _CMP_HEADER_SUB] + plain_rows
    natural, floor = [], []
    for c in range(len(_CMP_HEADER_TOP)):
        widest = 0.0
        widest_word = 0.0
        for r_idx, row in enumerate(all_rows):
            cell = row[c] if c < len(row) else ''
            if not cell:
                continue
            size = header_size if r_idx < 2 else body_size
            font = 'Helvetica-Bold' if r_idx < 2 else 'Helvetica'
            for line in str(cell).split('\n'):
                widest = max(widest, stringWidth(line, font, size))
                widest_word = max(widest_word, _longest_word_width(line, font, size))
        natural.append(widest + padding + _WRAP_SAFETY_MARGIN)
        floor.append(widest_word + padding + _WRAP_SAFETY_MARGIN)

    widths = [0.0] * len(natural)
    for c in _CMP_RIGID_COLS:
        widths[c] = natural[c]

    remaining = budget - sum(widths[c] for c in _CMP_RIGID_COLS)
    if remaining < sum(floor[c] for c in _CMP_WRAP_COLS):
        return None

    pending = list(_CMP_WRAP_COLS)
    while pending:
        total_ask = sum(natural[c] for c in pending)
        if total_ask <= remaining:
            # Everything fits unwrapped; hand the slack to the Item column,
            # which carries the longest text and benefits most from it.
            for c in pending:
                widths[c] = natural[c]
            widths[0] += remaining - total_ask
            break
        settled = False
        for c in list(pending):
            share = remaining * (natural[c] / total_ask)
            if share < floor[c]:
                widths[c] = floor[c]
                remaining -= floor[c]
                pending.remove(c)
                settled = True
        if not settled:
            for c in pending:
                widths[c] = remaining * (natural[c] / total_ask)
            break
    return widths


def _cmp_selection_cell(item):
    """The Manual Selection column, reproducing all three states the UI
    shows: Locked, Locked (Shipped) for an item already Ship & Posted, and
    Pending with whichever vendor is currently effective -- the manual
    override if one was saved, otherwise the system Best Bid. Single line
    -- status, party, and rate inline, separated by a dash -- rather than
    stacked across multiple lines, so each row stays one printed line
    regardless of state."""
    if item.get('IS_LOCKED'):
        label = 'Locked' if item.get('IS_UNLOCKABLE') else 'Locked (Shipped)'
        return label, LOCKED_RED, LOCKED_BADGE_BG
    bid = item.get('EFFECTIVE_SELECTED_BID')
    label = 'Pending'
    if bid:
        label += f" &mdash; <font color='#334155'>{_xml_escape(str(bid['VENDOR_NAME']))}, {_fmt_num(bid['PRICE'])}</font>"
    return label, PENDING_AMBER, PENDING_BADGE_BG


def build_quotation_comparison_pdf(division_label, month_label, division, target_month,
                                   generated_by=None, reference_no=None):
    items = build_comparison_rows(division, target_month)

    # Plain text mirrors of every cell, used only for width measurement --
    # the rendered cells carry inline markup that would skew the metrics.
    plain_rows, render_rows, meta = [], [], []
    for item in items:
        v1, v2, v3 = item.get('VENDOR1'), item.get('VENDOR2'), item.get('VENDOR3')
        lmw, yh, best = item.get('LAST_MONTH_WINNER'), item.get('YEARLY_HIGH'), item.get('BEST_BID')
        item_name = _fmt(item.get('ITEM_NAME'))
        sel_label, sel_colour, sel_bg = _cmp_selection_cell(item)

        def vname(v):
            return _fmt(v['VENDOR_NAME']) if v else _CMP_EM_DASH

        def vprice(v):
            return _fmt_num(v['PRICE']) if v else _CMP_EM_DASH

        plain_rows.append([
            item_name, _fmt(item.get('UOM')),
            vname(v1), vprice(v1), vname(v2), vprice(v2), vname(v3), vprice(v3),
            vname(lmw), vprice(lmw), vprice(yh), vname(best), vprice(best),
            sel_label.replace('<br/>', '\n'),
        ])
        render_rows.append({
            'item': f"<b>{_xml_escape(item_name)}</b>",
            'cells': plain_rows[-1],
            'sel_label': sel_label,
            'sel_colour': sel_colour,
            'sel_bg': sel_bg,
        })
        best_id = best['VENDOR_ID'] if best else None
        meta.append([
            bool(v1 and best_id and v1['VENDOR_ID'] == best_id),
            bool(v2 and best_id and v2['VENDOR_ID'] == best_id),
            bool(v3 and best_id and v3['VENDOR_ID'] == best_id),
        ])

    page_w, page_h = landscape(A4)
    margin = 10 * mm
    budget = page_w - 2 * margin
    padding = 4  # 2pt each side, set on the table below -- was 6 (3pt each side)

    # Auto-fit, stepping the font down only if the content genuinely can't
    # be laid out legibly at the preferred size. Range shifted down from
    # (7.5..5.5) to bring page count down for large item counts -- the
    # auto-fit logic itself is untouched, this just gives it a smaller
    # starting point and floor.
    widths = None
    body_size = 6.5
    for candidate in (6.5, 6.0, 5.5, 5.0, 4.5):
        widths = _autofit_comparison_widths(plain_rows, budget, candidate, candidate, padding)
        if widths:
            body_size = candidate
            break
    if not widths:  # pathological content: fall back to an even split
        body_size = 4.5
        widths = [budget / len(_CMP_HEADER_TOP)] * len(_CMP_HEADER_TOP)

    styles = getSampleStyleSheet()
    def _cell_style(name, align, bold=False, colour=INK):
        return ParagraphStyle(name, parent=styles['Normal'], fontName='Helvetica-Bold' if bold else 'Helvetica',
                              fontSize=body_size, leading=body_size + 1, textColor=colour, alignment=align)

    st_left = _cell_style('CmpLeft', TA_LEFT)
    st_centre = _cell_style('CmpCentre', TA_CENTER)
    st_right = _cell_style('CmpRight', TA_RIGHT)
    st_right_bold = _cell_style('CmpRightBold', TA_RIGHT, bold=True)
    st_muted = _cell_style('CmpMuted', TA_CENTER, colour=MUTED)
    st_head = ParagraphStyle('CmpHead', parent=styles['Normal'], fontName='Helvetica-Bold',
                             fontSize=body_size, leading=body_size + 2, textColor=INK, alignment=TA_CENTER)

    header_top = [Paragraph(_xml_escape(h), st_head) if h else '' for h in _CMP_HEADER_TOP]
    header_sub = [Paragraph(_xml_escape(h), st_head) if h else '' for h in _CMP_HEADER_SUB]

    table_data = [header_top, header_sub]
    for rr in render_rows:
        c = rr['cells']
        sel = Paragraph(f"<b><font color='{_hex(rr['sel_colour'])}'>{rr['sel_label']}</font></b>", st_centre)
        table_data.append([
            Paragraph(rr['item'], st_left),
            Paragraph(_xml_escape(c[1]), st_muted),
            Paragraph(_xml_escape(c[2]), st_centre), Paragraph(_xml_escape(c[3]), st_right_bold),
            Paragraph(_xml_escape(c[4]), st_centre), Paragraph(_xml_escape(c[5]), st_right),
            Paragraph(_xml_escape(c[6]), st_centre), Paragraph(_xml_escape(c[7]), st_right),
            Paragraph(_xml_escape(c[8]), st_centre), Paragraph(_xml_escape(c[9]), st_right),
            Paragraph(_xml_escape(c[10]), st_centre),
            Paragraph(_xml_escape(c[11]), st_centre), Paragraph(_xml_escape(c[12]), st_right_bold),
            sel,
        ])

    style_cmds = [
        ('GRID', (0, 0), (-1, -1), 0.4, BORDER),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('LEFTPADDING', (0, 0), (-1, -1), 2),
        ('RIGHTPADDING', (0, 0), (-1, -1), 2),
        ('TOPPADDING', (0, 0), (-1, -1), 2),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
        ('BACKGROUND', (0, 0), (-1, 1), HEADER_BG),
        # Two-tier header: rank bands span their Vendor/Cost pair, the
        # standalone columns span both header rows -- the rowspan/colspan
        # arrangement from the template's <thead>.
        ('SPAN', (0, 0), (0, 1)), ('SPAN', (1, 0), (1, 1)),
        ('SPAN', (2, 0), (3, 0)), ('SPAN', (4, 0), (5, 0)),
        ('SPAN', (6, 0), (7, 0)), ('SPAN', (8, 0), (9, 0)),
        ('SPAN', (10, 0), (10, 1)), ('SPAN', (11, 0), (12, 0)),
        ('SPAN', (13, 0), (13, 1)),
        ('ROWBACKGROUNDS', (0, 2), (-1, -1), [colors.white, ZEBRA]),
    ]
    # Column tints removed entirely, header and body both -- every table
    # cell now uses the same standard neutral background (ZEBRA via
    # ROWBACKGROUNDS above, or white), matching the rest of the table
    # with no distinct ranked-column banding at all.

    for i, rr in enumerate(render_rows):
        r = i + 2
        style_cmds.append(('BACKGROUND', (13, r), (13, r), rr['sel_bg']))
        # Winner ring removed -- was the last remaining green highlight
        # (a box border around the Best Bid vendor's own cell), separate
        # from the header/body tints removed earlier. No column-level
        # emphasis at all now, matching the plain, uniform table requested.

    if not render_rows:
        table_data.append([Paragraph('No items received bids for this month yet.', st_muted)]
                          + [''] * (len(_CMP_HEADER_TOP) - 1))
        style_cmds.append(('SPAN', (0, 2), (-1, 2)))

    table = Table(table_data, colWidths=widths, repeatRows=2, hAlign='LEFT')
    table.setStyle(TableStyle(style_cmds))

    reference_no = reference_no or f'CMP-{division}-{str(target_month)[:7]}'
    generated_at = datetime.now().strftime('%d-%b-%Y %H:%M')
    logo_path = _find_logo()

    def _furniture(canvas, page_num, page_count):
        canvas.saveState()
        top = page_h - 7 * mm
        text_x = margin
        if logo_path:
            try:
                canvas.drawImage(logo_path, margin, top - 7 * mm, width=18 * mm, height=7 * mm,
                                 preserveAspectRatio=True, anchor='sw', mask='auto')
                text_x = margin + 21 * mm
            except Exception:
                text_x = margin
        canvas.setFont('Helvetica-Bold', 10.5)
        canvas.setFillColor(PRIMARY)
        canvas.drawString(text_x, top - 3.5 * mm, 'Quotation Comparison Report')
        canvas.setFont('Helvetica', 6.5)
        canvas.setFillColor(MUTED)
        canvas.drawString(text_x, top - 7 * mm, 'Waste Sales Management')

        right = page_w - margin
        canvas.setFont('Helvetica', 6.5)
        canvas.setFillColor(MUTED)
        # Aligned with the "Waste Sales Management" subtitle's own line
        # (top - 7mm), not the main title above it.
        canvas.drawRightString(right, top - 7 * mm, f'Print: {generated_at}')
        canvas.setStrokeColor(BORDER)
        canvas.setLineWidth(0.6)
        # FIX: was top - 5.5mm, which sits ABOVE the subtitle at top - 7mm
        # (a smaller offset from the page top means higher on the page) --
        # the rule was actually being drawn straight through the subtitle
        # text instead of below it. Moved below both header lines, with
        # clearance before the story content begins at topMargin (19mm).
        canvas.line(margin, top - 10 * mm, right, top - 10 * mm)

        canvas.setFont('Helvetica', 7)
        canvas.setFillColor(MUTED)
        canvas.drawString(margin, 9 * mm, 'System Generated Report by ICT')
        canvas.drawRightString(right, 9 * mm, f'Page {page_num} of {page_count}')
        canvas.restoreState()

    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4),
                            topMargin=19 * mm, bottomMargin=12 * mm,
                            leftMargin=margin, rightMargin=margin,
                            title='Quotation Comparison Report')
    filter_style = ParagraphStyle('CmpFilters', parent=styles['Normal'], fontSize=7.5,
                                  textColor=INK, spaceAfter=4)
    filters = ' &nbsp;&nbsp;|&nbsp;&nbsp; '.join([
        f'Division: {_xml_escape(str(division_label))}',
        f'Month: {_xml_escape(str(month_label))}',
        f'{len(items)} items quoted',
    ])
    story = [Paragraph(filters, filter_style), table, _signature_block(budget, styles)]
    doc.build(story, canvasmaker=_make_numbered_canvas(_furniture))
    buf.seek(0)
    return buf.getvalue()


# ─── Gate Pass ───────────────────────────────────────────────────────
def build_gatepass_pdf(division_label, month_label, status_label, division, status, month, generated_by=None):
    records = fetch_all_gate_passes(division=division, status=status, month=month)
    headers = ['Gate Pass No', 'Module', 'Division', 'Sender', 'Receiver', 'Gate Pass Date', 'Status', 'Cancelled', 'Lines']
    rows = [[
        _fmt(r.get('GATE_PASS_ID')), _fmt(r.get('MODULE_TYPE')), _fmt(r.get('DIVISION')),
        _fmt(r.get('SENDER_NAME')), _fmt(r.get('RECEIVER_NAME')), _fmt(r.get('GATE_PASS_DATE')),
        _fmt(r.get('STATUS')), _fmt(r.get('CANCELLED_DATE')), _fmt(r.get('LINE_COUNT')),
    ] for r in records]
    filter_lines = [f'Division: {division_label}', f'Status: {status_label}', f'Month: {month_label}', f'{len(records)} entries']
    return _build_report_pdf(
        'Gate Pass Report', filter_lines, headers, rows,
        col_widths=[30 * mm, 24 * mm, 20 * mm, 40 * mm, 40 * mm, 30 * mm, 22 * mm, 26 * mm, 15 * mm],
        generated_by=generated_by, align_right_cols=[8],
    )


# ─── Gate Pass Detail (single pass, row-level PDF) ────────────────────
# Rebuilt to match the reference "Gate Pass" printout 1:1 rather than the
# masthead/box-field shell the other two detail reports use: centered
# underlined title, a stacked timestamp/page-number block top-right, a
# bold status stamp, a double rule, plain (unboxed) two-column fields,
# dotted rules bracketing the line-items table, a shaded Total box, and a
# Waste Incharge / Accounts / Security Incharge sign-off fixed at the
# bottom of the last page -- not flowing immediately after the table, so
# it always sits in the same place regardless of how many lines there are.
_GATEPASS_SIGNATURE_BLOCKS = ('Waste Incharge', 'Accounts', 'Security Incharge')
_GATEPASS_DOTTED = (1, 2)  # short dash + gap -> reads as a dotted rule


def _consolidate_gatepass_lines(lines):
    """Consolidates multiple Gate Pass lines for the SAME item into a
    single displayed row -- summing quantity, listing every contributing
    Sales Order comma-separated, and renumbering S.No sequentially per
    displayed row."""
    groups = {}
    order = []
    for l in lines:
        key = l.get('ITEM_ID') or l.get('ITEM_CODE')
        if key not in groups:
            groups[key] = {
                'ITEM_PREFIX': l.get('ITEM_PREFIX'),
                'ITEM_CODE': l.get('ITEM_CODE'),
                'ITEM_DESCRIPTION': l.get('ITEM_DESCRIPTION'),
                'UOM': l.get('UOM'),
                'GATEPASS_QTY': 0.0,
                'SO_DOC_IDS': [],
                'REMARKS': [],
            }
            order.append(key)
        g = groups[key]
        g['GATEPASS_QTY'] += float(l.get('GATEPASS_QTY') or 0)
        so_doc_id = l.get('SO_DOC_ID')
        if so_doc_id and str(so_doc_id).strip() and str(so_doc_id).strip() not in g['SO_DOC_IDS']:
            g['SO_DOC_IDS'].append(str(so_doc_id).strip())
        remark = (l.get('REMARKS') or '').strip()
        if remark and remark not in g['REMARKS']:
            g['REMARKS'].append(remark)

    consolidated = []
    for i, key in enumerate(order, start=1):
        g = groups[key]
        consolidated.append({
            'LINE_NO': i,
            'SO_DOC_ID': ', '.join(g['SO_DOC_IDS']),
            'ITEM_PREFIX': g['ITEM_PREFIX'],
            'ITEM_CODE': g['ITEM_CODE'],
            'ITEM_DESCRIPTION': g['ITEM_DESCRIPTION'],
            'UOM': g['UOM'],
            'GATEPASS_QTY': g['GATEPASS_QTY'],
            'REMARKS': '; '.join(g['REMARKS']),
        })
    return consolidated


def build_gate_pass_detail_pdf(gate_pass_id, division=None, generated_by=None):
    header = fetch_gate_pass_by_id(gate_pass_id, division=division)
    if not header:
        return None
    lines = _consolidate_gatepass_lines(fetch_gate_pass_lines(gate_pass_id))

    page_w, page_h = 722.85, 841.6  # Custom size matched to the reference
    # Datatex-format report: 255mm x 297mm, not standard A4 (210x297mm).
    margin = 8 * mm
    top_margin = 40 * mm
    bottom_margin = 45 * mm

    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=(page_w, page_h),
        topMargin=top_margin,
        bottomMargin=bottom_margin,
        leftMargin=margin,
        rightMargin=margin
    )
    styles = getSampleStyleSheet()

    # Base text styles -- sizes matched exactly to the reference PDF's own
    # embedded font metadata (extracted directly via pdfplumber, not
    # estimated visually): field labels/values both 8pt, labels bold.
    label_style = ParagraphStyle(
        'FieldLabel', parent=styles['Normal'], fontSize=8,
        fontName='Helvetica-Bold', textColor=colors.black, leading=10.5
    )
    value_style = ParagraphStyle(
        'FieldValue', parent=styles['Normal'], fontSize=8,
        textColor=colors.black, leading=10.5
    )
    empty_style = ParagraphStyle(
        'EmptyState', parent=styles['Normal'], fontSize=9,
        textColor=colors.HexColor('#666666'), spaceBefore=8
    )
    wrap_style = ParagraphStyle(
        'WrapCell', parent=styles['Normal'], fontSize=8, leading=10, textColor=colors.black
    )

    def _cell(label, value):
        return [
            Paragraph(_xml_escape(str(label or '')), label_style),
            Paragraph(_xml_escape(_fmt(value)), value_style)
        ]

    # Ship To and Sender Department deliberately have no colon, matching
    # the reference exactly -- an inconsistency in the source format, but
    # reproduced faithfully rather than "corrected".
    field_rows = [
        _cell('Gate Pass No :', header.get('GATE_PASS_ID')) + _cell('Gate Pass Date :', header.get('GATE_PASS_DATE')),
        _cell('Document Type :', header.get('DOCUMENT_TYPE')) + _cell('Ship To', header.get('SHIP_TO')),
        _cell('Sender Name :', header.get('SENDER_NAME')) + _cell('Sender Department', header.get('DEPT_NAME')),
        _cell('Vehicle  Type :', header.get('VEHICLE_TYPE')) + _cell('Vehicle/Container #', header.get('VEHICLE_NO')),
        _cell('Driver Name :', header.get('DRIVER_NAME')) + _cell('Receiver Name :', header.get('RECEIVER_NAME')),
        _cell('Remarks :', header.get('REMARKS')) + ['', ''],
    ]
    if header.get('CANCELLED_BY'):
        field_rows.append(
            _cell('Cancelled By :', header.get('CANCELLED_BY')) +
            _cell('Cancelled Date :', header.get('CANCELLED_DATE'))
        )

    # Label columns narrowed to match the reference's tighter label widths
    # (measured ~31-34mm there vs the old 38mm), giving the value columns
    # the extra room freed up by the wider page and narrower margins.
    field_table = Table(field_rows, colWidths=[32 * mm, 87 * mm, 32 * mm, 88 * mm])
    field_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 6),
    ]))
    story = [field_table, Spacer(1, 4 * mm)]

    # 8 headers matching 8 table columns. Doc.No/Ref#, Prefix, and Item
    # Code headers stay for layout, but their data cells are left
    # genuinely blank below -- not white text, which would still embed
    # the real values in the PDF's extractable text layer even though
    # they're invisible to the eye.
    headers2 = ['S.No', 'Doc.No/\nRef#', 'Prefix', 'Item\nCode', 'Item\nDescription', 'UOM', 'Quantity', 'Remarks']
    header_style = ParagraphStyle(
        'ColHeader', parent=styles['Normal'], fontSize=8, leading=10,
        fontName='Helvetica-Bold', textColor=colors.black, alignment=TA_CENTER
    )
    header_cells = [Paragraph(h.replace('\n', '<br/>'), header_style) for h in headers2]

    rows2 = []
    for l in lines:
        rows2.append([
            str(l.get('LINE_NO', '')),
            '',  # Doc.No/Ref# -- deliberately left blank, not populated from SO_DOC_ID
            '',  # Prefix -- deliberately left blank, not populated from ITEM_PREFIX
            '',  # Item Code -- deliberately left blank, not populated from ITEM_CODE
            Paragraph(_xml_escape(_fmt(l.get('ITEM_DESCRIPTION'), default='')), wrap_style),
            _fmt(l.get('UOM'), default=''),
            _fmt_num(l.get('GATEPASS_QTY'), default=''),
            Paragraph(_xml_escape(_fmt(l.get('REMARKS'), default='')), wrap_style),
        ])

    if rows2:
        total_qty = sum(float(l.get('GATEPASS_QTY') or 0) for l in lines)
        total_row_idx = len(rows2) + 1  # 1-indexed count considering header at index 0
        total_label_style = ParagraphStyle(
            'TotalLabel', parent=styles['Normal'],
            fontSize=8, fontName='Helvetica-Bold', alignment=TA_RIGHT
        )

        rows2.append([
            Paragraph('Total :', total_label_style),
            '', '', '', '', '',
            _fmt_num(total_qty),
            ''
        ])

        col_widths = [10 * mm, 22 * mm, 14 * mm, 20 * mm, None, 12 * mm, 20 * mm, 25 * mm]
        t = Table([header_cells] + rows2, colWidths=col_widths, repeatRows=1, hAlign='LEFT')
        t.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#BFBFBF')),
            ('LINEABOVE', (0, 0), (-1, 0), 1, colors.black, None, _GATEPASS_DOTTED),
            ('LINEBELOW', (0, 0), (-1, 0), 1, colors.black, None, _GATEPASS_DOTTED),
            ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 1), (-1, -1), 7.5),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('ALIGN', (0, 0), (3, -1), 'CENTER'),   # S.No, Doc.No, Prefix, Item Code
            ('ALIGN', (4, 0), (4, -1), 'LEFT'),     # Item Description
            ('ALIGN', (5, 0), (6, -1), 'CENTER'),   # UOM & Quantity
            ('ALIGN', (7, 0), (7, -1), 'LEFT'),     # Remarks
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
            ('LEFTPADDING', (0, 0), (-1, -1), 3),
            ('RIGHTPADDING', (0, 0), (-1, -1), 3),
            # Total Row Styling
            ('LINEABOVE', (0, total_row_idx), (-1, total_row_idx), 1, colors.black, None, _GATEPASS_DOTTED),
            ('SPAN', (0, total_row_idx), (4, total_row_idx)),
            ('ALIGN', (0, total_row_idx), (4, total_row_idx), 'RIGHT'),
            ('FONTNAME', (0, total_row_idx), (4, total_row_idx), 'Helvetica-Bold'),
            ('FONTNAME', (6, total_row_idx), (6, total_row_idx), 'Helvetica-Bold'),
            ('FONTSIZE', (0, total_row_idx), (-1, total_row_idx), 8),
            ('ALIGN', (6, total_row_idx), (6, total_row_idx), 'CENTER'),
            ('BACKGROUND', (6, total_row_idx), (6, total_row_idx), colors.HexColor('#BFBFBF')),
            ('BOX', (6, total_row_idx), (6, total_row_idx), 0.5, colors.black),
        ]))
        story.append(t)
    else:
        story.append(Paragraph("No line items on this gate pass.", empty_style))

    status_text = _fmt(header.get('STATUS'))
    stamp_text = datetime.now().strftime('%d-%b-%Y  %H:%M:%S')

    def _furniture(canvas, page_num, page_count):
        canvas.saveState()
        top_y = page_h - margin

        title = 'Gate Pass'
        canvas.setFont('Helvetica-Bold', 24)
        canvas.setFillColor(colors.black)
        title_w = canvas.stringWidth(title, 'Helvetica-Bold', 24)
        title_x = (page_w - title_w) / 2
        canvas.drawString(title_x, top_y - 18, title)
        canvas.setLineWidth(1.3)
        canvas.line(title_x, top_y - 21, title_x + title_w, top_y - 21)

        canvas.setFont('Helvetica', 8)
        canvas.drawRightString(page_w - margin, top_y - 6, stamp_text)
        canvas.drawRightString(page_w - margin, top_y - 18, f"Page {page_num} of {page_count}")

        canvas.setFont('Helvetica-Bold', 10)
        canvas.drawRightString(page_w - margin, top_y - 34, status_text)

        canvas.setLineWidth(1)
        canvas.line(margin, top_y - 40, page_w - margin, top_y - 40)
        canvas.line(margin, top_y - 42, page_w - margin, top_y - 42)

        if page_num == page_count:
            sig_y = 29.5 * mm
            n = len(_GATEPASS_SIGNATURE_BLOCKS)
            usable = page_w - 2 * margin
            col_w = usable / n
            canvas.setLineWidth(0.75)
            canvas.setFont('Helvetica-Bold', 8)
            for i, label in enumerate(_GATEPASS_SIGNATURE_BLOCKS):
                cx = margin + col_w * i + col_w / 2
                line_half = col_w * 0.32
                canvas.line(cx - line_half, sig_y, cx + line_half, sig_y)
                canvas.drawCentredString(cx, sig_y - 12, label)
        canvas.restoreState()

    doc.build(story, canvasmaker=_make_numbered_canvas(_furniture))
    buf.seek(0)
    return buf.getvalue()