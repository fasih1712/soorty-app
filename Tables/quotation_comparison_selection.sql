-- =====================================================================
-- Quotation Comparison: manual selection/override persistence
-- Run ONCE against apxprod. Idempotent (guarded).
-- =====================================================================
-- Stores ONLY the manual override (if management picks a different
-- vendor than the system's suggested Best Bid). This is what makes next
-- month's "Last Month Winner & Price" column correct: if a manual
-- selection exists for a given item+division+month, THAT is the winner;
-- if none was ever made, the winner falls back to that month's system
-- Best Bid (the highest bidder) -- computed live from
-- wst_djn_quotation_line, never duplicated into this table.
-- =====================================================================
SET SERVEROUTPUT ON

DECLARE n NUMBER;
BEGIN
    SELECT COUNT(*) INTO n FROM user_tables WHERE table_name = 'WST_DJN_QUOTE_COMPARISON_SEL';
    IF n = 0 THEN
        EXECUTE IMMEDIATE '
        CREATE TABLE wst_djn_quote_comparison_sel (
            selection_id     NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            item_id          NUMBER NOT NULL REFERENCES wst_djn_items(item_id),
            division         VARCHAR2(20) NOT NULL,
            target_month     DATE NOT NULL,          -- first-of-month
            vendor_id        NUMBER NOT NULL REFERENCES wst_djn_vendors(vendor_id),
            selected_price   NUMBER(15,3),
            created_by       VARCHAR2(100),
            created_date     DATE DEFAULT SYSDATE,
            updated_by       VARCHAR2(100),
            updated_date     DATE,
            CONSTRAINT uq_quote_comparison_sel UNIQUE (item_id, division, target_month)
        )';
        DBMS_OUTPUT.PUT_LINE('Created wst_djn_quote_comparison_sel');
    ELSE
        DBMS_OUTPUT.PUT_LINE('Skip  wst_djn_quote_comparison_sel (exists)');
    END IF;
END;
/
