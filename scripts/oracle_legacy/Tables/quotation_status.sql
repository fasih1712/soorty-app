-- =====================================================================
-- Quotation Status (Open/Locked) for the Comparison -> Sales routing flow
-- Run ONCE against apxprod. Idempotent (guarded).
-- =====================================================================
SET SERVEROUTPUT ON

DECLARE n NUMBER;
BEGIN
    SELECT COUNT(*) INTO n FROM user_tab_columns
    WHERE table_name = 'WST_DJN_QUOTATION_HEADER' AND column_name = 'STATUS';
    IF n = 0 THEN
        EXECUTE IMMEDIATE 'ALTER TABLE wst_djn_quotation_header ADD (status VARCHAR2(20) DEFAULT ''Open'')';
        EXECUTE IMMEDIATE 'UPDATE wst_djn_quotation_header SET status = ''Open'' WHERE status IS NULL';
        DBMS_OUTPUT.PUT_LINE('Added STATUS to wst_djn_quotation_header (defaulted existing rows to Open)');
    ELSE
        DBMS_OUTPUT.PUT_LINE('Skip  STATUS column (exists)');
    END IF;
END;
/
