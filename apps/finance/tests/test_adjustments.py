"""
PHASE 3 GATE - adjustments (refund, credit / debit note, transfer, journal).

No database: the pure rules are tested directly, the engine with its SQL
helpers replaced, so what is asserted is the ACCOUNTING each tool produces.
"""
from decimal import Decimal
from unittest import mock

from django.test import SimpleTestCase

from apps.finance import ledger as L
from apps.finance import posting as P

D = Decimal


class PureRules(SimpleTestCase):

    def test_reason_is_mandatory_and_tidied(self):
        self.assertEqual(L.clean_reason('  bid   cancelled '), 'bid cancelled')
        for bad in (None, '', '  ', 'abc'):
            with self.assertRaises(L.FinanceRuleError):
                L.clean_reason(bad)

    def test_credit_note_cannot_exceed_the_sale(self):
        self.assertEqual(L.check_credit_note('1000', '0', '0', '1000'), D('1000.00'))
        with self.assertRaises(L.FinanceRuleError):
            L.check_credit_note('1000', '0', '0', '1000.01')
        with self.assertRaises(L.FinanceRuleError):                 # earlier credit counts
            L.check_credit_note('1000', '600', '0', '400.01')

    def test_debit_notes_make_room_for_more_credit(self):
        self.assertEqual(L.check_credit_note('1000', '1000', '200', '200'), D('200.00'))

    def test_credit_note_amount_must_be_positive(self):
        for bad in (0, '-5', 'x'):
            with self.assertRaises(L.FinanceRuleError):
                L.check_credit_note('1000', 0, 0, bad)

    def test_transfer_needs_two_different_customers(self):
        L.check_transfer(1, 2)
        for a, b in ((1, 1), (None, 2), (1, 0)):
            with self.assertRaises(L.FinanceRuleError):
                L.check_transfer(a, b)

    def test_journal_balanced_blank_rows_ignored(self):
        rows = [{'account_id': 1, 'system_key': 'CASH', 'debit': '0', 'credit': '250'},
                {'account_id': 2, 'system_key': 'ROUNDING', 'debit': '250', 'credit': '0'},
                {'account_id': 3, 'system_key': None, 'debit': '', 'credit': ''}]
        out = L.clean_journal(rows)
        self.assertEqual(len(out), 2)
        self.assertEqual(L.assert_balanced(out), D('250.00'))

    def test_journal_cannot_touch_the_customer_control_accounts(self):
        for key in ('CUSTOMER_ADVANCE', 'RECEIVABLE'):
            rows = [{'account_id': 1, 'system_key': key, 'debit': '10', 'credit': '0'},
                    {'account_id': 2, 'system_key': 'CASH', 'debit': '0', 'credit': '10'}]
            with self.assertRaises(L.FinanceRuleError):
                L.clean_journal(rows)

    def test_journal_must_balance_and_have_two_lines(self):
        with self.assertRaises(L.Unbalanced):
            L.clean_journal([{'account_id': 1, 'system_key': 'CASH', 'debit': '10', 'credit': '0'},
                             {'account_id': 2, 'system_key': 'BANK', 'debit': '0', 'credit': '9'}])
        with self.assertRaises(L.Unbalanced):
            L.clean_journal([{'account_id': 1, 'system_key': 'CASH', 'debit': '10', 'credit': '10'}])
        with self.assertRaises(L.Unbalanced):
            L.clean_journal([])


RCV = {'RECEIVABLE_ID': 7, 'PARTY_ID': 5, 'DIVISION': '08', 'SOURCE_ID': 'GP1', 'AMOUNT': D('1000.00'), 'STATUS': 'SETTLED'}
ACC = {'CREDIT_NOTE': (41, 11), 'DEBIT_NOTE': (11, 41), 'ADVANCE_APPLIED': (21, 11),
       'REFUND_CASH': (21, 31), 'REFUND_BANK': (21, 32)}      # 11 AR, 21 Advance, 31 Cash, 32 Bank, 41 Returns


