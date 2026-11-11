"""
Phase 2 posting engine (Oracle). Vouchers, advances, receivables,
allocations, event log.

Two kinds of caller, both locked:
  * Super Admin screens -> functions that start with a user and call _guard(user).
  * The Gate Pass hooks (gateway.py) -> run inside system_context(), which only
    gateway.py enters. Outside both, every function refuses.

Rule: functions that take a cursor never commit; the caller commits once so
a sale, its knock-off and its event row are one all-or-nothing unit.
"""
import contextvars
import logging
from contextlib import contextmanager
from datetime import date

from django.core.exceptions import PermissionDenied

from . import audit
from . import ledger as L
from .access import is_finance_admin

logger = logging.getLogger('apps.finance.posting')

_SYSTEM = contextvars.ContextVar('finance_system_context', default=False)


@contextmanager
def system_context():
    token = _SYSTEM.set(True)
    try:
        yield
    finally:
        _SYSTEM.reset(token)


def _guard(user):
    if not is_finance_admin(user):
        raise PermissionDenied('Finance data is restricted to the Super Admin.')


def _guard_any(user=None):
    """Super Admin, or the Gate Pass hook acting inside system_context()."""
    if _SYSTEM.get():
        return
    _guard(user)


def _connect(username=None):
    from apps.wastage.oracle_data import get_connection
    return get_connection(username)


def _dicts(cur):
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


# ------------------------------------------------------------- lookups
def get_setting(cur, key, default=None):
    cur.execute("SELECT SETTING_VALUE FROM wst_djn_fin_setting WHERE SETTING_KEY = :1", [key])
    row = cur.fetchone()
    return row[0] if row and row[0] is not None else default


def rule_accounts(cur, event_code):
    """(debit_account_id, credit_account_id) for a posting rule. Both must be
    active posting heads, otherwise the posting stops with a clear message."""
    cur.execute("""SELECT r.DEBIT_ACCOUNT_KEY, r.CREDIT_ACCOUNT_KEY, d.ACCOUNT_ID, d.IS_ACTIVE, d.IS_POSTING,
                          c.ACCOUNT_ID, c.IS_ACTIVE, c.IS_POSTING
                   FROM wst_djn_fin_posting_rule r
                   LEFT JOIN wst_djn_fin_account d ON d.SYSTEM_KEY = r.DEBIT_ACCOUNT_KEY
                   LEFT JOIN wst_djn_fin_account c ON c.SYSTEM_KEY = r.CREDIT_ACCOUNT_KEY
                   WHERE r.EVENT_CODE = :1 AND r.IS_ACTIVE = 1""", [event_code])
    row = cur.fetchone()
    if not row:
        raise L.FinanceRuleError(f'Posting rule {event_code} is missing or switched off.')
    dkey, ckey, did, dact, dpost, cid, cact, cpost = row
    for acc_id, act, post, key in ((did, dact, dpost, dkey), (cid, cact, cpost, ckey)):
        if acc_id is None or not act or not post:
            raise L.FinanceRuleError(f'Posting rule {event_code}: account {key} is missing, inactive or not a posting head.')
    return int(did), int(cid)


def go_live_date(cur):
    return get_setting(cur, 'FINANCE_GO_LIVE_DATE')


def _period_open(cur, division, vdate):
    d = L.as_date(vdate)
    cur.execute("""SELECT STATUS FROM wst_djn_fin_period
                   WHERE DIVISION = :1 AND PERIOD_YEAR = :2 AND PERIOD_MONTH = :3""", [division, d.year, d.month])
    row = cur.fetchone()
    if row and row[0] == 'LOCKED':
        raise L.FinanceRuleError(f'The accounting period {d.year}-{d.month:02d} is locked for division {division}.')


# ------------------------------------------------------------- numbering
def next_voucher_no(cur, type_code, division, vdate):
    from core import db
    cur.execute("SELECT PREFIX FROM wst_djn_fin_voucher_type WHERE TYPE_CODE = :1 AND IS_ACTIVE = 1", [type_code])
    row = cur.fetchone()
    if not row:
        raise L.FinanceRuleError(f'Voucher type {type_code} is missing or inactive.')
    prefix = row[0]
    fy = L.fiscal_year(vdate, get_setting(cur, 'FISCAL_YEAR_START_MONTH', '7'))
    for _attempt in (1, 2):
        cur.execute("""SELECT LAST_NO FROM wst_djn_fin_sequence
                       WHERE TYPE_CODE = :1 AND DIVISION = :2 AND SEQ_YEAR = :3 FOR UPDATE""", [type_code, division, fy])
        r = cur.fetchone()
        if r:
            number = int(r[0]) + 1
            cur.execute("""UPDATE wst_djn_fin_sequence SET LAST_NO = :1
                           WHERE TYPE_CODE = :2 AND DIVISION = :3 AND SEQ_YEAR = :4""", [number, type_code, division, fy])
            return L.format_voucher_no(prefix, division, fy, number)
        try:
            cur.execute("""INSERT INTO wst_djn_fin_sequence (TYPE_CODE, DIVISION, SEQ_YEAR, LAST_NO)
                           VALUES (:1, :2, :3, 1)""", [type_code, division, fy])
            return L.format_voucher_no(prefix, division, fy, 1)
        except db.DatabaseError as exc:
            if getattr(exc.args[0], 'code', None) != 1:
                raise
            # someone else created the counter a moment ago: read it again
    raise L.FinanceRuleError('Could not allocate a voucher number. Please retry.')


