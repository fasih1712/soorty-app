-- =====================================================================
-- Gate Pass Module -- Phase 1: Schema Creation
-- FRD: "Gate Pass Module & Sales Order Integration"
--
-- Three new tables:
--   wst_djn_gatepass_senders  -- lookup for the Sender Name dropdown
--   wst_djn_gatepass_header   -- one row per printed Gate Pass
--   wst_djn_gatepass_line     -- one row per dispatched item line
--
-- Run ONCE against apxprod. Idempotent (every ALTER/CREATE is guarded).
-- =====================================================================
SET SERVEROUTPUT ON

-- ---------------------------------------------------------------------
-- 1. Sender lookup table -- backs the Sender Name dropdown's inline
--    add/edit requirement (Section 4), same shape as Vendors/Departments.
-- ---------------------------------------------------------------------
DECLARE n NUMBER;
BEGIN
    SELECT COUNT(*) INTO n FROM user_tables WHERE table_name = 'WST_DJN_GATEPASS_SENDERS';
    IF n = 0 THEN
        EXECUTE IMMEDIATE '
            CREATE TABLE wst_djn_gatepass_senders (
                SENDER_ID     NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                SENDER_NAME   VARCHAR2(200) NOT NULL,
                IS_ACTIVE     NUMBER(1) DEFAULT 1 NOT NULL,
                CREATED_BY    VARCHAR2(100),
                CREATED_DATE  DATE DEFAULT SYSDATE
            )';
        DBMS_OUTPUT.PUT_LINE('Created wst_djn_gatepass_senders');
    ELSE
        DBMS_OUTPUT.PUT_LINE('Skip   wst_djn_gatepass_senders (exists)');
    END IF;
END;
/

-- ---------------------------------------------------------------------
-- 2. Gate Pass header
--    MODULE_TYPE: 'Shipment' (SO-driven) or 'Transfer' (internal move).
--    SENDER_DEPARTMENT_ID: a real FK to wst_djn_departments, per sign-off
--    -- NOT free text as the FRD literally worded it.
-- ---------------------------------------------------------------------
DECLARE n NUMBER;
BEGIN
    SELECT COUNT(*) INTO n FROM user_tables WHERE table_name = 'WST_DJN_GATEPASS_HEADER';
    IF n = 0 THEN
        EXECUTE IMMEDIATE '
            CREATE TABLE wst_djn_gatepass_header (
                GATE_PASS_ID           VARCHAR2(20) PRIMARY KEY,
                MODULE_TYPE            VARCHAR2(20) NOT NULL
                                        CONSTRAINT ck_gatepass_module_type
                                        CHECK (MODULE_TYPE IN (''Shipment'',''Transfer'')),
                DIVISION               VARCHAR2(10) NOT NULL,
                GATE_PASS_DATE         DATE DEFAULT SYSDATE NOT NULL,
                DOCUMENT_TYPE          VARCHAR2(50) DEFAULT ''Waste'',
                SENDER_ID              NUMBER
                                        REFERENCES wst_djn_gatepass_senders(SENDER_ID),
                SHIP_TO                VARCHAR2(300),
                SENDER_DEPARTMENT_ID   NUMBER
                                        REFERENCES wst_djn_departments(DEPT_ID),
                VEHICLE_TYPE           VARCHAR2(100),
                VEHICLE_NO             VARCHAR2(50),
                DRIVER_NAME            VARCHAR2(150),
                RECEIVER_NAME          VARCHAR2(150),
                REMARKS                VARCHAR2(1000),
                STATUS                 VARCHAR2(20) DEFAULT ''Posted'' NOT NULL
                                        CONSTRAINT ck_gatepass_status
                                        CHECK (STATUS IN (''Posted'',''Cancelled'')),
                CREATED_BY             VARCHAR2(100),
                CREATED_DATE           DATE DEFAULT SYSDATE,
                CANCELLED_BY           VARCHAR2(100),
                CANCELLED_DATE         DATE
            )';
        DBMS_OUTPUT.PUT_LINE('Created wst_djn_gatepass_header');
    ELSE
        DBMS_OUTPUT.PUT_LINE('Skip   wst_djn_gatepass_header (exists)');
    END IF;
END;
/

-- ---------------------------------------------------------------------
-- 3. Gate Pass line
--    SO_DOC_ID / SO_LINE_ID are nullable -- populated for Shipment,
--    NULL for Transfer (Section 3B, "bypasses SO/Vendor filtering
--    entirely"). ITEM_PREFIX / ITEM_DESCRIPTION / UOM / SO_ORDER_QTY are
--    deliberately snapshotted, not derived live, per sign-off: this is a
--    signed, physical dispatch record and must read the same on a
--    reprint months later even if the item master changes afterward.
-- ---------------------------------------------------------------------
DECLARE n NUMBER;
BEGIN
    SELECT COUNT(*) INTO n FROM user_tables WHERE table_name = 'WST_DJN_GATEPASS_LINE';
    IF n = 0 THEN
        EXECUTE IMMEDIATE '
            CREATE TABLE wst_djn_gatepass_line (
                LINE_ID              NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                GATE_PASS_ID         VARCHAR2(20) NOT NULL
                                      REFERENCES wst_djn_gatepass_header(GATE_PASS_ID),
                LINE_NO              NUMBER NOT NULL,
                SO_DOC_ID            VARCHAR2(20)
                                      REFERENCES wst_djn_sales_header(DOC_ID),
                SO_LINE_ID           NUMBER
                                      REFERENCES wst_djn_sales_line(LINE_ID),
                ITEM_ID              NUMBER NOT NULL
                                      REFERENCES wst_djn_items(ITEM_ID),
                ITEM_PREFIX          VARCHAR2(20),
                ITEM_DESCRIPTION     VARCHAR2(300),
                UOM                  VARCHAR2(20),
                SO_ORDER_QTY         NUMBER,
                GATEPASS_QTY         NUMBER NOT NULL
                                      CONSTRAINT ck_gatepass_qty_positive
                                      CHECK (GATEPASS_QTY > 0),
                REMARKS              VARCHAR2(500)
            )';
        DBMS_OUTPUT.PUT_LINE('Created wst_djn_gatepass_line');
    ELSE
        DBMS_OUTPUT.PUT_LINE('Skip   wst_djn_gatepass_line (exists)');
    END IF;
END;
/

-- ---------------------------------------------------------------------
-- 4. Indexes for the lookups this module will do constantly:
--    finding a Gate Pass's lines, and finding every Gate Pass line
--    against a given SO line (needed to compute SHIPPED_QTY and to
--    walk the reversal chain when a Gate Pass is cancelled).
-- ---------------------------------------------------------------------
DECLARE n NUMBER;
BEGIN
    SELECT COUNT(*) INTO n FROM user_indexes WHERE index_name = 'IX_GATEPASS_LINE_HEADER';
    IF n = 0 THEN
        EXECUTE IMMEDIATE 'CREATE INDEX ix_gatepass_line_header ON wst_djn_gatepass_line(GATE_PASS_ID)';
        DBMS_OUTPUT.PUT_LINE('Created ix_gatepass_line_header');
    END IF;
    SELECT COUNT(*) INTO n FROM user_indexes WHERE index_name = 'IX_GATEPASS_LINE_SOLINE';
    IF n = 0 THEN
        EXECUTE IMMEDIATE 'CREATE INDEX ix_gatepass_line_soline ON wst_djn_gatepass_line(SO_LINE_ID)';
        DBMS_OUTPUT.PUT_LINE('Created ix_gatepass_line_soline');
    END IF;
END;
/
