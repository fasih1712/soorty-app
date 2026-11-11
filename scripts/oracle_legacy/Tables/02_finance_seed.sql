-- =====================================================================
-- Soorty ERP - Finance Module - PHASE 1 seed data
-- Run AFTER 01_finance_schema.sql. Run once.
-- Everything here can be changed later from the Finance screens except
-- the locked system heads (code, type and system key stay fixed).
-- =====================================================================

-- ---- Chart of accounts: group heads first ----
INSERT INTO apxwastage.wst_djn_fin_account (account_code, account_name, account_type, is_posting, is_locked, created_by) VALUES ('1000', 'Assets',      'ASSET',     0, 1, 'SYSTEM');
INSERT INTO apxwastage.wst_djn_fin_account (account_code, account_name, account_type, is_posting, is_locked, created_by) VALUES ('2000', 'Liabilities', 'LIABILITY', 0, 1, 'SYSTEM');
INSERT INTO apxwastage.wst_djn_fin_account (account_code, account_name, account_type, is_posting, is_locked, created_by) VALUES ('3000', 'Equity',      'EQUITY',    0, 1, 'SYSTEM');
INSERT INTO apxwastage.wst_djn_fin_account (account_code, account_name, account_type, is_posting, is_locked, created_by) VALUES ('4000', 'Income',      'INCOME',    0, 1, 'SYSTEM');
INSERT INTO apxwastage.wst_djn_fin_account (account_code, account_name, account_type, is_posting, is_locked, created_by) VALUES ('5000', 'Expenses',    'EXPENSE',   0, 1, 'SYSTEM');

-- ---- Posting heads (system_key = what the posting rules refer to) ----
INSERT INTO apxwastage.wst_djn_fin_account (account_code, account_name, account_type, parent_id, is_posting, is_locked, system_key, created_by)
SELECT '1010', 'Cash In Hand',          'ASSET', account_id, 1, 1, 'CASH',       'SYSTEM' FROM apxwastage.wst_djn_fin_account WHERE account_code = '1000';
INSERT INTO apxwastage.wst_djn_fin_account (account_code, account_name, account_type, parent_id, is_posting, is_locked, system_key, created_by)
SELECT '1020', 'Bank',                  'ASSET', account_id, 1, 1, 'BANK',       'SYSTEM' FROM apxwastage.wst_djn_fin_account WHERE account_code = '1000';
INSERT INTO apxwastage.wst_djn_fin_account (account_code, account_name, account_type, parent_id, is_posting, is_locked, system_key, created_by)
SELECT '1100', 'Accounts Receivable',   'ASSET', account_id, 1, 1, 'RECEIVABLE', 'SYSTEM' FROM apxwastage.wst_djn_fin_account WHERE account_code = '1000';

INSERT INTO apxwastage.wst_djn_fin_account (account_code, account_name, account_type, parent_id, is_posting, is_locked, system_key, created_by)
SELECT '2100', 'Customer Advances',     'LIABILITY', account_id, 1, 1, 'CUSTOMER_ADVANCE', 'SYSTEM' FROM apxwastage.wst_djn_fin_account WHERE account_code = '2000';

INSERT INTO apxwastage.wst_djn_fin_account (account_code, account_name, account_type, parent_id, is_posting, is_locked, system_key, created_by)
SELECT '3100', 'Retained Earnings',     'EQUITY', account_id, 1, 1, 'RETAINED_EARNINGS', 'SYSTEM' FROM apxwastage.wst_djn_fin_account WHERE account_code = '3000';

INSERT INTO apxwastage.wst_djn_fin_account (account_code, account_name, account_type, parent_id, is_posting, is_locked, system_key, created_by)
SELECT '4100', 'Sales Income',          'INCOME', account_id, 1, 1, 'SALES_INCOME',  'SYSTEM' FROM apxwastage.wst_djn_fin_account WHERE account_code = '4000';
INSERT INTO apxwastage.wst_djn_fin_account (account_code, account_name, account_type, parent_id, is_posting, is_locked, system_key, created_by)
SELECT '4200', 'Sales Returns And Allowances', 'INCOME', account_id, 1, 1, 'SALES_RETURNS', 'SYSTEM' FROM apxwastage.wst_djn_fin_account WHERE account_code = '4000';