class Harness:
    """Replaces every SQL helper with a recorder."""

    def __init__(self, test, credits=0, debits=0, rcv=RCV):
        self.vouchers, self.consumed, self.advances, self.adjustments = [], [], [], []
        patches = {
            '_adj_date': mock.Mock(side_effect=lambda cur, v: L.as_date(v)),
            '_lock_receivable': mock.Mock(return_value=rcv),
            '_note_totals': mock.Mock(return_value=(credits, debits)),
            'rule_accounts': mock.Mock(side_effect=lambda cur, code: ACC[code]),
            '_insert_adjustment': mock.Mock(side_effect=self._adj),
            'insert_voucher': mock.Mock(side_effect=self._vch),
            '_consume_advance': mock.Mock(side_effect=self._consume),
            '_insert_advance': mock.Mock(side_effect=self._adv),
            '_set_created_advance': mock.Mock(),
            '_party_exists': mock.Mock(),
            '_account_by_key': mock.Mock(return_value=21),
        }
        for name, m in patches.items():
            p = mock.patch.object(P, name, m)
            p.start(); test.addCleanup(p.stop)

    def _adj(self, cur, actor, adj_type, division, d, party, to_party, rcv, sref, mode, ref, amount, reason):
        self.adjustments.append((adj_type, party, to_party, amount, reason)); return len(self.adjustments)

    def _vch(self, cur, actor, vtype, division, d, party, narration, source_type, source_id, lines, **kw):
        L.assert_balanced(lines)
        self.vouchers.append((vtype, lines)); return 100 + len(self.vouchers)

    def _consume(self, cur, party, amount, adj_id):
        self.consumed.append((party, amount)); return []

    def _adv(self, cur, actor, party, division, d, kind, mode, ref, amount, voucher_id):
        self.advances.append((party, kind, amount)); return 900 + len(self.advances)

    def net(self, account_id, party=None):
        total = L.ZERO
        for _t, lines in self.vouchers:
            for l in lines:
                if l['account_id'] == account_id and (party is None or l.get('party_id') == party):
                    total += l['debit'] - l['credit']
        return total


CUR = object()


class RefundEngine(SimpleTestCase):

    def test_refund_debits_advance_credits_cash_and_consumes_the_advance(self):
        h = Harness(self)
        P.refund_advance(CUR, 'root', 5, '08', '2026-11-10', 'CASH', 'chq 1', '2500', 'bid cancelled')
        self.assertEqual(h.consumed, [(5, D('2500.00'))])
        self.assertEqual(h.net(21), D('2500.00'))        # Dr Customer Advances
        self.assertEqual(h.net(31), D('-2500.00'))       # Cr Cash
        self.assertEqual(h.vouchers[0][0], 'AV')

    def test_refund_by_bank_uses_the_bank_account(self):
        h = Harness(self)
        P.refund_advance(CUR, 'root', 5, '08', '2026-11-10', 'BANK', None, '10', 'customer left')
        self.assertEqual(h.net(32), D('-10.00'))

    def test_refund_needs_reason_mode_and_positive_amount(self):
        Harness(self)
        for args in (('CASH', '10', ''), ('XX', '10', 'long enough'), ('CASH', '0', 'long enough')):
            with self.subTest(args=args), self.assertRaises(L.FinanceRuleError):
                P.refund_advance(CUR, 'root', 5, '08', '2026-11-10', args[0], None, args[1], args[2])


