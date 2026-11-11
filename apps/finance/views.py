from datetime import date

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.http import Http404
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from . import data
from . import validators as v
from .decorators import super_admin_required


def _divisions():
    return list(getattr(get_user_model(), 'DIVISION_CHOICES', ()))


def _valid_division(raw):
    codes = [code for code, _label in _divisions()]
    return raw if raw in codes else (codes[0] if codes else '')


# ---------------------------------------------------------------- dashboard
@super_admin_required
def finance_home(request):
    return render(request, 'finance/home.html', {'counts': data.dashboard_counts(request.user)})


# ------------------------------------------------------- chart of accounts
@super_admin_required
def coa_list(request):
    search = (request.GET.get('q') or '').strip()
    acc_type = (request.GET.get('type') or '').strip().upper()
    return render(request, 'finance/coa_list.html', {
        'accounts': data.fetch_accounts(request.user, search or None, acc_type or None),
        'search': search, 'selected_type': acc_type, 'account_types': v.ACCOUNT_TYPES,
    })


def _account_form_context(request, form, existing=None, errors=None):
    return {'form': form, 'existing': existing, 'errors': errors or [],
            'parents': data.fetch_group_accounts(request.user), 'account_types': v.ACCOUNT_TYPES}


@super_admin_required
def coa_add(request):
    if request.method == 'POST':
        account_id, errors = data.create_account(request.user, request.POST, request)
        if not errors:
            messages.success(request, 'Account added.')
            return redirect('finance:coa_list')
        return render(request, 'finance/coa_form.html', _account_form_context(request, request.POST, None, errors))
    return render(request, 'finance/coa_form.html', _account_form_context(request, {'is_posting': '1'}))


@super_admin_required
def coa_edit(request, account_id):
    existing = data.fetch_account(request.user, account_id)
    if existing is None:
        raise Http404()
    if request.method == 'POST':
        errors = data.update_account(request.user, account_id, request.POST, request)
        if not errors:
            messages.success(request, 'Account updated.')
            return redirect('finance:coa_list')
        return render(request, 'finance/coa_form.html', _account_form_context(request, request.POST, existing, errors))
    form = {'code': existing['ACCOUNT_CODE'], 'name': existing['ACCOUNT_NAME'], 'type': existing['ACCOUNT_TYPE'],
            'parent_id': existing['PARENT_ID'] or '', 'is_posting': str(existing['IS_POSTING'])}
    return render(request, 'finance/coa_form.html', _account_form_context(request, form, existing))


@super_admin_required
@require_POST
def coa_toggle(request, account_id):
    active = request.POST.get('active') == '1'
    error = data.set_account_active(request.user, account_id, active, request)
    if error:
        messages.error(request, error)
    else:
        messages.success(request, 'Account activated.' if active else 'Account deactivated.')
    return redirect('finance:coa_list')


# ----------------------------------------------------------------- settings
@super_admin_required
def settings_list(request):
    rows = data.fetch_settings(request.user)
    for row in rows:
        row['OPTION_LIST'] = [o.strip() for o in (row.get('OPTIONS') or '').split(',') if o.strip()]
    return render(request, 'finance/settings.html', {'settings': rows})


@super_admin_required
@require_POST
def setting_update(request, key):
    error = data.update_setting(request.user, key, request.POST.get('value'), request)
    if error:
        messages.error(request, f'{key}: {error}')
    else:
        messages.success(request, f'{key} saved.')
    return redirect('finance:settings')


@super_admin_required
def posting_rules(request):
    return render(request, 'finance/posting_rules.html', {
        'rules': data.fetch_posting_rules(request.user),
        'keyed_accounts': data.fetch_keyed_accounts(request.user),
    })


@super_admin_required
@require_POST
def posting_rule_update(request, rule_id):
    errors = data.update_posting_rule(request.user, rule_id,
                                      (request.POST.get('debit') or '').strip(),
                                      (request.POST.get('credit') or '').strip(), request)
    if errors:
        for message in errors:
            messages.error(request, message)
    else:
        messages.success(request, 'Posting rule saved.')
    return redirect('finance:posting_rules')


# ------------------------------------------------------------------ periods
def _last_months(count=12, today=None):
    today = today or date.today()
    year, month = today.year, today.month
    months = []
    for _ in range(count):
        months.append((year, month))
        month -= 1
        if month == 0:
            year, month = year - 1, 12
    return months


