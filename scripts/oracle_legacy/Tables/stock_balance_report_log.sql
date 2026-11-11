-- =====================================================================
-- Historical Stock Balance Report — audit-trail log table
-- Run ONCE against apxprod. Idempotent (guarded).
-- =====================================================================
-- Every time someone generates this report, a row is logged here purely
-- as audit metadata (who ran it, when, for which as-of date/division, and
-- under what doc number) — this table does NOT store the report's actual
-- balance figures, since those are always recalculated live from
-- wst_djn_stock_ledger at view/export time (so the report is always
-- accurate to the current ledger, never a stale snapshot).
-- =====================================================================
SET SERVEROUTPUT ON

DECLARE n NUMBER;
BEGIN
    SELECT COUNT(*) INTO n FROM user_tables WHERE table_name = 'WST_DJN_STOCK_BAL_REPORT_LOG';
    IF n = 0 THEN
        EXECUTE IMMEDIATE '
        CREATE TABLE wst_djn_stock_bal_report_log (
            report_id     NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            doc_no        VARCHAR2(30) UNIQUE NOT NULL,
            division      VARCHAR2(20),
            as_of_date    DATE NOT NULL,
            created_by    VARCHAR2(100),
            created_date  DATE DEFAULT SYSDATE
        )';
        DBMS_OUTPUT.PUT_LINE('Created wst_djn_stock_bal_report_log');
    ELSE
        DBMS_OUTPUT.PUT_LINE('Skip  wst_djn_stock_bal_report_log (exists)');
    END IF;
END;
/
