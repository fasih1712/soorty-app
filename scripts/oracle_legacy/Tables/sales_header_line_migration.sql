-- =====================================================================
-- Soorty — Sales Header/Line (Master-Detail) replacement schema
-- Run ONCE against apxprod. Idempotent (guarded creates).
-- =====================================================================
-- Replaces wst_djn_sales / wst_djn_sale_items going forward.
-- The OLD tables are left in place, untouched, as historical source data
-- for the one-time migration script (see migrate_legacy_sales management
-- command) — do not drop them.
-- =====================================================================
SET SERVEROUTPUT ON

-- ── Sales Header ──
DECLARE n NUMBER;
BEGIN
    SELECT COUNT(*) INTO n FROM user_tables WHERE table_name = 'WST_DJN_SALES_HEADER';
    IF n = 0 THEN
        EXECUTE IMMEDIATE '
        CREATE TABLE wst_djn_sales_header (
            doc_id            VARCHAR2(20) PRIMARY KEY,           -- e.g. DOC-2026-0001
            division          VARCHAR2(20) NOT NULL,
            vendor_id         NUMBER REFERENCES wst_djn_vendors(vendor_id),
            doc_date          DATE NOT NULL,
            invoice_no        VARCHAR2(50),
            status            VARCHAR2(20) DEFAULT ''DRAFT'' NOT NULL,   -- DRAFT / POSTED / CANCELLED
            total_amount      NUMBER(15,2) DEFAULT 0,
            created_by        VARCHAR2(100),
            created_date      DATE,
            last_updated_by   VARCHAR2(100),
            last_updated_date DATE,
            posted_by         VARCHAR2(100),
            posted_date       DATE,
            cancelled_by      VARCHAR2(100),
            cancelled_date    DATE,
            legacy_sale_id    NUMBER     -- set only by migrate_legacy_sales; lets that
                                          -- command detect and skip already-migrated rows
                                          -- on a re-run, rather than creating duplicates
        )';
        DBMS_OUTPUT.PUT_LINE('Created wst_djn_sales_header');
    ELSE
        DBMS_OUTPUT.PUT_LINE('Skip  wst_djn_sales_header (exists)');
    END IF;
END;
/

-- ── Sales Line ──
DECLARE n NUMBER;
BEGIN
    SELECT COUNT(*) INTO n FROM user_tables WHERE table_name = 'WST_DJN_SALES_LINE';
    IF n = 0 THEN
        EXECUTE IMMEDIATE '
        CREATE TABLE wst_djn_sales_line (
            line_id       NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            doc_id        VARCHAR2(20) NOT NULL REFERENCES wst_djn_sales_header(doc_id),
            line_no       NUMBER(10) NOT NULL,
            item_id       NUMBER REFERENCES wst_djn_items(item_id),
            quantity      NUMBER(15,3) NOT NULL,
            unit_price    NUMBER(15,3) NOT NULL,
            line_total    NUMBER(15,2) GENERATED ALWAYS AS (quantity * unit_price) VIRTUAL,
            CONSTRAINT uq_sales_line_doc_lineno UNIQUE (doc_id, line_no)
        )';
        DBMS_OUTPUT.PUT_LINE('Created wst_djn_sales_line');
    ELSE
        DBMS_OUTPUT.PUT_LINE('Skip  wst_djn_sales_line (exists)');
    END IF;
END;
/

-- ── Helpful index for the doc_id generator's MAX-per-year lookup ──
DECLARE n NUMBER;
BEGIN
    SELECT COUNT(*) INTO n FROM user_indexes WHERE index_name = 'IX_SALES_HEADER_DOCID';
    IF n = 0 THEN
        EXECUTE IMMEDIATE 'CREATE INDEX ix_sales_header_docid ON wst_djn_sales_header(doc_id)';
        DBMS_OUTPUT.PUT_LINE('Created ix_sales_header_docid');
    ELSE
        DBMS_OUTPUT.PUT_LINE('Skip  ix_sales_header_docid (exists)');
    END IF;
END;
/
