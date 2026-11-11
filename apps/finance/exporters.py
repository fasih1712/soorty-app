"""
Phase 4 - turns a report "spec" into HTML cells, an Excel file or a PDF.

A spec is a plain dict built by views.py:
  {'title', 'subtitle', 'filters': [(label, value)], 'generated_by', 'generated_at',
   'sections': [{'heading', 'columns': [{'key','label','kind'}], 'rows': [dict],
                 'totals': dict or None, 'note': str or None}]}
kind is one of: text, date, int, money.

The report libraries are imported only when a file is requested, so the
rest of the Finance module still loads if they are not installed yet.
"""
import io
import re
from decimal import Decimal
from xml.sax.saxutils import escape

MONEY_KINDS = ('money',)
_FORMULA_START = ('=', '+', '-', '@', '\t', '\r')


class ExportUnavailable(Exception):
    """pip package missing on the server."""


def format_cell(kind, value):
    if value is None or value == '':
        return ''
    if kind == 'money':
        return f'{Decimal(str(value)):,.2f}'
    if kind == 'int':
        return f'{int(value):,}'
    return str(value)


def safe_filename(title, ext):
    stem = re.sub(r'[^A-Za-z0-9]+', '_', title).strip('_') or 'report'
    return f'{stem}.{ext}'


def table_rows(section):
    """Header + formatted body + totals as lists of strings (used by PDF and tests)."""
    cols = section['columns']
    head = [c['label'] for c in cols]
    body = [[format_cell(c['kind'], r.get(c['key'])) for c in cols] for r in section['rows']]
    if section.get('totals'):
        body.append([format_cell(c['kind'], section['totals'].get(c['key'])) for c in cols])
    return head, body


