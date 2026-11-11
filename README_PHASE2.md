# Soorty ERP - Finance Module - Phase 2 (Dispatch posting, prepaid advances, vouchers)

For @Syed Taha. Phase 1 is already installed; this adds to it. Do it on the TEST server first.

## What Phase 2 does

- Customers pay **in advance**. The Super Admin records it (Finance > Customer Advances > Receive Advance), or loads the reconciled opening balance on the cut-over date.
- **Before** a Shipment Gate Pass is posted, the system checks the customer's advance covers it. If not, the dispatch is refused with a plain message (no amounts shown to the user).
- **When** the Gate Pass is posted: sale = actual shipped quantity x Sales Order line price. It is booked (Dr Accounts Receivable, Cr Sales Income) and knocked off 100% against the oldest advance (Dr Customer Advances, Cr Accounts Receivable) in one transaction.
- **When** the Gate Pass is cancelled: both vouchers are reversed and the advance is given back.
- If finance fails after the Gate Pass is saved, the Gate Pass is **not** touched. The failure is logged as FAILED in Finance > Posting Events for the Super Admin to retry. The same screen lists Gate Passes finance never saw.
- Cut-over: nothing is posted for dispatches dated before **1 November 2026** (setting FINANCE_GO_LIVE_DATE).
- Posted vouchers can never be edited or deleted (database triggers); mistakes are corrected by reversal.

## Install (about 30 minutes)

1. Back up `apps\finance`, `core\settings.py`, `templates\base.html`, `apps\wastage\views.py`.
2. Replace the folder `apps\finance` with the one in this zip. Replace `core\settings.py` and `templates\base.html` with the files in `replace_these_files`.
3. Run `sql\03_finance_phase2_schema.sql`, then `sql\04_finance_phase2_seed.sql` (SQL Developer, as the APXWASTAGE owner). The last query must show: accounts 16, settings 12, voucher_types 9, posting_rules 12.
4. Connect Gate Pass. From the project folder with the venv active:
   `python patch_wastage_views.py` (copy `patch\patch_wastage_views.py` there first). It makes 4 edits to `apps\wastage\views.py`, saves `views.py.bak_finance`, and is safe to run twice.
5. Run the tests: `python manage.py test apps.finance.tests` - expect `OK` (one may be skipped).
6. Restart the service. **The link to Gate Pass is OFF** until you add `FINANCE_HOOKS_ENABLED=Y` to `.env` and restart.

## Gate checks on TEST (in this order)

Use a test copy of the database. On test only, set Finance Settings > FINANCE_GO_LIVE_DATE to the 1st of the current month (it is locked after the first posting, so never do this on production).

1. Hook OFF: post and cancel a Gate Pass as a normal user. Behaves exactly as before. Finance pages open for the Super Admin.
2. Hook ON (`FINANCE_HOOKS_ENABLED=Y`, restart). Load an opening balance of 10,000 for a customer. Create a Sales Order line at price 100.
3. As a normal user, post a Gate Pass of 120 units (12,000): refused with "does not have enough advance", no figures. Post 50 units (5,000): accepted.
4. As the Super Admin: Customer Advances shows balance 5,000; Vouchers shows one SV and one AV of 5,000; Posting Events shows Posted.
5. Cancel that Gate Pass: balance back to 10,000; two reversal vouchers (RVS) appear; the originals show Reversed.
6. Lock the current month for the division (Periods), then post a Gate Pass: the Gate Pass still posts, Posting Events shows **Failed** with the reason. Reopen the month, press Retry: it posts.
7. Normal user and Administrator: no Finance menu, `/finance/...` shows "Page not found", no amounts anywhere on Gate Pass screens.
8. Set `FINANCE_HOOKS_ENABLED=N`, restart: Gate Pass is back to the old behaviour instantly.

## Decisions I made (please review)

| # | Decision | Why |
| --- | --- | --- |
| P10 | The finance posting happens right **after** the Gate Pass commits, on its own transaction. | Your rule: a finance fault must never break a live dispatch. The cost is a short window where a Gate Pass exists without its finance entry; Posting Events shows it and offers Retry. |
| P11 | The advance check **before** posting fails closed: if it cannot run, the dispatch is not released. The kill switch (`FINANCE_HOOKS_ENABLED=N`) is the escape. | Prepaid is a hard rule. |
| P12 | Customer = the vendor on the Sales Order; price = that Sales Order line's price. A Shipment line with no Sales Order line cannot be priced and is refused (after cut-over). | There is no other price source. Tell me if such lines exist in practice. |
| P13 | Two dispatches for the same customer at the same moment: the check is a pre-check, the knock-off locks the advance rows. The second one could pass the check yet fail at knock-off and show as FAILED. | Locking at check time would make Gate Pass wait on finance. Rare; the Super Admin retries after a top-up. |
| P14 | A reversal is posted in the **current open** period dated today (like the stock reversal does), not back-dated. | Locked months stay locked. |
| P15 | An opening balance is one per customer and division, dated on the cut-over date. A wrong one is fixed by reversing it (only while unused) and loading again. | Keeps opening figures auditable. |
| P16 | "Receive Advance" is refused for dates before the cut-over and for future dates. | Month-start cut-over (D4). |
| P17 | The cut-over date cannot be changed after the first dispatch is posted. | Prevents shifting history. |
| P18 | `post_sales_document` ("Ship & Post" of a whole document) and `cancel_sales_document` are **not** linked. No screen calls `post_sales_document` today. If it is ever re-enabled it needs the same hook. | Gate Pass is the single dispatch path in the current screens. |
| P19 | New account 3200 Opening Balance Equity and rule OPENING_ADVANCE (Dr Opening Balance Equity, Cr Customer Advances). | The other side of an opening advance. |
| P20 | "Receive Advance" and "Load Opening" are Super Admin screens only. | Finance is Super Admin only. |

## Not in Phase 2

Payment-status badges (Paid / Partially Paid / Unpaid) for other users, credit notes, discounts, write-offs, manual journal vouchers, approvals, ageing and reports: Phases 3 and 4. Because every dispatch is settled at once, a normal user never needs a badge yet.

## What I could not verify here

The SQL (`sql\03`, `sql\04`, and the queries in `posting.py` / `data.py`) has **not been run against Oracle** from here. Static checks found and fixed two Oracle-only mistakes (a bind named `BY` - which also affected Phase 1 forms - and a column named `MODE`), and tests now block both. Expect that the first run on TEST may still show an Oracle message; send me the exact text from `logs\django.log` and I will fix it. The Gate Pass patch was tested on your uploaded `views.py` only; if your server copy has changed since, the script stops safely and tells you.
