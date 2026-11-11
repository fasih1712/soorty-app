"""
PHASE 2 GATE - the Gate Pass link.

Proves, without Oracle:
  * switched off = completely inert (no database touched)
  * prepaid rule blocks short advance, exact cover passes, check fails CLOSED
  * regular users get NO figures back, ever
  * a finance failure never raises into the Gate Pass; it becomes a FAILED event
  * posting is atomic (one commit) and idempotent (a POSTED event is never re-posted)
  * only the Super Admin can retry; the system door is not open to anyone else
"""
import glob
import os
import re
from decimal import Decimal
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.test import SimpleTestCase, override_settings

from apps.finance import gateway as G
from apps.finance import ledger as L
from apps.finance import posting as P

User = get_user_model()
SHIP = {'module_type': 'Shipment', 'gate_pass_date': '2026-11-05'}
LINES = [{'so_line_id': 11, 'gatepass_qty': '100'}]


class FakeConn:
    def __init__(self):
        self.commits = self.rollbacks = 0
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def cursor(self): return FakeCursor()
    def commit(self): self.commits += 1
    def rollback(self): self.rollbacks += 1


class FakeCursor:
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def execute(self, *a, **k): pass


def conns():
    """P._connect replacement that remembers every connection it handed out."""
    made = []
    def factory(username=None):
        c = FakeConn(); made.append(c); return c
    return factory, made


@override_settings(FINANCE_HOOKS_ENABLED=True)
class PrepaidCheck(SimpleTestCase):

    def run_check(self, header=SHIP, lines=LINES, live='2026-11-01', priced=None, available='1000.00'):
        priced = priced if priced is not None else [{'customer_id': 5, 'qty': '100', 'unit_price': '5'}]  # needs 500.00
        factory, _ = conns()
        with mock.patch.object(P, '_connect', factory), \
             mock.patch.object(P, 'go_live_date', return_value=live), \
             mock.patch.object(G, '_resolve_lines', return_value=priced), \
             mock.patch.object(P, 'advance_available', return_value=Decimal(available)):
            return G.check_dispatch_allowed(header, lines, None)

    def test_enough_advance_passes(self):
        self.assertEqual(self.run_check(available='500.00'), (True, ''))

    def test_one_paisa_short_is_blocked(self):
        ok, msg = self.run_check(available='499.99')
        self.assertFalse(ok)
        self.assertTrue(msg)

    def test_message_never_contains_a_figure(self):
        ok, msg = self.run_check(available='3.00')
        self.assertFalse(ok)
        self.assertIsNone(re.search(r'\d', msg), msg)
        for needle in ('500', '499', '3.00', 'PKR', 'Rs'):
            self.assertNotIn(needle, msg)

    def test_before_cut_over_everything_is_allowed(self):
        self.assertEqual(self.run_check(header={'module_type': 'Shipment', 'gate_pass_date': '2026-10-31'}, available='0'), (True, ''))

    def test_transfers_are_never_checked(self):
        self.assertEqual(self.run_check(header={'module_type': 'Transfer', 'gate_pass_date': '2026-11-05'}, available='0'), (True, ''))

    def test_missing_price_blocks_with_a_safe_message(self):
        factory, _ = conns()
        with mock.patch.object(P, '_connect', factory), mock.patch.object(P, 'go_live_date', return_value='2026-11-01'), \
             mock.patch.object(G, '_resolve_lines', side_effect=L.MissingPrice('x')):
            ok, msg = G.check_dispatch_allowed(SHIP, LINES, None)
        self.assertFalse(ok)
        self.assertIsNone(re.search(r'\d', msg))

    def test_the_check_fails_closed_when_it_cannot_run(self):
        with mock.patch.object(P, '_connect', side_effect=RuntimeError('db down')):
            ok, msg = G.check_dispatch_allowed(SHIP, LINES, None)
        self.assertFalse(ok)
        self.assertTrue(msg)

    def test_each_customer_is_checked_separately(self):
        priced = [{'customer_id': 1, 'qty': 1, 'unit_price': 10}, {'customer_id': 2, 'qty': 1, 'unit_price': 10}]
        factory, _ = conns()
        with mock.patch.object(P, '_connect', factory), mock.patch.object(P, 'go_live_date', return_value='2026-11-01'), \
             mock.patch.object(G, '_resolve_lines', return_value=priced), \
             mock.patch.object(P, 'advance_available', side_effect=[Decimal('10'), Decimal('9.99')]):
            ok, _msg = G.check_dispatch_allowed(SHIP, LINES, None)
        self.assertFalse(ok)


