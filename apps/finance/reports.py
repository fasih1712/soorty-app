"""
Phase 4 - report rules. PURE functions: no database, no Django.

The SQL in data.py only fetches plain rows; every sum, running balance,
bucket and check lives here so it can be tested without Oracle.

Sign conventions
  * Customer advance (a liability): balance = credits - debits.
  * Trial balance / general ledger: net = debits - credits.
  * Reversed vouchers stay in the books together with their mirror (RVS)
    voucher, so both are included everywhere and net to zero.
"""
from datetime import date, timedelta
from decimal import Decimal

from .ledger import ZERO, FinanceRuleError, as_date, money

MAX_RANGE_DAYS = 3660          # ten years; stops accidental "all time" pulls
AGEING_BUCKETS = (('0-30 days', 0, 30), ('31-60 days', 31, 60), ('61-90 days', 61, 90), ('Over 90 days', 91, None))
GRANULARITIES = ('day', 'month')


# ------------------------------------------------------------ date filters
def parse_range(raw_from, raw_to, today=None):
    """Both optional: defaults to 1st of this month .. today."""
    today = today or date.today()
    try:
        d_to = as_date(raw_to) if raw_to else today
        d_from = as_date(raw_from) if raw_from else d_to.replace(day=1)
    except ValueError:
        raise FinanceRuleError('Dates must look like 2026-11-30.')
    if d_from > d_to:
        raise FinanceRuleError('"From" date cannot be after "To" date.')
    if (d_to - d_from).days > MAX_RANGE_DAYS:
        raise FinanceRuleError('Choose a range of at most ten years.')
    return d_from, d_to


def parse_as_of(raw, today=None):
    try:
        return as_date(raw) if raw else (today or date.today())
    except ValueError:
        raise FinanceRuleError('Date must look like 2026-11-30.')


def parse_granularity(raw):
    raw = (raw or 'month').strip().lower()
    if raw not in GRANULARITIES:
        raise FinanceRuleError('Group by must be day or month.')
    return raw


# --------------------------------------------- 1. customer advance statement
def statement_label(type_code, source_type, adj_type, debit, credit):
    """Plain-English description of one customer-advance line."""
    if type_code == 'RVS':
        return 'Reversal'
    if source_type == 'OPENING':
        return 'Opening balance loaded'
    if source_type == 'ADVANCE':
        return 'Advance received'
    if source_type == 'GATEPASS':
        return 'Dispatch knock-off'
    if source_type == 'ADJUSTMENT':
        if adj_type == 'REFUND':
            return 'Refund paid'
        if adj_type == 'CREDIT_NOTE':
            return 'Credit note returned to advance'
        if adj_type == 'DEBIT_NOTE':
            return 'Debit note paid from advance'
        if adj_type == 'TRANSFER':
            return 'Transfer out' if money(debit) > 0 else 'Transfer in'
        return 'Adjustment'
    return 'Entry'


def build_statement(opening, lines):
    """lines: oldest first, each with DEBIT / CREDIT. Returns (rows, totals)."""
    running = money(opening)
    received = applied = ZERO
    rows = []
    for ln in lines:
        d, c = money(ln['DEBIT']), money(ln['CREDIT'])
        running += c - d
        received += c
        applied += d
        rows.append({**ln, 'DESCRIPTION': statement_label(ln.get('TYPE_CODE'), ln.get('SOURCE_TYPE'),
                                                          ln.get('ADJ_TYPE'), d, c),
                     'DEBIT': d, 'CREDIT': c, 'BALANCE': running})
    totals = {'OPENING': money(opening), 'RECEIVED': received, 'APPLIED': applied, 'CLOSING': running}
    if totals['CLOSING'] != totals['OPENING'] + received - applied:   # defensive; cannot happen
        raise FinanceRuleError('Statement does not add up.')
    return rows, totals


