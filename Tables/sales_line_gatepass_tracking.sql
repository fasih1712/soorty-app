-- =====================================================================
-- Gate Pass Module -- Phase 1: SHIPPED_QTY / LINE_STATUS on Sales Lines
-- FRD Section 2B/2C.
--
-- LINE_STATUS values: 'Entered' (nothing shipped) / 'Partial' /
-- 'Closed' (fully shipped) -- exactly the FRD's table in Section 2C.
--
-- Run ONCE, AFTER gatepass_schema.sql. Idempotent.
-- =====================================================================
SET SERVEROUTPUT ON

DECLARE n NUMBER;
BEGIN
    SELECT COUNT(*) INTO n FROM user_tab_columns
    WHERE table_name = 'WST_DJN_SALES_LINE' AND column_name = 'SHIPPED_QTY';
    IF n = 0 THEN
        EXECUTE IMMEDIATE 'ALTER TABLE wst_djn_sales_line ADD SHIPPED_QTY NUMBER DEFAULT 0';
        DBMS_OUTPUT.PUT_LINE('Added wst_djn_sales_line.SHIPPED_QTY');
    ELSE
        DBMS_OUTPUT.PUT_LINE('Skip  wst_djn_sales_line.SHIPPED_QTY (exists)');
    END IF;
END;
/

DECLARE n NUMBER;
BEGIN
    SELECT COUNT(*) INTO n FROM user_tab_columns
    WHERE table_name = 'WST_DJN_SALES_LINE' AND column_name = 'LINE_STATUS';
    IF n = 0 THEN
        EXECUTE IMMEDIATE q'[ALTER TABLE wst_djn_sales_line ADD LINE_STATUS VARCHAR2(20)
            DEFAULT 'Entered' CONSTRAINT ck_sales_line_status
            CHECK (LINE_STATUS IN ('Entered','Partial','Closed'))]';
        DBMS_OUTPUT.PUT_LINE('Added wst_djn_sales_line.LINE_STATUS');
    ELSE
        DBMS_OUTPUT.PUT_LINE('Skip  wst_djn_sales_line.LINE_STATUS (exists)');
    END IF;
END;
/

-- ---------------------------------------------------------------------
-- Backfill for lines that already exist on this live system.
--
-- The OLD "Ship & Post" model posts a whole Sales document atomically --
-- every line ships in full, all at once, or the document stays DRAFT.
-- There is no partial-per-line concept under the old model. So:
--
--   header.STATUS = 'POSTED'    -> every one of its lines was fully
--                                   shipped for its full quantity.
--                                   SHIPPED_QTY = QUANTITY, Closed.
--   header.STATUS = 'DRAFT'
--     or 'CANCELLED'            -> nothing has shipped (a cancelled
--                                   document's stock movement was
--                                   already reversed). SHIPPED_QTY = 0,
--                                   Entered.
--
-- Without this, every already-fulfilled line on this live system would
-- show as blank/Entered/editable the moment this migration runs --
-- which would be wrong, and would let someone edit a line that's
-- actually already been dispatched to a customer.
-- ---------------------------------------------------------------------
UPDATE wst_djn_sales_line sl
SET (SHIPPED_QTY, LINE_STATUS) = (
    SELECT sl.QUANTITY, 'Closed' FROM wst_djn_sales_header sh
    WHERE sh.DOC_ID = sl.DOC_ID AND sh.STATUS = 'POSTED'
)
WHERE EXISTS (
    SELECT 1 FROM wst_djn_sales_header sh
    WHERE sh.DOC_ID = sl.DOC_ID AND sh.STATUS = 'POSTED'
);

UPDATE wst_djn_sales_line sl
SET SHIPPED_QTY = 0, LINE_STATUS = 'Entered'
WHERE EXISTS (
    SELECT 1 FROM wst_djn_sales_header sh
    WHERE sh.DOC_ID = sl.DOC_ID AND sh.STATUS IN ('DRAFT','CANCELLED')
)
AND (SHIPPED_QTY IS NULL OR LINE_STATUS IS NULL);

COMMIT;
