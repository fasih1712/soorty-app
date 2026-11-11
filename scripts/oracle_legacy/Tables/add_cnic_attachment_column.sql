-- =====================================================================
-- Adds CNIC_ATTACHMENT_PATH to WST_DJN_VENDORS -- a separate column
-- from the existing CNIC field. CNIC already stores the ID NUMBER
-- (text); this new column stores the saved file path of the uploaded
-- CNIC document/photo, nothing else touches or overlaps with it.
--
-- Safe to run more than once -- skips if the column already exists.
-- Run as the DBA/APXPROD account (same one used for every other
-- ALTER TABLE in this project), or as apxWastage if it already has
-- ALTER privilege on APXPROD's tables (unconfirmed either way -- if
-- this fails with ORA-01031, that's the reason, same as before).
-- =====================================================================
SET SERVEROUTPUT ON SIZE UNLIMITED

DECLARE
BEGIN
  EXECUTE IMMEDIATE 'ALTER TABLE "APXPROD"."WST_DJN_VENDORS" ADD "CNIC_ATTACHMENT_PATH" VARCHAR2(500)';
  DBMS_OUTPUT.PUT_LINE('OK    WST_DJN_VENDORS.CNIC_ATTACHMENT_PATH added');
EXCEPTION
  WHEN OTHERS THEN
    IF SQLCODE = -1430 THEN  -- column already exists
      DBMS_OUTPUT.PUT_LINE('SKIP  WST_DJN_VENDORS.CNIC_ATTACHMENT_PATH already exists');
    ELSE
      DBMS_OUTPUT.PUT_LINE('FAIL  WST_DJN_VENDORS.CNIC_ATTACHMENT_PATH -- ' || SQLERRM);
    END IF;
END;
/

PROMPT Done.