@super_admin_required
def periods(request):
    division = _valid_division(request.GET.get('division', ''))
    stored = data.fetch_period_rows(request.user, division)
    locked = [(int(r['PERIOD_YEAR']), int(r['PERIOD_MONTH'])) for r in stored if r['STATUS'] == 'LOCKED']
    by_key = {(int(r['PERIOD_YEAR']), int(r['PERIOD_MONTH'])): r for r in stored}
    rows = []
    for year, month in _last_months():
        record = by_key.get((year, month), {})
        can_lock, _ = v.can_lock_period(year, month, locked)
        can_reopen, _ = v.can_reopen_period(year, month, locked, 'long enough reason')
        rows.append({'year': year, 'month': month, 'label': date(year, month, 1).strftime('%B %Y'),
                     'status': 'LOCKED' if (year, month) in locked else 'OPEN',
                     'locked_by': record.get('LOCKED_BY'), 'locked_at': record.get('LOCKED_AT'),
                     'reopen_reason': record.get('REOPEN_REASON'),
                     'can_lock': can_lock, 'can_reopen': can_reopen})
    return render(request, 'finance/periods.html', {
        'rows': rows, 'division': division, 'divisions': _divisions()})


def _period_args(request):
    try:
        year, month = int(request.POST.get('year')), int(request.POST.get('month'))
        if not (1 <= month <= 12 and 2000 <= year <= 2100):
            raise ValueError
    except (TypeError, ValueError):
        raise Http404()
    return _valid_division(request.POST.get('division', '')), year, month


@super_admin_required
@require_POST
def period_lock(request):
    division, year, month = _period_args(request)
    error = data.lock_period(request.user, division, year, month, request)
    if error:
        messages.error(request, error)
    else:
        messages.success(request, f'{date(year, month, 1).strftime("%B %Y")} locked for {division}.')
    return redirect(f"{reverse('finance:periods')}?division={division}")


@super_admin_required
@require_POST
def period_reopen(request):
    division, year, month = _period_args(request)
    error = data.reopen_period(request.user, division, year, month, request.POST.get('reason', ''), request)
    if error:
        messages.error(request, error)
    else:
        messages.success(request, f'{date(year, month, 1).strftime("%B %Y")} reopened for {division}.')
    return redirect(f"{reverse('finance:periods')}?division={division}")


# -------------------------------------------------------------------- audit
@super_admin_required
def finance_audit(request):
    event_type = (request.GET.get('type') or '').strip().upper()
    data.record_access(request.user, request, 'Opened finance audit log')
    return render(request, 'finance/audit.html', {
        'logs': data.fetch_audit(request.user, event_type or None),
        'selected_type': event_type, 'event_types': ('CHANGE', 'DENIED', 'ACCESS'),
    })


# =================================================================== PHASE 2
from . import gateway  # noqa: E402  (Super Admin retry uses the same worker as the live hook)


@super_admin_required
def customers(request):
    search = (request.GET.get('q') or '').strip()
    return render(request, 'finance/customers.html', {
        'rows': data.fetch_customers(request.user, search or None), 'search': search})


@super_admin_required
def customer_ledger(request, party_id):
    name = data.fetch_customer_name(request.user, party_id)
    if name is None:
        raise Http404()
    return render(request, 'finance/customer_ledger.html', {
        'party_id': party_id, 'name': name,
        'rows': data.fetch_customer_ledger(request.user, party_id),
        'advances': data.fetch_advances(request.user, party_id)})


def _entry_context(request, form, errors, title, action):
    return {'form': form, 'errors': errors, 'title': title, 'action': action,
            'customers': data.fetch_customer_options(request.user), 'divisions': _divisions(),
            'today': date.today().isoformat()}


@super_admin_required
def advance_add(request):
    if request.method == 'POST':
        message, errors = data.receive_advance_entry(request.user, request.POST, request)
        if not errors:
            messages.success(request, message)
            return redirect('finance:customers')
        return render(request, 'finance/advance_form.html',
                      _entry_context(request, request.POST, errors, 'Receive Customer Advance', 'advance'))
    return render(request, 'finance/advance_form.html',
                  _entry_context(request, {'advance_date': date.today().isoformat(), 'mode': 'BANK'}, [],
                                 'Receive Customer Advance', 'advance'))


@super_admin_required
def opening_add(request):
    if request.method == 'POST':
        message, errors = data.load_opening_entry(request.user, request.POST, request)
        if not errors:
            messages.success(request, message)
            return redirect('finance:customers')
        return render(request, 'finance/advance_form.html',
                      _entry_context(request, request.POST, errors, 'Load Opening Balance', 'opening'))
    return render(request, 'finance/advance_form.html',
                  _entry_context(request, {}, [], 'Load Opening Balance', 'opening'))


