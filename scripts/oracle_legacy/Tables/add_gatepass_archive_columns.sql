-- =====================================================================
-- Adds ARCHIVED_BY / ARCHIVED_DATE to WST_DJN_GATEPASS_HEADER, needed
-- for soft-deleting Cancelled Gate Passes (hidden from the list, but
-- the row, its lines, and every ledger entry it produced stay fully
-- intact for audit). A non-null ARCHIVED_DATE IS the "is archived"
-- flag -- no separate boolean column needed.
--
-- Safe to run more than once -- skips if the columns already exist.
-- Run as the DBA/APXPROD account, or as apxWastage if it owns this
-- table directly (matches whichever pattern the rest of this table's
-- columns were added under).
-- =====================================================================
SET SERVEROUTPUT ON SIZE UNLIMITED

DECLARE
BEGIN
  EXECUTE IMMEDIATE 'ALTER TABLE "WST_DJN_GATEPASS_HEADER" ADD "ARCHIVED_BY" VARCHAR2(50)';
  DBMS_OUTPUT.PUT_LINE('OK    WST_DJN_GATEPASS_HEADER.ARCHIVED_BY added');
EXCEPTION
  WHEN OTHERS THEN
    IF SQLCODE = -1430 THEN
      DBMS_OUTPUT.PUT_LINE('SKIP  WST_DJN_GATEPASS_HEADER.ARCHIVED_BY already exists');
    ELSE
      DBMS_OUTPUT.PUT_LINE('FAIL  WST_DJN_GATEPASS_HEADER.ARCHIVED_BY -- ' || SQLERRM);
    END IF;
END;
/

DECLARE
BEGIN
  EXECUTE IMMEDIATE 'ALTER TABLE "WST_DJN_GATEPASS_HEADER" ADD "ARCHIVED_DATE" DATE';
  DBMS_OUTPUT.PUT_LINE('OK    WST_DJN_GATEPASS_HEADER.ARCHIVED_DATE added');
EXCEPTION
  WHEN OTHERS THEN
    IF SQLCODE = -1430 THEN
      DBMS_OUTPUT.PUT_LINE('SKIP  WST_DJN_GATEPASS_HEADER.ARCHIVED_DATE already exists');
    ELSE
      DBMS_OUTPUT.PUT_LINE('FAIL  WST_DJN_GATEPASS_HEADER.ARCHIVED_DATE -- ' || SQLERRM);
    END IF;
END;
/

PROMPT Done -- scan for FAIL lines above (not DBMS_OUTPUT? re-run each statement bare, no wrapper, to see the real error).