# ------------------------------------------------------------- vouchers
def insert_voucher(cur, actor, type_code, division, vdate, party_id, narration,
                   source_type, source_id, lines, reverses_voucher_id=None):
    """Writes header + lines. Lines must balance. Returns voucher_id."""
    from core import db
    amount = L.assert_balanced(lines)
    _period_open(cur, division, vdate)
    vno = next_voucher_no(cur, type_code, division, vdate)
    cur.execute("""INSERT INTO wst_djn_fin_voucher
                     (voucher_no, type_code, division, voucher_date, party_id, narration,
                      source_type, source_id, amount, status, reverses_voucher_id, created_by)
                   VALUES (:no, :tc, :dv, TO_DATE(:vd,'YYYY-MM-DD'), :pty, :nar, :st, :sid, :amt, 'POSTED', :rev, :actor)
                   RETURNING voucher_id""",
                {'no': vno, 'tc': type_code, 'dv': division, 'vd': L.as_date(vdate).isoformat(),
                 'pty': party_id, 'nar': (narration or '')[:300], 'st': source_type,
                 'sid': (str(source_id)[:40] if source_id is not None else None),
                 'amt': amount, 'rev': reverses_voucher_id, 'actor': actor})
    voucher_id = int(cur.fetchone()[0])
    for i, ln in enumerate(lines, start=1):
        cur.execute("""INSERT INTO wst_djn_fin_voucher_line (voucher_id, line_no, account_id, party_id, debit, credit)
                       VALUES (:1, :2, :3, :4, :5, :6)""",
                    [voucher_id, i, ln['account_id'], ln.get('party_id'), L.money(ln['debit']), L.money(ln['credit'])])
    audit.record_changes(cur, actor, 'FIN_VOUCHER', voucher_id, 'CREATE',
                         new=f'{vno} {type_code} {amount} party={party_id} src={source_type}:{source_id}')
    return voucher_id


def reverse_voucher(cur, actor, voucher_id, reason, rev_date=None):
    """Posts the mirror-image voucher and flips the original to REVERSED."""
    from core import db
    cur.execute("""SELECT VOUCHER_ID, DIVISION, PARTY_ID, SOURCE_TYPE, SOURCE_ID, STATUS, VOUCHER_NO
                   FROM wst_djn_fin_voucher WHERE VOUCHER_ID = :1 FOR UPDATE""", [voucher_id])
    rows = _dicts(cur)
    if not rows:
        raise L.FinanceRuleError('Voucher not found.')
    h = rows[0]
    if h['STATUS'] != 'POSTED':
        raise L.FinanceRuleError(f"Voucher {h['VOUCHER_NO']} is already reversed.")
    cur.execute("""SELECT ACCOUNT_ID, PARTY_ID, DEBIT, CREDIT FROM wst_djn_fin_voucher_line
                   WHERE VOUCHER_ID = :1 ORDER BY LINE_NO""", [voucher_id])
    lines = [{'account_id': a, 'party_id': p, 'debit': d, 'credit': c} for a, p, d, c in cur.fetchall()]
    new_id = insert_voucher(cur, actor, 'RVS', h['DIVISION'], rev_date or date.today(), h['PARTY_ID'],
                            f"Reversal of {h['VOUCHER_NO']}: {reason}"[:300], h['SOURCE_TYPE'], h['SOURCE_ID'],
                            L.mirror(lines), reverses_voucher_id=voucher_id)
    cur.execute("UPDATE wst_djn_fin_voucher SET STATUS = 'REVERSED' WHERE VOUCHER_ID = :1", [voucher_id])
    return new_id


