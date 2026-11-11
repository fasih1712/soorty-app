-- =====================================================================
-- Soorty ERP — Stock Ledger & Balance Engine DDL Migration
-- Run ONCE against apxprod. Idempotent (column adds are guarded).
-- =====================================================================
SET SERVEROUTPUT ON

-- Helper: add column only if missing
DECLARE
    PROCEDURE add_col(p_tab VARCHAR2, p_col VARCHAR2, p_def VARCHAR2) IS
        n NUMBER;
    BEGIN
        SELECT COUNT(*) INTO n FROM user_tab_columns
        WHERE table_name = UPPER(p_tab) AND column_name = UPPER(p_col);
        IF n = 0 THEN
            EXECUTE IMMEDIATE 'ALTER TABLE ' || p_tab || ' ADD (' || p_col || ' ' || p_def || ')';
            DBMS_OUTPUT.PUT_LINE('Added ' || p_tab || '.' || p_col);
        ELSE
            DBMS_OUTPUT.PUT_LINE('Skip  ' || p_tab || '.' || p_col || ' (exists)');
        END IF;
    END;
BEGIN
    -- ── Stock Ledger: new columns ──
    add_col('wst_djn_stock_ledger', 'TRANSACTION_TYPE',  'VARCHAR2(20)');     -- RECEIVE / SALE / ADJUST
    add_col('wst_djn_stock_ledger', 'SOURCE_REF',        'VARCHAR2(100)');    -- e.g. RCV-2025-06-031
    add_col('wst_djn_stock_ledger', 'SOURCE_TABLE',      'VARCHAR2(50)');     -- wst_djn_stock_receiving / wst_djn_sales
    add_col('wst_djn_stock_ledger', 'SOURCE_ID',         'NUMBER');           -- PK of the source row
    add_col('wst_djn_stock_ledger', 'DIVISION',           'VARCHAR2(20)');
    add_col('wst_djn_stock_ledger', 'POSTED_BY',         'VARCHAR2(100)');
    -- audit
    add_col('wst_djn_stock_ledger', 'CREATED_BY',        'VARCHAR2(100)');
    add_col('wst_djn_stock_ledger', 'CREATED_DATE',      'DATE');
    add_col('wst_djn_stock_ledger', 'LAST_UPDATED_BY',   'VARCHAR2(100)');
    add_col('wst_djn_stock_ledger', 'LAST_UPDATED_DATE', 'DATE');

    -- ── Stock Receiving: division (may already exist per user) ──
    add_col('wst_djn_stock_receiving', 'DIVISION', 'VARCHAR2(20)');

    -- ── Sales: division ──
    add_col('wst_djn_sales', 'DIVISION', 'VARCHAR2(20)');
END;
/

-- ── Item Balance table (live position) ──
DECLARE n NUMBER;
BEGIN
    SELECT COUNT(*) INTO n FROM user_tables WHERE table_name = 'WST_DJN_ITEM_BALANCE';
    IF n = 0 THEN
        EXECUTE IMMEDIATE '
        CREATE TABLE wst_djn_item_balance (
            balance_id        NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            item_id           NUMBER NOT NULL REFERENCES wst_djn_items(item_id),
            division          VARCHAR2(20) NOT NULL,
            total_in          NUMBER(15,3) DEFAULT 0,
            total_out         NUMBER(15,3) DEFAULT 0,
            balance           NUMBER(15,3) DEFAULT 0,
            last_txn_date     DATE,
            last_txn_type     VARCHAR2(20),
            last_txn_qty      NUMBER(15,3),
            min_threshold     NUMBER(15,3) DEFAULT 0,
            created_by        VARCHAR2(100),
            created_date      DATE,
            last_updated_by   VARCHAR2(100),
            last_updated_date DATE,
            CONSTRAINT uq_item_div UNIQUE (item_id, division)
        )';
        DBMS_OUTPUT.PUT_LINE('Created wst_djn_item_balance');
    ELSE
        DBMS_OUTPUT.PUT_LINE('Skip wst_djn_item_balance (exists)');
    END IF;
END;
/

-- ── Audit triggers ──
CREATE OR REPLACE TRIGGER wst_djn_ledger_audit_trg
BEFORE INSERT OR UPDATE ON wst_djn_stock_ledger FOR EACH ROW
DECLARE v VARCHAR2(100) := NVL(SYS_CONTEXT('USERENV','CLIENT_IDENTIFIER'),'SYSTEM');
BEGIN
    IF INSERTING THEN :NEW.CREATED_BY:=v; :NEW.CREATED_DATE:=SYSDATE;
       :NEW.LAST_UPDATED_BY:=v; :NEW.LAST_UPDATED_DATE:=SYSDATE;
    ELSIF UPDATING THEN :NEW.CREATED_BY:=:OLD.CREATED_BY; :NEW.CREATED_DATE:=:OLD.CREATED_DATE;
       :NEW.LAST_UPDATED_BY:=v; :NEW.LAST_UPDATED_DATE:=SYSDATE;
    END IF;
END;
/

CREATE OR REPLACE TRIGGER wst_djn_balance_audit_trg
BEFORE INSERT OR UPDATE ON wst_djn_item_balance FOR EACH ROW
DECLARE v VARCHAR2(100) := NVL(SYS_CONTEXT('USERENV','CLIENT_IDENTIFIER'),'SYSTEM');
BEGIN
    IF INSERTING THEN :NEW.CREATED_BY:=v; :NEW.CREATED_DATE:=SYSDATE;
       :NEW.LAST_UPDATED_BY:=v; :NEW.LAST_UPDATED_DATE:=SYSDATE;
    ELSIF UPDATING THEN :NEW.CREATED_BY:=:OLD.CREATED_BY; :NEW.CREATED_DATE:=:OLD.CREATED_DATE;
       :NEW.LAST_UPDATED_BY:=v; :NEW.LAST_UPDATED_DATE:=SYSDATE;
    END IF;
END;
/

COMMIT;
