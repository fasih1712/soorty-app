-- =====================================================================
-- Soorty ERP — Wastage module: Audit-column migration
-- =====================================================================
-- Run this ONCE against the apxprod schema.
--
-- WHY: The wastage module has no Django ORM models (all access is raw
-- Oracle SQL), so there is no `manage.py migrate` path for schema
-- changes. This script is the equivalent "migration".
--
-- The audit columns + triggers ALREADY EXIST on the tables that work
-- today (categories, departments, vendors, items). This script brings
-- the remaining target tables to the same standard so the four audit
-- fields (Created By / Created Date / Last Updated By / Last Updated
-- Date) populate and display in their Eye-View modals.
--
-- The application sets the DB session identifier via
--   DBMS_SESSION.SET_IDENTIFIER(<django username>)
-- (see get_connection() in oracle_data.py). The triggers below read it
-- back with SYS_CONTEXT('USERENV','CLIENT_IDENTIFIER'). When a write
-- happens outside the app, the identifier is 'DIRECT_DB_EDIT'.
--
-- Safe to re-run: column adds are guarded, triggers use CREATE OR REPLACE.
--
-- IMPORTANT — wst_djn_sales:
--   That table already has a NUMERIC column CREATED_BY (a creator user-id
--   used by insert_sale). That collides with the VARCHAR audit CREATED_BY
--   used elsewhere, so this script does NOT add/overwrite CREATED_BY on
--   sales. It adds only CREATED_DATE, LAST_UPDATED_BY, LAST_UPDATED_DATE.
--   The sales Eye-View therefore shows Created Date / Last Updated By /
--   Last Updated Date, and leaves "Created By" blank. See the note at the
--   bottom for the two options to get a username there too.
-- =====================================================================

SET SERVEROUTPUT ON

-- ---------------------------------------------------------------------
-- Helper: add a column only if it does not already exist
-- ---------------------------------------------------------------------
DECLARE
    PROCEDURE add_col(p_table IN VARCHAR2, p_col IN VARCHAR2, p_def IN VARCHAR2) IS
        n NUMBER;
    BEGIN
        SELECT COUNT(*) INTO n
        FROM   user_tab_columns
        WHERE  table_name  = UPPER(p_table)
        AND    column_name = UPPER(p_col);
        IF n = 0 THEN
            EXECUTE IMMEDIATE 'ALTER TABLE ' || p_table || ' ADD (' || p_col || ' ' || p_def || ')';
            DBMS_OUTPUT.PUT_LINE('Added ' || p_table || '.' || p_col);
        ELSE
            DBMS_OUTPUT.PUT_LINE('Skip  ' || p_table || '.' || p_col || ' (already exists)');
        END IF;
    END;
BEGIN
    -- Stock Receiving --------------------------------------------------
    add_col('wst_djn_stock_receiving', 'CREATED_BY',        'VARCHAR2(100)');
    add_col('wst_djn_stock_receiving', 'CREATED_DATE',      'DATE');
    add_col('wst_djn_stock_receiving', 'LAST_UPDATED_BY',   'VARCHAR2(100)');
    add_col('wst_djn_stock_receiving', 'LAST_UPDATED_DATE', 'DATE');

    -- Group Type (master) ---------------------------------------------
    add_col('wst_djn_user_generic_group_type', 'CREATED_BY',        'VARCHAR2(100)');
    add_col('wst_djn_user_generic_group_type', 'CREATED_DATE',      'DATE');
    add_col('wst_djn_user_generic_group_type', 'LAST_UPDATED_BY',   'VARCHAR2(100)');
    add_col('wst_djn_user_generic_group_type', 'LAST_UPDATED_DATE', 'DATE');

    -- Generic Group (child) -------------------------------------------
    add_col('wst_djn_user_generic_group', 'CREATED_BY',        'VARCHAR2(100)');
    add_col('wst_djn_user_generic_group', 'CREATED_DATE',      'DATE');
    add_col('wst_djn_user_generic_group', 'LAST_UPDATED_BY',   'VARCHAR2(100)');
    add_col('wst_djn_user_generic_group', 'LAST_UPDATED_DATE', 'DATE');

    -- Sales (NO varchar CREATED_BY — numeric column already occupies it)
    add_col('wst_djn_sales', 'CREATED_DATE',      'DATE');
    add_col('wst_djn_sales', 'LAST_UPDATED_BY',   'VARCHAR2(100)');
    add_col('wst_djn_sales', 'LAST_UPDATED_DATE', 'DATE');
END;
/

-- ---------------------------------------------------------------------
-- Triggers. CLIENT_IDENTIFIER is set by the app per request.
-- Pattern mirrors the existing categories/vendors/items triggers.
-- ---------------------------------------------------------------------

