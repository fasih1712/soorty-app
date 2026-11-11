"""
Phase 4 - turns fetched rows into report "specs" (see exporters.py).
Pure: no database, no request. URLs are supplied by the caller.
"""
from decimal import Decimal

from . import reports

_MONEY, _TEXT, _DATE, _INT = 'money', 'text', 'date', 'int'


def _col(key, label, kind=_TEXT):
    return {'key': key, 'label': label, 'kind': kind}


def _spec(title, subtitle, filters, sections, ctx):
    return {'title': title, 'subtitle': subtitle, 'filters': filters, 'sections': sections,
            'generated_by': ctx.get('generated_by', ''), 'generated_at': ctx.get('generated_at', '')}


def _range_text(d_from, d_to):
    return f'{d_from:%d-%b-%Y} to {d_to:%d-%b-%Y}'


def _link(row, key, url):
    if url:
        row.setdefault('_links', {})[key] = url
    return row


# 1 -------------------------------------------------------------------------
def statement_spec(customer, division, d_from, d_to, opening, lines, ctx):
    rows, totals = reports.build_statement(opening, lines)
    out = []
    for r in rows:
        out.append(_link({'DATE': r['VOUCHER_DATE'], 'VOUCHER_NO': r['VOUCHER_NO'], 'DESCRIPTION': r['DESCRIPTION'],
                          'NARRATION': r.get('NARRATION') or '', 'RECEIVED': r['CREDIT'], 'APPLIED': r['DEBIT'],
                          'BALANCE': r['BALANCE']}, 'VOUCHER_NO', ctx['voucher_url'](r['VOUCHER_ID'])))
    cols = [_col('DATE', 'Date', _DATE), _col('VOUCHER_NO', 'Voucher'), _col('DESCRIPTION', 'Description'),
            _col('NARRATION', 'Narration'), _col('RECEIVED', 'Received', _MONEY),
            _col('APPLIED', 'Applied / paid out', _MONEY), _col('BALANCE', 'Balance', _MONEY)]
    summary = [{'LABEL': 'Opening balance', 'AMOUNT': totals['OPENING']},
               {'LABEL': 'Received in the period', 'AMOUNT': totals['RECEIVED']},
               {'LABEL': 'Applied to dispatches / paid out', 'AMOUNT': totals['APPLIED']},
               {'LABEL': 'Closing balance (advance remaining)', 'AMOUNT': totals['CLOSING']}]
    sections = [
        {'heading': 'Summary', 'columns': [_col('LABEL', ''), _col('AMOUNT', 'Amount', _MONEY)], 'rows': summary, 'totals': None},
        {'heading': 'Transactions', 'columns': cols, 'rows': out,
         'totals': {'DATE': 'Period total', 'RECEIVED': totals['RECEIVED'], 'APPLIED': totals['APPLIED'], 'BALANCE': totals['CLOSING']},
         'note': 'Reversed entries appear together with their reversal, so they cancel out.'}]
    filters = [('Customer', customer), ('Period', _range_text(d_from, d_to)), ('Division', division or 'All')]
    return _spec('Customer Advance Statement', 'Prepaid balance: receipts, dispatch knock-offs and the advance remaining',
                 filters, sections, ctx), totals