@super_admin_required
@require_POST
def advance_reverse(request, advance_id):
    error = data.reverse_advance_entry(request.user, advance_id, request.POST.get('reason', ''), request)
    if error:
        messages.error(request, error)
    else:
        messages.success(request, 'Advance reversed.')
    return redirect(request.POST.get('next') if (request.POST.get('next') or '').startswith('/finance/')
                    else reverse('finance:customers'))


@super_admin_required
def vouchers(request):
    search = (request.GET.get('q') or '').strip()
    return render(request, 'finance/vouchers.html', {
        'rows': data.fetch_vouchers(request.user, search or None), 'search': search})


@super_admin_required
def voucher_view(request, voucher_id):
    header, lines = data.fetch_voucher(request.user, voucher_id)
    if header is None:
        raise Http404()
    return render(request, 'finance/voucher_view.html', {'v': header, 'lines': lines})


@super_admin_required
def events(request):
    status = (request.GET.get('status') or '').strip().upper()
    return render(request, 'finance/events.html', {
        'rows': data.fetch_events(request.user, status or None), 'selected': status,
        'missed': data.fetch_missed_events(request.user),
        'hooks_enabled': gateway.hooks_enabled()})


@super_admin_required
@require_POST
def event_retry(request):
    event_type = (request.POST.get('event_type') or '').strip()
    source_id = (request.POST.get('source_id') or '').strip()
    if event_type not in ('GP_POSTED', 'GP_CANCELLED') or not source_id or len(source_id) > 40:
        raise Http404()
    status, message = gateway.retry_event(request.user, event_type, source_id)
    if status == 'FAILED':
        messages.error(request, f'{source_id}: still failing - {message}')
    else:
        messages.success(request, f'{source_id}: {status.title()} - {message}')
    return redirect('finance:events')


# =================================================================== PHASE 3
def _adj_context(request, form, errors, title, kind, **extra):
    ctx = {'form': form, 'errors': errors, 'title': title, 'kind': kind,
           'customers': data.fetch_customer_options(request.user), 'divisions': _divisions(),
           'today': date.today().isoformat()}
    ctx.update(extra)
    return ctx


@super_admin_required
def adjustments(request):
    return render(request, 'finance/adjustments.html', {'rows': data.fetch_adjustments(request.user)})


def _adjustment_view(request, template, title, kind, handler, initial, extra=None):
    if request.method == 'POST':
        message, errors = handler(request.user, request.POST, request)
        if not errors:
            messages.success(request, f'{title} saved.')
            return redirect('finance:adjustments')
        return render(request, template, _adj_context(request, request.POST, errors, title, kind, **(extra or {})))
    return render(request, template, _adj_context(request, initial, [], title, kind, **(extra or {})))


@super_admin_required
def adjustment_refund(request):
    return _adjustment_view(request, 'finance/adjustment_form.html', 'Refund Unused Advance', 'refund',
                            data.refund_entry, {'adj_date': date.today().isoformat(), 'mode': 'BANK'})


@super_admin_required
def adjustment_transfer(request):
    return _adjustment_view(request, 'finance/adjustment_form.html', 'Transfer Advance Between Customers', 'transfer',
                            data.transfer_entry, {'adj_date': date.today().isoformat()})


@super_admin_required
def adjustment_note(request):
    gp = (request.POST.get('gate_pass_id') or request.GET.get('gp') or '').strip()
    receivables = data.fetch_gatepass_receivables(request.user, gp) if gp else []
    return _adjustment_view(request, 'finance/adjustment_form.html', 'Credit / Debit Note', 'note',
                            data.note_entry, {'adj_date': date.today().isoformat(), 'gate_pass_id': gp},
                            extra={'gp': gp, 'receivables': receivables})


@super_admin_required
def adjustment_journal(request):
    return _adjustment_view(request, 'finance/journal_form.html', 'Manual Journal Voucher', 'journal',
                            data.journal_entry_post, {'adj_date': date.today().isoformat()},
                            extra={'accounts': data.fetch_posting_accounts(request.user)})


@super_admin_required
@require_POST
def adjustment_reverse(request, adjustment_id):
    error = data.reverse_adjustment_entry(request.user, adjustment_id, request.POST.get('reason', ''), request)
    if error:
        messages.error(request, error)
    else:
        messages.success(request, 'Adjustment reversed.')
    return redirect('finance:adjustments')


# =================================================================== PHASE 4
# Reports. Every view is Super Admin only (decorator + middleware + data layer),
# read-only, and every PDF / Excel download is written to the Finance Audit log.
from django.http import HttpResponse  # noqa: E402
from django.utils import timezone  # noqa: E402

