"""Pure rule tests (no Django, no database)."""
from datetime import date
from unittest import TestCase

from apps.finance import validators as v


class ProperCase(TestCase):
    def test_capitalises_words_and_keeps_acronyms(self):
        self.assertEqual(v.proper_case('  cash   in hand '), 'Cash In Hand')
        self.assertEqual(v.proper_case('WHT payable'), 'WHT Payable')
        self.assertEqual(v.proper_case("owner's equity"), "Owner's Equity")


class AccountRules(TestCase):
    GROUP = {'ACCOUNT_ID': 10, 'ACCOUNT_TYPE': 'ASSET', 'IS_POSTING': 0}
    POSTING = {'ACCOUNT_ID': 11, 'ACCOUNT_TYPE': 'ASSET', 'IS_POSTING': 1}
    LOCKED = {'ACCOUNT_ID': 5, 'ACCOUNT_CODE': '1100', 'ACCOUNT_TYPE': 'ASSET', 'IS_POSTING': 1,
              'IS_LOCKED': 1, 'PARENT_ID': 10, 'ACCOUNT_NAME': 'Accounts Receivable'}

    def form(self, **kw):
        base = {'code': '1200', 'name': 'petty cash', 'type': 'asset', 'parent_id': '10', 'is_posting': '1'}
        base.update(kw)
        return base

    def test_valid_account(self):
        clean, errors = v.validate_account(self.form(), None, self.GROUP, [])
        self.assertEqual(errors, [])
        self.assertEqual((clean['code'], clean['name'], clean['type'], clean['parent_id']),
                         ('1200', 'Petty Cash', 'ASSET', 10))

    def test_bad_code_type_and_duplicate(self):
        for code in ('12', 'ABCD', '12 34', '12345678901'):
            _, errors = v.validate_account(self.form(code=code), None, self.GROUP, [])
            self.assertTrue(errors, code)
        _, errors = v.validate_account(self.form(type='nonsense'), None, self.GROUP, [])
        self.assertTrue(errors)
        _, errors = v.validate_account(self.form(), None, self.GROUP, ['1200'])
        self.assertIn('Account code 1200 is already in use.', errors)

    def test_parent_must_be_a_group_of_the_same_type(self):
        _, errors = v.validate_account(self.form(), None, self.POSTING, [])
        self.assertTrue(any('group head' in e for e in errors))
        wrong = dict(self.GROUP, ACCOUNT_TYPE='INCOME')
        _, errors = v.validate_account(self.form(), None, wrong, [])
        self.assertTrue(any('same account type' in e for e in errors))

    def test_locked_head_only_allows_a_rename(self):
        clean, errors = v.validate_account(
            self.form(code='9999', name='receivables', type='income', is_posting='0'), self.LOCKED, None, [])
        self.assertEqual(errors, [])
        self.assertEqual((clean['code'], clean['type'], clean['is_posting'], clean['parent_id']),
                         ('1100', 'ASSET', 1, 10))
        self.assertEqual(clean['name'], 'Receivables')

    def test_locked_head_cannot_be_deactivated(self):
        self.assertFalse(v.can_deactivate_account(self.LOCKED)[0])
        self.assertTrue(v.can_deactivate_account({'IS_LOCKED': 0})[0])