# 2 -------------------------------------------------------------------------
def trial_balance_spec(division, cutoff, raw_rows, ctx):
    rows, totals = reports.trial_balance(raw_rows)
    out = []
    for r in rows:
        out.append(_link({'CODE': r['ACCOUNT_CODE'], 'NAME': r['ACCOUNT_NAME'], 'TYPE': r['ACCOUNT_TYPE'].title(),
                          'DEBIT': r['DEBIT'], 'CREDIT': r['CREDIT'],
                          'DEBIT_BALANCE': r['DEBIT_BALANCE'], 'CREDIT_BALANCE': r['CREDIT_BALANCE']},
                         'CODE', ctx['ledger_url'](r['ACCOUNT_ID'])))
    cols = [_col('CODE', 'Code'), _col('NAME', 'Account'), _col('TYPE', 'Type'), _col('DEBIT', 'Total debits', _MONEY),
            _col('CREDIT', 'Total credits', _MONEY), _col('DEBIT_BALANCE', 'Debit balance', _MONEY),
            _col('CREDIT_BALANCE', 'Credit balance', _MONEY)]
    note = ('Trial balance agrees: total debits equal total credits.' if totals['BALANCED']
            else 'WARNING: the trial balance does NOT agree. Run the Reconciliation Check.')
    sections = [{'heading': None, 'columns': cols, 'rows': out, 'note': note,
                 'totals': {'NAME': 'Total', 'DEBIT': totals['DEBIT'], 'CREDIT': totals['CREDIT'],
                            'DEBIT_BALANCE': totals['DEBIT_BALANCE'], 'CREDIT_BALANCE': totals['CREDIT_BALANCE']}}]
    return _spec('Trial Balance', f'As at {cutoff:%d-%b-%Y}', [('Division', division or 'All')], sections, ctx), totals


def general_ledger_spec(account, division, d_from, d_to, opening, lines, ctx):
    rows, totals = reports.build_general_ledger(opening, lines)
    out = []
    for r in rows:
        out.append(_link({'DATE': r['VOUCHER_DATE'], 'VOUCHER_NO': r['VOUCHER_NO'], 'TYPE': r['TYPE_CODE'],
                          'DIVISION': r['DIVISION'], 'PARTY': r.get('PARTY_NAME') or '', 'NARRATION': r.get('NARRATION') or '',
                          'DEBIT': r['DEBIT'], 'CREDIT': r['CREDIT'], 'BALANCE': r['BALANCE']},
                         'VOUCHER_NO', ctx['voucher_url'](r['VOUCHER_ID'])))
    cols = [_col('DATE', 'Date', _DATE), _col('VOUCHER_NO', 'Voucher'), _col('TYPE', 'Type'), _col('DIVISION', 'Division'),
            _col('PARTY', 'Customer'), _col('NARRATION', 'Narration'), _col('DEBIT', 'Debit', _MONEY),
            _col('CREDIT', 'Credit', _MONEY), _col('BALANCE', 'Balance (Dr + / Cr -)', _MONEY)]
    opening_row = {'DATE': '', 'VOUCHER_NO': '', 'NARRATION': 'Opening balance', 'BALANCE': totals['OPENING']}
    sections = [{'heading': None, 'columns': cols, 'rows': [opening_row] + out,
                 'totals': {'NARRATION': 'Period total / closing', 'DEBIT': totals['DEBIT'], 'CREDIT': totals['CREDIT'],
                            'BALANCE': totals['CLOSING']},
                 'note': 'Click a voucher number to see every line of that voucher.'}]
    filters = [('Account', f"{account['ACCOUNT_CODE']} - {account['ACCOUNT_NAME']}"),
               ('Period', _range_text(d_from, d_to)), ('Division', division or 'All')]
    return _spec('General Ledger', 'Every entry on one account head, with running balance', filters, sections, ctx), totals


# 3 -------------------------------------------------------------------------
def sales_spec(division, d_from, d_to, granularity, raw_rows, ctx):
    rows, totals = reports.summarise_sales(raw_rows, granularity)
    cols = [_col('PERIOD', 'Day' if granularity == 'day' else 'Month'), _col('DIVISION', 'Division'),
            _col('SALES', 'Dispatch sales', _MONEY), _col('NOTES', 'Debit - credit notes', _MONEY),
            _col('NET_SALES', 'Net sales', _MONEY), _col('COLLECTIONS', 'Advances collected', _MONEY),
            _col('DIFFERENCE', 'Collected less sales', _MONEY)]
    sections = [{'heading': None, 'columns': cols, 'rows': rows,
                 'totals': {'PERIOD': 'Total', **{k: totals[k] for k in ('SALES', 'NOTES', 'NET_SALES', 'COLLECTIONS', 'DIFFERENCE')}},
                 'note': 'Dispatch sales are shipped quantity x price from posted Gate Passes (cancelled ones net out). '
                         'Advances collected exclude the one-time opening balances, refunds and transfers.'}]
    filters = [('Period', _range_text(d_from, d_to)), ('Division', division or 'All'), ('Grouped by', granularity)]
    return _spec('Sales and Collections Summary', 'Dispatches against advance collections', filters, sections, ctx), totals