INSERT INTO apxwastage.wst_djn_fin_account (account_code, account_name, account_type, parent_id, is_posting, is_locked, system_key, created_by)
SELECT '5100', 'Discount Allowed',      'EXPENSE', account_id, 1, 1, 'DISCOUNT_ALLOWED', 'SYSTEM' FROM apxwastage.wst_djn_fin_account WHERE account_code = '5000';
INSERT INTO apxwastage.wst_djn_fin_account (account_code, account_name, account_type, parent_id, is_posting, is_locked, system_key, created_by)
SELECT '5200', 'Bad Debt Expense',      'EXPENSE', account_id, 1, 1, 'BAD_DEBT',         'SYSTEM' FROM apxwastage.wst_djn_fin_account WHERE account_code = '5000';
INSERT INTO apxwastage.wst_djn_fin_account (account_code, account_name, account_type, parent_id, is_posting, is_locked, system_key, created_by)
SELECT '5300', 'Rounding Difference',   'EXPENSE', account_id, 1, 1, 'ROUNDING',         'SYSTEM' FROM apxwastage.wst_djn_fin_account WHERE account_code = '5000';

-- ---- Settings (decisions D3-D12; all editable except base currency) ----
INSERT INTO apxwastage.wst_djn_fin_setting (setting_key, setting_value, value_type, options, description, is_editable) VALUES
 ('BASE_CURRENCY',          'PKR',          'TEXT',    NULL,                  'Base currency. Single currency only (decision D5).', 0);
INSERT INTO apxwastage.wst_djn_fin_setting (setting_key, setting_value, value_type, options, description) VALUES
 ('ROUNDING_TOLERANCE',     '1.00',         'DECIMAL', NULL,                  'Largest outstanding balance still treated as fully paid (PKR).');
INSERT INTO apxwastage.wst_djn_fin_setting (setting_key, setting_value, value_type, options, description) VALUES
 ('ALLOCATION_STRATEGY',    'OLDEST_FIRST', 'CHOICE',  'OLDEST_FIRST,MANUAL', 'How a receipt is applied to open sales by default.');
INSERT INTO apxwastage.wst_djn_fin_setting (setting_key, setting_value, value_type, options, description) VALUES
 ('AGEING_BUCKETS',         '30,60,90',     'INTLIST', NULL,                  'Upper day limits of the ageing buckets, ascending (e.g. 30,60,90 gives 0-30, 31-60, 61-90, 90+).');
INSERT INTO apxwastage.wst_djn_fin_setting (setting_key, setting_value, value_type, options, description) VALUES
 ('DEFAULT_CREDIT_DAYS',    '0',            'INT',     NULL,                  'Credit days given to a new customer unless set otherwise.');
INSERT INTO apxwastage.wst_djn_fin_setting (setting_key, setting_value, value_type, options, description) VALUES
 ('APPROVAL_ENABLED',       'N',            'YN',      NULL,                  'Maker-checker approval. Leave N while only one Super Admin exists.');
INSERT INTO apxwastage.wst_djn_fin_setting (setting_key, setting_value, value_type, options, description) VALUES
 ('APPROVAL_THRESHOLD',     '0',            'DECIMAL', NULL,                  'Vouchers above this amount need a second approver (when approval is enabled).');
INSERT INTO apxwastage.wst_djn_fin_setting (setting_key, setting_value, value_type, options, description) VALUES
 ('REASON_REQUIRED',        'Y',            'YN',      NULL,                  'Every adjustment and write-off needs a reason (recommended: Y).');
INSERT INTO apxwastage.wst_djn_fin_setting (setting_key, setting_value, value_type, options, description) VALUES
 ('TAX_ENABLED',            'N',            'YN',      NULL,                  'Tax / withholding lines on sales and receipts. Off until rules are provided (decision D5).');
INSERT INTO apxwastage.wst_djn_fin_setting (setting_key, setting_value, value_type, options, description) VALUES
 ('FISCAL_YEAR_START_MONTH','7',            'INT',     NULL,                  'First month of the financial year (1-12). 7 = July. Used for voucher number reset. Assumption: please confirm.');

