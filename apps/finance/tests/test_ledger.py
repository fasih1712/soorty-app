"""
PHASE 2 GATE - money rules (no database).

    python manage.py test apps.finance.tests.test_ledger
"""
import re
from datetime import date
from decimal import Decimal

from django.test import SimpleTestCase

from apps.finance import ledger as L


class MoneyRules(SimpleTestCase):

    def test_rounding_is_half_up_and_exact(self):
        self.assertEqual(L.money('25.0125'), Decimal('25.01'))
        self.assertEqual(L.money('25.015'), Decimal('25.02'))
        self.assertEqual(L.money(0.1) + L.money(0.2), Decimal('0.30'))   # no float drift

    def test_line_value_is_qty_times_price_rounded_per_line(self):
        self.assertEqual(L.line_value('2.5', '10.005'), Decimal('25.01'))
        self.assertEqual(L.line_value(4000, 85.5), Decimal('342000.00'))

    def test_missing_price_or_bad_qty_is_refused(self):
        with self.assertRaises(L.MissingPrice):
            L.line_value(5, None)
        with self.assertRaises(L.FinanceRuleError):
            L.line_value(0, 10)
        with self.assertRaises(L.FinanceRuleError):
            L.money('abc')

    def test_group_by_customer_sums_lines(self):
        lines = [{'customer_id': 1, 'qty': 10, 'unit_price': 5}, {'customer_id': 1, 'qty': 2, 'unit_price': '2.50'},
                 {'customer_id': 2, 'qty': 1, 'unit_price': 7}]
        self.assertEqual(L.group_dispatch_by_customer(lines), {1: Decimal('55.00'), 2: Decimal('7.00')})

    def test_a_line_without_customer_or_price_refuses_the_whole_dispatch(self):
        with self.assertRaises(L.MissingPrice):
            L.group_dispatch_by_customer([{'customer_id': 1, 'qty': 1, 'unit_price': 1},
                                          {'customer_id': None, 'qty': 1, 'unit_price': 1}])
        with self.assertRaises(L.MissingPrice):
            L.group_dispatch_by_customer([{'customer_id': 1, 'qty': 1, 'unit_price': None}])


class CutOver(SimpleTestCase):

    def test_nothing_before_the_go_live_date(self):
        self.assertFalse(L.is_live('2026-10-31', '2026-11-01'))
        self.assertTrue(L.is_live('2026-11-01', '2026-11-01'))
        self.assertTrue(L.is_live(date(2027, 1, 5), '2026-11-01'))

    def test_no_go_live_date_means_not_live(self):
        self.assertFalse(L.is_live('2030-01-01', None))
        self.assertFalse(L.is_live(None, '2026-11-01'))

    def test_go_live_must_be_first_of_month(self):
        self.assertEqual(L.validate_go_live('2026-11-01'), ('2026-11-01', None))
        self.assertIsNotNone(L.validate_go_live('2026-11-15')[1])
        self.assertIsNotNone(L.validate_go_live('01-11-2026')[1])
        self.assertIsNotNone(L.validate_go_live('')[1])


class DoubleEntry(SimpleTestCase):

    def test_two_line_voucher_balances(self):
        lines = L.two_line(10, 20, '100.50', party_id=7)
        self.assertEqual(L.assert_balanced(lines), Decimal('100.50'))
        self.assertEqual(lines[0]['debit'], Decimal('100.50'))
        self.assertEqual(lines[1]['credit'], Decimal('100.50'))

    def test_unbalanced_or_bad_vouchers_are_refused(self):
        bad = [
            [],
            [{'account_id': 1, 'debit': 10, 'credit': 0}, {'account_id': 2, 'debit': 0, 'credit': 9}],
            [{'account_id': 1, 'debit': 0, 'credit': 0}, {'account_id': 2, 'debit': 0, 'credit': 0}],
            [{'account_id': 1, 'debit': 10, 'credit': 10}, {'account_id': 2, 'debit': 0, 'credit': 0}],
            [{'account_id': 1, 'debit': -5, 'credit': 0}, {'account_id': 2, 'debit': 0, 'credit': -5}],
        ]
        for lines in bad:
            with self.subTest(lines=lines):
                with self.assertRaises(L.Unbalanced):
                    L.assert_balanced(lines)

    def test_zero_or_negative_amount_cannot_be_posted(self):
        for amt in (0, '0.00', -1):
            with self.assertRaises(L.FinanceRuleError):
                L.two_line(1, 2, amt)

    def test_reversal_is_the_exact_mirror_and_nets_to_zero(self):
        lines = L.two_line(10, 20, '342000.00', 7)
        rev = L.mirror(lines)
        L.assert_balanced(rev)
        for a, b in zip(lines, rev):
            self.assertEqual(a['debit'], b['credit'])
            self.assertEqual(a['credit'], b['debit'])
        net = sum(l['debit'] - l['credit'] for l in lines + rev)
        self.assertEqual(net, Decimal('0.00'))


