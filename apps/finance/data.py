"""
Oracle access for the Finance module. The ONLY place finance SQL lives.

Rules:
  * Every public function takes the acting user first and re-checks that
    they are the Super Admin (third lock, after middleware and decorator).
  * Every change and its audit rows are written on ONE connection and
    committed together, so there is never a change without its audit trail
    (or the reverse).
  * No other app should import this module.
"""
import logging

from django.core.exceptions import PermissionDenied

from .access import is_finance_admin
from . import audit
from . import validators as v

logger = logging.getLogger('apps.finance.data')


# ------------------------------------------------------------------ helpers
def _guard(user):
    if not is_finance_admin(user):
        raise PermissionDenied('Finance data is restricted to the Super Admin.')


def _connect(username=None):
    # Imported lazily: oracle_data reads .env and builds the DSN at import
    # time, which unit tests (and tooling) should not need.
    from apps.wastage.oracle_data import get_connection
    return get_connection(username)


def _dicts(cur):
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def _is_unique_violation(exc):
    try:
        return exc.args[0].code == 1
    except Exception:
        return False


# ---------------------------------------------------------------- accounts
_ACCOUNT_COLS = """a.ACCOUNT_ID, a.ACCOUNT_CODE, a.ACCOUNT_NAME, a.ACCOUNT_TYPE,
       a.PARENT_ID, p.ACCOUNT_CODE AS PARENT_CODE, p.ACCOUNT_NAME AS PARENT_NAME,
       a.IS_POSTING, a.IS_LOCKED, a.SYSTEM_KEY, a.IS_ACTIVE,
       a.CREATED_BY, TO_CHAR(a.CREATED_DATE,'DD-Mon-YYYY HH24:MI') AS CREATED_DATE,
       a.LAST_UPDATED_BY, TO_CHAR(a.LAST_UPDATED_DATE,'DD-Mon-YYYY HH24:MI') AS LAST_UPDATED_DATE"""


def fetch_accounts(user, search=None, acc_type=None):
    _guard(user)
    sql = f"""SELECT {_ACCOUNT_COLS}
              FROM wst_djn_fin_account a LEFT JOIN wst_djn_fin_account p ON p.ACCOUNT_ID = a.PARENT_ID
              WHERE 1=1"""
    params = []
    if search:
        sql += " AND (UPPER(a.ACCOUNT_NAME) LIKE UPPER(:s1) OR a.ACCOUNT_CODE LIKE :s2)"
        params += [f'%{search}%', f'%{search}%']
    if acc_type in v.ACCOUNT_TYPES:
        sql += " AND a.ACCOUNT_TYPE = :t"
        params.append(acc_type)
    sql += " ORDER BY a.ACCOUNT_CODE"
    with _connect(user.username) as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        return _dicts(cur)


def fetch_account(user, account_id):
    _guard(user)
    with _connect(user.username) as conn, conn.cursor() as cur:
        cur.execute(f"""SELECT {_ACCOUNT_COLS}
                        FROM wst_djn_fin_account a LEFT JOIN wst_djn_fin_account p ON p.ACCOUNT_ID = a.PARENT_ID
                        WHERE a.ACCOUNT_ID = :1""", [int(account_id)])
        rows = _dicts(cur)
        return rows[0] if rows else None


def fetch_group_accounts(user):
    """Active group heads, offered as parents in the account form."""
    _guard(user)
    with _connect(user.username) as conn, conn.cursor() as cur:
        cur.execute("""SELECT ACCOUNT_ID, ACCOUNT_CODE, ACCOUNT_NAME, ACCOUNT_TYPE
                       FROM wst_djn_fin_account WHERE IS_POSTING = 0 AND IS_ACTIVE = 1
                       ORDER BY ACCOUNT_CODE""")
        return _dicts(cur)


def _other_codes(cur, exclude_id=None):
    if exclude_id is None:
        cur.execute("SELECT ACCOUNT_CODE FROM wst_djn_fin_account")
    else:
        cur.execute("SELECT ACCOUNT_CODE FROM wst_djn_fin_account WHERE ACCOUNT_ID <> :1", [int(exclude_id)])
    return [r[0] for r in cur.fetchall()]


def _fetch_parent(cur, parent_id):
    if not parent_id:
        return None
    cur.execute("""SELECT ACCOUNT_ID, ACCOUNT_CODE, ACCOUNT_TYPE, IS_POSTING
                   FROM wst_djn_fin_account WHERE ACCOUNT_ID = :1""", [int(parent_id)])
    rows = _dicts(cur)
    return rows[0] if rows else None


def create_account(user, form, request=None):
    """Return (account_id, errors)."""
    _guard(user)
    import oracledb
    path, ip = audit.request_context(request) if request else (None, None)
    with _connect(user.username) as conn:
        with conn.cursor() as cur:
            parent_raw = (form.get('parent_id') or '').strip()
            parent = _fetch_parent(cur, parent_raw) if parent_raw.isdigit() else None
            clean, errors = v.validate_account(form, None, parent, _other_codes(cur))
            if errors:
                return None, errors
            new_id = cur.var(oracledb.NUMBER)
            try:
                cur.execute("""INSERT INTO wst_djn_fin_account
                                 (account_code, account_name, account_type, parent_id,
                                  is_posting, is_locked, is_active, created_by)
                               VALUES (:code, :name, :type, :parent, :posting, 0, 1, :actor)
                               RETURNING account_id INTO :rid""",
                            {'code': clean['code'], 'name': clean['name'], 'type': clean['type'],
                             'parent': clean['parent_id'], 'posting': clean['is_posting'],
                             'actor': user.username, 'rid': new_id})
            except oracledb.DatabaseError as exc:
                conn.rollback()
                if _is_unique_violation(exc):
                    return None, [f'Account code {clean["code"]} is already in use.']
                raise
            account_id = int(new_id.getvalue()[0])
            audit.record_changes(cur, user.username, 'FIN_ACCOUNT', account_id, 'CREATE',
                                 new=f'{clean["code"]} {clean["name"]} ({clean["type"]})', path=path, ip=ip)
        conn.commit()
    return account_id, []


