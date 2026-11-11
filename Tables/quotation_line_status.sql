-- =====================================================================
-- Line-level locking for Quotation Comparison
-- Run ONCE against apxprod. Idempotent (guarded).
-- =====================================================================
-- Locking was previously all-or-nothing at the Quotation Header level --
-- one "Lock & Generate Sales" click locked EVERY quotation for the whole
-- division+month, which meant the entire Comparison grid went read-only
-- the moment even one item was processed, hiding unrelated items
-- (including brand new bids arriving later) that had nothing to do with
-- what was actually locked.
--
-- This adds STATUS directly to wst_djn_quotation_line, so locking can
-- happen per ITEM instead. wst_djn_quotation_header.STATUS is repurposed
-- as a derived summary (Locked only once EVERY line under that header is
-- Locked) rather than something set directly by the routing action.
-- =====================================================================
SET SERVEROUTPUT ON

DECLARE n NUMBER;
BEGIN
    SELECT COUNT(*) INTO n FROM user_tab_columns
    WHERE table_name = 'WST_DJN_QUOTATION_LINE' AND column_name = 'STATUS';
    IF n = 0 THEN
        EXECUTE IMMEDIATE 'ALTER TABLE wst_djn_quotation_line ADD (status VARCHAR2(20) DEFAULT ''Open'')';
        EXECUTE IMMEDIATE 'UPDATE wst_djn_quotation_line SET status = ''Open'' WHERE status IS NULL';
        DBMS_OUTPUT.PUT_LINE('Added STATUS to wst_djn_quotation_line (defaulted existing rows to Open)');
    ELSE
        DBMS_OUTPUT.PUT_LINE('Skip  STATUS column (exists)');
    END IF;
END;
/

-- Any quotation header previously marked Locked under the old all-or-
-- nothing model reverts to Open here -- its individual lines are the ones
-- that actually carry a locked state now, and none of them have been
-- marked Locked yet (since that only happens through the routing action
-- from this point forward), so the header-level summary should not claim
-- Locked when none of its lines actually are.
UPDATE wst_djn_quotation_header SET status = 'Open' WHERE status = 'Locked';
COMMIT;
