-- Recomputes wst_djn_item_balance for "Ac Scrap" / Division 08 directly
-- from the real ledger totals -- the same numbers already showing
-- correctly on the Stock Ledger screen (Image 2), which the crashed
-- recalculation never got to write into the balance summary.
--
-- Safe to run as apxWastage. Finds the item by name so you don't need
-- to know its ITEM_ID.

MERGE INTO wst_djn_item_balance b
USING (
    SELECT l.ITEM_ID, '08' AS DIVISION,
           NVL(SUM(l.QTY_IN),0) AS TOTAL_IN,
           NVL(SUM(l.QTY_OUT),0) AS TOTAL_OUT,
           NVL(SUM(l.QTY_IN),0) - NVL(SUM(l.QTY_OUT),0) AS BALANCE
    FROM wst_djn_stock_ledger l
    JOIN wst_djn_items i ON l.ITEM_ID = i.ITEM_ID
    WHERE i.ITEM_NAME = 'Ac Scrap' AND NVL(l.DIVISION,'08') = '08'
    GROUP BY l.ITEM_ID
) s
ON (b.ITEM_ID = s.ITEM_ID AND b.DIVISION = s.DIVISION)
WHEN MATCHED THEN UPDATE SET
    b.TOTAL_IN = s.TOTAL_IN, b.TOTAL_OUT = s.TOTAL_OUT, b.BALANCE = s.BALANCE
WHEN NOT MATCHED THEN INSERT
    (ITEM_ID, DIVISION, TOTAL_IN, TOTAL_OUT, BALANCE)
    VALUES (s.ITEM_ID, s.DIVISION, s.TOTAL_IN, s.TOTAL_OUT, s.BALANCE);

COMMIT;

-- Confirm it now matches the ledger:
SELECT b.DIVISION, i.ITEM_NAME, b.TOTAL_IN, b.TOTAL_OUT, b.BALANCE
FROM wst_djn_item_balance b
JOIN wst_djn_items i ON b.ITEM_ID = i.ITEM_ID
WHERE i.ITEM_NAME = 'Ac Scrap' AND b.DIVISION = '08';