# ------------------------------------------------------------- advances
def customer_advances(cur, party_id, for_update=False):
    sql = """SELECT ADVANCE_ID, ADVANCE_DATE, REMAINING FROM wst_djn_fin_advance
             WHERE PARTY_ID = :1 AND STATUS = 'ACTIVE' AND REMAINING > 0 ORDER BY ADVANCE_DATE, ADVANCE_ID"""
    if for_update:
        sql += " FOR UPDATE"
    cur.execute(sql, [party_id])
    return [{'advance_id': a, 'advance_date': d, 'remaining': r} for a, d, r in cur.fetchall()]


def advance_available(cur, party_id):
    return L.available_advance(customer_advances(cur, party_id))


def _insert_advance(cur, actor, party_id, division, adv_date, kind, mode, reference, amount, voucher_id):
    from core import db
    cur.execute("""INSERT INTO wst_djn_fin_advance
                     (party_id, division, advance_date, kind, pay_mode, reference, amount, remaining, voucher_id, created_by)
                   VALUES (:p, :dv, TO_DATE(:d,'YYYY-MM-DD'), :k, :m, :ref, :amt, :amt, :v, :actor)
                   RETURNING advance_id""",
                {'p': party_id, 'dv': division, 'd': L.as_date(adv_date).isoformat(), 'k': kind, 'm': mode,
                 'ref': (reference or '')[:100] or None, 'amt': amount, 'v': voucher_id, 'actor': actor})
    return int(cur.fetchone()[0])


def _party_exists(cur, party_id):
    cur.execute("SELECT 1 FROM wst_djn_vendors WHERE VENDOR_ID = :1", [party_id])
    if not cur.fetchone():
        raise L.FinanceRuleError('That customer does not exist.')


def receive_advance(cur, actor, party_id, division, adv_date, mode, reference, amount):
    """Customer pays in advance (cash or bank): Dr Cash/Bank, Cr Customer Advance."""
    if mode not in ('CASH', 'BANK'):
        raise L.FinanceRuleError('Choose Cash or Bank.')
    amt = L.positive_money(amount)
    if L.as_date(adv_date) > date.today():
        raise L.FinanceRuleError('An advance cannot be dated in the future.')
    _party_exists(cur, party_id)
    cur.execute("SELECT SETTING_VALUE FROM wst_djn_fin_setting WHERE SETTING_KEY = 'FINANCE_GO_LIVE_DATE'")
    gl = cur.fetchone()
    if gl and not L.is_live(adv_date, gl[0]):
        raise L.FinanceRuleError(f'Finance starts on {gl[0]}. Earlier balances are loaded as an Opening Balance, not as a receipt.')
    debit, credit = rule_accounts(cur, 'ADVANCE_CASH' if mode == 'CASH' else 'ADVANCE_BANK')
    lines = L.two_line(debit, credit, amt, party_id)
    vid = insert_voucher(cur, actor, 'RV', division, adv_date, party_id,
                         f'Advance received ({mode.title()}) {reference or ""}'.strip(), 'ADVANCE', None, lines)
    return _insert_advance(cur, actor, party_id, division, adv_date, 'RECEIPT', mode, reference, amt, vid), vid


def load_opening_advance(cur, actor, party_id, division, amount, reference=None):
    """Opening balance at cut-over: Dr Opening Balance Equity, Cr Customer Advance,
    dated on the go-live date. One per customer per division."""
    amt = L.positive_money(amount)
    _party_exists(cur, party_id)
    gl = go_live_date(cur)
    if not gl:
        raise L.FinanceRuleError('Set the cut-over date (FINANCE_GO_LIVE_DATE) first.')
    cur.execute("""SELECT 1 FROM wst_djn_fin_advance WHERE PARTY_ID = :1 AND DIVISION = :2 AND KIND = 'OPENING' AND STATUS = 'ACTIVE'""",
                [party_id, division])
    if cur.fetchone():
        raise L.FinanceRuleError('An opening balance was already loaded for this customer and division. '
                                 'Reverse that voucher first if it was wrong.')
    debit, credit = rule_accounts(cur, 'OPENING_ADVANCE')
    lines = L.two_line(debit, credit, amt, party_id)
    vid = insert_voucher(cur, actor, 'JV', division, gl, party_id, f'Opening customer advance {reference or ""}'.strip(),
                         'OPENING', None, lines)
    return _insert_advance(cur, actor, party_id, division, gl, 'OPENING', None, reference, amt, vid), vid


