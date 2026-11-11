"""
The ONLY door between the live Gate Pass screens and Finance.

Design rules (all tested):
  * It returns no money. Callers get (allowed, message) or a short status
    word. Messages never contain amounts, balances or customer figures, so
    regular users running a Gate Pass learn nothing about finance.
  * It never raises into the Gate Pass. A finance problem after the Gate Pass
    is saved is written to wst_djn_fin_event_log as FAILED for the Super Admin
    to retry; the Gate Pass itself is already committed and is untouched.
  * Kill switch: nothing here runs unless settings.FINANCE_HOOKS_ENABLED is
    true, and nothing posts for dispatches dated before the cut-over date.
  * Prepaid policy: BEFORE a Gate Pass is posted, check_dispatch_allowed()
    refuses the dispatch when the customer's advance cannot cover it. This
    one check fails CLOSED (if it cannot be completed, the dispatch is not
    released).
"""
import logging

from django.conf import settings
from django.core.exceptions import PermissionDenied

from . import ledger as L
from . import posting as P
from .access import is_finance_admin

logger = logging.getLogger('apps.finance.gateway')


def hooks_enabled():
    return bool(getattr(settings, 'FINANCE_HOOKS_ENABLED', False))


def _actor(user_or_name):
    return getattr(user_or_name, 'username', None) or (str(user_or_name) if user_or_name else 'SYSTEM')


# ------------------------------------------------------------ DB readers
def _resolve_lines(cur, lines):
    """Pre-check input: [{'so_line_id', 'gatepass_qty'}] -> priced lines."""
    resolved = []
    for ln in lines:
        so_line_id = ln.get('so_line_id')
        if not so_line_id:
            raise L.MissingPrice('A dispatched line is not linked to a Sales Order line.')
        cur.execute("""SELECT sl.UNIT_PRICE, sh.VENDOR_ID FROM wst_djn_sales_line sl
                       JOIN wst_djn_sales_header sh ON sh.DOC_ID = sl.DOC_ID WHERE sl.LINE_ID = :1""", [int(so_line_id)])
        row = cur.fetchone()
        if not row:
            raise L.MissingPrice('A dispatched line has no Sales Order line.')
        resolved.append({'customer_id': row[1], 'qty': ln.get('gatepass_qty'), 'unit_price': row[0]})
    return resolved


def _load_gate_pass(cur, gp_id):
    cur.execute("""SELECT GATE_PASS_ID, DIVISION, MODULE_TYPE, STATUS, GATE_PASS_DATE
                   FROM wst_djn_gatepass_header WHERE GATE_PASS_ID = :1""", [gp_id])
    rows = P._dicts(cur)
    if not rows:
        return None, []
    cur.execute("""SELECT gl.SO_LINE_ID, gl.GATEPASS_QTY AS QTY FROM wst_djn_gatepass_line gl
                   WHERE gl.GATE_PASS_ID = :1 ORDER BY gl.LINE_NO""", [gp_id])
    lines = [{'so_line_id': r[0], 'gatepass_qty': r[1]} for r in cur.fetchall()]
    return rows[0], lines


# -------------------------------------------------------------- pre-check
def check_dispatch_allowed(header, lines, user=None):
    """Called by the Gate Pass screen right before posting.
    Returns (True, '') or (False, safe_message)."""
    if not hooks_enabled():
        return True, ''
    if (header or {}).get('module_type') != 'Shipment':
        return True, ''
    try:
        with P._connect(_actor(user)) as conn, conn.cursor() as cur:
            gp_date = (header or {}).get('gate_pass_date')
            if not L.is_live(gp_date, P.go_live_date(cur)):
                return True, ''
            totals = L.group_dispatch_by_customer(_resolve_lines(cur, lines or []))
            blocked = 0
            for customer_id, needed in totals.items():
                if not L.can_dispatch(P.advance_available(cur, customer_id), needed):
                    blocked += 1
            if blocked:
                return False, L.user_message(blocked_customers=blocked)
            return True, ''
    except L.MissingPrice:
        return False, L.user_message(missing_price=True)
    except Exception:
        logger.exception('Prepaid advance check failed; dispatch not released')
        return False, L.user_message(error=True)


# -------------------------------------------------------- event workers
def _process_posted(gp_id, actor):
    """Post (or re-post after a failure) the sale for one Gate Pass.
    Returns (status, message). Never raises."""
    status, message, vids, division, gp_date = L.ST_FAILED, '', [], None, None
    try:
        with P.system_context(), P._connect(actor) as conn:
            with conn.cursor() as cur:
                try:
                    ev = P.event_row(cur, L.EVENT_GP_POSTED, gp_id, for_update=True)
                    if ev and ev['STATUS'] == L.ST_POSTED:
                        return L.ST_POSTED, 'Already posted.'
                    gp, lines = _load_gate_pass(cur, gp_id)
                    if not gp:
                        raise L.FinanceRuleError('Gate Pass not found.')
                    division, gp_date = gp['DIVISION'], gp['GATE_PASS_DATE']
                    if gp['STATUS'] != 'Posted':
                        status, message = L.ST_SKIPPED, f"Gate Pass is {gp['STATUS']}, not Posted."
                    elif gp['MODULE_TYPE'] != 'Shipment':
                        status, message = L.ST_SKIPPED, 'Transfer: not a sale.'
                    elif not L.is_live(gp_date, P.go_live_date(cur)):
                        status, message = L.ST_SKIPPED, 'Dated before the finance cut-over.'
                    else:
                        totals = L.group_dispatch_by_customer(_resolve_lines(cur, lines))
                        for customer_id, amount in totals.items():
                            vids += P.post_dispatch_for_customer(cur, actor, gp_id, division, gp_date, customer_id, amount)
                        status, message = L.ST_POSTED, f'Posted for {len(totals)} customer(s).'
                    P.write_event(cur, L.EVENT_GP_POSTED, gp_id, division, gp_date, status, message, vids, actor)
                    conn.commit()
                    return status, message
                except Exception:
                    conn.rollback()
                    raise
    except Exception as exc:
        logger.exception('Finance posting failed for Gate Pass %s', gp_id)
        message = str(exc)[:400] or exc.__class__.__name__
    _record_failure(L.EVENT_GP_POSTED, gp_id, division, gp_date, message, actor)
    return L.ST_FAILED, message


