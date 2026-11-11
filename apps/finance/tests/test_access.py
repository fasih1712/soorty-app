"""
PHASE 1 GATE - access control.

Proves: only an active Django Super Admin can reach anything under
/finance, at every layer, for every URL (including URLs added later).
No database needed (SimpleTestCase, unsaved users, mocked data layer), so
this runs on the test server without touching Oracle:

    python manage.py test apps.finance.tests.test_access
"""
import inspect
import re
from unittest import mock

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied
from django.core.handlers.exception import convert_exception_to_response
from django.http import Http404
from django.test import RequestFactory, SimpleTestCase, override_settings
from django.urls import resolve

from apps.finance import audit, data
from apps.finance import urls as finance_urls
from apps.finance.access import is_finance_admin, is_finance_path
from apps.finance.middleware import FinanceAccessMiddleware

User = get_user_model()


def _user(**flags):
    flags.setdefault('is_active', True)
    return User(username=flags.pop('username', 'tester'), **flags)


def _all_perms_user():
    """A staff user who passes every Django permission check - the closest
    stand-in for a powerful 'Admin' role. Must STILL be denied."""
    user = _user(username='powerful', is_staff=True)
    user.has_perm = lambda perm, obj=None: True
    user.has_module_perms = lambda app_label: True
    return user


NON_ADMINS = {
    'anonymous': lambda: AnonymousUser(),
    'regular user': lambda: _user(),
    'staff user': lambda: _user(is_staff=True),
    'staff with every permission': _all_perms_user,
    'inactive superuser': lambda: _user(is_superuser=True, is_active=False),
}


def _sample_paths():
    """One concrete URL for every route in apps/finance/urls.py, built from
    the route list itself so new routes are covered automatically."""
    paths = []
    for pattern in finance_urls.urlpatterns:
        route = str(pattern.pattern)
        route = re.sub(r'<int:\w+>', '1', route)
        route = re.sub(r'<str:\w+>', 'SAMPLE', route)
        paths.append('/finance/' + route)
    return paths


def _dispatch(user, path, method='GET'):
    """Run the request through the real middleware, the real URL resolver
    and the real view, with Django's normal exception-to-response mapping."""
    request = getattr(RequestFactory(), method.lower())(path)
    request.user = user

    def get_response(req):
        match = resolve(req.path_info)
        return match.func(req, *match.args, **match.kwargs)

    return convert_exception_to_response(FinanceAccessMiddleware(get_response))(request)


@override_settings(DEBUG=False, ALLOWED_HOSTS=['testserver'])
class MiddlewareBlocksEveryUrl(SimpleTestCase):

    def test_there_are_routes_to_test(self):
        self.assertGreaterEqual(len(_sample_paths()), 10)

    def test_every_url_returns_404_for_every_non_super_admin(self):
        with mock.patch.object(audit, 'log_denied'):
            for label, make in NON_ADMINS.items():
                for path in _sample_paths():
                    for method in ('GET', 'POST'):
                        with self.subTest(user=label, path=path, method=method):
                            response = _dispatch(make(), path, method)
                            self.assertEqual(response.status_code, 404)

    def test_path_variants_are_all_caught(self):
        for variant in ('/finance', '/finance/', '/FINANCE/', '/Finance/accounts/', '//finance/', '/finance/../finance/'):
            with self.subTest(variant=variant):
                self.assertTrue(is_finance_path(variant))
        for other in ('/wastage/', '/financeX', '/accounts/finance/', '/'):
            with self.subTest(other=other):
                self.assertFalse(is_finance_path(other))

    def test_only_active_superuser_passes(self):
        self.assertTrue(is_finance_admin(_user(is_superuser=True)))
        for label, make in NON_ADMINS.items():
            with self.subTest(user=label):
                self.assertFalse(is_finance_admin(make()))