# ------------------------------------------------------------- dispatch
def post_dispatch_for_customer(cur, actor, gp_id, division, gp_date, party_id, amount):
    """One customer's share of a Gate Pass: sale voucher, receivable, knock-off
    against advance (oldest first), application voucher, allocations.
    Raises InsufficientAdvance if the advance cannot cover it in full."""
    from core import db
    amount = L.positive_money(amount)
    sale_dr, sale_cr = rule_accounts(cur, 'SALE_POSTED')
    app_dr, app_cr = rule_accounts(cur, 'ADVANCE_APPLIED')

    advances = customer_advances(cur, party_id, for_update=True)   # lock before deciding
    plan = L.allocate_oldest_first(advances, amount)               # all-or-nothing

    sv = insert_voucher(cur, actor, 'SV', division, gp_date, party_id, f'Sale on Gate Pass {gp_id}',
                        'GATEPASS', gp_id, L.two_line(sale_dr, sale_cr, amount, party_id))
    cur.execute("""INSERT INTO wst_djn_fin_receivable
                     (party_id, division, source_type, source_id, doc_date, amount, settled, status, voucher_id, created_by)
                   VALUES (:p, :dv, 'GATEPASS', :sid, TO_DATE(:d,'YYYY-MM-DD'), :amt, 0, 'OPEN', :v, :actor)
                   RETURNING receivable_id""",
                {'p': party_id, 'dv': division, 'sid': gp_id, 'd': L.as_date(gp_date).isoformat(),
                 'amt': amount, 'v': sv, 'actor': actor})
    receivable_id = int(cur.fetchone()[0])

    av = insert_voucher(cur, actor, 'AV', division, gp_date, party_id, f'Advance applied to Gate Pass {gp_id}',
                        'GATEPASS', gp_id, L.two_line(app_dr, app_cr, amount, party_id))
    for advance_id, part in plan:
        cur.execute("UPDATE wst_djn_fin_advance SET REMAINING = REMAINING - :1 WHERE ADVANCE_ID = :2", [part, advance_id])
        cur.execute("""INSERT INTO wst_djn_fin_allocation (receivable_id, advance_id, amount, voucher_id, status, created_by)
                       VALUES (:1, :2, :3, :4, 'ACTIVE', :5)""", [receivable_id, advance_id, part, av, actor])
    cur.execute("UPDATE wst_djn_fin_receivable SET SETTLED = AMOUNT, STATUS = 'SETTLED' WHERE RECEIVABLE_ID = :1", [receivable_id])
    audit.record_changes(cur, actor, 'FIN_RECEIVABLE', receivable_id, 'CREATE',
                         new=f'GP {gp_id} party={party_id} amount={amount} knocked off from {len(plan)} advance(s)')
    return [sv, av]


def reverse_dispatch(cur, actor, gp_id, reason):
    """Undo everything a Gate Pass posted: reverse its vouchers, give the
    advance back, mark receivables and allocations reversed."""
    cur.execute("""SELECT VOUCHER_ID FROM wst_djn_fin_voucher
                   WHERE SOURCE_TYPE = 'GATEPASS' AND SOURCE_ID = :1 AND STATUS = 'POSTED' AND TYPE_CODE IN ('SV','AV')
                   ORDER BY VOUCHER_ID FOR UPDATE""", [gp_id])
    vids = [r[0] for r in cur.fetchall()]
    new_ids = [reverse_voucher(cur, actor, vid, reason) for vid in vids]
    cur.execute("""SELECT ALLOCATION_ID, ADVANCE_ID, AMOUNT FROM wst_djn_fin_allocation
                   WHERE STATUS = 'ACTIVE' AND RECEIVABLE_ID IN
                     (SELECT RECEIVABLE_ID FROM wst_djn_fin_receivable WHERE SOURCE_TYPE = 'GATEPASS' AND SOURCE_ID = :1)
                   FOR UPDATE""", [gp_id])
    for _alloc_id, advance_id, amt in cur.fetchall():
        cur.execute("UPDATE wst_djn_fin_advance SET REMAINING = REMAINING + :1 WHERE ADVANCE_ID = :2", [amt, advance_id])
    cur.execute("""UPDATE wst_djn_fin_allocation SET STATUS = 'REVERSED' WHERE STATUS = 'ACTIVE' AND RECEIVABLE_ID IN
                     (SELECT RECEIVABLE_ID FROM wst_djn_fin_receivable WHERE SOURCE_TYPE = 'GATEPASS' AND SOURCE_ID = :1)""", [gp_id])
    cur.execute("""UPDATE wst_djn_fin_receivable SET STATUS = 'REVERSED' WHERE SOURCE_TYPE = 'GATEPASS' AND SOURCE_ID = :1
                   AND STATUS <> 'REVERSED'""", [gp_id])
    audit.record_changes(cur, actor, 'FIN_RECEIVABLE', gp_id, 'UPDATE',
                         old={'status': 'SETTLED'}, new={'status': 'REVERSED', 'reason': reason})
    return new_ids