def _process_cancelled(gp_id, actor):
    """Reverse what a cancelled Gate Pass posted. Returns (status, message). Never raises."""
    message = ''
    division = gp_date = None
    try:
        with P.system_context(), P._connect(actor) as conn:
            with conn.cursor() as cur:
                try:
                    done = P.event_row(cur, L.EVENT_GP_CANCELLED, gp_id, for_update=True)
                    if done and done['STATUS'] in (L.ST_POSTED, L.ST_SKIPPED):
                        return done['STATUS'], 'Already handled.'
                    gp, _lines = _load_gate_pass(cur, gp_id)
                    if not gp:
                        raise L.FinanceRuleError('Gate Pass not found.')
                    division, gp_date = gp['DIVISION'], gp['GATE_PASS_DATE']
                    if gp['STATUS'] != 'Cancelled':
                        raise L.FinanceRuleError(f"Gate Pass is {gp['STATUS']}, not Cancelled.")
                    orig = P.event_row(cur, L.EVENT_GP_POSTED, gp_id, for_update=True)
                    if orig and orig['STATUS'] == L.ST_POSTED:
                        vids = P.reverse_dispatch(cur, actor, gp_id, f'Gate Pass {gp_id} cancelled')
                        status, message = L.ST_POSTED, 'Sale reversed and advance restored.'
                        cur.execute("""UPDATE wst_djn_fin_event_log SET MESSAGE = 'Reversed: Gate Pass cancelled',
                                       UPDATED_AT = LOCALTIMESTAMP WHERE EVENT_TYPE = :1 AND SOURCE_ID = :2""",
                                    [L.EVENT_GP_POSTED, gp_id])
                    else:
                        vids = []
                        status, message = L.ST_SKIPPED, 'Nothing was posted to reverse.'
                        if orig and orig['STATUS'] == L.ST_FAILED:
                            cur.execute("""UPDATE wst_djn_fin_event_log SET STATUS = 'SKIPPED',
                                           MESSAGE = 'Gate Pass cancelled before it was posted to finance',
                                           UPDATED_AT = LOCALTIMESTAMP WHERE EVENT_TYPE = :1 AND SOURCE_ID = :2""",
                                        [L.EVENT_GP_POSTED, gp_id])
                    P.write_event(cur, L.EVENT_GP_CANCELLED, gp_id, division, gp_date, status, message, vids, actor)
                    conn.commit()
                    return status, message
                except Exception:
                    conn.rollback()
                    raise
    except Exception as exc:
        logger.exception('Finance reversal failed for Gate Pass %s', gp_id)
        message = str(exc)[:400] or exc.__class__.__name__
    _record_failure(L.EVENT_GP_CANCELLED, gp_id, division, gp_date, message, actor)
    return L.ST_FAILED, message


def _record_failure(event_type, gp_id, division, gp_date, message, actor):
    """FAILED row on its own connection (the posting transaction is already
    rolled back). If even this fails, only the Python log has it."""
    try:
        with P.system_context(), P._connect(actor) as conn:
            with conn.cursor() as cur:
                P.write_event(cur, event_type, gp_id, division, gp_date, L.ST_FAILED, message, [], actor)
            conn.commit()
    except Exception:
        logger.exception('Could not even record the FAILED finance event for %s %s', event_type, gp_id)


# ------------------------------------------------------------ the hooks
def on_gatepass_posted(gp_id, user=None):
    """Hook 2. Call AFTER the Gate Pass has been committed. Returns a status
    word only; never raises."""
    if not hooks_enabled():
        return 'OFF'
    try:
        return _process_posted(gp_id, _actor(user))[0]
    except Exception:
        logger.exception('on_gatepass_posted crashed for %s', gp_id)
        return L.ST_FAILED


def on_gatepass_cancelled(gp_id, user=None):
    """Call AFTER cancel_gate_pass() has committed. Never raises."""
    if not hooks_enabled():
        return 'OFF'
    try:
        return _process_cancelled(gp_id, _actor(user))[0]
    except Exception:
        logger.exception('on_gatepass_cancelled crashed for %s', gp_id)
        return L.ST_FAILED


# ------------------------------------------- Super Admin retry / catch-up
def retry_event(user, event_type, source_id):
    """Super Admin only. Returns (status, message)."""
    if not is_finance_admin(user):
        raise PermissionDenied('Finance data is restricted to the Super Admin.')
    if event_type == L.EVENT_GP_POSTED:
        return _process_posted(source_id, user.username)
    if event_type == L.EVENT_GP_CANCELLED:
        return _process_cancelled(source_id, user.username)
    return L.ST_FAILED, 'Unknown event type.'
