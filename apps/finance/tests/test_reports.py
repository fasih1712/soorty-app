"""
PHASE 4 GATE - reports. No database: pure rules, spec builders, file
exporters, and the views with the data layer mocked.
"""
import io
from datetime import date
from decimal import Decimal
from unittest import mock

from django.test import SimpleTestCase, override_settings

from apps.finance import data, exporters, report_builders as B, reports as R
from apps.finance.ledger import FinanceRuleError

from .test_access import _dispatch, _templates_without_oracle, _user

D = Decimal
CTX = {'generated_by': 'root', 'generated_at': 'now',
       'voucher_url': lambda i: f'/finance/vouchers/{i}/', 'ledger_url': lambda i: f'/finance/reports/general-ledger/?account={i}'}


class DateFilters(SimpleTestCase):

    def test_defaults_are_month_start_to_today(self):
        self.assertEqual(R.parse_range('', '', today=date(2026, 11, 18)), (date(2026, 11, 1), date(2026, 11, 18)))

    def test_bad_ranges_are_refused(self):
        for a, b in (('2026-11-30', '2026-11-01'), ('nonsense', ''), ('2000-01-01', '2026-11-01')):
            with self.subTest(a=a, b=b), self.assertRaises(FinanceRuleError):
                R.parse_range(a, b, today=date(2026, 11, 18))

    def test_as_of_and_grouping(self):
        self.assertEqual(R.parse_as_of('2026-12-31'), date(2026, 12, 31))
        with self.assertRaises(FinanceRuleError):
            R.parse_as_of('31/12/2026')
        self.assertEqual(R.parse_granularity(None), 'month')
        with self.assertRaises(FinanceRuleError):
            R.parse_granularity('year')


class Statement(SimpleTestCase):

    def line(self, d, c, type_code='AV', source='ADVANCE', adj=None, vid=1):
        return {'VOUCHER_DATE': '05-Nov-2026', 'VOUCHER_ID': vid, 'VOUCHER_NO': f'V{vid}', 'TYPE_CODE': type_code,
                'SOURCE_TYPE': source, 'ADJ_TYPE': adj, 'NARRATION': 'n', 'STATUS': 'POSTED', 'DEBIT': d, 'CREDIT': c}

    def test_running_balance_and_totals(self):
        rows, t = R.build_statement('1000', [self.line(0, '5000'), self.line('1200', 0, source='GATEPASS', vid=2)])
        self.assertEqual([r['BALANCE'] for r in rows], [D('6000.00'), D('4800.00')])
        self.assertEqual(t, {'OPENING': D('1000.00'), 'RECEIVED': D('5000.00'), 'APPLIED': D('1200.00'), 'CLOSING': D('4800.00')})

    def test_descriptions_are_plain_english(self):
        cases = [(('AV', 'ADVANCE', None, 0, 5), 'Advance received'), (('AV', 'OPENING', None, 0, 5), 'Opening balance loaded'),
                 (('AV', 'GATEPASS', None, 5, 0), 'Dispatch knock-off'), (('RVS', 'GATEPASS', None, 0, 5), 'Reversal'),
                 (('AV', 'ADJUSTMENT', 'REFUND', 5, 0), 'Refund paid'), (('AV', 'ADJUSTMENT', 'TRANSFER', 5, 0), 'Transfer out'),
                 (('AV', 'ADJUSTMENT', 'TRANSFER', 0, 5), 'Transfer in'),
                 (('AV', 'ADJUSTMENT', 'CREDIT_NOTE', 0, 5), 'Credit note returned to advance'),
                 (('AV', 'ADJUSTMENT', 'DEBIT_NOTE', 5, 0), 'Debit note paid from advance')]
        for args, text in cases:
            with self.subTest(text=text):
                self.assertEqual(R.statement_label(*args), text)

    def test_empty_period_keeps_opening_as_closing(self):
        rows, t = R.build_statement('250.50', [])
        self.assertEqual((rows, t['CLOSING']), ([], D('250.50')))