# ------------------------------------------------------------- event log
def event_row(cur, event_type, source_id, for_update=False):
    cur.execute("""SELECT EVENT_ID, STATUS, ATTEMPTS, VOUCHER_IDS FROM wst_djn_fin_event_log
                   WHERE EVENT_TYPE = :1 AND SOURCE_ID = :2""" + (" FOR UPDATE" if for_update else ""),
                [event_type, source_id])
    rows = _dicts(cur)
    return rows[0] if rows else None


def write_event(cur, event_type, source_id, division, event_date, status, message, voucher_ids, actor):
    """Upsert one event row (no commit)."""
    from core import db
    msg = (message or '')[:500] or None
    vids = ','.join(str(v) for v in (voucher_ids or []))[:200] or None
    d = L.as_date(event_date).isoformat() if event_date else None
    cur.execute("""UPDATE wst_djn_fin_event_log
                   SET STATUS = :st, MESSAGE = :msg, VOUCHER_IDS = :vids, ATTEMPTS = ATTEMPTS + 1,
                       UPDATED_AT = LOCALTIMESTAMP, ACTOR = :actor
                   WHERE EVENT_TYPE = :et AND SOURCE_ID = :sid""",
                {'st': status, 'msg': msg, 'vids': vids, 'actor': actor, 'et': event_type, 'sid': source_id})
    if cur.rowcount:
        return
    try:
        cur.execute("""INSERT INTO wst_djn_fin_event_log
                         (EVENT_TYPE, SOURCE_ID, DIVISION, EVENT_DATE, STATUS, ATTEMPTS, MESSAGE, VOUCHER_IDS, ACTOR)
                       VALUES (:et, :sid, :dv, TO_DATE(:d,'YYYY-MM-DD'), :st, 1, :msg, :vids, :actor)""",
                    {'et': event_type, 'sid': source_id, 'dv': division, 'd': d, 'st': status,
                     'msg': msg, 'vids': vids, 'actor': actor})
    except db.DatabaseError as exc:
        if getattr(exc.args[0], 'code', None) != 1:
            raise
        cur.execute("""UPDATE wst_djn_fin_event_log SET STATUS = :st, MESSAGE = :msg, VOUCHER_IDS = :vids,
                       ATTEMPTS = ATTEMPTS + 1, UPDATED_AT = LOCALTIMESTAMP, ACTOR = :actor
                       WHERE EVENT_TYPE = :et AND SOURCE_ID = :sid""",
                    {'st': status, 'msg': msg, 'vids': vids, 'actor': actor, 'et': event_type, 'sid': source_id})


def reverse_advance(cur, actor, advance_id, reason):
    """Undo an advance receipt or opening balance - only while none of it has
    been used by a dispatch."""
    cur.execute("""SELECT ADVANCE_ID, VOUCHER_ID, AMOUNT, REMAINING, STATUS FROM wst_djn_fin_advance
                   WHERE ADVANCE_ID = :1 FOR UPDATE""", [advance_id])
    rows = _dicts(cur)
    if not rows:
        raise L.FinanceRuleError('Advance not found.')
    adv = rows[0]
    if adv['STATUS'] != 'ACTIVE':
        raise L.FinanceRuleError('This advance is already reversed.')
    if L.money(adv['REMAINING']) != L.money(adv['AMOUNT']):
        raise L.FinanceRuleError('Part of this advance has already been used by a dispatch. '
                                 'Cancel those Gate Passes first, then reverse it.')
    if not (reason or '').strip() or len(reason.strip()) < 5:
        raise L.FinanceRuleError('Give a reason of at least 5 characters.')
    new_id = reverse_voucher(cur, actor, adv['VOUCHER_ID'], reason.strip())
    cur.execute("UPDATE wst_djn_fin_advance SET STATUS = 'REVERSED', REMAINING = 0 WHERE ADVANCE_ID = :1", [advance_id])
    audit.record_changes(cur, actor, 'FIN_ADVANCE', advance_id, 'UPDATE',
                         old={'status': 'ACTIVE'}, new={'status': 'REVERSED', 'reason': reason.strip()[:300]})
    return new_id


# ================================================================ PHASE 3
# Adjustments (Super Admin only; every function takes the open cursor and
# the caller commits once).

def _account_by_key(cur, key):
    cur.execute("SELECT ACCOUNT_ID FROM wst_djn_fin_account WHERE SYSTEM_KEY = :1 AND IS_ACTIVE = 1 AND IS_POSTING = 1", [key])
    row = cur.fetchone()
    if not row:
        raise L.FinanceRuleError(f'Account {key} is missing, inactive or not a posting head.')
    return int(row[0])


