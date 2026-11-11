-- =====================================================================
-- Smart Structured Item Code: schema changes
-- Run ONCE against apxprod. Idempotent (guarded).
-- =====================================================================
SET SERVEROUTPUT ON

DECLARE n NUMBER;
BEGIN
    SELECT COUNT(*) INTO n FROM user_tab_columns
    WHERE table_name = 'WST_DJN_CATEGORIES' AND column_name = 'PREFIX';
    IF n = 0 THEN
        EXECUTE IMMEDIATE 'ALTER TABLE wst_djn_categories ADD (prefix VARCHAR2(5))';
        DBMS_OUTPUT.PUT_LINE('Added PREFIX to wst_djn_categories');
    ELSE
        DBMS_OUTPUT.PUT_LINE('Skip  PREFIX column (exists)');
    END IF;
END;
/

DECLARE n NUMBER;
BEGIN
    SELECT COUNT(*) INTO n FROM user_tab_columns
    WHERE table_name = 'WST_DJN_ITEMS' AND column_name = 'ITEM_CODE';
    IF n = 0 THEN
        EXECUTE IMMEDIATE 'ALTER TABLE wst_djn_items ADD (item_code VARCHAR2(30))';
        DBMS_OUTPUT.PUT_LINE('Added ITEM_CODE to wst_djn_items');
    ELSE
        DBMS_OUTPUT.PUT_LINE('Skip  ITEM_CODE column (exists)');
    END IF;
END;
/

-- Unique index -- added ENABLE NOVALIDATE-equivalent via a plain unique
-- index rather than a constraint, so it doesn't fail if any pre-existing
-- rows briefly share a NULL item_code before the backfill command runs.
DECLARE n NUMBER;
BEGIN
    SELECT COUNT(*) INTO n FROM user_indexes WHERE index_name = 'UX_WST_DJN_ITEMS_CODE';
    IF n = 0 THEN
        EXECUTE IMMEDIATE 'CREATE UNIQUE INDEX ux_wst_djn_items_code ON wst_djn_items(item_code)';
        DBMS_OUTPUT.PUT_LINE('Created ux_wst_djn_items_code');
    ELSE
        DBMS_OUTPUT.PUT_LINE('Skip  ux_wst_djn_items_code (exists)');
    END IF;
END;
/

DECLARE n NUMBER;
BEGIN
    SELECT COUNT(*) INTO n FROM user_indexes WHERE index_name = 'UX_WST_DJN_CATEGORIES_PREFIX';
    IF n = 0 THEN
        EXECUTE IMMEDIATE 'CREATE UNIQUE INDEX ux_wst_djn_categories_prefix ON wst_djn_categories(prefix)';
        DBMS_OUTPUT.PUT_LINE('Created ux_wst_djn_categories_prefix');
    ELSE
        DBMS_OUTPUT.PUT_LINE('Skip  ux_wst_djn_categories_prefix (exists)');
    END IF;
END;
/