@override_settings(FINANCE_HOOKS_ENABLED=False)
class SwitchedOff(SimpleTestCase):

    def test_off_means_inert_and_never_touches_the_database(self):
        with mock.patch.object(P, '_connect', side_effect=AssertionError('database reached')):
            self.assertEqual(G.check_dispatch_allowed(SHIP, LINES, None), (True, ''))
            self.assertEqual(G.on_gatepass_posted('GP1', None), 'OFF')
            self.assertEqual(G.on_gatepass_cancelled('GP1', None), 'OFF')

    def test_default_when_the_setting_is_absent_is_off(self):
        with override_settings():
            from django.conf import settings
            if hasattr(settings, 'FINANCE_HOOKS_ENABLED'):
                del settings.FINANCE_HOOKS_ENABLED
            self.assertFalse(G.hooks_enabled())


GP = {'GATE_PASS_ID': 'GP1', 'DIVISION': '08', 'MODULE_TYPE': 'Shipment', 'STATUS': 'Posted', 'GATE_PASS_DATE': '2026-11-05'}


class PostedWorker(SimpleTestCase):

    def run_posted(self, event=None, gp=GP, live='2026-11-01', post_side_effect=None, totals=None):
        factory, made = conns()
        post = mock.Mock(side_effect=post_side_effect, return_value=[1, 2])
        write = mock.Mock()
        totals = totals or {5: Decimal('500.00')}
        with mock.patch.object(P, '_connect', factory), \
             mock.patch.object(P, 'event_row', return_value=event), \
             mock.patch.object(G, '_load_gate_pass', return_value=(gp, LINES)), \
             mock.patch.object(P, 'go_live_date', return_value=live), \
             mock.patch.object(G, '_resolve_lines', return_value=[]), \
             mock.patch.object(L, 'group_dispatch_by_customer', return_value=totals), \
             mock.patch.object(P, 'post_dispatch_for_customer', post), \
             mock.patch.object(P, 'write_event', write):
            result = G._process_posted('GP1', 'tester')
        return result, post, write, made

    def test_success_posts_once_and_commits_once(self):
        (status, _msg), post, write, made = self.run_posted()
        self.assertEqual(status, 'POSTED')
        post.assert_called_once()
        self.assertEqual(write.call_args[0][5], 'POSTED')
        self.assertEqual((made[0].commits, made[0].rollbacks), (1, 0))

    def test_already_posted_is_never_posted_twice(self):
        (status, _), post, write, _ = self.run_posted(event={'STATUS': 'POSTED'})
        self.assertEqual(status, 'POSTED')
        post.assert_not_called()
        write.assert_not_called()

    def test_failure_rolls_back_and_is_recorded_as_failed_on_a_fresh_connection(self):
        (status, msg), _post, write, made = self.run_posted(post_side_effect=L.InsufficientAdvance('not enough'))
        self.assertEqual(status, 'FAILED')
        self.assertIn('not enough', msg)
        self.assertEqual(made[0].rollbacks, 1)
        self.assertEqual(made[0].commits, 0)
        self.assertEqual(len(made), 2)                       # second connection for the FAILED row
        self.assertEqual(made[1].commits, 1)
        self.assertEqual(write.call_args[0][5], 'FAILED')

    def test_transfers_and_pre_go_live_are_skipped_not_posted(self):
        transfer = dict(GP, MODULE_TYPE='Transfer')
        (s1, _), post1, _, _ = self.run_posted(gp=transfer)
        (s2, _), post2, _, _ = self.run_posted(live='2026-12-01')
        self.assertEqual((s1, s2), ('SKIPPED', 'SKIPPED'))
        post1.assert_not_called(); post2.assert_not_called()

    def test_a_gate_pass_that_is_no_longer_posted_is_skipped(self):
        (status, _), post, _, _ = self.run_posted(gp=dict(GP, STATUS='Cancelled'))
        self.assertEqual(status, 'SKIPPED')
        post.assert_not_called()

    def test_multi_customer_dispatch_posts_each_customer_in_one_transaction(self):
        (status, _), post, _, made = self.run_posted(totals={1: Decimal('10.00'), 2: Decimal('20.00')})
        self.assertEqual(status, 'POSTED')
        self.assertEqual(post.call_count, 2)
        self.assertEqual(made[0].commits, 1)

    def test_second_customer_failing_undoes_the_first(self):
        (status, _), post, _, made = self.run_posted(totals={1: Decimal('10.00'), 2: Decimal('20.00')},
                                                      post_side_effect=[[1, 2], L.InsufficientAdvance('x')])
        self.assertEqual(status, 'FAILED')
        self.assertEqual(made[0].commits, 0)
        self.assertEqual(made[0].rollbacks, 1)