def _adj_date(cur, value):
    d = L.as_date(value)
    if d > date.today():
        raise L.FinanceRuleError('An adjustment cannot be dated in the future.')
    gl = go_live_date(cur)
    if not gl:
        raise L.FinanceRuleError('Set the cut-over date (FINANCE_GO_LIVE_DATE) first.')
    if not L.is_live(d, gl):
        raise L.FinanceRuleError(f'Finance starts on {gl}. Earlier dates are not allowed.')
    return d


def _insert_adjustment(cur, actor, adj_type, division, adj_date, party_id, to_party_id, receivable_id,
                       source_ref, pay_mode, reference, amount, reason):
    from core import db
    cur.execute("""INSERT INTO wst_djn_fin_adjustment
                     (adj_type, division, adj_date, party_id, to_party_id, receivable_id, source_ref,
                      pay_mode, reference, amount, reason, status, created_by)
                   VALUES (:t, :dv, TO_DATE(:d,'YYYY-MM-DD'), :p, :p2, :r, :sref, :pm, :ref, :amt, :why, 'ACTIVE', :actor)
                   RETURNING adjustment_id""",
                {'t': adj_type, 'dv': division, 'd': L.as_date(adj_date).isoformat(), 'p': party_id, 'p2': to_party_id,
                 'r': receivable_id, 'sref': (str(source_ref)[:40] if source_ref else None), 'pm': pay_mode,
                 'ref': (reference or '')[:100] or None, 'amt': amount, 'why': reason, 'actor': actor})
    adj_id = int(cur.fetchone()[0])
    audit.record_changes(cur, actor, 'FIN_ADJUSTMENT', adj_id, 'CREATE',
                         new=f'{adj_type} {amount} party={party_id} to={to_party_id} rcv={receivable_id} reason={reason}')
    return adj_id


def _consume_advance(cur, party_id, amount, adjustment_id):
    """Take `amount` from the customer's advances, oldest first (all or nothing)."""
    plan = L.allocate_oldest_first(customer_advances(cur, party_id, for_update=True), amount)
    for advance_id, part in plan:
        cur.execute("UPDATE wst_djn_fin_advance SET REMAINING = REMAINING - :1 WHERE ADVANCE_ID = :2", [part, advance_id])
        cur.execute("""INSERT INTO wst_djn_fin_advance_use (advance_id, adjustment_id, amount, status)
                       VALUES (:1, :2, :3, 'ACTIVE')""", [advance_id, adjustment_id, part])
    return plan


def _set_created_advance(cur, adj_id, advance_id):
    cur.execute("UPDATE wst_djn_fin_adjustment SET CREATED_ADVANCE_ID = :1 WHERE ADJUSTMENT_ID = :2", [advance_id, adj_id])


def _vch(cur, actor, vtype, division, d, party_id, narration, adj_id, lines):
    return insert_voucher(cur, actor, vtype, division, d, party_id, narration, 'ADJUSTMENT', str(adj_id), lines)


def refund_advance(cur, actor, party_id, division, adj_date, mode, reference, amount, reason):
    """Give unused advance back: Dr Customer Advances, Cr Cash/Bank."""
    if mode not in ('CASH', 'BANK'):
        raise L.FinanceRuleError('Choose Cash or Bank.')
    amt = L.positive_money(amount)
    why = L.clean_reason(reason)
    d = _adj_date(cur, adj_date)
    _party_exists(cur, party_id)
    debit, credit = rule_accounts(cur, 'REFUND_CASH' if mode == 'CASH' else 'REFUND_BANK')
    adj_id = _insert_adjustment(cur, actor, L.ADJ_REFUND, division, d, party_id, None, None, None, mode, reference, amt, why)
    _consume_advance(cur, party_id, amt, adj_id)
    _vch(cur, actor, 'AV', division, d, party_id, f'Advance refunded ({mode.title()}): {why}', adj_id,
         L.two_line(debit, credit, amt, party_id))
    return adj_id


def _lock_receivable(cur, receivable_id):
    cur.execute("""SELECT RECEIVABLE_ID, PARTY_ID, DIVISION, SOURCE_ID, AMOUNT, STATUS FROM wst_djn_fin_receivable
                   WHERE RECEIVABLE_ID = :1 FOR UPDATE""", [int(receivable_id)])
    rows = _dicts(cur)
    if not rows:
        raise L.FinanceRuleError('That Gate Pass sale was not found.')
    r = rows[0]
    if r['STATUS'] == 'REVERSED':
        raise L.FinanceRuleError('That sale has been reversed (its Gate Pass was cancelled).')
    return r