class TrialBalance(SimpleTestCase):

    def rows(self, *items):
        return [{'ACCOUNT_ID': i, 'ACCOUNT_CODE': str(i), 'ACCOUNT_NAME': f'A{i}', 'ACCOUNT_TYPE': 'ASSET', 'DEBIT': d, 'CREDIT': c}
                for i, (d, c) in enumerate(items, 1)]

    def test_balanced_book_agrees_and_idle_accounts_drop_out(self):
        rows, t = R.trial_balance(self.rows(('1000', '0'), ('0', '600'), ('0', '400'), ('0', '0')))
        self.assertEqual(len(rows), 3)
        self.assertTrue(t['BALANCED'])
        self.assertEqual((t['DEBIT_BALANCE'], t['CREDIT_BALANCE']), (D('1000.00'), D('1000.00')))

    def test_netting_per_account(self):
        rows, _ = R.trial_balance(self.rows(('700', '200')))
        self.assertEqual((rows[0]['DEBIT_BALANCE'], rows[0]['CREDIT_BALANCE']), (D('500.00'), D('0.00')))

    def test_a_broken_book_is_flagged(self):
        _, t = R.trial_balance(self.rows(('1000', '0'), ('0', '999.99')))
        self.assertFalse(t['BALANCED'])

    def test_general_ledger_running_balance(self):
        rows, t = R.build_general_ledger('100', [{'DEBIT': '50', 'CREDIT': 0}, {'DEBIT': 0, 'CREDIT': '200'}])
        self.assertEqual([r['BALANCE'] for r in rows], [D('150.00'), D('-50.00')])
        self.assertEqual(t['CLOSING'], D('-50.00'))


class SalesSummary(SimpleTestCase):

    def r(self, day, key, source, net, division='08'):
        return {'PERIOD_DATE': day, 'DIVISION': division, 'SYSTEM_KEY': key, 'SOURCE_TYPE': source, 'NET': net}

    ROWS = None

    def setUp(self):
        self.rows = [self.r('2026-11-05', 'SALES_INCOME', 'GATEPASS', '5000'),
                     self.r('2026-11-20', 'SALES_INCOME', 'GATEPASS', '3000'),
                     self.r('2026-11-20', 'SALES_RETURNS', 'ADJUSTMENT', '-300'),      # credit note
                     self.r('2026-11-05', 'CUSTOMER_ADVANCE', 'ADVANCE', '10000'),
                     self.r('2026-11-06', 'CUSTOMER_ADVANCE', 'OPENING', '99999'),      # not a collection
                     self.r('2026-11-07', 'CUSTOMER_ADVANCE', 'GATEPASS', '-5000'),     # knock-off: not a collection
                     self.r('2026-11-08', 'CUSTOMER_ADVANCE', 'ADJUSTMENT', '-100')]    # refund: not a collection

    def test_month_view(self):
        rows, t = R.summarise_sales(self.rows, 'month')
        self.assertEqual(len(rows), 1)
        self.assertEqual((t['SALES'], t['NOTES'], t['NET_SALES'], t['COLLECTIONS'], t['DIFFERENCE']),
                         (D('8000.00'), D('-300.00'), D('7700.00'), D('10000.00'), D('2300.00')))

    def test_day_view_splits_and_skips_days_with_nothing_relevant(self):
        rows, _ = R.summarise_sales(self.rows, 'day')
        self.assertEqual([r['PERIOD'] for r in rows], ['2026-11-05', '2026-11-20'])

    def test_divisions_are_kept_apart(self):
        rows, _ = R.summarise_sales(self.rows + [self.r('2026-11-05', 'SALES_INCOME', 'GATEPASS', '1', division='09')], 'month')
        self.assertEqual({r['DIVISION'] for r in rows}, {'08', '09'})

    def test_reversed_receipt_nets_out(self):
        rows, t = R.summarise_sales([self.r('2026-11-05', 'CUSTOMER_ADVANCE', 'ADVANCE', '0')], 'month')
        self.assertEqual(rows, [])


def _good():
    return {'control_advance': '5000', 'ledger_by_party': [{'PARTY_ID': 1, 'PARTY_NAME': 'A', 'AMOUNT': '5000'}],
            'subledger_by_party': [{'PARTY_ID': 1, 'PARTY_NAME': 'A', 'AMOUNT': '5000'}], 'unattributed_lines': 0,
            'control_receivable': '0', 'open_receivables': '0', 'unbalanced_vouchers': [], 'advance_mismatches': [],
            'failed_events': 0, 'missed_events': []}


