r"""
Connects Gate Pass to Finance (Phase 2). Safe to run twice.

Run from the project folder (where manage.py is), venv active:
    python patch_wastage_views.py

It edits apps\wastage\views.py in 4 places and first saves a backup:
    apps\wastage\views.py.bak_finance
Nothing changes in how Gate Pass behaves until FINANCE_HOOKS_ENABLED=Y is set
in .env, and not for dispatches dated before the finance cut-over date.
"""
import shutil
import sys
from pathlib import Path

target = Path('apps') / 'wastage' / 'views.py'
if len(sys.argv) > 1:
    target = Path(sys.argv[1])
if not target.exists():
    sys.exit('views.py not found. Run this from the project folder (where manage.py is).')

text = target.read_text(encoding='utf-8')
nl = '\r\n' if '\r\n' in text else '\n'
text = text.replace('\r\n', '\n')

if 'finance_gateway' in text:
    sys.exit('Already done: views.py already contains the finance link. Nothing changed.')


def replace_once(src, old, new, label):
    if src.count(old) != 1:
        sys.exit(f'Could not find the expected code for step "{label}" (found {src.count(old)} times). '
                 f'Nothing was changed. Send me your current views.py.')
    return src.replace(old, new, 1)


# 1. import + three safe helpers (right after the oracle_data import)
IMPORT = "from .oracle_data import *\n"
HELPERS = '''from .oracle_data import *

# --- Finance link (Phase 2). Everything here is fail-safe: finance can never crash a Gate Pass. ---
try:
    from apps.finance import gateway as finance_gateway
except Exception:  # finance app not installed: Gate Pass works exactly as before
    finance_gateway = None


def _finance_dispatch_check(header, lines, user):
    """Prepaid rule: (True, '') or (False, message with NO amounts)."""
    if finance_gateway is None:
        return True, ''
    try:
        return finance_gateway.check_dispatch_allowed(header, lines, user)
    except Exception:
        return False, ('The prepaid-advance check could not be completed, so this dispatch was not released. '
                       'Please contact Finance.')


def _finance_gatepass_posted(gate_pass_id, user):
    try:
        if finance_gateway is not None:
            finance_gateway.on_gatepass_posted(gate_pass_id, user)
    except Exception:
        pass  # logged inside the gateway; the Gate Pass is already saved


def _finance_gatepass_cancelled(gate_pass_id, user):
    try:
        if finance_gateway is not None:
            finance_gateway.on_gatepass_cancelled(gate_pass_id, user)
    except Exception:
        pass
'''
text = replace_once(text, IMPORT, HELPERS, 'import')

# 2. block the dispatch if the customer's advance cannot cover it
OLD_POST = "            ok, result = post_gate_pass(header, lines, gate_pass_id=gate_pass_id, username=request.user.username)\n"
NEW_POST = '''            _fin_ok, _fin_msg = _finance_dispatch_check(header, lines, request.user)
            if not _fin_ok:
                ok, result = False, _fin_msg
            else:
                ok, result = post_gate_pass(header, lines, gate_pass_id=gate_pass_id, username=request.user.username)
'''
text = replace_once(text, OLD_POST, NEW_POST, 'dispatch check')

# 3. after a successful post: hand the Gate Pass to finance (before the audit line, which can raise)
OLD_LOG = "                log_audit('GATEPASS', result, 'POST', request.user.username)\n"
NEW_LOG = "                _finance_gatepass_posted(result, request.user)\n" + OLD_LOG
text = replace_once(text, OLD_LOG, NEW_LOG, 'post hook')

# 4. after a successful cancel: reverse in finance
OLD_CANCEL = "            log_audit('GATEPASS', gate_pass_id, 'CANCEL', request.user.username)\n"
NEW_CANCEL = "            _finance_gatepass_cancelled(gate_pass_id, request.user)\n" + OLD_CANCEL
text = replace_once(text, OLD_CANCEL, NEW_CANCEL, 'cancel hook')

shutil.copy2(target, target.with_name(target.name + '.bak_finance'))
target.write_text(text.replace('\n', nl), encoding='utf-8', newline='')
print('Done. 4 changes made. Backup saved as ' + target.name + '.bak_finance')
print('Restart the service. The link stays OFF until FINANCE_HOOKS_ENABLED=Y is added to .env.')