CREATE OR REPLACE TRIGGER wst_djn_receiving_audit_trg
BEFORE INSERT OR UPDATE ON wst_djn_stock_receiving
FOR EACH ROW
DECLARE
    v_user VARCHAR2(100) := NVL(SYS_CONTEXT('USERENV','CLIENT_IDENTIFIER'), 'DIRECT_DB_EDIT');
BEGIN
    IF INSERTING THEN
        :NEW.CREATED_BY        := v_user;
        :NEW.CREATED_DATE      := SYSDATE;
        :NEW.LAST_UPDATED_BY   := v_user;
        :NEW.LAST_UPDATED_DATE := SYSDATE;
    ELSIF UPDATING THEN
        :NEW.CREATED_BY        := :OLD.CREATED_BY;
        :NEW.CREATED_DATE      := :OLD.CREATED_DATE;
        :NEW.LAST_UPDATED_BY   := v_user;
        :NEW.LAST_UPDATED_DATE := SYSDATE;
    END IF;
END;
/

CREATE OR REPLACE TRIGGER wst_djn_grouptype_audit_trg
BEFORE INSERT OR UPDATE ON wst_djn_user_generic_group_type
FOR EACH ROW
DECLARE
    v_user VARCHAR2(100) := NVL(SYS_CONTEXT('USERENV','CLIENT_IDENTIFIER'), 'DIRECT_DB_EDIT');
BEGIN
    IF INSERTING THEN
        :NEW.CREATED_BY        := v_user;
        :NEW.CREATED_DATE      := SYSDATE;
        :NEW.LAST_UPDATED_BY   := v_user;
        :NEW.LAST_UPDATED_DATE := SYSDATE;
    ELSIF UPDATING THEN
        :NEW.CREATED_BY        := :OLD.CREATED_BY;
        :NEW.CREATED_DATE      := :OLD.CREATED_DATE;
        :NEW.LAST_UPDATED_BY   := v_user;
        :NEW.LAST_UPDATED_DATE := SYSDATE;
    END IF;
END;
/

CREATE OR REPLACE TRIGGER wst_djn_genericgroup_audit_trg
BEFORE INSERT OR UPDATE ON wst_djn_user_generic_group
FOR EACH ROW
DECLARE
    v_user VARCHAR2(100) := NVL(SYS_CONTEXT('USERENV','CLIENT_IDENTIFIER'), 'DIRECT_DB_EDIT');
BEGIN
    IF INSERTING THEN
        :NEW.CREATED_BY        := v_user;
        :NEW.CREATED_DATE      := SYSDATE;
        :NEW.LAST_UPDATED_BY   := v_user;
        :NEW.LAST_UPDATED_DATE := SYSDATE;
    ELSIF UPDATING THEN
        :NEW.CREATED_BY        := :OLD.CREATED_BY;
        :NEW.CREATED_DATE      := :OLD.CREATED_DATE;
        :NEW.LAST_UPDATED_BY   := v_user;
        :NEW.LAST_UPDATED_DATE := SYSDATE;
    END IF;
END;
/

-- Sales: only the three non-colliding audit columns are maintained here.
CREATE OR REPLACE TRIGGER wst_djn_sales_audit_trg
BEFORE INSERT OR UPDATE ON wst_djn_sales
FOR EACH ROW
DECLARE
    v_user VARCHAR2(100) := NVL(SYS_CONTEXT('USERENV','CLIENT_IDENTIFIER'), 'DIRECT_DB_EDIT');
BEGIN
    IF INSERTING THEN
        :NEW.CREATED_DATE      := SYSDATE;
        :NEW.LAST_UPDATED_BY   := v_user;
        :NEW.LAST_UPDATED_DATE := SYSDATE;
    ELSIF UPDATING THEN
        :NEW.CREATED_DATE      := :OLD.CREATED_DATE;
        :NEW.LAST_UPDATED_BY   := v_user;
        :NEW.LAST_UPDATED_DATE := SYSDATE;
    END IF;
END;
/

COMMIT;

-- =====================================================================
-- OPTIONAL — give wst_djn_sales a real "Created By" username
-- =====================================================================
-- The audit "Created By" is blank on sales because the varchar name slot
-- is taken by the numeric creator-id column. Pick ONE if you want a name:
--
--  Option A (recommended, non-destructive): add a separate column and
--  have the trigger stamp it, then also select it in fetch_all_sales and
--  re-add s.CREATED_BY_NAME to the sales Eye-View data-created-by.
--     ALTER TABLE wst_djn_sales ADD (CREATED_BY_NAME VARCHAR2(100));
--     -- then in wst_djn_sales_audit_trg add on INSERT:
--     --   :NEW.CREATED_BY_NAME := v_user;
--
--  Option B (destructive, only if the numeric CREATED_BY is unused): drop
--  the numeric column, add a varchar CREATED_BY, and set it in the trigger
--  exactly like the other tables. Remove `created_by` from insert_sale().
--
-- Leaving this commented so nothing changes until you choose.
-- =====================================================================
