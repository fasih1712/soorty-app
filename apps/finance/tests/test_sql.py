"""
PHASE 2 GATE - SQL hygiene (reads the .sql files; no database).

Catches the two mistakes that already cost one 500 error: a table name in
Python that the scripts do not create, and an identifier Oracle would
reject (over 30 characters).
"""
import glob
import os
import re

from django.test import SimpleTestCase

BASE = os.path.dirname(os.path.dirname(__file__))
SQL_DIR = os.path.normpath(os.path.join(BASE, '..', '..', 'sql'))


def _read(path):
    with open(path, encoding='utf-8') as fh:
        return fh.read()


def _active_sql(text):
    """SQL with comment lines removed (the reset blocks are commented)."""
    return '\n'.join(l for l in text.splitlines() if not l.strip().startswith('--'))


class SchemaScripts(SimpleTestCase):

    def setUp(self):
        self.files = sorted(glob.glob(os.path.join(SQL_DIR, '0[1345]_*schema.sql')))
        if len(self.files) < 2:
            self.skipTest('sql folder not found next to apps/ (running from an installed copy)')
        self.schema = '\n'.join(_active_sql(_read(p)) for p in self.files)

    def test_every_object_is_named_wst_djn_fin_and_fits_oracle(self):
        names = re.findall(r'(?:TABLE|INDEX|TRIGGER|CONSTRAINT)\s+(?:apxwastage\.)?(wst_djn_\w+)', self.schema, flags=re.I)
        self.assertGreater(len(names), 40)
        for n in names:
            with self.subTest(name=n):
                self.assertTrue(n.lower().startswith('wst_djn_fin_'), n)
                self.assertLessEqual(len(n), 30, n)

    def test_tables_created_by_the_scripts(self):
        tables = set(t.lower() for t in re.findall(r'CREATE TABLE\s+apxwastage\.(wst_djn_\w+)', self.schema, flags=re.I))
        expected = {'account', 'setting', 'period', 'sequence', 'voucher_type', 'posting_rule', 'audit_log',
                    'voucher', 'voucher_line', 'advance', 'receivable', 'allocation', 'event_log',
                    'adjustment', 'advance_use'}
        self.assertEqual(tables, {f'wst_djn_fin_{e}' for e in expected})

    def test_python_only_names_tables_the_scripts_create(self):
        created = set(t.lower() for t in re.findall(r'CREATE TABLE\s+apxwastage\.(wst_djn_\w+)', self.schema, flags=re.I))
        for name in ('data.py', 'posting.py', 'gateway.py', 'audit.py'):
            src = _read(os.path.join(BASE, name))
            for table in set(re.findall(r'\b(wst_djn_fin_\w+)', src)):
                if table.endswith('_'):
                    continue
                with self.subTest(file=name, table=table):
                    self.assertIn(table.lower(), created)

    def test_no_old_unprefixed_fin_tables_in_python(self):
        for name in ('data.py', 'posting.py', 'gateway.py', 'audit.py'):
            src = _read(os.path.join(BASE, name))
            self.assertIsNone(re.search(r'(?:FROM|INTO|UPDATE|JOIN)\s+fin_', src, flags=re.I), name)

    def test_posted_rows_are_protected_by_triggers(self):
        for trig in ('wst_djn_fin_vln_lock', 'wst_djn_fin_vch_lock', 'wst_djn_fin_adv_nodel',
                     'wst_djn_fin_rcv_nodel', 'wst_djn_fin_alc_nodel', 'wst_djn_fin_audit_lock',
                     'wst_djn_fin_adj_nodel', 'wst_djn_fin_use_nodel'):
            self.assertIn(trig, self.schema)

    def test_voucher_lines_are_never_updated_or_deleted_by_code(self):
        for name in ('data.py', 'posting.py', 'gateway.py'):
            src = _read(os.path.join(BASE, name))
            self.assertIsNone(re.search(r'(UPDATE|DELETE\s+FROM)\s+wst_djn_fin_voucher_line', src, flags=re.I), name)
            self.assertIsNone(re.search(r'DELETE\s+FROM\s+wst_djn_fin_(voucher|advance|receivable|allocation|audit_log)\b', src, flags=re.I), name)