class Reconciliation(SimpleTestCase):

    def run_with(self, **changes):
        d = _good()
        d.update(changes)
        return R.reconcile(d)

    def failed(self, checks):
        return [c['NAME'] for c in checks if c['STATUS'] != 'OK']

    def test_clean_books_pass_every_check(self):
        checks = self.run_with()
        self.assertEqual(len(checks), 8)
        self.assertTrue(R.overall(checks))

    def test_customer_difference_is_named(self):
        checks = self.run_with(ledger_by_party=[{'PARTY_ID': 1, 'PARTY_NAME': 'A', 'AMOUNT': '5001'}])
        self.assertEqual(self.failed(checks), ['Each customer: ledger balance equals advance balance'])
        self.assertEqual(checks[0]['ITEMS'][0]['DIFFERENCE'], D('1.00'))

    def test_control_account_drift(self):
        self.assertIn('Customer Advances account equals total of customer advances', self.failed(self.run_with(control_advance='4999.99')))

    def test_every_other_failure_is_caught(self):
        for change in ({'unattributed_lines': 2}, {'control_receivable': '10'}, {'unbalanced_vouchers': [{'VOUCHER_NO': 'x', 'DEBIT': D(1), 'CREDIT': D(2)}]},
                       {'advance_mismatches': [{'ADVANCE_ID': 1, 'USED': D(5), 'RECORDED': D(4)}]}, {'failed_events': 1},
                       {'missed_events': [{'SOURCE_ID': 'GP1'}]}):
            with self.subTest(change=list(change)):
                checks = self.run_with(**change)
                self.assertFalse(R.overall(checks))
                self.assertEqual(len(self.failed(checks)), 1)

    def test_party_missing_on_one_side_is_a_difference(self):
        checks = self.run_with(subledger_by_party=[], control_advance='5000')
        self.assertIn('Each customer: ledger balance equals advance balance', self.failed(checks))


class Ageing(SimpleTestCase):

    def test_bucket_edges(self):
        for age, label in ((0, '0-30 days'), (30, '0-30 days'), (31, '31-60 days'), (60, '31-60 days'),
                           (61, '61-90 days'), (90, '61-90 days'), (91, 'Over 90 days'), (400, 'Over 90 days')):
            with self.subTest(age=age):
                self.assertEqual(R.bucket_for(age), label)

    def test_customers_sorted_oldest_first_and_totalled(self):
        rows = [{'PARTY_ID': 1, 'PARTY_NAME': 'Young', 'ADVANCE_DATE': '2026-11-25', 'REMAINING': '100'},
                {'PARTY_ID': 2, 'PARTY_NAME': 'Old', 'ADVANCE_DATE': '2026-08-01', 'REMAINING': '700'},
                {'PARTY_ID': 2, 'PARTY_NAME': 'Old', 'ADVANCE_DATE': '2026-11-20', 'REMAINING': '50'},
                {'PARTY_ID': 3, 'PARTY_NAME': 'Spent', 'ADVANCE_DATE': '2026-09-01', 'REMAINING': '0'}]
        out, t = R.age_advances(rows, date(2026, 11, 30))
        self.assertEqual([c['PARTY_NAME'] for c in out], ['Old', 'Young'])
        self.assertEqual(out[0]['Over 90 days'], D('700.00'))
        self.assertEqual(out[0]['0-30 days'], D('50.00'))
        self.assertEqual(t['TOTAL'], D('850.00'))
        self.assertEqual(out[0]['OLDEST_DAYS'], 121)