@override_settings(DEBUG=False, ALLOWED_HOSTS=['testserver'])
class MiddlewareAloneIsEnough(SimpleTestCase):
    """The middleware must block on its own, even for a brand-new finance
    route whose view forgot the decorator (the downstream handler here is a
    deliberately UNGUARDED stub that would 'leak' if reached)."""

    def test_unguarded_downstream_view_is_never_reached(self):
        from django.http import HttpResponse
        paths = _sample_paths() + ['/finance/some-future-report/', '/finance/x/y/z/']
        with mock.patch.object(audit, 'log_denied'):
            for label, make in NON_ADMINS.items():
                for path in paths:
                    with self.subTest(user=label, path=path):
                        request = RequestFactory().get(path)
                        request.user = make()
                        handler = convert_exception_to_response(
                            FinanceAccessMiddleware(lambda req: HttpResponse('LEAK')))
                        response = handler(request)
                        self.assertEqual(response.status_code, 404)
                        self.assertNotIn(b'LEAK', response.content)

    def test_super_admin_is_passed_through(self):
        from django.http import HttpResponse
        request = RequestFactory().get('/finance/')
        request.user = _user(is_superuser=True)
        response = FinanceAccessMiddleware(lambda req: HttpResponse('ok'))(request)
        self.assertEqual(response.content, b'ok')

    def test_other_areas_are_untouched(self):
        from django.http import HttpResponse
        request = RequestFactory().get('/wastage/')
        request.user = _user()
        response = FinanceAccessMiddleware(lambda req: HttpResponse('ok'))(request)
        self.assertEqual(response.content, b'ok')


@override_settings(DEBUG=False, ALLOWED_HOSTS=['testserver'])
class ViewsAreLockedEvenWithoutMiddleware(SimpleTestCase):
    """Defence in depth: if the middleware were removed from settings, each
    view must still refuse on its own."""

    def test_every_view_carries_the_guard(self):
        for pattern in finance_urls.urlpatterns:
            with self.subTest(view=pattern.callback.__name__):
                self.assertTrue(getattr(pattern.callback, '_finance_guarded', False),
                                'Missing @super_admin_required')

    def test_every_view_refuses_non_super_admins_directly(self):
        with mock.patch.object(audit, 'log_denied'):
            for label, make in NON_ADMINS.items():
                for path in _sample_paths():
                    with self.subTest(user=label, path=path):
                        request = RequestFactory().get(path)
                        request.user = make()
                        match = resolve(path)
                        with self.assertRaises(Http404):
                            match.func(request, *match.args, **match.kwargs)


class DataLayerRefusesNonSuperAdmins(SimpleTestCase):
    """Third lock. Each public data function must refuse BEFORE touching the
    database - _connect is rigged to fail the test if it is reached."""

    EXEMPT = {'write_denial'}  # internal: only reachable after a denial

    def _public_functions(self):
        for name, func in inspect.getmembers(data, inspect.isfunction):
            if name.startswith('_') or name in self.EXEMPT or func.__module__ != data.__name__:
                continue
            yield name, func

    def test_guard_runs_before_any_database_access(self):
        checked = 0
        with mock.patch.object(data, '_connect', side_effect=AssertionError('database reached')):
            for name, func in self._public_functions():
                required = [p for p in inspect.signature(func).parameters.values()
                            if p.default is inspect.Parameter.empty][1:]
                args = ['x'] * len(required)
                for label, make in NON_ADMINS.items():
                    with self.subTest(function=name, user=label):
                        with self.assertRaises(PermissionDenied):
                            func(make(), *args)
                checked += 1
        self.assertGreaterEqual(checked, 15)


class DenialsAreAudited(SimpleTestCase):

    def test_logged_in_denial_is_written_to_the_finance_audit(self):
        request = RequestFactory().get('/finance/accounts/')
        request.user = _user(username='operator')
        with mock.patch.object(data, 'write_denial') as write:
            audit.log_denied(request, 'middleware')
        write.assert_called_once()
        self.assertEqual(write.call_args[0][0], 'operator')

    def test_anonymous_denial_never_writes_to_the_database(self):
        request = RequestFactory().get('/finance/')
        request.user = AnonymousUser()
        with mock.patch.object(data, 'write_denial') as write:
            audit.log_denied(request, 'middleware')
        write.assert_not_called()

    def test_audit_failure_never_breaks_the_response(self):
        request = RequestFactory().get('/finance/')
        request.user = _user(username='operator')
        with mock.patch.object(data, 'write_denial', side_effect=RuntimeError('db down')):
            audit.log_denied(request, 'middleware')  # must not raise