class SeedScripts(SimpleTestCase):

    def test_phase_two_seed_adds_what_the_code_needs(self):
        path = os.path.join(SQL_DIR, '04_finance_phase2_seed.sql')
        if not os.path.exists(path):
            self.skipTest('sql folder not found')
        seed = _read(path)
        for needle in ('OPENING_EQUITY', 'OPENING_ADVANCE', 'FINANCE_GO_LIVE_DATE', '2026-11-01', 'PREPAID_ONLY'):
            self.assertIn(needle, seed)

    def test_every_rule_the_engine_asks_for_is_seeded(self):
        seeds = ''.join(_read(os.path.join(SQL_DIR, n)) for n in
                        ('02_finance_seed.sql', '04_finance_phase2_seed.sql', '06_finance_phase3_seed.sql'))
        src = _read(os.path.join(BASE, 'posting.py')) + _read(os.path.join(BASE, 'gateway.py'))
        for rule in set(re.findall(r"rule_accounts\(cur, '(\w+)'", src)) | {'ADVANCE_CASH', 'ADVANCE_BANK', 'REFUND_CASH', 'REFUND_BANK'}:
            self.assertIn(f"'{rule}'", seeds, rule)
        for vt in ('SV', 'RV', 'AV', 'JV', 'RVS'):
            self.assertIn(f"'{vt}'", seeds)


class BindNames(SimpleTestCase):
    """':by' is an Oracle reserved word and raises ORA-01745 at run time - a
    mistake no mock-based test can see. Block every reserved word as a bind."""
    RESERVED = set(('ACCESS ADD ALL ALTER AND ANY AS ASC AUDIT BETWEEN BY CHAR CHECK CLUSTER COLUMN COMMENT COMPRESS CONNECT '
                    'CREATE CURRENT DATE DECIMAL DEFAULT DELETE DESC DISTINCT DROP ELSE EXCLUSIVE EXISTS FILE FLOAT FOR FROM '
                    'GRANT GROUP HAVING IDENTIFIED IMMEDIATE IN INCREMENT INDEX INITIAL INSERT INTEGER INTERSECT INTO IS LEVEL '
                    'LIKE LOCK LONG MAXEXTENTS MINUS MLSLABEL MODE MODIFY NOAUDIT NOCOMPRESS NOT NOWAIT NULL NUMBER OF OFFLINE '
                    'ON ONLINE OPTION OR ORDER PCTFREE PRIOR PRIVILEGES PUBLIC RAW RENAME RESOURCE REVOKE ROW ROWID ROWNUM ROWS '
                    'SELECT SESSION SET SHARE SIZE SMALLINT START SUCCESSFUL SYNONYM SYSDATE TABLE THEN TO TRIGGER UID UNION '
                    'UNIQUE UPDATE USER VALIDATE VALUES VARCHAR VARCHAR2 VIEW WHENEVER WHERE WITH').split())

    def test_no_bind_variable_is_an_oracle_reserved_word(self):
        for name in ('data.py', 'posting.py', 'gateway.py', 'audit.py'):
            src = _read(os.path.join(BASE, name))
            for bind in set(re.findall(r"(?<![:\w]):([A-Za-z_]\w*)", src)):
                with self.subTest(file=name, bind=bind):
                    self.assertNotIn(bind.upper(), self.RESERVED)


class ColumnNames(SimpleTestCase):
    """A column named after an Oracle reserved word (e.g. MODE) makes CREATE TABLE fail."""

    def test_no_column_uses_a_reserved_word(self):
        files = sorted(glob.glob(os.path.join(SQL_DIR, '0[1345]_*schema.sql')))
        if not files:
            self.skipTest('sql folder not found')
        schema = '\n'.join(_active_sql(_read(p)) for p in files)
        reserved = BindNames.RESERVED
        for block in re.findall(r'CREATE TABLE\s+\S+\s*\((.*?)\n\);', schema, flags=re.S | re.I):
            for line in block.splitlines():
                m = re.match(r'\s+(\w+)\s+(NUMBER|VARCHAR2|TIMESTAMP|DATE)\b', line, flags=re.I)
                if m:
                    with self.subTest(column=m.group(1)):
                        self.assertNotIn(m.group(1).upper(), reserved)