class Builders(SimpleTestCase):

    def test_statement_spec_links_vouchers_and_totals(self):
        line = {'VOUCHER_DATE': '05-Nov-2026', 'VOUCHER_ID': 7, 'VOUCHER_NO': 'AV-1', 'TYPE_CODE': 'AV', 'SOURCE_TYPE': 'ADVANCE',
                'ADJ_TYPE': None, 'NARRATION': 'x', 'STATUS': 'POSTED', 'DEBIT': 0, 'CREDIT': '900'}
        spec, totals = B.statement_spec('Al Noor', '', date(2026, 11, 1), date(2026, 11, 30), '100', [line], CTX)
        self.assertEqual(totals['CLOSING'], D('1000.00'))
        tx = spec['sections'][1]
        self.assertEqual(tx['rows'][0]['_links']['VOUCHER_NO'], '/finance/vouchers/7/')
        table = B.html_table(tx)
        self.assertEqual(table['body'][0][4]['text'], '900.00')
        self.assertEqual(table['total'][-1]['text'], '1,000.00')

    def test_trial_balance_warns_when_broken(self):
        rows = [{'ACCOUNT_ID': 1, 'ACCOUNT_CODE': '1010', 'ACCOUNT_NAME': 'Cash', 'ACCOUNT_TYPE': 'ASSET', 'DEBIT': '10', 'CREDIT': '0'}]
        spec, totals = B.trial_balance_spec('', date(2026, 11, 30), rows, CTX)
        self.assertFalse(totals['BALANCED'])
        self.assertIn('does NOT agree', spec['sections'][0]['note'])

    def test_reconciliation_spec_lists_details_only_for_failures(self):
        good, ok = B.reconciliation_spec(R.reconcile(_good()), CTX)
        self.assertTrue(ok)
        self.assertEqual(len(good['sections']), 1)
        bad = _good()
        bad['failed_events'] = 2
        bad['unbalanced_vouchers'] = [{'VOUCHER_NO': 'X', 'DEBIT': D(1), 'CREDIT': D(2)}]
        spec, ok = B.reconciliation_spec(R.reconcile(bad), CTX)
        self.assertFalse(ok)
        self.assertEqual(len(spec['sections']), 2)
        self.assertIn('FAILED', spec['filters'][0][1])


def _spec():
    return {'title': 'T <b>x</b>', 'subtitle': 's', 'filters': [('A', '=1+1')], 'generated_by': 'root', 'generated_at': 'now',
            'sections': [{'heading': 'H', 'columns': [{'key': 'a', 'label': 'A', 'kind': 'text'}, {'key': 'm', 'label': 'M', 'kind': 'money'}],
                          'rows': [{'a': '=HYPERLINK("http://x")', 'm': D('1234.5')}, {'a': '<para>&', 'm': -5}],
                          'totals': {'a': 'Total', 'm': D('1229.5')}, 'note': 'n'}]}


class Exporters(SimpleTestCase):

    def test_excel_keeps_numbers_numeric_and_text_as_text(self):
        import openpyxl
        ws = openpyxl.load_workbook(io.BytesIO(exporters.to_xlsx(_spec()))).active
        cells = {c.value: c for row in ws.iter_rows() for c in row if c.value is not None}
        self.assertEqual(cells[1234.5].data_type, 'n')
        self.assertEqual(cells['=HYPERLINK("http://x")'].data_type, 's')       # never a live formula
        self.assertEqual(cells['A: =1+1'].data_type, 's')

    def test_pdf_builds_even_with_markup_characters(self):
        blob = exporters.to_pdf(_spec())
        self.assertTrue(blob.startswith(b'%PDF'))

    def test_pdf_labels_with_broken_markup_do_not_crash(self):
        spec = _spec()
        spec['sections'][0]['columns'][0]['label'] = 'Name <b>unclosed & <i'
        self.assertTrue(exporters.to_pdf(spec).startswith(b'%PDF'))

    def test_pdf_empty_report(self):
        spec = _spec()
        spec['sections'][0]['rows'], spec['sections'][0]['totals'] = [], None
        self.assertTrue(exporters.to_pdf(spec).startswith(b'%PDF'))

    def test_missing_library_is_reported_not_crashed(self):
        real = __import__
        def fake(name, *a, **k):
            if name.startswith(('openpyxl', 'reportlab')):
                raise ImportError(name)
            return real(name, *a, **k)
        with mock.patch('builtins.__import__', side_effect=fake):
            for fn in (exporters.to_xlsx, exporters.to_pdf):
                with self.assertRaises(exporters.ExportUnavailable):
                    fn(_spec())

    def test_filenames_are_safe(self):
        self.assertEqual(exporters.safe_filename('Sales / "Collections" ../x', 'pdf'), 'Sales_Collections_x.pdf')