def update_account(user, account_id, form, request=None):
    """Return list of errors (empty = saved)."""
    _guard(user)
    path, ip = audit.request_context(request) if request else (None, None)
    with _connect(user.username) as conn:
        with conn.cursor() as cur:
            cur.execute(f"""SELECT {_ACCOUNT_COLS}
                            FROM wst_djn_fin_account a LEFT JOIN wst_djn_fin_account p ON p.ACCOUNT_ID = a.PARENT_ID
                            WHERE a.ACCOUNT_ID = :1 FOR UPDATE OF a.ACCOUNT_ID""", [int(account_id)])
            rows = _dicts(cur)
            if not rows:
                return ['Account not found.']
            existing = rows[0]
            parent_raw = (form.get('parent_id') or '').strip()
            parent = _fetch_parent(cur, parent_raw) if parent_raw.isdigit() else None
            clean, errors = v.validate_account(form, existing, parent, _other_codes(cur, int(account_id)))
            if errors:
                conn.rollback()
                return errors
            cur.execute("""UPDATE wst_djn_fin_account
                           SET account_code = :code, account_name = :name, account_type = :type,
                               parent_id = :parent, is_posting = :posting,
                               last_updated_by = :actor, last_updated_date = SYSTIMESTAMP
                           WHERE account_id = :id""",
                        {'code': clean['code'], 'name': clean['name'], 'type': clean['type'],
                         'parent': clean['parent_id'], 'posting': clean['is_posting'],
                         'actor': user.username, 'id': int(account_id)})
            old = {'code': existing['ACCOUNT_CODE'], 'name': existing['ACCOUNT_NAME'],
                   'type': existing['ACCOUNT_TYPE'], 'parent_id': existing['PARENT_ID'],
                   'is_posting': existing['IS_POSTING']}
            audit.record_changes(cur, user.username, 'FIN_ACCOUNT', account_id, 'UPDATE',
                                 old=old, new=clean, path=path, ip=ip)
        conn.commit()
    return []


def set_account_active(user, account_id, active, request=None):
    """Return error string or ''. Phase 2 adds the 'no postings' check here."""
    _guard(user)
    path, ip = audit.request_context(request) if request else (None, None)
    with _connect(user.username) as conn:
        with conn.cursor() as cur:
            cur.execute("""SELECT ACCOUNT_ID, IS_LOCKED, IS_ACTIVE FROM wst_djn_fin_account
                           WHERE ACCOUNT_ID = :1 FOR UPDATE""", [int(account_id)])
            rows = _dicts(cur)
            if not rows:
                return 'Account not found.'
            row = rows[0]
            if not active:
                ok, message = v.can_deactivate_account(row)
                if not ok:
                    conn.rollback()
                    return message
            new_flag = 1 if active else 0
            if row['IS_ACTIVE'] == new_flag:
                conn.rollback()
                return ''
            cur.execute("""UPDATE wst_djn_fin_account SET is_active = :f, last_updated_by = :actor,
                           last_updated_date = SYSTIMESTAMP WHERE account_id = :id""",
                        {'f': new_flag, 'actor': user.username, 'id': int(account_id)})
            audit.record_changes(cur, user.username, 'FIN_ACCOUNT', account_id, 'UPDATE',
                                 old={'is_active': row['IS_ACTIVE']}, new={'is_active': new_flag},
                                 path=path, ip=ip)
        conn.commit()
    return ''


# ---------------------------------------------------------------- settings
def fetch_settings(user):
    _guard(user)
    with _connect(user.username) as conn, conn.cursor() as cur:
        cur.execute("""SELECT SETTING_KEY, SETTING_VALUE, VALUE_TYPE, OPTIONS, DESCRIPTION, IS_EDITABLE,
                              UPDATED_BY, TO_CHAR(UPDATED_AT,'DD-Mon-YYYY HH24:MI') AS UPDATED_AT
                       FROM wst_djn_fin_setting ORDER BY SETTING_KEY""")
        return _dicts(cur)


def update_setting(user, key, raw_value, request=None):
    """Return error string or ''."""
    _guard(user)
    path, ip = audit.request_context(request) if request else (None, None)
    with _connect(user.username) as conn:
        with conn.cursor() as cur:
            cur.execute("""SELECT SETTING_KEY, SETTING_VALUE, VALUE_TYPE, OPTIONS, IS_EDITABLE
                           FROM wst_djn_fin_setting WHERE SETTING_KEY = :1 FOR UPDATE""", [key])
            rows = _dicts(cur)
            if not rows:
                return 'Setting not found.'
            row = rows[0]
            clean, error = v.validate_setting(row, raw_value)
            if error:
                conn.rollback()
                return error
            if key == 'FINANCE_GO_LIVE_DATE' and clean != row['SETTING_VALUE']:
                cur.execute("SELECT COUNT(*) FROM wst_djn_fin_event_log WHERE STATUS = 'POSTED'")
                if cur.fetchone()[0] > 0:
                    conn.rollback()
                    return 'The cut-over date cannot be changed after the first dispatch has been posted.'
            if clean == row['SETTING_VALUE']:
                conn.rollback()
                return ''
            cur.execute("""UPDATE wst_djn_fin_setting SET setting_value = :val, updated_by = :actor,
                           updated_at = SYSTIMESTAMP WHERE setting_key = :k""",
                        {'val': clean, 'actor': user.username, 'k': key})
            audit.record_changes(cur, user.username, 'FIN_SETTING', key, 'UPDATE',
                                 old={key: row['SETTING_VALUE']}, new={key: clean}, path=path, ip=ip)
        conn.commit()
    return ''


# ------------------------------------------------------------ posting rules
def fetch_posting_rules(user):
    _guard(user)
    with _connect(user.username) as conn, conn.cursor() as cur:
        cur.execute("""SELECT r.RULE_ID, r.EVENT_CODE, r.DESCRIPTION,
                              r.DEBIT_ACCOUNT_KEY, d.ACCOUNT_CODE AS DEBIT_CODE, d.ACCOUNT_NAME AS DEBIT_NAME,
                              r.CREDIT_ACCOUNT_KEY, c.ACCOUNT_CODE AS CREDIT_CODE, c.ACCOUNT_NAME AS CREDIT_NAME,
                              r.IS_ACTIVE, r.UPDATED_BY,
                              TO_CHAR(r.UPDATED_AT,'DD-Mon-YYYY HH24:MI') AS UPDATED_AT
                       FROM wst_djn_fin_posting_rule r
                       LEFT JOIN wst_djn_fin_account d ON d.SYSTEM_KEY = r.DEBIT_ACCOUNT_KEY
                       LEFT JOIN wst_djn_fin_account c ON c.SYSTEM_KEY = r.CREDIT_ACCOUNT_KEY
                       ORDER BY r.RULE_ID""")
        return _dicts(cur)


def fetch_keyed_accounts(user):
    """Active posting heads that carry a system key (valid rule targets)."""
    _guard(user)
    with _connect(user.username) as conn, conn.cursor() as cur:
        cur.execute("""SELECT ACCOUNT_CODE, ACCOUNT_NAME, SYSTEM_KEY, IS_ACTIVE, IS_POSTING
                       FROM wst_djn_fin_account WHERE SYSTEM_KEY IS NOT NULL AND IS_ACTIVE = 1 AND IS_POSTING = 1
                       ORDER BY ACCOUNT_CODE""")
        return _dicts(cur)


