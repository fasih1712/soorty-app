-- =====================================================================
-- Monthly Stock Snapshot (Stock Operations -> Monthly Stock List)
-- Run ONCE against apxprod. Idempotent (guarded).
-- =====================================================================
-- Distinct from wst_djn_stock_bal_report_log (the ad-hoc Reports-module
-- report, which always recalculates live and is left completely
-- untouched by this feature). This is a PERMANENT, IMMUTABLE monthly
-- archive: once generated for a (division, month), the header + line
-- items are frozen and stored -- never silently recalculated again.
--
-- ITEM_NAME and UOM are frozen as plain text on the line, not looked up
-- live from wst_djn_items at display time -- if an item's master data
-- ever changes later, a past snapshot must still show what was true at
-- the moment it was generated, matching "immutable historical record".
-- =====================================================================
SET SERVEROUTPUT ON

DECLARE n NUMBER;
BEGIN
    SELECT COUNT(*) INTO n FROM user_tables WHERE table_name = 'WST_DJN_MSL_SNAPSHOT_HEADER';
    IF n = 0 THEN
        EXECUTE IMMEDIATE '
        CREATE TABLE wst_djn_msl_snapshot_header (
            snapshot_id    NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            doc_no         VARCHAR2(30) UNIQUE NOT NULL,
            division       VARCHAR2(20) NOT NULL,
            target_month   DATE NOT NULL,          -- first-of-month, e.g. 2026-07-01
            cutoff_date    DATE NOT NULL,           -- Transaction Cut-off Date
            created_by     VARCHAR2(100),
            created_date   DATE DEFAULT SYSDATE,
            CONSTRAINT uq_msl_snapshot_div_month UNIQUE (division, target_month)
        )';
        DBMS_OUTPUT.PUT_LINE('Created wst_djn_msl_snapshot_header');
    ELSE
        DBMS_OUTPUT.PUT_LINE('Skip  wst_djn_msl_snapshot_header (exists)');
    END IF;
END;
/

DECLARE n NUMBER;
BEGIN
    SELECT COUNT(*) INTO n FROM user_tables WHERE table_name = 'WST_DJN_MSL_SNAPSHOT_LINE';
    IF n = 0 THEN
        EXECUTE IMMEDIATE '
        CREATE TABLE wst_djn_msl_snapshot_line (
            line_id         NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            snapshot_id     NUMBER NOT NULL REFERENCES wst_djn_msl_snapshot_header(snapshot_id),
            item_id         NUMBER REFERENCES wst_djn_items(item_id),
            item_code       VARCHAR2(20),
            item_name       VARCHAR2(200),          -- frozen at generation time
            uom             VARCHAR2(20),            -- frozen at generation time
            closing_balance NUMBER(15,3)
        )';
        DBMS_OUTPUT.PUT_LINE('Created wst_djn_msl_snapshot_line');
    ELSE
        DBMS_OUTPUT.PUT_LINE('Skip  wst_djn_msl_snapshot_line (exists)');
    END IF;
END;
/
