"""
Finance audit framework.

All finance audit rows go to wst_djn_fin_audit_log (append-only, Super Admin
screens only) - NOT wst_djn_audit_log, because the Wastage Audit Log
screen lists every table in that log and would leak finance entries to
anyone holding the audit_log permission.

Two entry points:
  record_changes(cur, ...)  - used by the data layer INSIDE the same
                              transaction as the change, so the change and
                              its audit rows commit or roll back together.
  log_denied(request, why)  - records a blocked attempt. It must never
                              break the request, so any failure is only
                              written to the Python log.
"""
import logging

logger = logging.getLogger('apps.finance.audit')

_MAX = 1900


def _clip(value):
    text = '' if value is None else str(value)
    return text[:_MAX]


def record_changes(cur, actor, table_name, record_id, action, old=None, new=None, path=None, ip=None):
    """Insert audit rows through an open cursor (caller commits).

    CREATE / DELETE -> one row (field ALL).
    UPDATE          -> one row per field whose value actually changed."""
    base = [actor, 'CHANGE', table_name, str(record_id), action]
    tail = [_clip(path)[:300] or None, _clip(ip)[:120] or None]
    sql = """INSERT INTO wst_djn_fin_audit_log
             (actor, event_type, table_name, record_id, action, field_name,
              old_value, new_value, request_path, ip_address)
             VALUES (:1,:2,:3,:4,:5,:6,:7,:8,:9,:10)"""
    if action == 'UPDATE':
        old = old or {}
        for key, new_val in (new or {}).items():
            old_val = old.get(key)
            if str(old_val) != str(new_val):
                cur.execute(sql, base + [key, _clip(old_val), _clip(new_val)] + tail)
    elif action == 'DELETE':
        cur.execute(sql, base + ['ALL', _clip(old), 'DELETED'] + tail)
    else:
        cur.execute(sql, base + ['ALL', '', _clip(new) or 'CREATED'] + tail)


def request_context(request):
    """(path, ip) for audit rows. The forwarded header is recorded as
    information only; nothing authorises on it."""
    path = getattr(request, 'path', '') or ''
    meta = getattr(request, 'META', {}) or {}
    ip = meta.get('REMOTE_ADDR', '')
    fwd = meta.get('HTTP_X_FORWARDED_FOR')
    if fwd:
        ip = f'{ip} (fwd {fwd})'
    return path, ip


def log_denied(request, layer):
    """Record a blocked attempt on /finance. Logged-in users go to
    wst_djn_fin_audit_log; anonymous visitors only to the Python log, so an
    unauthenticated scanner cannot fill the table."""
    user = getattr(request, 'user', None)
    username = getattr(user, 'username', '') if getattr(user, 'is_authenticated', False) else ''
    path, ip = request_context(request)
    logger.warning('Finance access denied (%s): user=%r path=%r ip=%r', layer, username or 'anonymous', path, ip)
    if not username:
        return
    try:
        from .data import write_denial
        write_denial(username, path, ip, layer)
    except Exception:  # never let auditing break the response
        logger.exception('Could not write finance denial to wst_djn_fin_audit_log')