# --------------------------------------------------------- 2. trial balance
def trial_balance(rows):
    """rows: ACCOUNT_ID/CODE/NAME/TYPE, DEBIT, CREDIT (period totals up to the date).
    Accounts with no activity are dropped. Returns (rows, totals)."""
    out = []
    t_debit = t_credit = t_dbal = t_cbal = ZERO
    for r in rows:
        d, c = money(r['DEBIT'] or 0), money(r['CREDIT'] or 0)
        if d == 0 and c == 0:
            continue
        net = d - c
        dbal = net if net > 0 else ZERO
        cbal = -net if net < 0 else ZERO
        out.append({**r, 'DEBIT': d, 'CREDIT': c, 'DEBIT_BALANCE': dbal, 'CREDIT_BALANCE': cbal})
        t_debit += d
        t_credit += c
        t_dbal += dbal
        t_cbal += cbal
    totals = {'DEBIT': t_debit, 'CREDIT': t_credit, 'DEBIT_BALANCE': t_dbal, 'CREDIT_BALANCE': t_cbal,
              'BALANCED': t_debit == t_credit and t_dbal == t_cbal}
    return out, totals


# ---------------------------------------------------------- general ledger
def build_general_ledger(opening_net, lines):
    """Running debit-minus-credit balance. Returns (rows, totals)."""
    running = money(opening_net)
    t_d = t_c = ZERO
    rows = []
    for ln in lines:
        d, c = money(ln['DEBIT']), money(ln['CREDIT'])
        running += d - c
        t_d += d
        t_c += c
        rows.append({**ln, 'DEBIT': d, 'CREDIT': c, 'BALANCE': running})
    return rows, {'OPENING': money(opening_net), 'DEBIT': t_d, 'CREDIT': t_c, 'CLOSING': running}


# ------------------------------------------- 3. sales & collections summary
def period_key(value, granularity):
    d = as_date(value)
    return d.strftime('%Y-%m-%d') if granularity == 'day' else d.strftime('%Y-%m')


def summarise_sales(rows, granularity):
    """rows: PERIOD_DATE, DIVISION, SYSTEM_KEY, SOURCE_TYPE, NET (credit minus debit).

    sales        = net credits on Sales Income (dispatches, less cancelled ones)
    notes        = net on Sales Returns: debit notes (+) minus credit notes (-)
    collections  = advances received (net of reversed receipts); the one-time
                   opening balances are NOT collections and are left out."""
    buckets = {}
    for r in rows:
        key = (period_key(r['PERIOD_DATE'], granularity), r['DIVISION'])
        b = buckets.setdefault(key, {'PERIOD': key[0], 'DIVISION': key[1],
                                     'SALES': ZERO, 'NOTES': ZERO, 'COLLECTIONS': ZERO})
        net = money(r['NET'])
        if r['SYSTEM_KEY'] == 'SALES_INCOME':
            b['SALES'] += net
        elif r['SYSTEM_KEY'] == 'SALES_RETURNS':
            b['NOTES'] += net
        elif r['SYSTEM_KEY'] == 'CUSTOMER_ADVANCE' and r['SOURCE_TYPE'] == 'ADVANCE':
            b['COLLECTIONS'] += net
    out = []
    totals = {'SALES': ZERO, 'NOTES': ZERO, 'NET_SALES': ZERO, 'COLLECTIONS': ZERO, 'DIFFERENCE': ZERO}
    for key in sorted(buckets):
        b = buckets[key]
        b['NET_SALES'] = b['SALES'] + b['NOTES']
        b['DIFFERENCE'] = b['COLLECTIONS'] - b['NET_SALES']
        if all(b[k] == 0 for k in ('SALES', 'NOTES', 'COLLECTIONS')):
            continue
        out.append(b)
        for k in totals:
            totals[k] += b[k]
    return out, totals


# ------------------------------------------------------ 4. reconciliation
def _check(name, ok, detail, items=None):
    return {'NAME': name, 'STATUS': 'OK' if ok else 'FAIL', 'DETAIL': detail, 'ITEMS': items or []}


