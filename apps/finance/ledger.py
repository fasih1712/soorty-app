"""
Pure posting rules for Phase 2 (no database, no Django), so every money
rule can be unit-tested without Oracle.

Business model (decided by the Super Admin, Oct 2026): wastage sales are
100% prepaid. A dispatch (Gate Pass) creates a sale for ACTUAL shipped
quantity x price and it is knocked off 100% against the customer's advance
in the same transaction. No dispatch without enough advance.
"""
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation

TWO = Decimal('0.01')
ZERO = Decimal('0.00')

# Event log
EVENT_GP_POSTED = 'GP_POSTED'
EVENT_GP_CANCELLED = 'GP_CANCELLED'
EVENT_TYPES = (EVENT_GP_POSTED, EVENT_GP_CANCELLED)

ST_POSTED = 'POSTED'
ST_FAILED = 'FAILED'
ST_SKIPPED = 'SKIPPED'      # nothing to do (before go-live, transfer, nothing posted to reverse)
EVENT_STATUSES = (ST_POSTED, ST_FAILED, ST_SKIPPED)


class FinanceRuleError(Exception):
    """A business rule stops the posting. Message is safe for the Super Admin
    screens; it never carries amounts into the user-facing gateway."""


class MissingPrice(FinanceRuleError):
    pass


class InsufficientAdvance(FinanceRuleError):
    pass


class Unbalanced(FinanceRuleError):
    pass


# ------------------------------------------------------------------ money
def money(value):
    """Decimal rounded half-up to 2 places. Never goes through float math."""
    if value is None:
        raise FinanceRuleError('Amount is missing.')
    try:
        return Decimal(str(value)).quantize(TWO, rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError):
        raise FinanceRuleError('Amount is not a valid number.')


def positive_money(value, what='Amount'):
    amt = money(value)
    if amt <= ZERO:
        raise FinanceRuleError(f'{what} must be greater than zero.')
    return amt


def line_value(qty, unit_price):
    """Shipped quantity x price, rounded per line (so lines add up exactly)."""
    if unit_price is None:
        raise MissingPrice('A dispatched line has no price on its Sales Order line.')
    q = Decimal(str(qty))
    if q <= 0:
        raise FinanceRuleError('Dispatched quantity must be greater than zero.')
    return money(q * Decimal(str(unit_price)))


def group_dispatch_by_customer(lines):
    """lines: [{customer_id, qty, unit_price, ...}] -> {customer_id: total}.
    Every line must carry a customer and a price; otherwise the whole
    dispatch is refused rather than guessed."""
    totals = {}
    for ln in lines:
        cid = ln.get('customer_id')
        if cid is None:
            raise MissingPrice('A dispatched line is not linked to a Sales Order customer.')
        totals[cid] = totals.get(cid, ZERO) + line_value(ln.get('qty'), ln.get('unit_price'))
    return totals


# ------------------------------------------------------- go-live (cut-over)
def as_date(value):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return datetime.strptime(str(value)[:10], '%Y-%m-%d').date()


def is_live(txn_date, go_live):
    """Finance only tracks dispatches dated on/after the cut-over date.
    No go-live date configured = not live."""
    if not go_live or not txn_date:
        return False
    return as_date(txn_date) >= as_date(go_live)


# ---------------------------------------------------------------- vouchers
def two_line(debit_account_id, credit_account_id, amount, party_id=None):
    amt = positive_money(amount)
    return [
        {'account_id': debit_account_id, 'debit': amt, 'credit': ZERO, 'party_id': party_id},
        {'account_id': credit_account_id, 'debit': ZERO, 'credit': amt, 'party_id': party_id},
    ]


def assert_balanced(lines):
    if not lines:
        raise Unbalanced('A voucher needs at least two lines.')
    d = sum((money(l['debit']) for l in lines), ZERO)
    c = sum((money(l['credit']) for l in lines), ZERO)
    if d != c or d <= ZERO:
        raise Unbalanced('Debits and credits do not match.')
    for l in lines:
        if money(l['debit']) < ZERO or money(l['credit']) < ZERO:
            raise Unbalanced('Negative amounts are not allowed.')
        if money(l['debit']) > ZERO and money(l['credit']) > ZERO:
            raise Unbalanced('A line cannot carry both a debit and a credit.')
    return d


def mirror(lines):
    """Reversal = the same lines with debit and credit swapped (decision D8:
    posted vouchers are never edited, only reversed)."""
    return [{**l, 'debit': money(l['credit']), 'credit': money(l['debit'])} for l in lines]


# ------------------------------------------------------ advance knock-off
def allocate_oldest_first(advances, amount):
    """advances: [{advance_id, remaining, advance_date}] -> [(advance_id, amt)].
    Oldest first (setting ALLOCATION_STRATEGY = OLDEST_FIRST). Raises
    InsufficientAdvance if the pool cannot cover the amount in full; the
    pool is never partially consumed."""
    need = positive_money(amount)
    ordered = sorted(advances, key=lambda a: (as_date(a['advance_date']), a['advance_id']))
    out = []
    for a in ordered:
        if need <= ZERO:
            break
        rem = money(a['remaining'])
        if rem <= ZERO:
            continue
        take = min(rem, need)
        out.append((a['advance_id'], take))
        need -= take
    if need > ZERO:
        raise InsufficientAdvance('Customer advance is not enough to cover this dispatch.')
    return out