class NoteEngine(SimpleTestCase):

    def test_credit_note_nets_receivable_to_zero_and_gives_the_customer_advance_back(self):
        h = Harness(self)
        P.credit_note(CUR, 'root', 7, '2026-11-10', '300', 'weighbridge correction')
        self.assertEqual([t for t, _ in h.vouchers], ['CN', 'AV'])
        self.assertEqual(h.net(41), D('300.00'))         # Dr Sales Returns
        self.assertEqual(h.net(11), D('0.00'))           # receivable nets out
        self.assertEqual(h.net(21), D('-300.00'))        # Cr Customer Advances
        self.assertEqual(h.advances, [(5, 'CREDIT', D('300.00'))])
        self.assertEqual(h.consumed, [])

    def test_credit_note_over_the_sale_is_refused_and_nothing_is_written(self):
        h = Harness(self, credits=D('900'))
        with self.assertRaises(L.FinanceRuleError):
            P.credit_note(CUR, 'root', 7, '2026-11-10', '100.01', 'too much')
        self.assertEqual((h.vouchers, h.advances, h.adjustments), ([], [], []))

    def test_debit_note_raises_the_sale_and_is_paid_from_advance_at_once(self):
        h = Harness(self)
        P.debit_note(CUR, 'root', 7, '2026-11-10', '150', 'rate was higher')
        self.assertEqual([t for t, _ in h.vouchers], ['DN', 'AV'])
        self.assertEqual(h.net(11), D('0.00'))           # Dr then Cr receivable
        self.assertEqual(h.net(41), D('-150.00'))        # Cr Sales Returns
        self.assertEqual(h.net(21), D('150.00'))         # Dr Customer Advances
        self.assertEqual(h.consumed, [(5, D('150.00'))])

    def test_debit_note_without_enough_advance_writes_nothing_more(self):
        h = Harness(self)
        P._consume_advance.side_effect = L.InsufficientAdvance('short')
        with self.assertRaises(L.InsufficientAdvance):
            P.debit_note(CUR, 'root', 7, '2026-11-10', '150', 'rate was higher')
        self.assertEqual(h.vouchers, [])                 # no voucher posted after the failed knock-off

    def test_notes_on_a_reversed_sale_are_refused(self):
        with mock.patch.object(P, '_adj_date', side_effect=lambda c, v: L.as_date(v)):
            cur = mock.Mock()
            cur.description = [(c,) for c in ('RECEIVABLE_ID', 'PARTY_ID', 'DIVISION', 'SOURCE_ID', 'AMOUNT', 'STATUS')]
            cur.fetchall.return_value = [(7, 5, '08', 'GP1', D('10'), 'REVERSED')]
            with self.assertRaises(L.FinanceRuleError):
                P._lock_receivable(cur, 7)


class TransferEngine(SimpleTestCase):

    def test_transfer_moves_advance_between_customers_on_one_account(self):
        h = Harness(self)
        P.transfer_advance(CUR, 'root', 5, 6, '08', '2026-11-10', '4000', 'paid under group company')
        self.assertEqual(h.consumed, [(5, D('4000.00'))])
        self.assertEqual(h.net(21, party=5), D('4000.00'))
        self.assertEqual(h.net(21, party=6), D('-4000.00'))
        self.assertEqual(h.net(21), D('0.00'))           # control account unchanged overall
        self.assertEqual(h.advances, [(6, 'TRANSFER', D('4000.00'))])

    def test_transfer_to_self_or_without_reason_is_refused(self):
        h = Harness(self)
        with self.assertRaises(L.FinanceRuleError):
            P.transfer_advance(CUR, 'root', 5, 5, '08', '2026-11-10', '10', 'same customer')
        with self.assertRaises(L.FinanceRuleError):
            P.transfer_advance(CUR, 'root', 5, 6, '08', '2026-11-10', '10', '')
        self.assertEqual(h.vouchers, [])


class JournalEngine(SimpleTestCase):

    def setUp(self):
        self.h = Harness(self)

    def cursor_with_keys(self, keys):
        cur = mock.Mock()
        results = iter(keys)
        cur.fetchone.side_effect = lambda: next(results)
        return cur

    def test_journal_posts_one_balanced_JV(self):
        cur = self.cursor_with_keys([('BANK_CHARGES', 1, 1), ('BANK', 1, 1)])
        rows = [{'account_id': 8, 'debit': '120', 'credit': '0'}, {'account_id': 9, 'debit': '0', 'credit': '120'}]
        P.journal_entry(cur, 'root', '08', '2026-11-10', 'monthly bank charges', rows)
        self.assertEqual([t for t, _ in self.h.vouchers], ['JV'])
        self.assertEqual(self.h.adjustments[0][3], D('120.00'))

    def test_journal_on_a_control_account_is_refused_before_anything_is_written(self):
        cur = self.cursor_with_keys([('CUSTOMER_ADVANCE', 1, 1), ('BANK', 1, 1)])
        rows = [{'account_id': 8, 'debit': '120', 'credit': '0'}, {'account_id': 9, 'debit': '0', 'credit': '120'}]
        with self.assertRaises(L.FinanceRuleError):
            P.journal_entry(cur, 'root', '08', '2026-11-10', 'sneaky correction', rows)
        self.assertEqual((self.h.vouchers, self.h.adjustments), ([], []))

    def test_journal_needs_narration_and_active_posting_accounts(self):
        rows = [{'account_id': 8, 'debit': '1', 'credit': '0'}, {'account_id': 9, 'debit': '0', 'credit': '1'}]
        with self.assertRaises(L.FinanceRuleError):
            P.journal_entry(self.cursor_with_keys([]), 'root', '08', '2026-11-10', '', rows)
        with self.assertRaises(L.FinanceRuleError):
            P.journal_entry(self.cursor_with_keys([(None, 0, 1), (None, 1, 1)]), 'root', '08', '2026-11-10', 'valid narration', rows)


