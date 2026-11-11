-- =====================================================================
-- Non-negative stock balance constraints (defense-in-depth)
-- Run ONCE against apxprod. Idempotent (guarded).
-- =====================================================================
-- The application already prevents this at the Sales posting layer
-- (post_sales_document() checks available stock BEFORE writing anything,
-- and the whole document is rejected — not partially posted — if any
-- item would go negative). These constraints are a second, database-level
-- backstop: if a future code path ever bypasses that check, Oracle itself
-- refuses the write rather than silently allowing negative stock.
--
-- Added as ENABLE NOVALIDATE rather than a fully validated constraint:
-- this does NOT retroactively check existing rows (so it can't fail here
-- if any historical row somehow already has a negative value) — it only
-- enforces the rule on NEW inserts/updates from this point forward.
-- =====================================================================
SET SERVEROUTPUT ON

DECLARE n NUMBER;
BEGIN
    SELECT COUNT(*) INTO n FROM user_constraints
    WHERE table_name = 'WST_DJN_ITEM_BALANCE' AND constraint_name = 'CK_ITEM_BALANCE_NONNEG';
    IF n = 0 THEN
        EXECUTE IMMEDIATE 'ALTER TABLE wst_djn_item_balance
            ADD CONSTRAINT ck_item_balance_nonneg CHECK (BALANCE >= 0) ENABLE NOVALIDATE';
        DBMS_OUTPUT.PUT_LINE('Added ck_item_balance_nonneg on wst_djn_item_balance');
    ELSE
        DBMS_OUTPUT.PUT_LINE('Skip  ck_item_balance_nonneg (exists)');
    END IF;
END;
/

DECLARE n NUMBER;
BEGIN
    SELECT COUNT(*) INTO n FROM user_constraints
    WHERE table_name = 'WST_DJN_STOCK_LEDGER' AND constraint_name = 'CK_STOCK_LEDGER_NONNEG';
    IF n = 0 THEN
        EXECUTE IMMEDIATE 'ALTER TABLE wst_djn_stock_ledger
            ADD CONSTRAINT ck_stock_ledger_nonneg CHECK (BALANCE >= 0) ENABLE NOVALIDATE';
        DBMS_OUTPUT.PUT_LINE('Added ck_stock_ledger_nonneg on wst_djn_stock_ledger');
    ELSE
        DBMS_OUTPUT.PUT_LINE('Skip  ck_stock_ledger_nonneg (exists)');
    END IF;
END;
/
