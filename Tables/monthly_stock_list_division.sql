-- =====================================================================
-- Monthly Stock List: add division tracking + auto-rolling support
-- Run ONCE against apxprod. Idempotent (guarded).
-- =====================================================================
-- wst_djn_monthly_stock_list predates the division-security feature and
-- has never tracked division at all. This adds it, matching the same
-- convention used everywhere else (VARCHAR2(20), default '08' for any
-- pre-existing rows), and adds a UNIQUE constraint on
-- (item_id, division, month_year) so the new auto-rolling upsert from
-- Stock Receiving can use a clean, atomic MERGE rather than a
-- select-then-insert-or-update race.
-- =====================================================================
SET SERVEROUTPUT ON

DECLARE n NUMBER;
BEGIN
    SELECT COUNT(*) INTO n FROM user_tab_columns
    WHERE table_name = 'WST_DJN_MONTHLY_STOCK_LIST' AND column_name = 'DIVISION';
    IF n = 0 THEN
        EXECUTE IMMEDIATE 'ALTER TABLE wst_djn_monthly_stock_list ADD (division VARCHAR2(20) DEFAULT ''08'')';
        DBMS_OUTPUT.PUT_LINE('Added DIVISION column to wst_djn_monthly_stock_list');
    ELSE
        DBMS_OUTPUT.PUT_LINE('Skip  DIVISION column (exists)');
    END IF;
END;
/

DECLARE n NUMBER;
BEGIN
    SELECT COUNT(*) INTO n FROM user_constraints
    WHERE table_name = 'WST_DJN_MONTHLY_STOCK_LIST' AND constraint_name = 'UQ_MONTHLY_STOCK_ITEM_DIV_MTH';
    IF n = 0 THEN
        EXECUTE IMMEDIATE 'ALTER TABLE wst_djn_monthly_stock_list
            ADD CONSTRAINT uq_monthly_stock_item_div_mth UNIQUE (item_id, division, month_year)
            ENABLE NOVALIDATE';
        DBMS_OUTPUT.PUT_LINE('Added uq_monthly_stock_item_div_mth');
    ELSE
        DBMS_OUTPUT.PUT_LINE('Skip  uq_monthly_stock_item_div_mth (exists)');
    END IF;
END;
/