class NotInTheRoleMatrix(SimpleTestCase):
    """Finance must never be assignable through Role Management."""

    def test_finance_is_not_registered_in_rbac(self):
        try:
            from apps.accounts.rbac import PAGE_REGISTRY_SEED
        except ImportError:
            self.skipTest('apps.accounts not available in this environment')
        for key, label, group, url_name, _order in PAGE_REGISTRY_SEED:
            with self.subTest(key=key):
                self.assertNotIn('finance', (key + label + group + url_name).lower().replace('payment_status', ''))


class SidebarLink(SimpleTestCase):

    def test_finance_menu_only_inside_a_superuser_block(self):
        from django.template import TemplateDoesNotExist
        from django.template.loader import get_template
        try:
            source = get_template('base.html').template.source
        except TemplateDoesNotExist:
            self.skipTest('base.html not available in this environment')
        self.assertIn('finance:home', source, 'Finance menu entry is missing from base.html')
        for match in re.finditer(r"finance:", source):
            before = source[:match.start()]
            last_if = before.rfind('{% if user.is_superuser %}')
            self.assertNotEqual(last_if, -1)
            self.assertNotIn('{% endif %}', before[last_if:],
                             'Finance link sits outside the superuser-only block')


# Rendering checks for the Super Admin (data layer mocked, no Oracle). The
# sidebar context processor queries Oracle, so it is removed for these tests.
def _templates_without_oracle():
    from django.conf import settings
    templates = []
    for engine in settings.TEMPLATES:
        engine = dict(engine)
        options = dict(engine.get('OPTIONS', {}))
        options['context_processors'] = [
            cp for cp in options.get('context_processors', []) if 'sidebar_summary' not in cp]
        engine['OPTIONS'] = options
        templates.append(engine)
    return templates