def update_posting_rule(user, rule_id, debit_key, credit_key, request=None):
    """Return list of errors."""
    _guard(user)
    path, ip = audit.request_context(request) if request else (None, None)
    with _connect(user.username) as conn:
        with conn.cursor() as cur:
            cur.execute("""SELECT RULE_ID, EVENT_CODE, DEBIT_ACCOUNT_KEY, CREDIT_ACCOUNT_KEY
                           FROM wst_djn_fin_posting_rule WHERE RULE_ID = :1 FOR UPDATE""", [int(rule_id)])
            rows = _dicts(cur)
            if not rows:
                return ['Posting rule not found.']
            rule = rows[0]
            cur.execute("""SELECT ACCOUNT_CODE, SYSTEM_KEY, IS_ACTIVE, IS_POSTING
                           FROM wst_djn_fin_account WHERE SYSTEM_KEY IS NOT NULL""")
            by_key = {r['SYSTEM_KEY']: r for r in _dicts(cur)}
            errors = v.validate_posting_rule(debit_key, credit_key, by_key)
            if errors:
                conn.rollback()
                return errors
            cur.execute("""UPDATE wst_djn_fin_posting_rule SET debit_account_key = :d, credit_account_key = :c,
                           updated_by = :actor, updated_at = SYSTIMESTAMP WHERE rule_id = :id""",
                        {'d': debit_key, 'c': credit_key, 'actor': user.username, 'id': int(rule_id)})
            audit.record_changes(cur, user.username, 'FIN_POSTING_RULE', rule['EVENT_CODE'], 'UPDATE',
                                 old={'debit': rule['DEBIT_ACCOUNT_KEY'], 'credit': rule['CREDIT_ACCOUNT_KEY']},
                                 new={'debit': debit_key, 'credit': credit_key}, path=path, ip=ip)
        conn.commit()
    return []


# ----------------------------------------------------------------- periods
def fetch_period_rows(user, division):
    """All stored period rows for a division (months with no row are OPEN)."""
    _guard(user)
    with _connect(user.username) as conn, conn.cursor() as cur:
        cur.execute("""SELECT PERIOD_YEAR, PERIOD_MONTH, STATUS, LOCKED_BY,
                              TO_CHAR(LOCKED_AT,'DD-Mon-YYYY HH24:MI') AS LOCKED_AT,
                              REOPENED_BY, REOPEN_REASON
                       FROM wst_djn_fin_period WHERE DIVISION = :1
                       ORDER BY PERIOD_YEAR DESC, PERIOD_MONTH DESC""", [division])
        return _dicts(cur)


def _locked_list(cur, division):
    cur.execute("""SELECT PERIOD_YEAR, PERIOD_MONTH FROM wst_djn_fin_period
                   WHERE DIVISION = :1 AND STATUS = 'LOCKED'""", [division])
    return [(int(y), int(m)) for y, m in cur.fetchall()]


def lock_period(user, division, year, month, request=None, today=None):
    """Return error string or ''."""
    _guard(user)
    path, ip = audit.request_context(request) if request else (None, None)
    with _connect(user.username) as conn:
        with conn.cursor() as cur:
            # Locks existing rows for this division so two clicks cannot race (the
            # unique key on division/year/month covers the very first lock).
            cur.execute("""SELECT PERIOD_ID FROM wst_djn_fin_period WHERE DIVISION = :1 FOR UPDATE""", [division])
            ok, message = v.can_lock_period(year, month, _locked_list(cur, division), today)
            if not ok:
                conn.rollback()
                return message
            cur.execute("""UPDATE wst_djn_fin_period SET status = 'LOCKED', locked_by = :actor, locked_at = SYSTIMESTAMP
                           WHERE division = :d AND period_year = :y AND period_month = :m""",
                        {'actor': user.username, 'd': division, 'y': year, 'm': month})
            if cur.rowcount == 0:
                cur.execute("""INSERT INTO wst_djn_fin_period (division, period_year, period_month, status, locked_by, locked_at)
                               VALUES (:d, :y, :m, 'LOCKED', :actor, SYSTIMESTAMP)""",
                            {'d': division, 'y': year, 'm': month, 'actor': user.username})
            audit.record_changes(cur, user.username, 'FIN_PERIOD', f'{division}-{year}-{month:02d}', 'UPDATE',
                                 old={'status': 'OPEN'}, new={'status': 'LOCKED'}, path=path, ip=ip)
        conn.commit()
    return ''


def reopen_period(user, division, year, month, reason, request=None):
    """Return error string or ''."""
    _guard(user)
    path, ip = audit.request_context(request) if request else (None, None)
    with _connect(user.username) as conn:
        with conn.cursor() as cur:
            cur.execute("""SELECT PERIOD_ID FROM wst_djn_fin_period WHERE DIVISION = :1 FOR UPDATE""", [division])
            ok, message = v.can_reopen_period(year, month, _locked_list(cur, division), reason)
            if not ok:
                conn.rollback()
                return message
            cur.execute("""UPDATE wst_djn_fin_period SET status = 'OPEN', reopened_by = :actor, reopened_at = SYSTIMESTAMP,
                           reopen_reason = :r
                           WHERE division = :d AND period_year = :y AND period_month = :m""",
                        {'actor': user.username, 'r': reason.strip()[:300], 'd': division, 'y': year, 'm': month})
            audit.record_changes(cur, user.username, 'FIN_PERIOD', f'{division}-{year}-{month:02d}', 'UPDATE',
                                 old={'status': 'LOCKED'}, new={'status': 'OPEN', 'reason': reason.strip()[:300]},
                                 path=path, ip=ip)
        conn.commit()
    return ''


# ------------------------------------------------------------------- audit
def fetch_audit(user, event_type=None, limit=200):
    _guard(user)
    limit = max(1, min(int(limit), 500))
    sql = """SELECT LOG_ID, TO_CHAR(EVENT_TIME,'DD-Mon-YYYY HH24:MI:SS') AS EVENT_TIME, ACTOR, EVENT_TYPE,
                    TABLE_NAME, RECORD_ID, ACTION, FIELD_NAME, OLD_VALUE, NEW_VALUE, REQUEST_PATH, IP_ADDRESS
             FROM wst_djn_fin_audit_log"""
    params = []
    if event_type in ('CHANGE', 'DENIED', 'ACCESS'):
        sql += " WHERE EVENT_TYPE = :1"
        params.append(event_type)
    sql += f" ORDER BY LOG_ID DESC FETCH FIRST {limit} ROWS ONLY"
    with _connect(user.username) as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        return _dicts(cur)


def write_denial(username, path, ip, layer):
    """Called only by audit.log_denied (after the access check has already
    failed), so it has no guard of its own."""
    with _connect(username) as conn:
        with conn.cursor() as cur:
            cur.execute("""INSERT INTO wst_djn_fin_audit_log
                           (actor, event_type, table_name, action, new_value, request_path, ip_address)
                           VALUES (:1, 'DENIED', 'FINANCE_ACCESS', 'DENIED', :2, :3, :4)""",
                        [username, f'blocked by {layer}', (path or '')[:300], (ip or '')[:120]])
        conn.commit()


def record_access(user, request, what):
    """Log that the Super Admin opened a sensitive screen (audit page)."""
    _guard(user)
    path, ip = audit.request_context(request)
    with _connect(user.username) as conn:
        with conn.cursor() as cur:
            cur.execute("""INSERT INTO wst_djn_fin_audit_log
                           (actor, event_type, table_name, action, new_value, request_path, ip_address)
                           VALUES (:1, 'ACCESS', 'FINANCE_ACCESS', 'VIEW', :2, :3, :4)""",
                        [user.username, what, path[:300], ip[:120]])
        conn.commit()


