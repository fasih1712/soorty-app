-- Confirms exactly which columns UQ_WST_DJN_QUOTATION_HEADER covers
SELECT cc.column_name, cc.position
FROM all_cons_columns cc
WHERE cc.constraint_name = 'UQ_WST_DJN_QUOTATION_HEADER'
ORDER BY cc.position;

-- Finds the quotation(s) already sitting there for this month/division --
-- open one of these instead of creating a new one.
SELECT QUOTE_DOC_ID, VENDOR_ID, DIVISION, TARGET_MONTH, STATUS
FROM WST_DJN_QUOTATION_HEADER
WHERE DIVISION = '08'
  AND TARGET_MONTH = TO_DATE('2026-09-01','YYYY-MM-DD')
ORDER BY VENDOR_ID;
