-- =====================================================================
-- Shipment tables: dedicated physical record of a Ship & Post event
-- Run ONCE against apxprod. Idempotent (guarded creates).
-- =====================================================================
-- One shipment per Sales Header, created the moment that header is
-- Ship & Posted (the existing "Ship and Post" button/action). Kept at
-- the same header-level granularity as Post/Cancel already use, rather
-- than introducing partial/per-line shipping that isn't requested.
--
-- Cancelling a shipment is a SOFT delete (status flips to Cancelled,
-- row stays for the audit trail) and reverts the Sales Header back to
-- DRAFT -- re-editable / re-shippable -- NOT to a terminal CANCELLED
-- state. Cancelling or deleting the Sales Order itself is the separate,
-- distinct action that cascades back to release the Quotation
-- Comparison lock (see quotation_comparison_unlock migration below).
-- =====================================================================
SET SERVEROUTPUT ON

-- ── Shipment Header ──
DECLARE n NUMBER;
BEGIN
    SELECT COUNT(*) INTO n FROM user_tables WHERE table_name = 'WST_DJN_SHIPMENT_HEADER';
    IF n = 0 THEN
        EXECUTE IMMEDIATE '
        CREATE TABLE wst_djn_shipment_header (
            ship_doc_id       VARCHAR2(20) PRIMARY KEY,           -- e.g. SHP-2026-0001
            sales_doc_id      VARCHAR2(20) NOT NULL REFERENCES wst_djn_sales_header(doc_id),
            division          VARCHAR2(20) NOT NULL,
            ship_date         DATE NOT NULL,
            status            VARCHAR2(20) DEFAULT ''Shipped'' NOT NULL,   -- Shipped / Cancelled
            created_by        VARCHAR2(100),
            created_date      DATE DEFAULT SYSDATE,
            cancelled_by      VARCHAR2(100),
            cancelled_date    DATE
        )';
        DBMS_OUTPUT.PUT_LINE('Created wst_djn_shipment_header');
    ELSE
        DBMS_OUTPUT.PUT_LINE('Skip  wst_djn_shipment_header (exists)');
    END IF;
END;
/

-- ── Shipment Line ──
DECLARE n NUMBER;
BEGIN
    SELECT COUNT(*) INTO n FROM user_tables WHERE table_name = 'WST_DJN_SHIPMENT_LINE';
    IF n = 0 THEN
        EXECUTE IMMEDIATE '
        CREATE TABLE wst_djn_shipment_line (
            line_id        NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            ship_doc_id    VARCHAR2(20) NOT NULL REFERENCES wst_djn_shipment_header(ship_doc_id),
            sales_line_id  NUMBER REFERENCES wst_djn_sales_line(line_id),
            item_id        NUMBER REFERENCES wst_djn_items(item_id),
            quantity       NUMBER(15,3) NOT NULL
        )';
        DBMS_OUTPUT.PUT_LINE('Created wst_djn_shipment_line');
    ELSE
        DBMS_OUTPUT.PUT_LINE('Skip  wst_djn_shipment_line (exists)');
    END IF;
END;
/

-- ── Index for the sales-doc -> shipment lookup used on the Sales detail page ──
DECLARE n NUMBER;
BEGIN
    SELECT COUNT(*) INTO n FROM user_indexes WHERE index_name = 'IX_SHIPMENT_HEADER_SALESDOC';
    IF n = 0 THEN
        EXECUTE IMMEDIATE 'CREATE INDEX ix_shipment_header_salesdoc ON wst_djn_shipment_header(sales_doc_id)';
        DBMS_OUTPUT.PUT_LINE('Created ix_shipment_header_salesdoc');
    ELSE
        DBMS_OUTPUT.PUT_LINE('Skip  ix_shipment_header_salesdoc (exists)');
    END IF;
END;
/