class ScriptedCursor:
    """Answers SQL by substring so reverse_adjustment can be driven step by step."""
    def __init__(self, script):
        self.script, self.sql, self.description, self._rows = script, [], None, []
    def execute(self, sql, params=None):
        self.sql.append(sql); self.params = getattr(self, 'params', []) + [(sql, params)]
        for needle, (cols, rows) in self.script.items():
            if needle in sql:
                self.description = [(c,) for c in cols]; self._rows = list(rows); return
        self.description, self._rows = None, []
    def fetchall(self): return list(self._rows)
    def fetchone(self): return self._rows[0] if self._rows else None


class ReverseEngine(SimpleTestCase):
    ADJ = ('ADJUSTMENT_ID', 'ADJ_TYPE', 'STATUS', 'CREATED_ADVANCE_ID')

    def test_already_reversed_is_refused(self):
        cur = ScriptedCursor({'FROM wst_djn_fin_adjustment': (self.ADJ, [(1, 'REFUND', 'REVERSED', None)])})
        with self.assertRaises(L.FinanceRuleError):
            P.reverse_adjustment(cur, 'root', 1, 'posted by mistake')

    def test_reason_is_required(self):
        with self.assertRaises(L.FinanceRuleError):
            P.reverse_adjustment(ScriptedCursor({}), 'root', 1, '')

    def test_credit_whose_advance_was_already_used_cannot_be_reversed(self):
        cur = ScriptedCursor({
            'FROM wst_djn_fin_adjustment': (self.ADJ, [(1, 'CREDIT_NOTE', 'ACTIVE', 9)]),
            'FROM wst_djn_fin_advance WHERE ADVANCE_ID': (('AMOUNT', 'REMAINING', 'STATUS'), [(D('300'), D('120'), 'ACTIVE')])})
        with self.assertRaises(L.FinanceRuleError):
            P.reverse_adjustment(cur, 'root', 1, 'posted by mistake')
        self.assertFalse(any('UPDATE wst_djn_fin_adjustment' in s for s in cur.sql))

    def test_unused_credit_is_reversed_vouchers_included(self):
        cur = ScriptedCursor({
            'FROM wst_djn_fin_adjustment': (self.ADJ, [(1, 'CREDIT_NOTE', 'ACTIVE', 9)]),
            'FROM wst_djn_fin_advance WHERE ADVANCE_ID': (('AMOUNT', 'REMAINING', 'STATUS'), [(D('300'), D('300'), 'ACTIVE')]),
            'FROM wst_djn_fin_voucher': (('VOUCHER_ID',), [(101,), (102,)])})
        with mock.patch.object(P, 'reverse_voucher') as rv, mock.patch.object(P.audit, 'record_changes'):
            P.reverse_adjustment(cur, 'root', 1, 'posted by mistake')
        self.assertEqual([c.args[2] for c in rv.call_args_list], [101, 102])
        self.assertTrue(any("SET STATUS = 'REVERSED', REMAINING = 0" in s for s in cur.sql))
        self.assertTrue(any('UPDATE wst_djn_fin_adjustment' in s for s in cur.sql))

    def test_consumed_advance_is_given_back(self):
        cur = ScriptedCursor({
            'FROM wst_djn_fin_adjustment': (self.ADJ, [(1, 'REFUND', 'ACTIVE', None)]),
            'FROM wst_djn_fin_advance_use': (('ADVANCE_ID', 'AMOUNT'), [(4, D('2500'))]),
            'FROM wst_djn_fin_voucher': (('VOUCHER_ID',), [(101,)])})
        with mock.patch.object(P, 'reverse_voucher'), mock.patch.object(P.audit, 'record_changes'):
            P.reverse_adjustment(cur, 'root', 1, 'posted by mistake')
        give_back = [p for s, p in cur.params if 'REMAINING = REMAINING + :1' in s]
        self.assertEqual(give_back, [[D('2500'), 4]])
