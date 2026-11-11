-- =====================================================================
-- Gate Pass Module -- Add "Save Draft" support
--
-- Two changes to wst_djn_gatepass_header:
--   1. STATUS check constraint currently only allows 'Posted'/'Cancelled'
--      -- widen it to also allow 'Draft'.
--   2. New nullable VENDOR_ID column (FK to wst_djn_vendors), so a
--      Shipment-module draft can be reopened and its open Sales Order
--      lines re-loaded even before any line item has been added yet
--      (Gate Pass lines only carry a vendor indirectly, via SO_DOC_ID,
--      so with zero lines saved there'd otherwise be no way to know
--      which vendor the draft belongs to).
--
-- Run ONCE against apxprod. Idempotent (every ALTER is guarded) --
-- safe to re-run.
--
-- MUST be run before deploying the "Save Draft" code -- without this,
-- any attempt to save a Draft fails with ORA-02290 (check constraint
-- violated) on the STATUS column.
-- =====================================================================
SET SERVEROUTPUT ON

-- ---------------------------------------------------------------------
-- 1. Widen the STATUS check constraint to include 'Draft'
-- ---------------------------------------------------------------------
DECLARE n NUMBER;
BEGIN
    SELECT COUNT(*) INTO n FROM user_constraints
    WHERE table_name = 'WST_DJN_GATEPASS_HEADER' AND constraint_name = 'CK_GATEPASS_STATUS';
    IF n > 0 THEN
        EXECUTE IMMEDIATE 'ALTER TABLE wst_djn_gatepass_header DROP CONSTRAINT ck_gatepass_status';
        DBMS_OUTPUT.PUT_LINE('Dropped old ck_gatepass_status');
    END IF;

    EXECUTE IMMEDIATE '
        ALTER TABLE wst_djn_gatepass_header
        ADD CONSTRAINT ck_gatepass_status
        CHECK (STATUS IN (''Draft'',''Posted'',''Cancelled''))';
    DBMS_OUTPUT.PUT_LINE('Added ck_gatepass_status with Draft included');
END;
/

-- ---------------------------------------------------------------------
-- 2. VENDOR_ID column (nullable -- Transfer-module gate passes never
--    set it; Shipment-module ones set it as soon as a vendor is chosen,
--    independent of whether any line has been added yet)
-- ---------------------------------------------------------------------
DECLARE n NUMBER;
BEGIN
    SELECT COUNT(*) INTO n FROM user_tab_columns
    WHERE table_name = 'WST_DJN_GATEPASS_HEADER' AND column_name = 'VENDOR_ID';
    IF n = 0 THEN
        EXECUTE IMMEDIATE '
            ALTER TABLE wst_djn_gatepass_header
            ADD (VENDOR_ID NUMBER REFERENCES wst_djn_vendors(VENDOR_ID))';
        DBMS_OUTPUT.PUT_LINE('Added VENDOR_ID to wst_djn_gatepass_header');
    ELSE
        DBMS_OUTPUT.PUT_LINE('Skip   VENDOR_ID (already exists)');
    END IF;
END;
/
