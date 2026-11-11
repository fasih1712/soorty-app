-- =====================================================================
-- One-time data correction: strip the accidental double "WI-" prefix
-- from any wst_djn_quotation_line rows saved before this bug was fixed.
-- Safe to run multiple times (idempotent) -- only touches rows that
-- still have the double prefix.
-- =====================================================================
SET SERVEROUTPUT ON

DECLARE
    n NUMBER;
BEGIN
    UPDATE wst_djn_quotation_line
    SET item_code = SUBSTR(item_code, 4)   -- strip the leading redundant 'WI-'
    WHERE item_code LIKE 'WI-WI-%';
    n := SQL%ROWCOUNT;
    DBMS_OUTPUT.PUT_LINE(n || ' quotation line(s) corrected.');
    COMMIT;
END;
/
