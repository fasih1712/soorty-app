-- =====================================================================
-- Decouples "which Quotation Comparison month did this Sales document
-- originate from" (needed to correctly link a Comparison-generated
-- document back to its period for the lock/unlock lifecycle) from
-- DOC_DATE (the actual posting/transaction date, which must be
-- editable and should default to today, not the 1st of some month).
--
-- Previously these were the same column: DOC_DATE was silently set to
-- the 1st of the Comparison's target month, and every place that needed
-- to find "the Sales document(s) for this Quotation period" matched
-- against TRUNC(DOC_DATE,'MM'). That's what caused Document Date to
-- show a stale, always-1st-of-month value instead of today, and is a
-- large part of why editing it before Ship & Post didn't stick --
-- DOC_DATE was carrying two different meanings at once.
--
-- Run ONCE against apxprod. Idempotent (guarded ALTER).
-- =====================================================================
SET SERVEROUTPUT ON

DECLARE n NUMBER;
BEGIN
    SELECT COUNT(*) INTO n FROM user_tab_columns
    WHERE table_name = 'WST_DJN_SALES_HEADER' AND column_name = 'SOURCE_TARGET_MONTH';
    IF n = 0 THEN
        EXECUTE IMMEDIATE 'ALTER TABLE wst_djn_sales_header ADD SOURCE_TARGET_MONTH DATE';
        DBMS_OUTPUT.PUT_LINE('Added wst_djn_sales_header.SOURCE_TARGET_MONTH');
    ELSE
        DBMS_OUTPUT.PUT_LINE('Skip  wst_djn_sales_header.SOURCE_TARGET_MONTH (exists)');
    END IF;
END;
/

-- Backfill existing Comparison-generated documents: their DOC_DATE was
-- always set to the 1st of the target month under the old scheme, so
-- for any row where DOC_DATE is already exactly a month's first day,
-- copy it into the new column before anything downstream starts
-- relying on SOURCE_TARGET_MONTH instead. Rows that were created via
-- the manual "New Sale Document" form (never went through Comparison)
-- correctly get NULL here, since they have no originating period.
UPDATE wst_djn_sales_header
SET SOURCE_TARGET_MONTH = TRUNC(DOC_DATE, 'MM')
WHERE SOURCE_TARGET_MONTH IS NULL
  AND DOC_DATE = TRUNC(DOC_DATE, 'MM');
COMMIT;