from . import exporters, report_builders, reports  # noqa: E402
from .ledger import FinanceRuleError  # noqa: E402

REPORT_LIST = (
    ('finance:report_statement', 'Customer Advance Statement', 'ti-file-invoice',
     'Opening balance, receipts, Gate Pass knock-offs and the advance remaining. Printable for the customer.'),
    ('finance:report_trial_balance', 'Trial Balance', 'ti-scale',
     'Every account head with debits, credits and balances. Click a code to see its ledger.'),
    ('finance:report_ledger', 'General Ledger', 'ti-book',
     'All entries on one account with running balance. Click a voucher to see its lines.'),
    ('finance:report_sales', 'Sales and Collections', 'ti-chart-bar',
     'Dispatches against advances collected, per day or month, per division.'),
    ('finance:report_reconciliation', 'Reconciliation Check', 'ti-shield-check',
     'Proves customer balances equal the control account and flags Gate Passes finance missed.'),
    ('finance:report_ageing', 'Advance Ageing', 'ti-hourglass',
     'How long each customer\'s unused advance has been sitting (0-30, 31-60, 61-90, over 90 days).'),
)


def _division_filter(raw):
    raw = (raw or '').strip()
    if not raw:
        return ''
    if raw not in [code for code, _label in _divisions()]:
        raise FinanceRuleError('Choose a valid division.')
    return raw


def _report_ctx(request):
    return {'generated_by': request.user.username, 'generated_at': timezone.localtime().strftime('%d-%b-%Y %H:%M'),
            'voucher_url': lambda vid: reverse('finance:voucher_view', args=[vid]),
            'ledger_url': lambda acc: reverse('finance:report_ledger') + f'?account={acc}'}


def _field(name, label, kind, value, options=None):
    return {'name': name, 'label': label, 'kind': kind, 'value': value, 'options': options or []}


def _division_field(value):
    return _field('division', 'Division', 'select', value, [('', 'All divisions')] + list(_divisions()))


def _qs_without_fmt(request):
    params = request.GET.copy()
    params.pop('fmt', None)
    return params.urlencode()


def _deliver(request, title, fields, spec=None, errors=None, extra=None):
    """HTML page, or a PDF / Excel download when ?fmt= asks for one."""
    fmt = (request.GET.get('fmt') or '').lower()
    if spec is not None and fmt in ('pdf', 'xlsx'):
        try:
            blob = exporters.to_pdf(spec) if fmt == 'pdf' else exporters.to_xlsx(spec)
        except exporters.ExportUnavailable as exc:
            errors = (errors or []) + [str(exc)]
        else:
            data.record_export(request.user, request, f"Downloaded {fmt.upper()} report: {spec['title']}")
            ctype = 'application/pdf' if fmt == 'pdf' else \
                'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
            response = HttpResponse(blob, content_type=ctype)
            response['Content-Disposition'] = f'attachment; filename="{exporters.safe_filename(spec["title"], fmt)}"'
            response['Cache-Control'] = 'no-store'
            return response
    context = {'title': title, 'fields': fields, 'errors': errors or [], 'spec': spec,
               'tables': [report_builders.html_table(s) for s in spec['sections']] if spec else [],
               'query': _qs_without_fmt(request),
               'can_export': spec is not None}
    context.update(extra or {})
    return render(request, 'finance/report.html', context)


@super_admin_required
def report_index(request):
    return render(request, 'finance/report_index.html', {'reports': REPORT_LIST})


@super_admin_required
def report_statement(request):
    customers = data.fetch_customer_options(request.user)
    g = request.GET
    fields = [_field('party', 'Customer', 'select', g.get('party', ''),
                     [('', 'Choose a customer')] + [(str(c['VENDOR_ID']), c['VENDOR_NAME']) for c in customers]),
              _division_field(g.get('division', '')),
              _field('from', 'From', 'date', g.get('from', '')), _field('to', 'To', 'date', g.get('to', ''))]
    if not g.get('party'):
        return _deliver(request, 'Customer Advance Statement', fields)
    try:
        division = _division_filter(g.get('division'))
        d_from, d_to = reports.parse_range(g.get('from'), g.get('to'))
        if not g['party'].isdigit():
            raise FinanceRuleError('Choose a customer.')
        name, opening, lines = data.fetch_statement(request.user, g['party'], division, d_from, d_to)
        if name is None:
            raise FinanceRuleError('Customer not found.')
    except FinanceRuleError as exc:
        return _deliver(request, 'Customer Advance Statement', fields, errors=[str(exc)])
    for f in fields:
        if f['name'] == 'from':
            f['value'] = d_from.isoformat()
        if f['name'] == 'to':
            f['value'] = d_to.isoformat()
    spec, _totals = report_builders.statement_spec(name, division, d_from, d_to, opening, lines, _report_ctx(request))
    return _deliver(request, 'Customer Advance Statement', fields, spec)


