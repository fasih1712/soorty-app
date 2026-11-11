-- =====================================================================
-- Soorty ERP - Finance Module - PHASE 2 seed. Run AFTER 03. Run once.
-- =====================================================================
-- Opening balance contra account (the other side of an opening advance)
INSERT INTO apxwastage.wst_djn_fin_account (account_code, account_name, account_type, parent_id, is_posting, is_locked, system_key, created_by)
SELECT '3200', 'Opening Balance Equity', 'EQUITY', account_id, 1, 1, 'OPENING_EQUITY', 'SYSTEM'
FROM apxwastage.wst_djn_fin_account WHERE account_code = '3000';

INSERT INTO apxwastage.wst_djn_fin_posting_rule (event_code, description, debit_account_key, credit_account_key)
VALUES ('OPENING_ADVANCE', 'Opening customer advance loaded at cut-over', 'OPENING_EQUITY', 'CUSTOMER_ADVANCE');

-- Cut-over and the prepaid policy
INSERT INTO apxwastage.wst_djn_fin_setting (setting_key, setting_value, value_type, options, description, is_editable) VALUES
 ('FINANCE_GO_LIVE_DATE', '2026-11-01', 'TEXT', NULL, 'Cut-over date (a 1st of a month, YYYY-MM-DD). Dispatches dated before it are never posted to finance. Cannot be changed once anything has been posted.', 1);
INSERT INTO apxwastage.wst_djn_fin_setting (setting_key, setting_value, value_type, options, description, is_editable) VALUES
 ('PREPAID_ONLY', 'Y', 'YN', NULL, 'Policy: no dispatch without enough customer advance, and every sale is knocked off against advance at dispatch. Fixed policy.', 0);

COMMIT;

-- Expect: accounts 16, settings 12, voucher types 9, posting rules 12
SELECT (SELECT COUNT(*) FROM apxwastage.wst_djn_fin_account)      AS accounts,
       (SELECT COUNT(*) FROM apxwastage.wst_djn_fin_setting)      AS settings,
       (SELECT COUNT(*) FROM apxwastage.wst_djn_fin_voucher_type) AS voucher_types,
       (SELECT COUNT(*) FROM apxwastage.wst_djn_fin_posting_rule) AS posting_rules
FROM dual;
