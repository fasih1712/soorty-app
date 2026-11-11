-- Finds every item where wst_djn_item_balance disagrees with the real
-- ledger totals -- i.e. every item potentially affected by the same
-- crash, not just the one you happened to spot.
SELECT i.ITEM_NAME, b.DIVISION,
       b.BALANCE AS SHOWN_BALANCE,
       (l.TOTAL_IN - l.TOTAL_OUT) AS REAL_BALANCE
FROM wst_djn_item_balance b
JOIN wst_djn_items i ON b.ITEM_ID = i.ITEM_ID
JOIN (
    SELECT ITEM_ID, NVL(DIVISION,'08') AS DIVISION,
           NVL(SUM(QTY_IN),0) AS TOTAL_IN, NVL(SUM(QTY_OUT),0) AS TOTAL_OUT
    FROM wst_djn_stock_ledger
    GROUP BY ITEM_ID, NVL(DIVISION,'08')
) l ON b.ITEM_ID = l.ITEM_ID AND b.DIVISION = l.DIVISION
WHERE b.BALANCE != (l.TOTAL_IN - l.TOTAL_OUT);