class ReportScreens(SimpleTestCase):

    def setUp(self):
        self.admin = _user(is_superuser=True, username='root', is_staff=True)
        override = override_settings(TEMPLATES=_templates_without_oracle())
        override.enable()
        self.addCleanup(override.disable)
        self.record = mock.Mock()
        self.patches = dict(
            fetch_customer_options=mock.Mock(return_value=[{'VENDOR_ID': 5, 'VENDOR_NAME': 'Al Noor Traders'}]),
            fetch_ledger_accounts=mock.Mock(return_value=[{'ACCOUNT_ID': 3, 'ACCOUNT_CODE': '2100', 'ACCOUNT_NAME': 'Customer Advances'}]),
            record_export=self.record)

    def get(self, path, **more):
        with mock.patch.multiple(data, **{**self.patches, **more}):
            return _dispatch(self.admin, path)

    def stmt(self):
        line = {'VOUCHER_DATE': '05-Nov-2026', 'VOUCHER_ID': 7, 'VOUCHER_NO': 'AV-08-2026-00001', 'TYPE_CODE': 'AV', 'SOURCE_TYPE': 'ADVANCE',
                'ADJ_TYPE': None, 'NARRATION': 'x', 'STATUS': 'POSTED', 'DEBIT': 0, 'CREDIT': 5000}
        return mock.Mock(return_value=('Al Noor Traders', 1000, [line]))

    def test_index_lists_all_six_reports(self):
        r = self.get('/finance/reports/')
        self.assertEqual(r.status_code, 200)
        for name in (b'Customer Advance Statement', b'Trial Balance', b'General Ledger', b'Sales and Collections',
                     b'Reconciliation Check', b'Advance Ageing'):
            self.assertIn(name, r.content)

    def test_statement_needs_a_customer_then_shows_figures_and_links(self):
        self.assertIn(b'press Show', self.get('/finance/reports/advance-statement/').content)
        r = self.get('/finance/reports/advance-statement/?party=5&from=2026-11-01&to=2026-11-30', fetch_statement=self.stmt())
        self.assertEqual(r.status_code, 200)
        self.assertIn(b'Al Noor Traders', r.content)
        self.assertIn(b'6,000.00', r.content)
        self.assertIn(b'/finance/vouchers/7/', r.content)

    def test_bad_input_shows_a_message_not_an_error_page(self):
        for path in ('/finance/reports/advance-statement/?party=5&from=2026-12-01&to=2026-11-01',
                     '/finance/reports/advance-statement/?party=abc',
                     '/finance/reports/advance-statement/?party=5&division=ZZZ',
                     '/finance/reports/trial-balance/?as_of=junk', '/finance/reports/general-ledger/?account=x',
                     '/finance/reports/sales-collections/?group=year', '/finance/reports/advance-ageing/?as_of=2026-02-30'):
            with self.subTest(path=path):
                r = self.get(path, fetch_statement=self.stmt())
                self.assertEqual(r.status_code, 200)
                self.assertIn(b'class="fin-alert fin-alert-danger"', r.content)

    def test_unknown_customer_and_account(self):
        r = self.get('/finance/reports/advance-statement/?party=99', fetch_statement=mock.Mock(return_value=(None, None, [])))
        self.assertIn(b'Customer not found', r.content)
        r = self.get('/finance/reports/general-ledger/?account=99', fetch_general_ledger=mock.Mock(return_value=(None, None, [])))
        self.assertIn(b'Account not found', r.content)

    def test_trial_balance_page_and_downloads(self):
        rows = [{'ACCOUNT_ID': 1, 'ACCOUNT_CODE': '1010', 'ACCOUNT_NAME': 'Cash In Hand', 'ACCOUNT_TYPE': 'ASSET', 'DEBIT': 10, 'CREDIT': 0},
                {'ACCOUNT_ID': 2, 'ACCOUNT_CODE': '2100', 'ACCOUNT_NAME': 'Customer Advances', 'ACCOUNT_TYPE': 'LIABILITY', 'DEBIT': 0, 'CREDIT': 10}]
        fetch = mock.Mock(return_value=rows)
        r = self.get('/finance/reports/trial-balance/?as_of=2026-11-30', fetch_trial_balance_rows=fetch)
        self.assertIn(b'Cash In Hand', r.content)
        self.assertIn(b'agrees', r.content)
        self.assertIn(b'/finance/reports/general-ledger/?account=1', r.content)
        pdf = self.get('/finance/reports/trial-balance/?as_of=2026-11-30&fmt=pdf', fetch_trial_balance_rows=fetch)
        self.assertEqual(pdf['Content-Type'], 'application/pdf')
        self.assertTrue(pdf.content.startswith(b'%PDF'))
        self.assertIn('attachment', pdf['Content-Disposition'])
        xl = self.get('/finance/reports/trial-balance/?fmt=xlsx', fetch_trial_balance_rows=fetch)
        self.assertIn('spreadsheetml', xl['Content-Type'])
        self.assertEqual(self.record.call_count, 2)                        # both downloads were audited
        self.assertIn('PDF', self.record.call_args_list[0].args[2])

    def test_a_page_view_is_not_a_download_and_is_not_logged_as_one(self):
        self.get('/finance/reports/trial-balance/', fetch_trial_balance_rows=mock.Mock(return_value=[]))
        self.record.assert_not_called()

    def test_missing_library_gives_a_message_on_the_page(self):
        with mock.patch.object(exporters, 'to_pdf', side_effect=exporters.ExportUnavailable('install reportlab')):
            r = self.get('/finance/reports/trial-balance/?fmt=pdf', fetch_trial_balance_rows=mock.Mock(return_value=[]))
        self.assertEqual(r.status_code, 200)
        self.assertIn(b'install reportlab', r.content)
        self.record.assert_not_called()

    def test_general_ledger_sales_ageing_and_reconciliation_render(self):
        gl = mock.Mock(return_value=({'ACCOUNT_ID': 3, 'ACCOUNT_CODE': '2100', 'ACCOUNT_NAME': 'Customer Advances'}, 0,
                                     [{'VOUCHER_DATE': '05-Nov-2026', 'VOUCHER_ID': 9, 'VOUCHER_NO': 'AV-9', 'TYPE_CODE': 'AV', 'DIVISION': '08',
                                       'PARTY_NAME': 'Al Noor', 'NARRATION': 'x', 'STATUS': 'POSTED', 'DEBIT': 0, 'CREDIT': 300}]))
        r = self.get('/finance/reports/general-ledger/?account=3&from=2026-11-01&to=2026-11-30', fetch_general_ledger=gl)
        self.assertIn(b'AV-9', r.content)
        sales = mock.Mock(return_value=[{'PERIOD_DATE': date(2026, 11, 5), 'DIVISION': '08', 'SYSTEM_KEY': 'SALES_INCOME',
                                         'SOURCE_TYPE': 'GATEPASS', 'NET': 8000}])
        r = self.get('/finance/reports/sales-collections/?from=2026-11-01&to=2026-11-30', fetch_sales_rows=sales)
        self.assertIn(b'2026-11', r.content)
        self.assertIn(b'8,000.00', r.content)
        age = mock.Mock(return_value=[{'PARTY_ID': 1, 'PARTY_NAME': 'Al Noor', 'ADVANCE_DATE': date(2026, 8, 1), 'REMAINING': 700}])
        r = self.get('/finance/reports/advance-ageing/?as_of=2026-11-30', fetch_ageing_rows=age)
        self.assertIn(b'Over 90 days', r.content)
        r = self.get('/finance/reports/reconciliation/', fetch_reconciliation_data=mock.Mock(return_value=_good()))
        self.assertIn(b'All checks passed', r.content)
        bad = {**_good(), 'failed_events': 3}
        r = self.get('/finance/reports/reconciliation/', fetch_reconciliation_data=mock.Mock(return_value=bad))
        self.assertIn(b'check(s) failed', r.content.lower().replace(b'one or more checks failed', b'check(s) failed'))
        self.assertIn(b'FAILED', r.content)

    def test_no_payment_status_badges_anywhere_in_reports(self):
        r = self.get('/finance/reports/reconciliation/', fetch_reconciliation_data=mock.Mock(return_value=_good()))
        for banned in (b'Partially Paid', b'Unpaid'):
            self.assertNotIn(banned, r.content)