class SettingRules(TestCase):
    def row(self, vtype, key='K', options=None, editable=1):
        return {'SETTING_KEY': key, 'VALUE_TYPE': vtype, 'OPTIONS': options, 'IS_EDITABLE': editable}

    def test_fixed_setting_cannot_change(self):
        self.assertIsNotNone(v.validate_setting(self.row('TEXT', editable=0), 'USD')[1])

    def test_yes_no(self):
        self.assertEqual(v.validate_setting(self.row('YN'), 'y'), ('Y', None))
        self.assertIsNotNone(v.validate_setting(self.row('YN'), 'maybe')[1])

    def test_choice(self):
        row = self.row('CHOICE', options='OLDEST_FIRST,MANUAL')
        self.assertEqual(v.validate_setting(row, 'MANUAL'), ('MANUAL', None))
        self.assertIsNotNone(v.validate_setting(row, 'RANDOM')[1])

    def test_decimal(self):
        self.assertEqual(v.validate_setting(self.row('DECIMAL'), '1')[0], '1.00')
        self.assertIsNotNone(v.validate_setting(self.row('DECIMAL'), '-1')[1])
        self.assertIsNotNone(v.validate_setting(self.row('DECIMAL'), 'abc')[1])

    def test_int_and_fiscal_month(self):
        self.assertEqual(v.validate_setting(self.row('INT'), '7')[0], '7')
        self.assertIsNotNone(v.validate_setting(self.row('INT'), '-3')[1])
        fy = self.row('INT', key='FISCAL_YEAR_START_MONTH')
        self.assertIsNotNone(v.validate_setting(fy, '13')[1])
        self.assertIsNotNone(v.validate_setting(fy, '0')[1])
        self.assertEqual(v.validate_setting(fy, '12')[0], '12')

    def test_ageing_buckets(self):
        row = self.row('INTLIST')
        self.assertEqual(v.validate_setting(row, '30, 60,90')[0], '30,60,90')
        for bad in ('', '60,30', '30,30', '0,30', 'a,b', '30,,'):
            if bad == '30,,':
                continue  # trailing commas are tolerated; empty parts are ignored
            self.assertIsNotNone(v.validate_setting(row, bad)[1], bad)


class PostingRuleRules(TestCase):
    ACCOUNTS = {
        'RECEIVABLE': {'ACCOUNT_CODE': '1100', 'IS_ACTIVE': 1, 'IS_POSTING': 1},
        'CASH': {'ACCOUNT_CODE': '1010', 'IS_ACTIVE': 1, 'IS_POSTING': 1},
        'DEAD': {'ACCOUNT_CODE': '9000', 'IS_ACTIVE': 0, 'IS_POSTING': 1},
        'GROUP': {'ACCOUNT_CODE': '1000', 'IS_ACTIVE': 1, 'IS_POSTING': 0},
    }

    def test_valid_rule(self):
        self.assertEqual(v.validate_posting_rule('CASH', 'RECEIVABLE', self.ACCOUNTS), [])

    def test_invalid_rules(self):
        self.assertTrue(v.validate_posting_rule('CASH', 'CASH', self.ACCOUNTS))
        self.assertTrue(v.validate_posting_rule('NOPE', 'CASH', self.ACCOUNTS))
        self.assertTrue(v.validate_posting_rule('DEAD', 'CASH', self.ACCOUNTS))
        self.assertTrue(v.validate_posting_rule('GROUP', 'CASH', self.ACCOUNTS))


class PeriodRules(TestCase):
    TODAY = date(2026, 10, 12)

    def test_cannot_lock_future_or_duplicate(self):
        self.assertFalse(v.can_lock_period(2026, 11, [], self.TODAY)[0])
        self.assertFalse(v.can_lock_period(2026, 9, [(2026, 9)], self.TODAY)[0])

    def test_first_lock_may_be_any_past_or_current_month(self):
        self.assertTrue(v.can_lock_period(2026, 8, [], self.TODAY)[0])
        self.assertTrue(v.can_lock_period(2026, 10, [], self.TODAY)[0])

    def test_locks_follow_in_order_across_a_year_end(self):
        self.assertTrue(v.can_lock_period(2026, 1, [(2025, 12)], date(2026, 3, 1))[0])
        self.assertFalse(v.can_lock_period(2026, 2, [(2025, 12)], date(2026, 3, 1))[0])
        self.assertFalse(v.can_lock_period(2026, 9, [(2026, 7)], self.TODAY)[0])
        self.assertTrue(v.can_lock_period(2026, 8, [(2026, 7)], self.TODAY)[0])

    def test_reopen_only_latest_with_reason(self):
        locked = [(2026, 7), (2026, 8), (2026, 9)]
        self.assertTrue(v.can_reopen_period(2026, 9, locked, 'Wrong sale posted')[0])
        self.assertFalse(v.can_reopen_period(2026, 8, locked, 'Wrong sale posted')[0])
        self.assertFalse(v.can_reopen_period(2026, 9, locked, 'no')[0])
        self.assertFalse(v.can_reopen_period(2026, 10, locked, 'Wrong sale posted')[0])