def available_advance(advances):
    return sum((max(money(a['remaining']), ZERO) for a in advances), ZERO)


def can_dispatch(available, needed):
    """Prepaid rule. Exact comparison on 2-decimal money, no tolerance."""
    return money(available) >= money(needed)


# ----------------------------------------------------------- event helpers
def event_key(event_type, source_id):
    return f'{event_type}:{source_id}'


def can_retry(status):
    return status == ST_FAILED


def user_message(blocked_customers=0, missing_price=False, error=False):
    """The ONLY text the dispatch screen ever shows about finance. No
    amounts, balances or customer figures - ever."""
    if missing_price:
        return ('This dispatch cannot be priced from its Sales Order line, so it cannot be released. '
                'Please contact Finance.')
    if error:
        return 'The prepaid-advance check could not be completed, so this dispatch was not released. Please contact Finance.'
    if blocked_customers:
        return 'This customer does not have enough advance payment on account for this dispatch. Please contact Finance.'
    return ''


# --------------------------------------------------------- numbering
def fiscal_year(txn_date, start_month):
    """Financial year label = calendar year in which the year STARTS.
    start_month=7: Aug 2026 -> 2026, Mar 2027 -> 2026. start_month=1 -> calendar year."""
    d = as_date(txn_date)
    sm = int(start_month)
    return d.year if d.month >= sm else d.year - 1


def format_voucher_no(prefix, division, fy, number):
    return f'{prefix}-{division}-{fy}-{int(number):05d}'


def validate_go_live(raw):
    """Setting FINANCE_GO_LIVE_DATE: YYYY-MM-DD and the 1st of a month
    (month-start cut-over, decision D4). Returns (clean, error)."""
    text = (raw or '').strip()
    try:
        d = datetime.strptime(text, '%Y-%m-%d').date()
    except ValueError:
        return None, 'Enter the date as YYYY-MM-DD, for example 2026-11-01.'
    if d.day != 1:
        return None, 'The cut-over must be the 1st of a month.'
    return d.isoformat(), None


# ================================================================ PHASE 3
# Adjustments: refund, credit/debit note, advance transfer, manual journal.
ADJ_REFUND, ADJ_CREDIT, ADJ_DEBIT, ADJ_TRANSFER, ADJ_JOURNAL = 'REFUND', 'CREDIT_NOTE', 'DEBIT_NOTE', 'TRANSFER', 'JOURNAL'
ADJ_TYPES = (ADJ_REFUND, ADJ_CREDIT, ADJ_DEBIT, ADJ_TRANSFER, ADJ_JOURNAL)

# Control accounts must stay in step with the customer sub-ledger (advances,
# receivables), so a hand-made journal may never touch them.
JOURNAL_BLOCKED_KEYS = ('CUSTOMER_ADVANCE', 'RECEIVABLE')


def clean_reason(text, minimum=5):
    reason = ' '.join((text or '').split())
    if len(reason) < minimum:
        raise FinanceRuleError(f'A reason of at least {minimum} characters is required.')
    return reason[:300]


def check_credit_note(sale_amount, active_credits, active_debits, new_credit):
    """Net credited (credits - debits) may never exceed the original sale."""
    new_credit = positive_money(new_credit, 'Credit note amount')
    net = money(active_credits) - money(active_debits) + new_credit
    if net > money(sale_amount):
        raise FinanceRuleError('Credit notes cannot exceed the original sale for this Gate Pass.')
    return new_credit


def check_transfer(from_party, to_party):
    if not from_party or not to_party:
        raise FinanceRuleError('Choose both customers.')
    if int(from_party) == int(to_party):
        raise FinanceRuleError('The two customers must be different.')


def clean_journal(lines):
    """lines: [{account_id, system_key, debit, credit, party_id}] typed by the
    Super Admin. Returns posted-ready lines or raises. Blank rows are ignored."""
    out = []
    for ln in lines:
        d = money(ln.get('debit') or 0)
        c = money(ln.get('credit') or 0)
        if d == ZERO and c == ZERO:
            continue
        if ln.get('system_key') in JOURNAL_BLOCKED_KEYS:
            raise FinanceRuleError('Customer Advances and Accounts Receivable cannot be used in a manual journal. '
                                   'Use Refund, Credit/Debit Note or Transfer so the customer ledger stays correct.')
        out.append({'account_id': ln['account_id'], 'party_id': ln.get('party_id'), 'debit': d, 'credit': c})
    if len(out) < 2:
        raise Unbalanced('A journal needs at least two lines with an amount.')
    assert_balanced(out)
    return out
