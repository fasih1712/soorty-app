-- Mirrors wst_djn_stock_bal_report_log exactly, for the new Monthly
-- Stock Report. Doesn't store the actual figures -- those are always
-- (re)computed live from the ledger/receiving/gate pass data, same
-- philosophy as the existing Stock Balance Report. This table only
-- logs who generated the report, when, and under what document number.
--
-- Safe to run more than once.

SET SERVEROUTPUT ON SIZE UNLIMITED

DECLARE
BEGIN
  EXECUTE IMMEDIATE q'[
    CREATE TABLE wst_djn_monthly_stock_report_log (
      LOG_ID           NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
      DOC_NO           VARCHAR2(30) NOT NULL UNIQUE,
      DIVISION         VARCHAR2(20),
      TARGET_MONTH     DATE NOT NULL,
      CREATED_BY       VARCHAR2(50),
      CREATED_DATE     DATE DEFAULT SYSDATE
    )
  ]';
  DBMS_OUTPUT.PUT_LINE('OK    wst_djn_monthly_stock_report_log created');
EXCEPTION
  WHEN OTHERS THEN
    IF SQLCODE = -955 THEN
      DBMS_OUTPUT.PUT_LINE('SKIP  wst_djn_monthly_stock_report_log already exists');
    ELSE
      DBMS_OUTPUT.PUT_LINE('FAIL  wst_djn_monthly_stock_report_log -- ' || SQLERRM);
    END IF;
END;
/