@override_settings(DEBUG=False, ALLOWED_HOSTS=['testserver'])
class SuperAdminCanUseFinance(SimpleTestCase):

    def setUp(self):
        self.admin = _user(is_superuser=True, username='root', is_staff=True)
        override = override_settings(TEMPLATES=_templates_without_oracle())
        override.enable()
        self.addCleanup(override.disable)

    def _get(self, path, **patches):
        with mock.patch.multiple(data, **patches):
            return _dispatch(self.admin, path)

    def test_home(self):
        response = self._get('/finance/', dashboard_counts=mock.Mock(return_value={
            'ACCOUNTS': 15, 'POSTING_HEADS': 10, 'LOCKED_PERIODS': 0, 'RULES': 11, 'DENIED_7D': 2,
            'FAILED_EVENTS': 1, 'ADVANCE_TOTAL': 1500000, 'ADVANCE_CUSTOMERS': 3}))
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Active accounts', response.content)

    def test_chart_of_accounts(self):
        rows = [{'ACCOUNT_ID': 1, 'ACCOUNT_CODE': '1100', 'ACCOUNT_NAME': 'Accounts Receivable',
                 'ACCOUNT_TYPE': 'ASSET', 'PARENT_CODE': '1000', 'IS_POSTING': 1, 'IS_LOCKED': 1,
                 'SYSTEM_KEY': 'RECEIVABLE', 'IS_ACTIVE': 1}]
        response = self._get('/finance/accounts/', fetch_accounts=mock.Mock(return_value=rows))
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Accounts Receivable', response.content)

    def test_settings_page_lists_choices(self):
        rows = [{'SETTING_KEY': 'ALLOCATION_STRATEGY', 'SETTING_VALUE': 'OLDEST_FIRST', 'VALUE_TYPE': 'CHOICE',
                 'OPTIONS': 'OLDEST_FIRST,MANUAL', 'DESCRIPTION': 'x', 'IS_EDITABLE': 1,
                 'UPDATED_BY': None, 'UPDATED_AT': None}]
        response = self._get('/finance/settings/', fetch_settings=mock.Mock(return_value=rows))
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'value="MANUAL"', response.content)

    def test_audit_page_records_the_access(self):
        record = mock.Mock()
        response = self._get('/finance/audit/', fetch_audit=mock.Mock(return_value=[]), record_access=record)
        self.assertEqual(response.status_code, 200)
        record.assert_called_once()

    def test_account_forms_and_rules_and_periods_render(self):
        parents = [{'ACCOUNT_ID': 10, 'ACCOUNT_CODE': '1000', 'ACCOUNT_NAME': 'Assets', 'ACCOUNT_TYPE': 'ASSET'}]
        existing = {'ACCOUNT_ID': 5, 'ACCOUNT_CODE': '1100', 'ACCOUNT_NAME': 'Accounts Receivable',
                    'ACCOUNT_TYPE': 'ASSET', 'PARENT_ID': 10, 'IS_POSTING': 1, 'IS_LOCKED': 1}
        rule = {'RULE_ID': 1, 'EVENT_CODE': 'SALE_POSTED', 'DESCRIPTION': 'Sale posted',
                'DEBIT_ACCOUNT_KEY': 'RECEIVABLE', 'CREDIT_ACCOUNT_KEY': 'SALES_INCOME',
                'UPDATED_BY': None, 'UPDATED_AT': None}
        keyed = [{'ACCOUNT_CODE': '1100', 'ACCOUNT_NAME': 'Accounts Receivable', 'SYSTEM_KEY': 'RECEIVABLE'},
                 {'ACCOUNT_CODE': '4100', 'ACCOUNT_NAME': 'Sales Income', 'SYSTEM_KEY': 'SALES_INCOME'}]
        cases = [
            ('/finance/accounts/add/', {'fetch_group_accounts': mock.Mock(return_value=parents)}, b'Add Account'),
            ('/finance/accounts/5/edit/', {'fetch_group_accounts': mock.Mock(return_value=parents),
                                           'fetch_account': mock.Mock(return_value=existing)}, b'System head'),
            ('/finance/posting-rules/', {'fetch_posting_rules': mock.Mock(return_value=[rule]),
                                         'fetch_keyed_accounts': mock.Mock(return_value=keyed)}, b'SALE_POSTED'),
            ('/finance/periods/', {'fetch_period_rows': mock.Mock(return_value=[])}, b'Accounting Periods'),
        ]
        for path, patches, expected in cases:
            with self.subTest(path=path):
                response = self._get(path, **patches)
                self.assertEqual(response.status_code, 200)
                self.assertIn(expected, response.content)

    def test_posting_a_change_redirects_and_never_leaves_the_module(self):
        request = RequestFactory().post('/finance/settings/ROUNDING_TOLERANCE/update/', {'value': '2'})
        request.user = self.admin
        request.session = {}
        from django.contrib.messages.storage.fallback import FallbackStorage
        request._messages = FallbackStorage(request)
        with mock.patch.object(data, 'update_setting', return_value='') as update:
            match = resolve(request.path_info)
            response = match.func(request, *match.args, **match.kwargs)
        self.assertEqual(response.status_code, 302)
        update.assert_called_once()
        self.assertEqual(update.call_args[0][1:3], ('ROUNDING_TOLERANCE', '2'))