class CancelledWorker(SimpleTestCase):

    def run_cancel(self, orig=None, done=None, gp_status='Cancelled', reverse_error=None):
        factory, made = conns()
        reverse = mock.Mock(return_value=[9], side_effect=reverse_error)
        write = mock.Mock()
        def event_row(cur, etype, sid, for_update=False):
            return done if etype == L.EVENT_GP_CANCELLED else orig
        with mock.patch.object(P, '_connect', factory), \
             mock.patch.object(P, 'event_row', side_effect=event_row), \
             mock.patch.object(G, '_load_gate_pass', return_value=(dict(GP, STATUS=gp_status), [])), \
             mock.patch.object(P, 'reverse_dispatch', reverse), \
             mock.patch.object(P, 'write_event', write):
            result = G._process_cancelled('GP1', 'tester')
        return result, reverse, write, made

    def test_posted_sale_is_reversed(self):
        (status, _), reverse, write, made = self.run_cancel(orig={'STATUS': 'POSTED'})
        self.assertEqual(status, 'POSTED')
        reverse.assert_called_once()
        self.assertEqual(made[0].commits, 1)

    def test_nothing_posted_means_nothing_to_reverse(self):
        for orig in (None, {'STATUS': 'FAILED'}, {'STATUS': 'SKIPPED'}):
            with self.subTest(orig=orig):
                (status, _), reverse, _, _ = self.run_cancel(orig=orig)
                self.assertEqual(status, 'SKIPPED')
                reverse.assert_not_called()

    def test_already_handled_is_idempotent(self):
        (status, _), reverse, write, _ = self.run_cancel(orig={'STATUS': 'POSTED'}, done={'STATUS': 'POSTED'})
        self.assertEqual(status, 'POSTED')
        reverse.assert_not_called(); write.assert_not_called()

    def test_reversal_failure_becomes_a_failed_event_and_rolls_back(self):
        (status, _), _r, write, made = self.run_cancel(orig={'STATUS': 'POSTED'}, reverse_error=L.FinanceRuleError('period locked'))
        self.assertEqual(status, 'FAILED')
        self.assertEqual(made[0].rollbacks, 1)
        self.assertEqual(write.call_args[0][5], 'FAILED')

    def test_a_gate_pass_that_is_not_cancelled_is_refused(self):
        (status, _), reverse, _, _ = self.run_cancel(orig={'STATUS': 'POSTED'}, gp_status='Posted')
        self.assertEqual(status, 'FAILED')
        reverse.assert_not_called()


