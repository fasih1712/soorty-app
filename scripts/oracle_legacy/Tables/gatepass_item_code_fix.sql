-- =====================================================================
-- Gate Pass Module -- correction to the already-approved schema
--
-- The FRD's line grid (Section 5A) calls for Prefix, Item Code, AND
-- Item Description as three SEPARATE columns. The original
-- gatepass_schema.sql only snapshotted ITEM_PREFIX and ITEM_DESCRIPTION
-- -- ITEM_CODE (the item master's full generated code, e.g.
-- "BW-SZ-001", distinct from just its prefix) was missed. Caught this
-- while building the actual grid display and finding there was nowhere
-- to put a genuinely separate "Item Code" value.
--
-- Run AFTER gatepass_schema.sql. Idempotent. If gatepass_schema.sql
-- hasn't been run yet, run it FIRST, then this.
-- =====================================================================
SET SERVEROUTPUT ON

DECLARE n NUMBER;
BEGIN
    SELECT COUNT(*) INTO n FROM user_tab_columns
    WHERE table_name = 'WST_DJN_GATEPASS_LINE' AND column_name = 'ITEM_CODE';
    IF n = 0 THEN
        EXECUTE IMMEDIATE 'ALTER TABLE wst_djn_gatepass_line ADD ITEM_CODE VARCHAR2(30)';
        DBMS_OUTPUT.PUT_LINE('Added wst_djn_gatepass_line.ITEM_CODE');
    ELSE
        DBMS_OUTPUT.PUT_LINE('Skip  wst_djn_gatepass_line.ITEM_CODE (exists)');
    END IF;
END;
/