# --------------------------------------------------------------- dashboard
def dashboard_counts(user):
    _guard(user)
    with _connect(user.username) as conn, conn.cursor() as cur:
        cur.execute("""SELECT (SELECT COUNT(*) FROM wst_djn_fin_account WHERE IS_ACTIVE = 1) AS ACCOUNTS,
                              (SELECT COUNT(*) FROM wst_djn_fin_account WHERE IS_ACTIVE = 1 AND IS_POSTING = 1) AS POSTING_HEADS,
                              (SELECT COUNT(*) FROM wst_djn_fin_period WHERE STATUS = 'LOCKED') AS LOCKED_PERIODS,
                              (SELECT COUNT(*) FROM wst_djn_fin_posting_rule WHERE IS_ACTIVE = 1) AS RULES,
                              (SELECT COUNT(*) FROM wst_djn_fin_audit_log WHERE EVENT_TYPE = 'DENIED'
                                  AND EVENT_TIME > SYSTIMESTAMP - INTERVAL '7' DAY) AS DENIED_7D,
                              (SELECT COUNT(*) FROM wst_djn_fin_event_log WHERE STATUS = 'FAILED') AS FAILED_EVENTS,
                              (SELECT NVL(SUM(REMAINING),0) FROM wst_djn_fin_advance WHERE STATUS = 'ACTIVE') AS ADVANCE_TOTAL,
                              (SELECT COUNT(DISTINCT PARTY_ID) FROM wst_djn_fin_advance WHERE STATUS = 'ACTIVE' AND REMAINING > 0) AS ADVANCE_CUSTOMERS
                       FROM dual""")
        return _dicts(cur)[0]


# =================================================================== PHASE 2
# Customers, advances, vouchers, events. Super Admin only (same _guard).

def fetch_customers(user, search=None):
    """Customers (vendors on Sales Orders) with their advance position."""
    _guard(user)
    sql = """SELECT v.VENDOR_ID, v.VENDOR_NAME, a.DIVISION,
                    SUM(a.AMOUNT) AS TOTAL_IN, SUM(a.AMOUNT - a.REMAINING) AS USED, SUM(a.REMAINING) AS BALANCE
             FROM wst_djn_fin_advance a JOIN wst_djn_vendors v ON v.VENDOR_ID = a.PARTY_ID
             WHERE a.STATUS = 'ACTIVE'"""
    params = []
    if search:
        sql += " AND UPPER(v.VENDOR_NAME) LIKE UPPER(:s)"
        params.append(f'%{search}%')
    sql += " GROUP BY v.VENDOR_ID, v.VENDOR_NAME, a.DIVISION ORDER BY v.VENDOR_NAME, a.DIVISION"
    with _connect(user.username) as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        return _dicts(cur)


def fetch_customer_options(user):
    _guard(user)
    with _connect(user.username) as conn, conn.cursor() as cur:
        cur.execute("SELECT VENDOR_ID, VENDOR_NAME FROM wst_djn_vendors ORDER BY VENDOR_NAME")
        return _dicts(cur)


def fetch_customer_name(user, party_id):
    _guard(user)
    with _connect(user.username) as conn, conn.cursor() as cur:
        cur.execute("SELECT VENDOR_NAME FROM wst_djn_vendors WHERE VENDOR_ID = :1", [int(party_id)])
        row = cur.fetchone()
        return row[0] if row else None


def fetch_customer_ledger(user, party_id):
    """Every voucher line for the customer, oldest first, with a running
    balance of the customer-advance account (credit minus debit)."""
    _guard(user)
    with _connect(user.username) as conn, conn.cursor() as cur:
        cur.execute("""SELECT TO_CHAR(h.VOUCHER_DATE,'DD-Mon-YYYY') AS VOUCHER_DATE, h.VOUCHER_ID, h.VOUCHER_NO, h.TYPE_CODE,
                              h.STATUS, h.NARRATION, a.ACCOUNT_CODE, a.ACCOUNT_NAME, a.SYSTEM_KEY, l.DEBIT, l.CREDIT
                       FROM wst_djn_fin_voucher_line l
                       JOIN wst_djn_fin_voucher h ON h.VOUCHER_ID = l.VOUCHER_ID
                       JOIN wst_djn_fin_account a ON a.ACCOUNT_ID = l.ACCOUNT_ID
                       WHERE l.PARTY_ID = :1
                       ORDER BY h.VOUCHER_DATE, h.VOUCHER_ID, l.LINE_NO""", [int(party_id)])
        rows = _dicts(cur)
    from decimal import Decimal
    running = Decimal('0.00')
    for r in rows:
        if r['SYSTEM_KEY'] == 'CUSTOMER_ADVANCE':
            running += Decimal(str(r['CREDIT'])) - Decimal(str(r['DEBIT']))
            r['ADVANCE_BALANCE'] = running
        else:
            r['ADVANCE_BALANCE'] = None
    return rows


def fetch_advances(user, party_id=None, limit=200):
    _guard(user)
    sql = """SELECT a.ADVANCE_ID, a.PARTY_ID, v.VENDOR_NAME, a.DIVISION, TO_CHAR(a.ADVANCE_DATE,'DD-Mon-YYYY') AS ADVANCE_DATE,
                    a.KIND, a.PAY_MODE, a.REFERENCE, a.AMOUNT, a.REMAINING, a.STATUS, a.CREATED_BY
             FROM wst_djn_fin_advance a JOIN wst_djn_vendors v ON v.VENDOR_ID = a.PARTY_ID WHERE 1=1"""
    params = []
    if party_id:
        sql += " AND a.PARTY_ID = :p"
        params.append(int(party_id))
    sql += " ORDER BY a.ADVANCE_DATE DESC, a.ADVANCE_ID DESC FETCH FIRST :n ROWS ONLY"
    params.append(int(limit))
    with _connect(user.username) as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        return _dicts(cur)


def receive_advance_entry(user, form, request=None):
    """Return (message, errors)."""
    _guard(user)
    from . import ledger as L
    from . import posting as P
    path, ip = audit.request_context(request) if request else (None, None)
    errors = []
    try:
        party_id = int(form.get('party_id') or 0)
    except ValueError:
        party_id = 0
    division = (form.get('division') or '').strip()
    if not party_id:
        errors.append('Choose a customer.')
    if not division:
        errors.append('Choose a division.')
    try:
        adv_date = L.as_date(form.get('advance_date'))
    except ValueError:
        adv_date = None
        errors.append('Enter the date as YYYY-MM-DD.')
    if errors:
        return None, errors
    with _connect(user.username) as conn:
        with conn.cursor() as cur:
            try:
                advance_id, vid = P.receive_advance(cur, user.username, party_id, division, adv_date,
                                                    (form.get('mode') or '').upper(), form.get('reference'),
                                                    form.get('amount'))
                audit.record_changes(cur, user.username, 'FIN_ADVANCE', advance_id, 'CREATE',
                                     new=f"party={party_id} {form.get('mode')} {form.get('amount')}", path=path, ip=ip)
            except L.FinanceRuleError as exc:
                conn.rollback()
                return None, [str(exc)]
        conn.commit()
    return 'Advance recorded.', []