def reconcile(data):
    """data keys (all Decimal-able unless noted):
        control_advance      - Customer Advances account, credits - debits
        ledger_by_party      - [{PARTY_ID, PARTY_NAME, AMOUNT}] voucher-based per customer
        subledger_by_party   - [{PARTY_ID, PARTY_NAME, AMOUNT}] remaining on active advances
        unattributed_lines   - int, advance-account lines with no customer
        control_receivable   - Accounts Receivable account, debits - credits
        open_receivables     - sum(amount - settled) of live sales
        unbalanced_vouchers  - [{VOUCHER_NO, DEBIT, CREDIT}]
        advance_mismatches   - [{ADVANCE_ID, PARTY_NAME, USED, RECORDED}]
        failed_events        - int
        missed_events        - [{EVENT_TYPE, SOURCE_ID, DIVISION, EVENT_DATE}]
    Returns a list of checks; an overall pass needs every check OK."""
    checks = []

    ledger = {r['PARTY_ID']: r for r in data['ledger_by_party']}
    sub = {r['PARTY_ID']: r for r in data['subledger_by_party']}
    diffs = []
    for pid in sorted(set(ledger) | set(sub), key=lambda p: (p is None, p)):
        a = money((ledger.get(pid) or {}).get('AMOUNT') or 0)
        b = money((sub.get(pid) or {}).get('AMOUNT') or 0)
        if a != b:
            name = (ledger.get(pid) or sub.get(pid) or {}).get('PARTY_NAME') or f'Customer {pid}'
            diffs.append({'PARTY': name, 'LEDGER': a, 'ADVANCES': b, 'DIFFERENCE': a - b})
    checks.append(_check('Each customer: ledger balance equals advance balance', not diffs,
                         'All customers agree.' if not diffs else f'{len(diffs)} customer(s) differ.', diffs))

    sub_total = sum((money(r['AMOUNT']) for r in data['subledger_by_party']), ZERO)
    control = money(data['control_advance'])
    checks.append(_check('Customer Advances account equals total of customer advances', control == sub_total,
                         f'Account {control:,.2f} vs customers {sub_total:,.2f}.' if control != sub_total else 'Totals agree.'))

    n = int(data['unattributed_lines'] or 0)
    checks.append(_check('Every Customer Advances entry names a customer', n == 0,
                         'None missing.' if n == 0 else f'{n} entries have no customer.'))

    recv_c, recv_o = money(data['control_receivable']), money(data['open_receivables'])
    checks.append(_check('Accounts Receivable equals open sales', recv_c == recv_o,
                         'Agree.' if recv_c == recv_o else f'Account {recv_c:,.2f} vs open sales {recv_o:,.2f}.'))

    ub = data['unbalanced_vouchers']
    checks.append(_check('Every voucher balances (debits = credits)', not ub,
                         'All balanced.' if not ub else f'{len(ub)} voucher(s) do not balance.', ub))

    am = data['advance_mismatches']
    checks.append(_check('Each advance: amount used equals knock-offs recorded', not am,
                         'All agree.' if not am else f'{len(am)} advance(s) differ.', am))

    failed = int(data['failed_events'] or 0)
    checks.append(_check('No failed Gate Pass postings', failed == 0,
                         'None failed.' if failed == 0 else f'{failed} failed - retry them in Posting Events.'))

    missed = data['missed_events']
    checks.append(_check('No Gate Pass missed by finance', not missed,
                         'None missed.' if not missed else f'{len(missed)} Gate Pass event(s) never reached finance.', missed))
    return checks


def overall(checks):
    return all(c['STATUS'] == 'OK' for c in checks)


# ------------------------------------------------------------ 5. ageing
def bucket_for(age_days):
    for label, low, high in AGEING_BUCKETS:
        if age_days >= low and (high is None or age_days <= high):
            return label
    return AGEING_BUCKETS[0][0]          # future-dated cannot happen; treated as newest


def age_advances(rows, as_of):
    """rows: PARTY_ID, PARTY_NAME, ADVANCE_DATE, REMAINING (active, > 0).
    Allocation is oldest-first, so each row's remaining money really is that old.
    Returns (customers, totals)."""
    as_of = as_date(as_of)
    labels = [b[0] for b in AGEING_BUCKETS]
    by_party = {}
    for r in rows:
        amount = money(r['REMAINING'])
        if amount <= 0:
            continue
        age = max((as_of - as_date(r['ADVANCE_DATE'])).days, 0)
        p = by_party.setdefault(r['PARTY_ID'], {'PARTY_NAME': r['PARTY_NAME'], 'OLDEST_DAYS': 0,
                                                'TOTAL': ZERO, **{l: ZERO for l in labels}})
        p[bucket_for(age)] += amount
        p['TOTAL'] += amount
        p['OLDEST_DAYS'] = max(p['OLDEST_DAYS'], age)
    out = sorted(by_party.values(), key=lambda p: (-p['OLDEST_DAYS'], p['PARTY_NAME'] or ''))
    totals = {l: sum((p[l] for p in out), ZERO) for l in labels}
    totals['TOTAL'] = sum((p['TOTAL'] for p in out), ZERO)
    return out, totals