def _note_totals(cur, receivable_id):
    cur.execute("""SELECT COALESCE(SUM(CASE WHEN ADJ_TYPE = 'CREDIT_NOTE' THEN AMOUNT END), 0),
                          COALESCE(SUM(CASE WHEN ADJ_TYPE = 'DEBIT_NOTE'  THEN AMOUNT END), 0)
                   FROM wst_djn_fin_adjustment WHERE RECEIVABLE_ID = :1 AND STATUS = 'ACTIVE'""", [int(receivable_id)])
    credits, debits = cur.fetchone()
    return credits, debits


def credit_note(cur, actor, receivable_id, adj_date, amount, reason):
    """Sale was too high (rate / weight): CN voucher (Dr Sales Returns, Cr Receivable),
    then the customer gets the amount back as advance (Dr Receivable, Cr Customer Advances)."""
    why = L.clean_reason(reason)
    d = _adj_date(cur, adj_date)
    rcv = _lock_receivable(cur, receivable_id)
    credits, debits = _note_totals(cur, receivable_id)
    amt = L.check_credit_note(rcv['AMOUNT'], credits, debits, amount)
    cn_dr, cn_cr = rule_accounts(cur, 'CREDIT_NOTE')
    app_dr, app_cr = rule_accounts(cur, 'ADVANCE_APPLIED')       # Dr Customer Advances, Cr Receivable
    party, division = rcv['PARTY_ID'], rcv['DIVISION']
    adj_id = _insert_adjustment(cur, actor, L.ADJ_CREDIT, division, d, party, None, int(receivable_id),
                                rcv['SOURCE_ID'], None, None, amt, why)
    _vch(cur, actor, 'CN', division, d, party, f"Credit note on Gate Pass {rcv['SOURCE_ID']}: {why}", adj_id,
         L.two_line(cn_dr, cn_cr, amt, party))
    back = _vch(cur, actor, 'AV', division, d, party, f"Credit returned to advance, Gate Pass {rcv['SOURCE_ID']}", adj_id,
                L.two_line(app_cr, app_dr, amt, party))           # mirrored: Dr Receivable, Cr Customer Advances
    advance_id = _insert_advance(cur, actor, party, division, d, 'CREDIT', None, f"CN {rcv['SOURCE_ID']}", amt, back)
    _set_created_advance(cur, adj_id, advance_id)
    return adj_id


def debit_note(cur, actor, receivable_id, adj_date, amount, reason):
    """Sale was too low: DN voucher (Dr Receivable, Cr Sales Returns) and the extra is
    knocked off the customer's advance at once. Refused if the advance cannot cover it."""
    why = L.clean_reason(reason)
    d = _adj_date(cur, adj_date)
    amt = L.positive_money(amount, 'Debit note amount')
    rcv = _lock_receivable(cur, receivable_id)
    dn_dr, dn_cr = rule_accounts(cur, 'DEBIT_NOTE')
    app_dr, app_cr = rule_accounts(cur, 'ADVANCE_APPLIED')
    party, division = rcv['PARTY_ID'], rcv['DIVISION']
    adj_id = _insert_adjustment(cur, actor, L.ADJ_DEBIT, division, d, party, None, int(receivable_id),
                                rcv['SOURCE_ID'], None, None, amt, why)
    _consume_advance(cur, party, amt, adj_id)
    _vch(cur, actor, 'DN', division, d, party, f"Debit note on Gate Pass {rcv['SOURCE_ID']}: {why}", adj_id,
         L.two_line(dn_dr, dn_cr, amt, party))
    _vch(cur, actor, 'AV', division, d, party, f"Advance applied to debit note, Gate Pass {rcv['SOURCE_ID']}", adj_id,
         L.two_line(app_dr, app_cr, amt, party))
    return adj_id


def transfer_advance(cur, actor, from_party, to_party, division, adj_date, amount, reason):
    """Move unused advance from one customer to another (reason mandatory)."""
    L.check_transfer(from_party, to_party)
    amt = L.positive_money(amount)
    why = L.clean_reason(reason)
    d = _adj_date(cur, adj_date)
    _party_exists(cur, from_party)
    _party_exists(cur, to_party)
    acc = _account_by_key(cur, 'CUSTOMER_ADVANCE')
    adj_id = _insert_adjustment(cur, actor, L.ADJ_TRANSFER, division, d, from_party, to_party, None, None, None, None, amt, why)
    _consume_advance(cur, from_party, amt, adj_id)
    lines = [{'account_id': acc, 'party_id': from_party, 'debit': amt, 'credit': L.ZERO},
             {'account_id': acc, 'party_id': to_party, 'debit': L.ZERO, 'credit': amt}]
    vid = _vch(cur, actor, 'AV', division, d, from_party, f'Advance transferred: {why}', adj_id, lines)
    advance_id = _insert_advance(cur, actor, to_party, division, d, 'TRANSFER', None, f'From customer {from_party}', amt, vid)
    _set_created_advance(cur, adj_id, advance_id)
    return adj_id