def load_opening_entry(user, form, request=None):
    """Return (message, errors)."""
    _guard(user)
    from . import ledger as L
    from . import posting as P
    path, ip = audit.request_context(request) if request else (None, None)
    try:
        party_id = int(form.get('party_id') or 0)
    except ValueError:
        party_id = 0
    division = (form.get('division') or '').strip()
    if not party_id or not division:
        return None, ['Choose a customer and a division.']
    with _connect(user.username) as conn:
        with conn.cursor() as cur:
            try:
                advance_id, vid = P.load_opening_advance(cur, user.username, party_id, division,
                                                         form.get('amount'), form.get('reference'))
                audit.record_changes(cur, user.username, 'FIN_ADVANCE', advance_id, 'CREATE',
                                     new=f"OPENING party={party_id} {form.get('amount')}", path=path, ip=ip)
            except L.FinanceRuleError as exc:
                conn.rollback()
                return None, [str(exc)]
        conn.commit()
    return 'Opening balance loaded.', []


def reverse_advance_entry(user, advance_id, reason, request=None):
    """Return error string or ''."""
    _guard(user)
    from . import ledger as L
    from . import posting as P
    with _connect(user.username) as conn:
        with conn.cursor() as cur:
            try:
                P.reverse_advance(cur, user.username, int(advance_id), reason)
            except L.FinanceRuleError as exc:
                conn.rollback()
                return str(exc)
        conn.commit()
    return ''


def fetch_vouchers(user, search=None, limit=200):
    _guard(user)
    sql = """SELECT h.VOUCHER_ID, h.VOUCHER_NO, h.TYPE_CODE, h.DIVISION, TO_CHAR(h.VOUCHER_DATE,'DD-Mon-YYYY') AS VOUCHER_DATE,
                    v.VENDOR_NAME, h.NARRATION, h.SOURCE_TYPE, h.SOURCE_ID, h.AMOUNT, h.STATUS, h.CREATED_BY
             FROM wst_djn_fin_voucher h LEFT JOIN wst_djn_vendors v ON v.VENDOR_ID = h.PARTY_ID WHERE 1=1"""
    params = []
    if search:
        sql += " AND (UPPER(h.VOUCHER_NO) LIKE UPPER(:s1) OR UPPER(h.SOURCE_ID) LIKE UPPER(:s2) OR UPPER(v.VENDOR_NAME) LIKE UPPER(:s3))"
        params += [f'%{search}%'] * 3
    sql += " ORDER BY h.VOUCHER_ID DESC FETCH FIRST :n ROWS ONLY"
    params.append(int(limit))
    with _connect(user.username) as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        return _dicts(cur)


def fetch_voucher(user, voucher_id):
    _guard(user)
    with _connect(user.username) as conn, conn.cursor() as cur:
        cur.execute("""SELECT h.VOUCHER_ID, h.VOUCHER_NO, h.TYPE_CODE, h.DIVISION, TO_CHAR(h.VOUCHER_DATE,'DD-Mon-YYYY') AS VOUCHER_DATE,
                              v.VENDOR_NAME, h.NARRATION, h.SOURCE_TYPE, h.SOURCE_ID, h.AMOUNT, h.STATUS, h.CREATED_BY,
                              TO_CHAR(h.CREATED_AT,'DD-Mon-YYYY HH24:MI') AS CREATED_AT, h.REVERSES_VOUCHER_ID
                       FROM wst_djn_fin_voucher h LEFT JOIN wst_djn_vendors v ON v.VENDOR_ID = h.PARTY_ID
                       WHERE h.VOUCHER_ID = :1""", [int(voucher_id)])
        rows = _dicts(cur)
        if not rows:
            return None, []
        cur.execute("""SELECT l.LINE_NO, a.ACCOUNT_CODE, a.ACCOUNT_NAME, l.DEBIT, l.CREDIT
                       FROM wst_djn_fin_voucher_line l JOIN wst_djn_fin_account a ON a.ACCOUNT_ID = l.ACCOUNT_ID
                       WHERE l.VOUCHER_ID = :1 ORDER BY l.LINE_NO""", [int(voucher_id)])
        return rows[0], _dicts(cur)


def fetch_events(user, status=None, limit=200):
    _guard(user)
    sql = """SELECT EVENT_ID, EVENT_TYPE, SOURCE_ID, DIVISION, TO_CHAR(EVENT_DATE,'DD-Mon-YYYY') AS EVENT_DATE, STATUS,
                    ATTEMPTS, MESSAGE, VOUCHER_IDS, ACTOR, TO_CHAR(NVL(UPDATED_AT, CREATED_AT),'DD-Mon-YYYY HH24:MI') AS WHEN_TS
             FROM wst_djn_fin_event_log WHERE 1=1"""
    params = []
    if status in ('POSTED', 'FAILED', 'SKIPPED'):
        sql += " AND STATUS = :st"
        params.append(status)
    sql += " ORDER BY CASE STATUS WHEN 'FAILED' THEN 0 ELSE 1 END, NVL(UPDATED_AT, CREATED_AT) DESC FETCH FIRST :n ROWS ONLY"
    params.append(int(limit))
    with _connect(user.username) as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        return _dicts(cur)


def fetch_missed_events(user):
    """Gate Passes that the finance hook never saw (hook off, server stopped
    mid-way, ...): posted ones with no GP_POSTED event, and cancelled ones
    whose sale was posted but never reversed. Only dispatches on/after the
    cut-over date."""
    _guard(user)
    with _connect(user.username) as conn, conn.cursor() as cur:
        cur.execute("SELECT SETTING_VALUE FROM wst_djn_fin_setting WHERE SETTING_KEY = 'FINANCE_GO_LIVE_DATE'")
        row = cur.fetchone()
        if not row or not row[0]:
            return []
        cur.execute("""SELECT 'GP_POSTED' AS EVENT_TYPE, g.GATE_PASS_ID AS SOURCE_ID, g.DIVISION,
                              TO_CHAR(g.GATE_PASS_DATE,'DD-Mon-YYYY') AS EVENT_DATE
                       FROM wst_djn_gatepass_header g
                       WHERE g.STATUS = 'Posted' AND g.MODULE_TYPE = 'Shipment'
                         AND g.GATE_PASS_DATE >= TO_DATE(:gl,'YYYY-MM-DD')
                         AND NOT EXISTS (SELECT 1 FROM wst_djn_fin_event_log e
                                         WHERE e.EVENT_TYPE = 'GP_POSTED' AND e.SOURCE_ID = g.GATE_PASS_ID)
                       UNION ALL
                       SELECT 'GP_CANCELLED', g.GATE_PASS_ID, g.DIVISION, TO_CHAR(g.GATE_PASS_DATE,'DD-Mon-YYYY')
                       FROM wst_djn_gatepass_header g
                       JOIN wst_djn_fin_event_log p ON p.EVENT_TYPE = 'GP_POSTED' AND p.SOURCE_ID = g.GATE_PASS_ID AND p.STATUS = 'POSTED'
                       WHERE g.STATUS = 'Cancelled'
                         AND NOT EXISTS (SELECT 1 FROM wst_djn_fin_event_log e
                                         WHERE e.EVENT_TYPE = 'GP_CANCELLED' AND e.SOURCE_ID = g.GATE_PASS_ID
                                           AND e.STATUS IN ('POSTED','SKIPPED'))
                       ORDER BY 4""", {'gl': row[0]})
        return _dicts(cur)


