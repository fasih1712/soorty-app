"""
Pure validation and rule functions (no database, no Django), so every rule
can be unit-tested without Oracle. The data layer calls these before it
writes.
"""
import re
from datetime import date
from decimal import Decimal, InvalidOperation

ACCOUNT_TYPES = ('ASSET', 'LIABILITY', 'INCOME', 'EXPENSE', 'EQUITY')
_CODE_RE = re.compile(r'^[0-9]{4,10}$')


def proper_case(text):
    """Project standard: names stored in Proper Case. Words are capitalised
    without lower-casing the rest, so acronyms such as WHT survive."""
    return ' '.join(w[:1].upper() + w[1:] for w in (text or '').strip().split())


# ---------------------------------------------------------------- accounts
def validate_account(form, existing=None, parent=None, other_codes=()):
    """Return (clean, errors).

    form      dict: code, name, type, parent_id, is_posting
    existing  current row (dict) when editing, else None
    parent    parent row (dict) or None
    other_codes  codes already used by OTHER accounts"""
    errors = []
    locked = bool(existing and existing.get('IS_LOCKED'))

    code = (form.get('code') or '').strip()
    name = proper_case(form.get('name'))
    acc_type = (form.get('type') or '').strip().upper()
    is_posting = 1 if str(form.get('is_posting', '1')) in ('1', 'on', 'true', 'True') else 0

    if locked:
        # System heads keep code, type, kind. Only the name may change.
        code = existing['ACCOUNT_CODE']
        acc_type = existing['ACCOUNT_TYPE']
        is_posting = existing['IS_POSTING']
        parent_id = existing.get('PARENT_ID')
    else:
        if not _CODE_RE.match(code):
            errors.append('Account code must be 4 to 10 digits.')
        if acc_type not in ACCOUNT_TYPES:
            errors.append('Choose a valid account type.')
        if code in set(other_codes):
            errors.append(f'Account code {code} is already in use.')
        parent_id = None
        if parent is not None:
            parent_id = parent['ACCOUNT_ID']
            if parent['IS_POSTING']:
                errors.append('The parent must be a group head, not a posting head.')
            if parent['ACCOUNT_TYPE'] != acc_type:
                errors.append('The parent must have the same account type.')
            if existing and parent['ACCOUNT_ID'] == existing['ACCOUNT_ID']:
                errors.append('An account cannot be its own parent.')
        elif (form.get('parent_id') or '').strip():
            errors.append('The chosen parent does not exist.')

    if not (2 <= len(name) <= 150):
        errors.append('Account name must be 2 to 150 characters.')

    clean = {'code': code, 'name': name, 'type': acc_type,
             'parent_id': parent_id, 'is_posting': is_posting}
    return clean, errors


def can_deactivate_account(row):
    if row.get('IS_LOCKED'):
        return False, 'System heads cannot be deactivated.'
    return True, ''


# ---------------------------------------------------------------- settings
def validate_setting(row, raw_value):
    """Return (clean_value, error). row = the wst_djn_fin_setting row (dict)."""
    if not row.get('IS_EDITABLE'):
        return None, 'This setting is fixed and cannot be changed.'
    value = (raw_value if raw_value is not None else '').strip()
    vtype = row['VALUE_TYPE']

    if row.get('SETTING_KEY') == 'FINANCE_GO_LIVE_DATE':
        from . import ledger
        return ledger.validate_go_live(value)

    if vtype == 'YN':
        value = value.upper()
        if value not in ('Y', 'N'):
            return None, 'Choose Y or N.'
        return value, None

    if vtype == 'CHOICE':
        options = [o.strip() for o in (row.get('OPTIONS') or '').split(',') if o.strip()]
        if value not in options:
            return None, 'Choose one of: ' + ', '.join(options) + '.'
        return value, None

    if vtype == 'INT':
        if not re.fullmatch(r'\d{1,6}', value):
            return None, 'Enter a whole number, zero or more.'
        number = int(value)
        if row['SETTING_KEY'] == 'FISCAL_YEAR_START_MONTH' and not (1 <= number <= 12):
            return None, 'Month must be between 1 and 12.'
        return str(number), None

    if vtype == 'DECIMAL':
        try:
            number = Decimal(value)
        except InvalidOperation:
            return None, 'Enter a number.'
        if number < 0:
            return None, 'The value cannot be negative.'
        return f'{number.quantize(Decimal("0.01"))}', None

    if vtype == 'INTLIST':
        parts = [p.strip() for p in value.split(',') if p.strip()]
        if not parts or not all(re.fullmatch(r'\d{1,4}', p) for p in parts):
            return None, 'Enter whole numbers separated by commas, e.g. 30,60,90.'
        numbers = [int(p) for p in parts]
        if numbers != sorted(set(numbers)) or numbers[0] <= 0:
            return None, 'Numbers must be above zero and in ascending order, with no repeats.'
        return ','.join(str(n) for n in numbers), None

    if not value or len(value) > 500:
        return None, 'Enter a value of up to 500 characters.'
    return value, None


# ----------------------------------------------------------- posting rules
def validate_posting_rule(debit_key, credit_key, accounts_by_key):
    """accounts_by_key: {SYSTEM_KEY: account row}. Both sides must be
    active posting heads and must differ."""
    errors = []
    if debit_key == credit_key:
        errors.append('Debit and credit accounts must be different.')
    for label, key in (('Debit', debit_key), ('Credit', credit_key)):
        acc = accounts_by_key.get(key)
        if acc is None:
            errors.append(f'{label} account "{key}" does not exist.')
        elif not acc['IS_ACTIVE']:
            errors.append(f'{label} account {acc["ACCOUNT_CODE"]} is inactive.')
        elif not acc['IS_POSTING']:
            errors.append(f'{label} account {acc["ACCOUNT_CODE"]} is a group head and cannot receive postings.')
    return errors


# ---------------------------------------------------------------- periods
def month_index(year, month):
    return year * 12 + (month - 1)


def can_lock_period(year, month, locked, today=None):
    """Rules (decision D9, standard practice):
       - a future month cannot be locked;
       - months lock in order: the month right after the latest locked one
         (the very first lock may be any past or current month).
    locked = list of (year, month) currently LOCKED for the division."""
    today = today or date.today()
    if (year, month) in set(locked):
        return False, 'That month is already locked.'
    if month_index(year, month) > month_index(today.year, today.month):
        return False, 'A future month cannot be locked.'
    if locked:
        latest = max(month_index(y, m) for y, m in locked)
        if month_index(year, month) != latest + 1:
            return False, 'Months must be locked in order. Lock the month after the latest locked one.'
    return True, ''


def can_reopen_period(year, month, locked, reason):
    """Only the latest locked month can be reopened (reverse order), and a
    reason is mandatory."""
    if (year, month) not in set(locked):
        return False, 'That month is not locked.'
    if month_index(year, month) != max(month_index(y, m) for y, m in locked):
        return False, 'Only the latest locked month can be reopened. Reopen later months first.'
    if len((reason or '').strip()) < 5:
        return False, 'Give a reason of at least 5 characters.'
    return True, ''