class AdvanceKnockOff(SimpleTestCase):
    POOL = [
        {'advance_id': 2, 'remaining': '50.00', 'advance_date': '2026-11-02'},
        {'advance_id': 1, 'remaining': '100.00', 'advance_date': '2026-11-01'},
        {'advance_id': 3, 'remaining': '0.00', 'advance_date': '2026-11-03'},
    ]

    def test_oldest_advance_is_used_first(self):
        self.assertEqual(L.allocate_oldest_first(self.POOL, '120'),
                         [(1, Decimal('100.00')), (2, Decimal('20.00'))])

    def test_exact_cover_works_and_one_paisa_short_is_refused(self):
        self.assertEqual(sum(a for _i, a in L.allocate_oldest_first(self.POOL, '150')), Decimal('150.00'))
        with self.assertRaises(L.InsufficientAdvance):
            L.allocate_oldest_first(self.POOL, '150.01')

    def test_empty_pool_is_refused_and_pool_is_not_changed(self):
        before = [dict(a) for a in self.POOL]
        with self.assertRaises(L.InsufficientAdvance):
            L.allocate_oldest_first([], '1')
        with self.assertRaises(L.InsufficientAdvance):
            L.allocate_oldest_first(self.POOL, '999')
        self.assertEqual(self.POOL, before)

    def test_prepaid_check_is_exact_with_no_tolerance(self):
        self.assertTrue(L.can_dispatch('100.00', '100.00'))
        self.assertFalse(L.can_dispatch('99.99', '100.00'))
        self.assertFalse(L.can_dispatch('0', '0.01'))

    def test_available_advance_ignores_nonpositive(self):
        self.assertEqual(L.available_advance(self.POOL), Decimal('150.00'))

    def test_full_cycle_dispatch_then_cancel_restores_the_advance(self):
        """In-memory model of: two advances, a 120 dispatch, then its cancel."""
        pool = {a['advance_id']: Decimal(a['remaining']) for a in self.POOL}
        plan = L.allocate_oldest_first(self.POOL, '120')
        for adv_id, part in plan:
            pool[adv_id] -= part
        self.assertEqual(sum(pool.values()), Decimal('30.00'))
        for adv_id, part in plan:           # reversal gives back exactly what was taken
            pool[adv_id] += part
        self.assertEqual(sum(pool.values()), Decimal('150.00'))
        self.assertEqual(pool[1], Decimal('100.00'))


class Numbering(SimpleTestCase):

    def test_fiscal_year_follows_the_start_month(self):
        self.assertEqual(L.fiscal_year('2026-08-15', 7), 2026)
        self.assertEqual(L.fiscal_year('2027-03-01', 7), 2026)
        self.assertEqual(L.fiscal_year('2026-06-30', 7), 2025)
        self.assertEqual(L.fiscal_year('2026-06-30', 1), 2026)

    def test_voucher_number_format(self):
        self.assertEqual(L.format_voucher_no('SV', '08', 2026, 42), 'SV-08-2026-00042')


class UserMessagesNeverCarryFigures(SimpleTestCase):
    def test_no_digits_in_any_message_shown_to_dispatch_users(self):
        for msg in (L.user_message(blocked_customers=3), L.user_message(missing_price=True), L.user_message(error=True)):
            self.assertTrue(msg)
            self.assertIsNone(re.search(r'\d', msg), msg)
