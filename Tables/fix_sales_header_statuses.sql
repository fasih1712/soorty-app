-- One-time catch-up for headers stuck showing DRAFT/Open despite real
-- shipment activity underneath -- a past Gate Pass posting updated
-- their lines' SHIPPED_QTY correctly, but ran before the header-status
-- recalc bug was fixed, so the header itself never moved. This
-- recomputes every non-cancelled header's status fresh from its own
-- lines' real numbers, exactly matching the app's own logic:
--   every line fully shipped           -> CLOSED
--   at least one line has shipped some -> PARTIAL
--   nothing shipped on any line        -> OPEN
--
-- Safe to run more than once.

UPDATE wst_djn_sales_header h
SET h.STATUS = (
    SELECT CASE
        WHEN NOT EXISTS (
            SELECT 1 FROM wst_djn_sales_line l
            WHERE l.DOC_ID = h.DOC_ID AND NVL(l.SHIPPED_QTY,0) < l.QUANTITY
        ) THEN 'CLOSED'
        WHEN EXISTS (
            SELECT 1 FROM wst_djn_sales_line l
            WHERE l.DOC_ID = h.DOC_ID AND NVL(l.SHIPPED_QTY,0) > 0
        ) THEN 'PARTIAL'
        ELSE 'OPEN'
    END
    FROM DUAL
)
WHERE h.STATUS != 'CANCELLED'
  AND EXISTS (SELECT 1 FROM wst_djn_sales_line l WHERE l.DOC_ID = h.DOC_ID);

COMMIT;

-- Confirm the two documents from the screenshots now show correctly:
SELECT DOC_ID, STATUS FROM wst_djn_sales_header WHERE DOC_ID IN ('DOC-2026-0003', 'DOC-2026-0002');
-- Expect: DOC-2026-0003 -> PARTIAL, DOC-2026-0002 -> CLOSED