def first_posting_exists(user):
    """True once any dispatch has been posted - the cut-over date is then frozen."""
    _guard(user)
    with _connect(user.username) as conn, conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM wst_djn_fin_event_log WHERE STATUS = 'POSTED'")
        return cur.fetchone()[0] > 0


# =================================================================== PHASE 3
# Adjustments. Super Admin only (same _guard).

def _int_or_zero(raw):
    try:
        return int(raw or 0)
    except (TypeError, ValueError):
        return 0


def _run_adjustment(user, request, work):
    """Open one connection, run `work(cur)`, commit once. Returns (message, errors)."""
    from . import ledger as L
    path, ip = audit.request_context(request) if request else (None, None)
    with _connect(user.username) as conn:
        with conn.cursor() as cur:
            try:
                work(cur)
            except L.FinanceRuleError as exc:
                conn.rollback()
                return None, [str(exc)]
        conn.commit()
    return 'Saved.', []


def fetch_adjustments(user, limit=200):
    _guard(user)
    with _connect(user.username) as conn, conn.cursor() as cur:
        cur.execute("""SELECT a.ADJUSTMENT_ID, a.ADJ_TYPE, a.DIVISION, TO_CHAR(a.ADJ_DATE,'DD-Mon-YYYY') AS ADJ_DATE,
                              v.VENDOR_NAME, v2.VENDOR_NAME AS TO_NAME, a.SOURCE_REF, a.AMOUNT, a.REASON, a.STATUS,
                              a.CREATED_BY, a.REVERSAL_REASON
                       FROM wst_djn_fin_adjustment a
                       LEFT JOIN wst_djn_vendors v  ON v.VENDOR_ID  = a.PARTY_ID
                       LEFT JOIN wst_djn_vendors v2 ON v2.VENDOR_ID = a.TO_PARTY_ID
                       ORDER BY a.ADJUSTMENT_ID DESC FETCH FIRST :n ROWS ONLY""", {'n': int(limit)})
        return _dicts(cur)


def fetch_gatepass_receivables(user, gate_pass_id):
    """The sale(s) a Gate Pass created, for the credit / debit note forms."""
    _guard(user)
    with _connect(user.username) as conn, conn.cursor() as cur:
        cur.execute("""SELECT r.RECEIVABLE_ID, r.PARTY_ID, v.VENDOR_NAME, r.DIVISION, r.SOURCE_ID,
                              TO_CHAR(r.DOC_DATE,'DD-Mon-YYYY') AS DOC_DATE, r.AMOUNT, r.STATUS
                       FROM wst_djn_fin_receivable r JOIN wst_djn_vendors v ON v.VENDOR_ID = r.PARTY_ID
                       WHERE r.SOURCE_TYPE = 'GATEPASS' AND UPPER(r.SOURCE_ID) = UPPER(:1) AND r.STATUS <> 'REVERSED'
                       ORDER BY r.RECEIVABLE_ID""", [(gate_pass_id or '').strip()])
        return _dicts(cur)


def fetch_posting_accounts(user):
    _guard(user)
    with _connect(user.username) as conn, conn.cursor() as cur:
        cur.execute("""SELECT ACCOUNT_ID, ACCOUNT_CODE, ACCOUNT_NAME, SYSTEM_KEY FROM wst_djn_fin_account
                       WHERE IS_ACTIVE = 1 AND IS_POSTING = 1 ORDER BY ACCOUNT_CODE""")
        return _dicts(cur)


def refund_entry(user, form, request=None):
    _guard(user)
    from . import posting as P
    from . import ledger as L
    try:
        d = L.as_date(form.get('adj_date'))
    except ValueError:
        return None, ['Enter the date as YYYY-MM-DD.']
    return _run_adjustment(user, request, lambda cur: P.refund_advance(
        cur, user.username, _int_or_zero(form.get('party_id')), (form.get('division') or '').strip(), d,
        (form.get('mode') or '').upper(), form.get('reference'), form.get('amount'), form.get('reason')))


def note_entry(user, form, request=None):
    _guard(user)
    from . import posting as P
    from . import ledger as L
    try:
        d = L.as_date(form.get('adj_date'))
    except ValueError:
        return None, ['Enter the date as YYYY-MM-DD.']
    kind = (form.get('note_type') or '').upper()
    if kind not in ('CREDIT', 'DEBIT'):
        return None, ['Choose credit note or debit note.']
    fn = P.credit_note if kind == 'CREDIT' else P.debit_note
    return _run_adjustment(user, request, lambda cur: fn(
        cur, user.username, _int_or_zero(form.get('receivable_id')), d, form.get('amount'), form.get('reason')))


def transfer_entry(user, form, request=None):
    _guard(user)
    from . import posting as P
    from . import ledger as L
    try:
        d = L.as_date(form.get('adj_date'))
    except ValueError:
        return None, ['Enter the date as YYYY-MM-DD.']
    return _run_adjustment(user, request, lambda cur: P.transfer_advance(
        cur, user.username, _int_or_zero(form.get('from_party')), _int_or_zero(form.get('to_party')),
        (form.get('division') or '').strip(), d, form.get('amount'), form.get('reason')))


def journal_entry_post(user, form, request=None):
    _guard(user)
    from . import posting as P
    from . import ledger as L
    try:
        d = L.as_date(form.get('adj_date'))
    except ValueError:
        return None, ['Enter the date as YYYY-MM-DD.']
    getlist = form.getlist if hasattr(form, 'getlist') else (lambda k: form.get(k, []))
    accounts, debits, credits = getlist('account_id'), getlist('debit'), getlist('credit')
    rows = []
    for i, acc in enumerate(accounts):
        if not str(acc).strip():
            continue
        rows.append({'account_id': _int_or_zero(acc),
                     'debit': (debits[i] if i < len(debits) else '') or 0,
                     'credit': (credits[i] if i < len(credits) else '') or 0})
    return _run_adjustment(user, request, lambda cur: P.journal_entry(
        cur, user.username, (form.get('division') or '').strip(), d, form.get('narration'), rows))


