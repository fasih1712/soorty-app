-- =====================================================================
-- Gate Pass Module -- Phase 3: Sales Header STATUS vocabulary change
--
-- Repurposes wst_djn_sales_header.STATUS from DRAFT/POSTED/CANCELLED to
-- DRAFT/OPEN/CLOSED/CANCELLED, per sign-off on Option 1:
--   DRAFT  -> no line has shipped anything
--   OPEN   -> at least one line has SHIPPED_QTY > 0, but not every line
--             is fully Closed yet
--   CLOSED -> every line on the document is Closed
--   CANCELLED unchanged
--
-- This applies to BOTH parallel posting paths that exist right now
-- (Ship & Post, kept live as a bridge, and Gate Pass) so the whole app
-- reads one consistent vocabulary regardless of which path a given
-- document went through -- not two disconnected ones.
--
-- Run ONCE, AFTER gatepass_schema.sql and sales_line_gatepass_tracking.sql.
-- Idempotent.
-- =====================================================================
SET SERVEROUTPUT ON

-- ---------------------------------------------------------------------
-- 1. Migrate existing data FIRST, before the constraint changes, so an
--    old 'POSTED' row is never left violating the new allowed-value set
--    even for an instant.
-- ---------------------------------------------------------------------
UPDATE wst_djn_sales_header SET STATUS = 'CLOSED' WHERE STATUS = 'POSTED';
COMMIT;

-- ---------------------------------------------------------------------
-- 2. Replace the CHECK constraint (if one exists) with the new allowed
--    value set. Guarded: only touches a constraint actually named this,
--    and only if it doesn't already reflect the new set.
-- ---------------------------------------------------------------------
DECLARE
    n NUMBER;
    existing_condition VARCHAR2(4000);
BEGIN
    SELECT COUNT(*) INTO n FROM user_constraints
    WHERE table_name = 'WST_DJN_SALES_HEADER' AND constraint_name = 'CK_SALES_HEADER_STATUS';

    IF n > 0 THEN
        EXECUTE IMMEDIATE 'ALTER TABLE wst_djn_sales_header DROP CONSTRAINT ck_sales_header_status';
        DBMS_OUTPUT.PUT_LINE('Dropped existing ck_sales_header_status');
    END IF;

    EXECUTE IMMEDIATE q'[ALTER TABLE wst_djn_sales_header ADD CONSTRAINT ck_sales_header_status
        CHECK (STATUS IN ('DRAFT','OPEN','CLOSED','CANCELLED'))]';
    DBMS_OUTPUT.PUT_LINE('Added ck_sales_header_status (DRAFT/OPEN/CLOSED/CANCELLED)');
EXCEPTION
    WHEN OTHERS THEN
        IF SQLCODE = -2264 THEN  -- constraint name already in use, already correct
            DBMS_OUTPUT.PUT_LINE('Skip ck_sales_header_status (already exists)');
        ELSE
            RAISE;
        END IF;
END;
/