# ------------------------------------------------------------------- Excel
def to_xlsx(spec):
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Alignment, Font, PatternFill
        from openpyxl.utils import get_column_letter
    except ImportError as exc:
        raise ExportUnavailable('Excel export needs the "openpyxl" package (pip install openpyxl).') from exc

    wb = Workbook()
    ws = wb.active
    ws.title = re.sub(r'[\[\]\*\?/\\:]', ' ', spec['title'])[:31] or 'Report'
    navy, gold = '1B2A41', 'C9A227'
    row = 1

    def put(r, c, value, kind='text', bold=False, fill=None, color=None):
        cell = ws.cell(row=r, column=c)
        if kind == 'money' and value not in (None, ''):
            cell.value = Decimal(str(value))
            cell.number_format = '#,##0.00;[Red]-#,##0.00'
            cell.alignment = Alignment(horizontal='right')
        elif kind == 'int' and value not in (None, ''):
            cell.value = int(value)
            cell.number_format = '#,##0'
        else:
            cell.value = '' if value is None else str(value)
            cell.data_type = 's'          # never let user-typed text become a formula
        if bold or color:
            cell.font = Font(bold=bold, color=color)
        if fill:
            cell.fill = PatternFill('solid', fgColor=fill)
        return cell

    put(row, 1, spec['title'], bold=True).font = Font(bold=True, size=14, color=navy)
    row += 1
    if spec.get('subtitle'):
        put(row, 1, spec['subtitle'])
        row += 1
    for label, value in spec.get('filters', []):
        put(row, 1, f'{label}: {value}')
        row += 1
    put(row, 1, f"Generated {spec.get('generated_at', '')} by {spec.get('generated_by', '')}")
    row += 2

    widths = {}
    for section in spec['sections']:
        if section.get('heading'):
            put(row, 1, section['heading'], bold=True).font = Font(bold=True, size=12, color=navy)
            row += 1
        for i, col in enumerate(section['columns'], 1):
            put(row, i, col['label'], bold=True, fill=navy, color='FFFFFF')
            widths[i] = max(widths.get(i, 10), len(col['label']) + 2)
        row += 1
        for r in section['rows']:
            for i, col in enumerate(section['columns'], 1):
                v = r.get(col['key'])
                put(row, i, v, col['kind'])
                widths[i] = min(max(widths.get(i, 10), len(format_cell(col['kind'], v)) + 2), 60)
            row += 1
        if section.get('totals'):
            for i, col in enumerate(section['columns'], 1):
                put(row, i, section['totals'].get(col['key']), col['kind'], bold=True, fill='F3E9C6')
            row += 1
        if section.get('note'):
            put(row, 1, section['note'])
            row += 1
        row += 1
    for i, w in widths.items():
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.sheet_view.showGridLines = False
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# --------------------------------------------------------------------- PDF
def to_pdf(spec):
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import mm
        from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    except ImportError as exc:
        raise ExportUnavailable('PDF export needs the "reportlab" package (pip install reportlab).') from exc

    navy, gold = colors.HexColor('#1B2A41'), colors.HexColor('#C9A227')
    widest = max((len(s['columns']) for s in spec['sections']), default=1)
    page = landscape(A4) if widest > 5 else A4
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=page, leftMargin=12 * mm, rightMargin=12 * mm,
                            topMargin=14 * mm, bottomMargin=16 * mm, title=spec['title'], author='Soorty ERP')
    styles = getSampleStyleSheet()
    h1 = ParagraphStyle('h1', parent=styles['Title'], textColor=navy, fontSize=16, alignment=0, spaceAfter=2)
    h2 = ParagraphStyle('h2', parent=styles['Heading3'], textColor=navy, spaceBefore=8)
    small = ParagraphStyle('small', parent=styles['Normal'], fontSize=8, textColor=colors.HexColor('#555555'))
    cell = ParagraphStyle('cell', parent=styles['Normal'], fontSize=7.5, leading=9)
    cell_r = ParagraphStyle('cellr', parent=cell, alignment=2)
    head = ParagraphStyle('head', parent=cell, textColor=colors.white, fontName='Helvetica-Bold')
    head_r = ParagraphStyle('headr', parent=head, alignment=2)

    story = [Paragraph(escape(spec['title']), h1)]
    if spec.get('subtitle'):
        story.append(Paragraph(escape(spec['subtitle']), small))
    for label, value in spec.get('filters', []):
        story.append(Paragraph(f'<b>{escape(label)}:</b> {escape(str(value))}', small))
    story.append(Paragraph(escape(f"Generated {spec.get('generated_at', '')} by {spec.get('generated_by', '')}"), small))
    story.append(Spacer(1, 4 * mm))

    usable = page[0] - 24 * mm
    for section in spec['sections']:
        if section.get('heading'):
            story.append(Paragraph(escape(section['heading']), h2))
        cols = section['columns']
        weights = [1.0 if c['kind'] in ('money', 'int') else (1.0 if c['kind'] == 'date' else 2.2) for c in cols]
        widths = [usable * w / sum(weights) for w in weights]
        right = [c['kind'] in ('money', 'int') for c in cols]
        header, body = table_rows(section)
        data = [[Paragraph(escape(h), head_r if right[i] else head) for i, h in enumerate(header)]]
        for r in body:
            data.append([Paragraph(escape(v), cell_r if right[i] else cell) for i, v in enumerate(r)])
        if not body:
            data.append([Paragraph('No data for these filters.', cell)] + [''] * (len(cols) - 1))
        table = Table(data, colWidths=widths, repeatRows=1)
        style = [('BACKGROUND', (0, 0), (-1, 0), navy), ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                 ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F6F7FA')]),
                 ('LINEBELOW', (0, 0), (-1, -1), 0.25, colors.HexColor('#D8DCE3'))]
        if section.get('totals'):
            style += [('BACKGROUND', (0, -1), (-1, -1), colors.HexColor('#F3E9C6')),
                      ('LINEABOVE', (0, -1), (-1, -1), 0.8, gold)]
        table.setStyle(TableStyle(style))
        story.append(table)
        if section.get('note'):
            story.append(Spacer(1, 2 * mm))
            story.append(Paragraph(escape(section['note']), small))

    def footer(canvas, document):
        canvas.saveState()
        canvas.setFont('Helvetica', 7)
        canvas.setFillColor(colors.HexColor('#777777'))
        canvas.drawString(12 * mm, 8 * mm, 'Soorty ERP - Finance - Confidential')
        canvas.drawRightString(page[0] - 12 * mm, 8 * mm, f'Page {document.page}')
        canvas.restoreState()

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return buf.getvalue()