def reverse_adjustment_entry(user, adjustment_id, reason, request=None):
    """Return error string or ''."""
    _guard(user)
    from . import posting as P
    message, errors = _run_adjustment(user, request, lambda cur: P.reverse_adjustment(
        cur, user.username, int(adjustment_id), reason))
    return errors[0] if errors else ''


# ======================================================================
# PHASE 4 - report data. Read-only: plain rows in, all arithmetic in reports.py
# ======================================================================
def _division_clause(division, params, alias='h'):
    if division:
        params['div'] = division
        return f' AND {alias}.DIVISION = :div'
    return ''


def fetch_statement(user, party_id, division, d_from, d_to):
    """(customer name, opening balance, lines) of the customer-advance account."""
    _guard(user)
    from . import reports
    params = {'party': int(party_id), 'dfrom': d_from, 'dto': d_to}
    div_sql = _division_clause(division, params)
    open_params = {'party': params['party'], 'dfrom': d_from}
    open_div = _division_clause(division, open_params)
    with _connect(user.username) as conn, conn.cursor() as cur:
        cur.execute("SELECT VENDOR_NAME FROM wst_djn_vendors WHERE VENDOR_ID = :party", {'party': params['party']})
        row = cur.fetchone()
        if not row:
            return None, None, []
        cur.execute(f"""SELECT NVL(SUM(l.CREDIT - l.DEBIT), 0)
                        FROM wst_djn_fin_voucher_line l
                        JOIN wst_djn_fin_voucher h ON h.VOUCHER_ID = l.VOUCHER_ID
                        JOIN wst_djn_fin_account a ON a.ACCOUNT_ID = l.ACCOUNT_ID AND a.SYSTEM_KEY = 'CUSTOMER_ADVANCE'
                        WHERE l.PARTY_ID = :party AND h.VOUCHER_DATE < :dfrom{open_div}""", open_params)
        opening = cur.fetchone()[0]
        cur.execute(f"""SELECT TO_CHAR(h.VOUCHER_DATE,'DD-Mon-YYYY') AS VOUCHER_DATE, h.VOUCHER_ID, h.VOUCHER_NO, h.TYPE_CODE,
                               h.SOURCE_TYPE, adj.ADJ_TYPE, h.NARRATION, h.STATUS, l.DEBIT, l.CREDIT
                        FROM wst_djn_fin_voucher_line l
                        JOIN wst_djn_fin_voucher h ON h.VOUCHER_ID = l.VOUCHER_ID
                        JOIN wst_djn_fin_account a ON a.ACCOUNT_ID = l.ACCOUNT_ID AND a.SYSTEM_KEY = 'CUSTOMER_ADVANCE'
                        LEFT JOIN wst_djn_fin_adjustment adj ON h.SOURCE_TYPE = 'ADJUSTMENT' AND TO_CHAR(adj.ADJUSTMENT_ID) = h.SOURCE_ID
                        WHERE l.PARTY_ID = :party AND h.VOUCHER_DATE >= :dfrom AND h.VOUCHER_DATE < :dto + 1{div_sql}
                        ORDER BY h.VOUCHER_DATE, h.VOUCHER_ID, l.LINE_NO""", params)
        lines = _dicts(cur)
    return row[0], opening, lines


def fetch_trial_balance_rows(user, division, cutoff):
    _guard(user)
    params = {'cutoff': cutoff}
    div_sql = _division_clause(division, params)
    with _connect(user.username) as conn, conn.cursor() as cur:
        cur.execute(f"""SELECT a.ACCOUNT_ID, a.ACCOUNT_CODE, a.ACCOUNT_NAME, a.ACCOUNT_TYPE,
                               SUM(x.DEBIT) AS DEBIT, SUM(x.CREDIT) AS CREDIT
                        FROM wst_djn_fin_account a
                        JOIN (SELECT l.ACCOUNT_ID, l.DEBIT, l.CREDIT
                              FROM wst_djn_fin_voucher_line l
                              JOIN wst_djn_fin_voucher h ON h.VOUCHER_ID = l.VOUCHER_ID
                              WHERE h.VOUCHER_DATE < :cutoff + 1{div_sql}) x ON x.ACCOUNT_ID = a.ACCOUNT_ID
                        GROUP BY a.ACCOUNT_ID, a.ACCOUNT_CODE, a.ACCOUNT_NAME, a.ACCOUNT_TYPE
                        ORDER BY a.ACCOUNT_CODE""", params)
        return _dicts(cur)


def fetch_ledger_accounts(user):
    """Every posting head, active or not, for the General Ledger picker."""
    _guard(user)
    with _connect(user.username) as conn, conn.cursor() as cur:
        cur.execute("""SELECT ACCOUNT_ID, ACCOUNT_CODE, ACCOUNT_NAME FROM wst_djn_fin_account
                       WHERE IS_POSTING = 1 ORDER BY ACCOUNT_CODE""")
        return _dicts(cur)


def fetch_general_ledger(user, account_id, division, d_from, d_to):
    """(account row or None, opening net debit-minus-credit, lines)."""
    _guard(user)
    params = {'acc': int(account_id), 'dfrom': d_from, 'dto': d_to}
    div_sql = _division_clause(division, params)
    open_params = {'acc': params['acc'], 'dfrom': d_from}
    open_div = _division_clause(division, open_params)
    with _connect(user.username) as conn, conn.cursor() as cur:
        cur.execute("""SELECT ACCOUNT_ID, ACCOUNT_CODE, ACCOUNT_NAME FROM wst_djn_fin_account
                       WHERE ACCOUNT_ID = :acc AND IS_POSTING = 1""", {'acc': params['acc']})
        found = _dicts(cur)
        if not found:
            return None, None, []
        cur.execute(f"""SELECT NVL(SUM(l.DEBIT - l.CREDIT), 0)
                        FROM wst_djn_fin_voucher_line l JOIN wst_djn_fin_voucher h ON h.VOUCHER_ID = l.VOUCHER_ID
                        WHERE l.ACCOUNT_ID = :acc AND h.VOUCHER_DATE < :dfrom{open_div}""", open_params)
        opening = cur.fetchone()[0]
        cur.execute(f"""SELECT TO_CHAR(h.VOUCHER_DATE,'DD-Mon-YYYY') AS VOUCHER_DATE, h.VOUCHER_ID, h.VOUCHER_NO, h.TYPE_CODE,
                               h.DIVISION, v.VENDOR_NAME AS PARTY_NAME, h.NARRATION, h.STATUS, l.DEBIT, l.CREDIT
                        FROM wst_djn_fin_voucher_line l
                        JOIN wst_djn_fin_voucher h ON h.VOUCHER_ID = l.VOUCHER_ID
                        LEFT JOIN wst_djn_vendors v ON v.VENDOR_ID = l.PARTY_ID
                        WHERE l.ACCOUNT_ID = :acc AND h.VOUCHER_DATE >= :dfrom AND h.VOUCHER_DATE < :dto + 1{div_sql}
                        ORDER BY h.VOUCHER_DATE, h.VOUCHER_ID, l.LINE_NO""", params)
        lines = _dicts(cur)
    return found[0], opening, lines