@override_settings(DEBUG=False, ALLOWED_HOSTS=['testserver'])
class PhaseTwoScreensRender(SimpleTestCase):

    def setUp(self):
        self.admin = _user(is_superuser=True, username='root', is_staff=True)
        override = override_settings(TEMPLATES=_templates_without_oracle())
        override.enable()
        self.addCleanup(override.disable)

    def _get(self, path, **patches):
        with mock.patch.multiple(data, **patches):
            return _dispatch(self.admin, path)

    def test_customers_and_ledger(self):
        rows = [{'VENDOR_ID': 5, 'VENDOR_NAME': 'Al Noor Traders', 'DIVISION': '08',
                 'TOTAL_IN': 1000000, 'USED': 342000, 'BALANCE': 658000}]
        r = self._get('/finance/customers/', fetch_customers=mock.Mock(return_value=rows))
        self.assertEqual(r.status_code, 200)
        self.assertIn(b'Al Noor Traders', r.content)
        self.assertIn(b'658,000.00', r.content)
        ledger = [{'VOUCHER_DATE': '05-Nov-2026', 'VOUCHER_ID': 1, 'VOUCHER_NO': 'AV-08-2026-00001', 'TYPE_CODE': 'AV',
                   'STATUS': 'POSTED', 'NARRATION': 'x', 'ACCOUNT_CODE': '2100', 'ACCOUNT_NAME': 'Customer Advances',
                   'SYSTEM_KEY': 'CUSTOMER_ADVANCE', 'DEBIT': 342000, 'CREDIT': 0, 'ADVANCE_BALANCE': 658000}]
        r = self._get('/finance/customers/5/', fetch_customer_name=mock.Mock(return_value='Al Noor Traders'),
                      fetch_customer_ledger=mock.Mock(return_value=ledger), fetch_advances=mock.Mock(return_value=[]))
        self.assertEqual(r.status_code, 200)
        self.assertIn(b'AV-08-2026-00001', r.content)

    def test_unknown_customer_is_404(self):
        r = self._get('/finance/customers/99/', fetch_customer_name=mock.Mock(return_value=None))
        self.assertEqual(r.status_code, 404)

    def test_entry_forms(self):
        opts = {'fetch_customer_options': mock.Mock(return_value=[{'VENDOR_ID': 5, 'VENDOR_NAME': 'Al Noor Traders'}])}
        for path, expected in (('/finance/advances/add/', b'Receive Customer Advance'),
                               ('/finance/advances/opening/', b'Load Opening Balance')):
            with self.subTest(path=path):
                r = self._get(path, **opts)
                self.assertEqual(r.status_code, 200)
                self.assertIn(expected, r.content)

    def test_vouchers_and_one_voucher(self):
        row = {'VOUCHER_ID': 1, 'VOUCHER_NO': 'SV-08-2026-00001', 'TYPE_CODE': 'SV', 'DIVISION': '08', 'VOUCHER_DATE': '05-Nov-2026',
               'VENDOR_NAME': 'Al Noor', 'NARRATION': 'Sale', 'SOURCE_TYPE': 'GATEPASS', 'SOURCE_ID': 'GP1',
               'AMOUNT': 342000, 'STATUS': 'POSTED', 'CREATED_BY': 'x', 'CREATED_AT': 'y'}
        r = self._get('/finance/vouchers/', fetch_vouchers=mock.Mock(return_value=[row]))
        self.assertIn(b'SV-08-2026-00001', r.content)
        lines = [{'LINE_NO': 1, 'ACCOUNT_CODE': '1100', 'ACCOUNT_NAME': 'Accounts Receivable', 'DEBIT': 342000, 'CREDIT': 0},
                 {'LINE_NO': 2, 'ACCOUNT_CODE': '4100', 'ACCOUNT_NAME': 'Sales Income', 'DEBIT': 0, 'CREDIT': 342000}]
        r = self._get('/finance/vouchers/1/', fetch_voucher=mock.Mock(return_value=(row, lines)))
        self.assertEqual(r.status_code, 200)
        self.assertIn(b'Sales Income', r.content)

    def test_events_page_shows_failures_missed_items_and_the_switch_state(self):
        failed = {'EVENT_ID': 1, 'EVENT_TYPE': 'GP_POSTED', 'SOURCE_ID': 'GP9', 'DIVISION': '08', 'EVENT_DATE': '05-Nov-2026',
                  'STATUS': 'FAILED', 'ATTEMPTS': 2, 'MESSAGE': 'Customer advance is not enough', 'VOUCHER_IDS': None,
                  'ACTOR': 'x', 'WHEN_TS': 'now'}
        missed = [{'EVENT_TYPE': 'GP_POSTED', 'SOURCE_ID': 'GP10', 'DIVISION': '08', 'EVENT_DATE': '06-Nov-2026'}]
        with override_settings(FINANCE_HOOKS_ENABLED=False):
            r = self._get('/finance/events/', fetch_events=mock.Mock(return_value=[failed]),
                          fetch_missed_events=mock.Mock(return_value=missed))
        self.assertEqual(r.status_code, 200)
        for needle in (b'GP9', b'Retry', b'GP10', b'Process now', b'switched off'):
            self.assertIn(needle, r.content)

    def test_retry_posts_through_the_gateway_and_redirects(self):
        from apps.finance import gateway
        request = RequestFactory().post('/finance/events/retry/', {'event_type': 'GP_POSTED', 'source_id': 'GP9'})
        request.user = self.admin
        request.session = {}
        from django.contrib.messages.storage.fallback import FallbackStorage
        request._messages = FallbackStorage(request)
        with mock.patch.object(gateway, 'retry_event', return_value=('POSTED', 'ok')) as retry:
            match = resolve(request.path_info)
            response = match.func(request, *match.args, **match.kwargs)
        self.assertEqual(response.status_code, 302)
        retry.assert_called_once_with(self.admin, 'GP_POSTED', 'GP9')

    def test_retry_rejects_unknown_event_types(self):
        request = RequestFactory().post('/finance/events/retry/', {'event_type': 'EVIL', 'source_id': 'GP9'})
        request.user = self.admin
        match = resolve(request.path_info)
        with self.assertRaises(Http404):
            match.func(request, *match.args, **match.kwargs)