@super_admin_required
def report_trial_balance(request):
    g = request.GET
    fields = [_division_field(g.get('division', '')), _field('as_of', 'As at', 'date', g.get('as_of', ''))]
    try:
        division = _division_filter(g.get('division'))
        cutoff = reports.parse_as_of(g.get('as_of'))
        fields[1]['value'] = cutoff.isoformat()
        raw = data.fetch_trial_balance_rows(request.user, division, cutoff)
    except FinanceRuleError as exc:
        return _deliver(request, 'Trial Balance', fields, errors=[str(exc)])
    spec, _totals = report_builders.trial_balance_spec(division, cutoff, raw, _report_ctx(request))
    return _deliver(request, 'Trial Balance', fields, spec)


@super_admin_required
def report_ledger(request):
    g = request.GET
    accounts = data.fetch_ledger_accounts(request.user)
    fields = [_field('account', 'Account', 'select', g.get('account', ''),
                     [('', 'Choose an account')] + [(str(a['ACCOUNT_ID']), f"{a['ACCOUNT_CODE']} - {a['ACCOUNT_NAME']}") for a in accounts]),
              _division_field(g.get('division', '')),
              _field('from', 'From', 'date', g.get('from', '')), _field('to', 'To', 'date', g.get('to', ''))]
    if not g.get('account'):
        return _deliver(request, 'General Ledger', fields)
    try:
        division = _division_filter(g.get('division'))
        d_from, d_to = reports.parse_range(g.get('from'), g.get('to'))
        if not g['account'].isdigit():
            raise FinanceRuleError('Choose an account.')
        account, opening, lines = data.fetch_general_ledger(request.user, g['account'], division, d_from, d_to)
        if account is None:
            raise FinanceRuleError('Account not found.')
    except FinanceRuleError as exc:
        return _deliver(request, 'General Ledger', fields, errors=[str(exc)])
    for f in fields:
        if f['name'] == 'from':
            f['value'] = d_from.isoformat()
        if f['name'] == 'to':
            f['value'] = d_to.isoformat()
    spec, _totals = report_builders.general_ledger_spec(account, division, d_from, d_to, opening, lines, _report_ctx(request))
    return _deliver(request, 'General Ledger', fields, spec)


@super_admin_required
def report_sales(request):
    g = request.GET
    fields = [_division_field(g.get('division', '')), _field('from', 'From', 'date', g.get('from', '')),
              _field('to', 'To', 'date', g.get('to', '')),
              _field('group', 'Group by', 'select', g.get('group', 'month'), [('month', 'Month'), ('day', 'Day')])]
    try:
        division = _division_filter(g.get('division'))
        d_from, d_to = reports.parse_range(g.get('from'), g.get('to'))
        granularity = reports.parse_granularity(g.get('group'))
        fields[1]['value'], fields[2]['value'] = d_from.isoformat(), d_to.isoformat()
        raw = data.fetch_sales_rows(request.user, division, d_from, d_to)
    except FinanceRuleError as exc:
        return _deliver(request, 'Sales and Collections Summary', fields, errors=[str(exc)])
    spec, _totals = report_builders.sales_spec(division, d_from, d_to, granularity, raw, _report_ctx(request))
    return _deliver(request, 'Sales and Collections Summary', fields, spec)


@super_admin_required
def report_reconciliation(request):
    checks = reports.reconcile(data.fetch_reconciliation_data(request.user))
    spec, ok = report_builders.reconciliation_spec(checks, _report_ctx(request))
    return _deliver(request, 'Reconciliation Check', [], spec, extra={'verdict_ok': ok, 'show_verdict': True})


@super_admin_required
def report_ageing(request):
    g = request.GET
    fields = [_division_field(g.get('division', '')), _field('as_of', 'As at', 'date', g.get('as_of', ''))]
    try:
        division = _division_filter(g.get('division'))
        as_of = reports.parse_as_of(g.get('as_of'))
        fields[1]['value'] = as_of.isoformat()
        raw = data.fetch_ageing_rows(request.user, division)
    except FinanceRuleError as exc:
        return _deliver(request, 'Advance Ageing', fields, errors=[str(exc)])
    spec, _totals = report_builders.ageing_spec(division, as_of, raw, _report_ctx(request))
    return _deliver(request, 'Advance Ageing', fields, spec)