def fetch_sales_rows(user, division, d_from, d_to):
    _guard(user)
    params = {'dfrom': d_from, 'dto': d_to}
    div_sql = _division_clause(division, params)
    with _connect(user.username) as conn, conn.cursor() as cur:
        cur.execute(f"""SELECT TRUNC(h.VOUCHER_DATE) AS PERIOD_DATE, h.DIVISION, a.SYSTEM_KEY, h.SOURCE_TYPE,
                               SUM(l.CREDIT - l.DEBIT) AS NET
                        FROM wst_djn_fin_voucher_line l
                        JOIN wst_djn_fin_voucher h ON h.VOUCHER_ID = l.VOUCHER_ID
                        JOIN wst_djn_fin_account a ON a.ACCOUNT_ID = l.ACCOUNT_ID
                        WHERE a.SYSTEM_KEY IN ('SALES_INCOME','SALES_RETURNS','CUSTOMER_ADVANCE')
                          AND h.VOUCHER_DATE >= :dfrom AND h.VOUCHER_DATE < :dto + 1{div_sql}
                        GROUP BY TRUNC(h.VOUCHER_DATE), h.DIVISION, a.SYSTEM_KEY, h.SOURCE_TYPE""", params)
        return _dicts(cur)


def fetch_reconciliation_data(user):
    """Everything reports.reconcile needs, read on one connection so the
    figures describe the same moment."""
    _guard(user)
    missed = fetch_missed_events(user)
    with _connect(user.username) as conn, conn.cursor() as cur:
        cur.execute("""SELECT NVL(SUM(l.CREDIT - l.DEBIT), 0) FROM wst_djn_fin_voucher_line l
                       JOIN wst_djn_fin_account a ON a.ACCOUNT_ID = l.ACCOUNT_ID AND a.SYSTEM_KEY = 'CUSTOMER_ADVANCE'""")
        control_advance = cur.fetchone()[0]
        cur.execute("""SELECT l.PARTY_ID, v.VENDOR_NAME AS PARTY_NAME, SUM(l.CREDIT - l.DEBIT) AS AMOUNT
                       FROM wst_djn_fin_voucher_line l
                       JOIN wst_djn_fin_account a ON a.ACCOUNT_ID = l.ACCOUNT_ID AND a.SYSTEM_KEY = 'CUSTOMER_ADVANCE'
                       LEFT JOIN wst_djn_vendors v ON v.VENDOR_ID = l.PARTY_ID
                       WHERE l.PARTY_ID IS NOT NULL GROUP BY l.PARTY_ID, v.VENDOR_NAME""")
        ledger_by_party = _dicts(cur)
        cur.execute("""SELECT x.PARTY_ID, v.VENDOR_NAME AS PARTY_NAME, SUM(x.REMAINING) AS AMOUNT
                       FROM wst_djn_fin_advance x LEFT JOIN wst_djn_vendors v ON v.VENDOR_ID = x.PARTY_ID
                       WHERE x.STATUS = 'ACTIVE' GROUP BY x.PARTY_ID, v.VENDOR_NAME""")
        subledger_by_party = _dicts(cur)
        cur.execute("""SELECT COUNT(*) FROM wst_djn_fin_voucher_line l
                       JOIN wst_djn_fin_account a ON a.ACCOUNT_ID = l.ACCOUNT_ID AND a.SYSTEM_KEY = 'CUSTOMER_ADVANCE'
                       WHERE l.PARTY_ID IS NULL""")
        unattributed = cur.fetchone()[0]
        cur.execute("""SELECT NVL(SUM(l.DEBIT - l.CREDIT), 0) FROM wst_djn_fin_voucher_line l
                       JOIN wst_djn_fin_account a ON a.ACCOUNT_ID = l.ACCOUNT_ID AND a.SYSTEM_KEY = 'RECEIVABLE'""")
        control_receivable = cur.fetchone()[0]
        cur.execute("""SELECT NVL(SUM(AMOUNT - SETTLED), 0) FROM wst_djn_fin_receivable WHERE STATUS <> 'REVERSED'""")
        open_receivables = cur.fetchone()[0]
        cur.execute("""SELECT h.VOUCHER_NO, SUM(l.DEBIT) AS DEBIT, SUM(l.CREDIT) AS CREDIT
                       FROM wst_djn_fin_voucher h JOIN wst_djn_fin_voucher_line l ON l.VOUCHER_ID = h.VOUCHER_ID
                       GROUP BY h.VOUCHER_NO HAVING SUM(l.DEBIT) <> SUM(l.CREDIT)
                       FETCH FIRST 50 ROWS ONLY""")
        unbalanced = _dicts(cur)
        cur.execute("""SELECT * FROM (
                         SELECT a.ADVANCE_ID, v.VENDOR_NAME AS PARTY_NAME, a.AMOUNT - a.REMAINING AS USED,
                                NVL((SELECT SUM(k.AMOUNT) FROM wst_djn_fin_allocation k
                                     WHERE k.ADVANCE_ID = a.ADVANCE_ID AND k.STATUS = 'ACTIVE'), 0)
                              + NVL((SELECT SUM(u.AMOUNT) FROM wst_djn_fin_advance_use u
                                     WHERE u.ADVANCE_ID = a.ADVANCE_ID AND u.STATUS = 'ACTIVE'), 0) AS RECORDED
                         FROM wst_djn_fin_advance a LEFT JOIN wst_djn_vendors v ON v.VENDOR_ID = a.PARTY_ID
                         WHERE a.STATUS = 'ACTIVE')
                       WHERE USED <> RECORDED FETCH FIRST 50 ROWS ONLY""")
        mismatches = _dicts(cur)
        cur.execute("SELECT COUNT(*) FROM wst_djn_fin_event_log WHERE STATUS = 'FAILED'")
        failed = cur.fetchone()[0]
    return {'control_advance': control_advance, 'ledger_by_party': ledger_by_party,
            'subledger_by_party': subledger_by_party, 'unattributed_lines': unattributed,
            'control_receivable': control_receivable, 'open_receivables': open_receivables,
            'unbalanced_vouchers': unbalanced, 'advance_mismatches': mismatches,
            'failed_events': failed, 'missed_events': missed}


def fetch_ageing_rows(user, division):
    _guard(user)
    params = {}
    div_sql = ''
    if division:
        params['div'] = division
        div_sql = ' AND a.DIVISION = :div'
    with _connect(user.username) as conn, conn.cursor() as cur:
        cur.execute(f"""SELECT a.PARTY_ID, v.VENDOR_NAME AS PARTY_NAME, a.ADVANCE_DATE, a.REMAINING
                        FROM wst_djn_fin_advance a LEFT JOIN wst_djn_vendors v ON v.VENDOR_ID = a.PARTY_ID
                        WHERE a.STATUS = 'ACTIVE' AND a.REMAINING > 0{div_sql}""", params)
        return _dicts(cur)


def record_export(user, request, what):
    """Every file download of financial figures is written to the audit log."""
    record_access(user, request, what)