def journal_entry(cur, actor, division, adj_date, narration, rows):
    """Manual journal. rows: [{account_id, debit, credit, party_id}]. Narration mandatory."""
    why = L.clean_reason(narration)
    d = _adj_date(cur, adj_date)
    keyed = []
    for r in rows:
        cur.execute("""SELECT SYSTEM_KEY, IS_ACTIVE, IS_POSTING FROM wst_djn_fin_account WHERE ACCOUNT_ID = :1""", [int(r['account_id'])])
        a = cur.fetchone()
        if not a or not a[1] or not a[2]:
            raise L.FinanceRuleError('Every journal line needs an active posting account.')
        keyed.append({**r, 'system_key': a[0]})
    lines = L.clean_journal(keyed)
    total = L.assert_balanced(lines)
    adj_id = _insert_adjustment(cur, actor, L.ADJ_JOURNAL, division, d, None, None, None, None, None, None, total, why)
    _vch(cur, actor, 'JV', division, d, None, f'Journal: {why}', adj_id, lines)
    return adj_id


def reverse_adjustment(cur, actor, adjustment_id, reason):
    """Undo an adjustment: reverse its vouchers, give back consumed advance, and
    cancel any advance it created (only while that advance is still untouched)."""
    why = L.clean_reason(reason)
    cur.execute("""SELECT ADJUSTMENT_ID, ADJ_TYPE, STATUS, CREATED_ADVANCE_ID FROM wst_djn_fin_adjustment
                   WHERE ADJUSTMENT_ID = :1 FOR UPDATE""", [int(adjustment_id)])
    rows = _dicts(cur)
    if not rows:
        raise L.FinanceRuleError('Adjustment not found.')
    adj = rows[0]
    if adj['STATUS'] != 'ACTIVE':
        raise L.FinanceRuleError('This adjustment is already reversed.')
    if adj['CREATED_ADVANCE_ID']:
        cur.execute("SELECT AMOUNT, REMAINING, STATUS FROM wst_djn_fin_advance WHERE ADVANCE_ID = :1 FOR UPDATE",
                    [adj['CREATED_ADVANCE_ID']])
        amount, remaining, status = cur.fetchone()
        if status != 'ACTIVE' or L.money(remaining) != L.money(amount):
            raise L.FinanceRuleError('The advance this created has already been used by a dispatch. '
                                     'Cancel those Gate Passes first, then reverse this adjustment.')
        cur.execute("UPDATE wst_djn_fin_advance SET STATUS = 'REVERSED', REMAINING = 0 WHERE ADVANCE_ID = :1",
                    [adj['CREATED_ADVANCE_ID']])
    cur.execute("""SELECT ADVANCE_ID, AMOUNT FROM wst_djn_fin_advance_use
                   WHERE ADJUSTMENT_ID = :1 AND STATUS = 'ACTIVE' FOR UPDATE""", [int(adjustment_id)])
    for advance_id, amt in cur.fetchall():
        cur.execute("UPDATE wst_djn_fin_advance SET REMAINING = REMAINING + :1 WHERE ADVANCE_ID = :2", [amt, advance_id])
    cur.execute("UPDATE wst_djn_fin_advance_use SET STATUS = 'REVERSED' WHERE ADJUSTMENT_ID = :1 AND STATUS = 'ACTIVE'",
                [int(adjustment_id)])
    cur.execute("""SELECT VOUCHER_ID FROM wst_djn_fin_voucher
                   WHERE SOURCE_TYPE = 'ADJUSTMENT' AND SOURCE_ID = :1 AND STATUS = 'POSTED' AND TYPE_CODE <> 'RVS'
                   ORDER BY VOUCHER_ID FOR UPDATE""", [str(adjustment_id)])
    for (vid,) in cur.fetchall():
        reverse_voucher(cur, actor, vid, why)
    cur.execute("""UPDATE wst_djn_fin_adjustment SET STATUS = 'REVERSED', REVERSED_BY = :actor,
                   REVERSED_AT = LOCALTIMESTAMP, REVERSAL_REASON = :why WHERE ADJUSTMENT_ID = :id""",
                {'actor': actor, 'why': why, 'id': int(adjustment_id)})
    audit.record_changes(cur, actor, 'FIN_ADJUSTMENT', adjustment_id, 'UPDATE',
                         old={'status': 'ACTIVE'}, new={'status': 'REVERSED', 'reason': why})