-- ---- Voucher types ----
INSERT INTO apxwastage.wst_djn_fin_voucher_type (type_code, type_name, prefix, is_system) VALUES ('SV',  'Sales Voucher',          'SV',  1);
INSERT INTO apxwastage.wst_djn_fin_voucher_type (type_code, type_name, prefix, is_system) VALUES ('RV',  'Receipt Voucher',        'RV',  1);
INSERT INTO apxwastage.wst_djn_fin_voucher_type (type_code, type_name, prefix, is_system) VALUES ('AV',  'Adjustment Voucher',     'AV',  1);
INSERT INTO apxwastage.wst_djn_fin_voucher_type (type_code, type_name, prefix, is_system) VALUES ('CN',  'Credit Note',            'CN',  1);
INSERT INTO apxwastage.wst_djn_fin_voucher_type (type_code, type_name, prefix, is_system) VALUES ('DN',  'Debit Note',             'DN',  1);
INSERT INTO apxwastage.wst_djn_fin_voucher_type (type_code, type_name, prefix, is_system) VALUES ('RVS', 'Reversal Voucher',       'RVS', 1);
INSERT INTO apxwastage.wst_djn_fin_voucher_type (type_code, type_name, prefix, is_system) VALUES ('JV',  'Journal Voucher',        'JV',  0);
INSERT INTO apxwastage.wst_djn_fin_voucher_type (type_code, type_name, prefix, is_system) VALUES ('CV',  'Cash Voucher',           'CV',  0);
INSERT INTO apxwastage.wst_djn_fin_voucher_type (type_code, type_name, prefix, is_system) VALUES ('BV',  'Bank Voucher',           'BV',  0);

-- ---- Posting rules (account keys; reversals mirror the original entry) ----
INSERT INTO apxwastage.wst_djn_fin_posting_rule (event_code, description, debit_account_key, credit_account_key) VALUES ('SALE_POSTED',     'Sale posted',                          'RECEIVABLE',       'SALES_INCOME');
INSERT INTO apxwastage.wst_djn_fin_posting_rule (event_code, description, debit_account_key, credit_account_key) VALUES ('RECEIPT_CASH',    'Cash receipt against sales',           'CASH',             'RECEIVABLE');
INSERT INTO apxwastage.wst_djn_fin_posting_rule (event_code, description, debit_account_key, credit_account_key) VALUES ('RECEIPT_BANK',    'Bank receipt against sales',           'BANK',             'RECEIVABLE');
INSERT INTO apxwastage.wst_djn_fin_posting_rule (event_code, description, debit_account_key, credit_account_key) VALUES ('ADVANCE_CASH',    'Cash received in advance',             'CASH',             'CUSTOMER_ADVANCE');
INSERT INTO apxwastage.wst_djn_fin_posting_rule (event_code, description, debit_account_key, credit_account_key) VALUES ('ADVANCE_BANK',    'Bank receipt in advance',              'BANK',             'CUSTOMER_ADVANCE');
INSERT INTO apxwastage.wst_djn_fin_posting_rule (event_code, description, debit_account_key, credit_account_key) VALUES ('ADVANCE_APPLIED', 'Customer advance applied to a sale',  'CUSTOMER_ADVANCE', 'RECEIVABLE');
INSERT INTO apxwastage.wst_djn_fin_posting_rule (event_code, description, debit_account_key, credit_account_key) VALUES ('DISCOUNT',        'Discount allowed',                     'DISCOUNT_ALLOWED', 'RECEIVABLE');
INSERT INTO apxwastage.wst_djn_fin_posting_rule (event_code, description, debit_account_key, credit_account_key) VALUES ('WRITE_OFF',       'Write-off of uncollectable balance',   'BAD_DEBT',         'RECEIVABLE');
INSERT INTO apxwastage.wst_djn_fin_posting_rule (event_code, description, debit_account_key, credit_account_key) VALUES ('CREDIT_NOTE',     'Credit note (price / quantity fix)',   'SALES_RETURNS',    'RECEIVABLE');
INSERT INTO apxwastage.wst_djn_fin_posting_rule (event_code, description, debit_account_key, credit_account_key) VALUES ('DEBIT_NOTE',      'Debit note (extra charge)',            'RECEIVABLE',       'SALES_RETURNS');
INSERT INTO apxwastage.wst_djn_fin_posting_rule (event_code, description, debit_account_key, credit_account_key) VALUES ('ROUNDING',        'Rounding difference within tolerance', 'ROUNDING',         'RECEIVABLE');

COMMIT;

-- Quick check: expect 15 accounts, 10 settings, 9 voucher types, 11 posting rules
SELECT (SELECT COUNT(*) FROM apxwastage.wst_djn_fin_account)      AS accounts,
       (SELECT COUNT(*) FROM apxwastage.wst_djn_fin_setting)      AS settings,
       (SELECT COUNT(*) FROM apxwastage.wst_djn_fin_voucher_type) AS voucher_types,
       (SELECT COUNT(*) FROM apxwastage.wst_djn_fin_posting_rule) AS posting_rules
FROM dual;