class PhaseThreeScreensRender(SimpleTestCase):

    def setUp(self):
        self.admin = _user(is_superuser=True, username='root', is_staff=True)
        override = override_settings(TEMPLATES=_templates_without_oracle())
        override.enable()
        self.addCleanup(override.disable)
        self.opts = {'fetch_customer_options': mock.Mock(return_value=[{'VENDOR_ID': 5, 'VENDOR_NAME': 'Al Noor Traders'}]),
                     'fetch_posting_accounts': mock.Mock(return_value=[{'ACCOUNT_ID': 8, 'ACCOUNT_CODE': '5200', 'ACCOUNT_NAME': 'Bank Charges'}]),
                     'fetch_gatepass_receivables': mock.Mock(return_value=[])}

    def _get(self, path, **patches):
        with mock.patch.multiple(data, **{**self.opts, **patches}):
            return _dispatch(self.admin, path)

    def _post(self, path, post, **patches):
        from django.contrib.messages.storage.fallback import FallbackStorage
        request = RequestFactory().post(path, post)
        request.user, request.session = self.admin, {}
        request._messages = FallbackStorage(request)
        with mock.patch.multiple(data, **{**self.opts, **patches}):
            match = resolve(request.path_info)
            return match.func(request, *match.args, **match.kwargs)

    def test_list_page_never_shows_payment_status_badges(self):
        row = {'ADJUSTMENT_ID': 1, 'ADJ_TYPE': 'CREDIT_NOTE', 'DIVISION': '08', 'ADJ_DATE': '10-Nov-2026', 'VENDOR_NAME': 'Al Noor',
               'TO_NAME': None, 'SOURCE_REF': 'GP1', 'AMOUNT': 300, 'REASON': 'weighbridge', 'STATUS': 'ACTIVE',
               'CREATED_BY': 'root', 'REVERSAL_REASON': None}
        r = self._get('/finance/adjustments/', fetch_adjustments=mock.Mock(return_value=[row]))
        self.assertEqual(r.status_code, 200)
        self.assertIn(b'Credit', r.content)
        for banned in (b'Partially Paid', b'Unpaid'):
            self.assertNotIn(banned, r.content)

    def test_every_form_renders(self):
        for path, needle in (('/finance/adjustments/refund/', b'Refund Unused Advance'),
                             ('/finance/adjustments/transfer/', b'Transfer Advance'),
                             ('/finance/adjustments/note/', b'Credit / Debit Note'),
                             ('/finance/adjustments/journal/', b'Manual Journal Voucher')):
            with self.subTest(path=path):
                r = self._get(path)
                self.assertEqual(r.status_code, 200)
                self.assertIn(needle, r.content)

    def test_a_refused_post_redisplays_the_form_with_the_message(self):
        r = self._post('/finance/adjustments/refund/', {'party_id': '5'},
                       refund_entry=mock.Mock(return_value=(None, ['A reason is required.'])))
        self.assertEqual(r.status_code, 200)
        self.assertIn(b'A reason is required.', r.content)

    def test_a_good_post_redirects_to_the_list(self):
        r = self._post('/finance/adjustments/journal/', {'narration': 'x'},
                       journal_entry_post=mock.Mock(return_value=('ok', [])))
        self.assertEqual(r.status_code, 302)

    def test_reverse_is_post_only_and_passes_the_reason(self):
        rev = mock.Mock(return_value=None)
        r = self._post('/finance/adjustments/5/reverse/', {'reason': 'posted by mistake'}, reverse_adjustment_entry=rev)
        self.assertEqual(r.status_code, 302)
        self.assertEqual(rev.call_args.args[:3], (self.admin, 5, 'posted by mistake'))