# 4 -------------------------------------------------------------------------
def _items_section(check):
    items = check['ITEMS']
    keys = list(items[0].keys())
    cols = []
    for k in keys:
        sample = items[0][k]
        kind = _MONEY if isinstance(sample, Decimal) else _TEXT
        cols.append(_col(k, k.replace('_', ' ').title(), kind))
    return {'heading': f"Details: {check['NAME']}", 'columns': cols, 'rows': items, 'totals': None}


def reconciliation_spec(checks, ctx):
    ok = reports.overall(checks)
    rows = [{'CHECK': c['NAME'], 'RESULT': 'OK' if c['STATUS'] == 'OK' else 'FAILED', 'DETAIL': c['DETAIL']} for c in checks]
    sections = [{'heading': None, 'columns': [_col('CHECK', 'Control check'), _col('RESULT', 'Result'), _col('DETAIL', 'Detail')],
                 'rows': rows, 'totals': None}]
    sections += [_items_section(c) for c in checks if c['ITEMS']]
    verdict = 'ALL CHECKS PASSED' if ok else f"{sum(1 for c in checks if c['STATUS'] != 'OK')} CHECK(S) FAILED"
    return _spec('Reconciliation Check', 'Sub-ledgers against control accounts, and Gate Passes finance has not seen',
                 [('Result', verdict)], sections, ctx), ok


# 5 -------------------------------------------------------------------------
def ageing_spec(division, as_of, raw_rows, ctx):
    customers, totals = reports.age_advances(raw_rows, as_of)
    labels = [b[0] for b in reports.AGEING_BUCKETS]
    cols = [_col('PARTY_NAME', 'Customer')] + [_col(l, l, _MONEY) for l in labels] + \
           [_col('TOTAL', 'Total', _MONEY), _col('OLDEST_DAYS', 'Oldest (days)', _INT)]
    sections = [{'heading': None, 'columns': cols, 'rows': customers,
                 'totals': {'PARTY_NAME': 'Total', **totals},
                 'note': 'Age is counted from the date the advance was received. Dispatches use the oldest advance first, '
                         'so what is left is the newest money.'}]
    return _spec('Advance Ageing', f'Unused customer advance by age, as at {as_of:%d-%b-%Y}',
                 [('Division', division or 'All')], sections, ctx), totals


# ------------------------------------------------------------ HTML helper
def html_table(section):
    """Header / body / totals as plain dicts for the template (formatting done here)."""
    from .exporters import format_cell
    cols = section['columns']
    right = [c['kind'] in ('money', 'int') for c in cols]
    head = [{'label': c['label'], 'right': right[i]} for i, c in enumerate(cols)]
    body = []
    for r in section['rows']:
        links = r.get('_links', {})
        body.append([{'text': format_cell(c['kind'], r.get(c['key'])), 'right': right[i], 'url': links.get(c['key']),
                      'tone': ('ok' if r.get(c['key']) == 'OK' else 'bad') if c['key'] == 'RESULT' else ''}
                     for i, c in enumerate(cols)])
    total = None
    if section.get('totals'):
        total = [{'text': format_cell(c['kind'], section['totals'].get(c['key'])), 'right': right[i]} for i, c in enumerate(cols)]
    return {'heading': section.get('heading'), 'head': head, 'body': body, 'total': total, 'note': section.get('note')}