@override_settings(FINANCE_HOOKS_ENABLED=True)
class HooksNeverRaise(SimpleTestCase):

    def test_posted_hook_swallows_everything(self):
        with mock.patch.object(G, '_process_posted', side_effect=RuntimeError('boom')):
            self.assertEqual(G.on_gatepass_posted('GP1', None), 'FAILED')

    def test_cancel_hook_swallows_everything(self):
        with mock.patch.object(G, '_process_cancelled', side_effect=RuntimeError('boom')):
            self.assertEqual(G.on_gatepass_cancelled('GP1', None), 'FAILED')

    def test_workers_survive_a_dead_database(self):
        with mock.patch.object(P, '_connect', side_effect=RuntimeError('db down')):
            self.assertEqual(G._process_posted('GP1', 'x')[0], 'FAILED')
            self.assertEqual(G._process_cancelled('GP1', 'x')[0], 'FAILED')

    def test_hooks_return_status_words_only(self):
        with mock.patch.object(G, '_process_posted', return_value=('POSTED', 'Posted for 1 customer(s).')):
            out = G.on_gatepass_posted('GP1', None)
        self.assertIsInstance(out, str)
        self.assertIn(out, {'OFF', 'POSTED', 'FAILED', 'SKIPPED'})


class OnlyTheSuperAdminHoldsTheKeys(SimpleTestCase):

    def admin(self): return User(username='root', is_superuser=True, is_active=True)
    def regular(self): return User(username='bob', is_active=True)

    def test_retry_is_super_admin_only(self):
        with mock.patch.object(G, '_process_posted', side_effect=AssertionError('reached')):
            for user in (self.regular(), User(username='s', is_staff=True, is_active=True),
                         User(username='x', is_superuser=True, is_active=False)):
                with self.assertRaises(PermissionDenied):
                    G.retry_event(user, L.EVENT_GP_POSTED, 'GP1')

    def test_super_admin_retry_runs_the_same_worker(self):
        with mock.patch.object(G, '_process_posted', return_value=('POSTED', 'ok')) as w:
            self.assertEqual(G.retry_event(self.admin(), L.EVENT_GP_POSTED, 'GP1'), ('POSTED', 'ok'))
        w.assert_called_once_with('GP1', 'root')

    def test_unknown_event_type_is_refused(self):
        self.assertEqual(G.retry_event(self.admin(), 'DROP_TABLE', 'x')[0], 'FAILED')

    def test_posting_functions_guard_refuses_outsiders_and_system_context_is_scoped(self):
        with self.assertRaises(PermissionDenied):
            P._guard_any(self.regular())
        with self.assertRaises(PermissionDenied):
            P._guard_any(None)
        P._guard_any(self.admin())
        with P.system_context():
            P._guard_any(None)                       # the Gate Pass hook
        with self.assertRaises(PermissionDenied):    # context does not leak
            P._guard_any(self.regular())

    def test_only_the_gateway_may_open_the_system_door(self):
        base = os.path.dirname(os.path.dirname(__file__))
        offenders = []
        for path in glob.glob(os.path.join(base, '*.py')):
            name = os.path.basename(path)
            if name in ('gateway.py', 'posting.py'):
                continue
            with open(path, encoding='utf-8') as fh:
                if 'system_context' in fh.read():
                    offenders.append(name)
        self.assertEqual(offenders, [], f'system_context used outside gateway.py: {offenders}')

    def test_no_screen_imports_the_posting_engine_directly_except_through_data_layer(self):
        base = os.path.dirname(os.path.dirname(__file__))
        for name in ('views.py', 'urls.py', 'middleware.py', 'decorators.py'):
            with open(os.path.join(base, name), encoding='utf-8') as fh:
                src = fh.read()
            self.assertNotIn('import posting', src, name)
            self.assertNotIn('from .posting', src, name)
