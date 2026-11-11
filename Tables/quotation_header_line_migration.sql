-- =====================================================================
-- Quotation Header/Line (Master-Detail) — replaces the flat
-- wst_djn_quotations table for all NEW quotation activity.
-- Run ONCE against apxprod. Idempotent (guarded).
-- =====================================================================
-- Mirrors wst_djn_sales_header / wst_djn_sales_line exactly in spirit:
-- doc-numbered header, auto-sequenced (10,20,30...) line items.
--
-- Line items are constrained to items that actually appear in the
-- selected month's Monthly Stock List SNAPSHOT (wst_djn_msl_snapshot_line)
-- -- this is enforced at the application layer (the item dropdown is
-- built from that snapshot's lines), and item_code/uom/offered_qty are
-- frozen onto the quotation line at the moment it's added, matching the
-- same "freeze at the moment of action" pattern already used for
-- snapshot lines -- if the underlying snapshot or item master ever
-- changes later, this quotation still shows what was true when it was
-- quoted.
--
-- The old wst_djn_quotations table is left in place, untouched, as
-- historical read-only data -- nothing here migrates it automatically.
-- =====================================================================
SET SERVEROUTPUT ON

DECLARE n NUMBER;
BEGIN
    SELECT COUNT(*) INTO n FROM user_tables WHERE table_name = 'WST_DJN_QUOTATION_HEADER';
    IF n = 0 THEN
        EXECUTE IMMEDIATE '
        CREATE TABLE wst_djn_quotation_header (
            quote_doc_id   VARCHAR2(20) PRIMARY KEY,          -- e.g. QUO-2026-0001
            division       VARCHAR2(20) NOT NULL,
            target_month   DATE NOT NULL,                     -- first-of-month
            vendor_id      NUMBER REFERENCES wst_djn_vendors(vendor_id),
            reference_no   VARCHAR2(30),                       -- the snapshot doc_no this quote is against
            receive_date   DATE,
            valid_until    DATE,
            remarks        VARCHAR2(500),
            created_by     VARCHAR2(100),
            created_date   DATE DEFAULT SYSDATE,
            CONSTRAINT uq_quotation_div_month_vendor UNIQUE (division, target_month, vendor_id)
        )';
        DBMS_OUTPUT.PUT_LINE('Created wst_djn_quotation_header');
    ELSE
        DBMS_OUTPUT.PUT_LINE('Skip  wst_djn_quotation_header (exists)');
    END IF;
END;
/

DECLARE n NUMBER;
BEGIN
    SELECT COUNT(*) INTO n FROM user_tables WHERE table_name = 'WST_DJN_QUOTATION_LINE';
    IF n = 0 THEN
        EXECUTE IMMEDIATE '
        CREATE TABLE wst_djn_quotation_line (
            line_id               NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            quote_doc_id          VARCHAR2(20) NOT NULL REFERENCES wst_djn_quotation_header(quote_doc_id),
            line_no               NUMBER(10) NOT NULL,
            item_id               NUMBER REFERENCES wst_djn_items(item_id),
            item_code             VARCHAR2(20),                -- frozen at add-time
            uom                   VARCHAR2(20),                -- frozen at add-time
            offered_qty           NUMBER(15,3),                -- frozen at add-time, from the snapshot
            current_offered_price NUMBER(15,3),
            CONSTRAINT uq_quotation_line_doc_lineno UNIQUE (quote_doc_id, line_no),
            CONSTRAINT uq_quotation_line_doc_item UNIQUE (quote_doc_id, item_id)
        )';
        DBMS_OUTPUT.PUT_LINE('Created wst_djn_quotation_line');
    ELSE
        DBMS_OUTPUT.PUT_LINE('Skip  wst_djn_quotation_line (exists)');
    END IF;
END;
/
