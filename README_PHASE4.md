# Soorty ERP - Finance Module - Phase 4 (Reports)

For @Syed Taha. Phases 1-3 must already be installed. **No database changes in this phase** (no new SQL): reports only read.

## What Phase 4 adds (Super Admin only: Finance > Reports)

1. **Customer Advance Statement** - pick a customer, optional division and dates. Shows opening balance, advances received, Gate Pass knock-offs, refunds / transfers / notes, and the advance remaining. Clean enough to print and give to the customer.
2. **Trial Balance** - every account with total debits, total credits and the debit / credit balance as at a date. A banner says whether it agrees. Click an account code to open its ledger.
3. **General Ledger** - all entries on one account with a running balance. Click a voucher number to open that voucher with all its lines (the drill-down).
4. **Sales and Collections Summary** - dispatch sales vs advances collected, per day or per month, per division, with debit / credit notes shown separately.
5. **Reconciliation Check** - 8 control checks: each customer's ledger equals their advance balance; the Customer Advances account equals the total of customers; no entry without a customer; Accounts Receivable equals open sales; every voucher balances; each advance's used amount equals its recorded knock-offs; no failed Gate Pass postings; no Gate Pass missed by finance. Any failure lists exactly which customer / voucher / Gate Pass.
6. **Advance Ageing** (replaces credit ageing, as you chose) - how long each customer's unused advance has been sitting: 0-30, 31-60, 61-90, over 90 days.

Every report has **PDF**, **Excel** and **Print** buttons. Every download is written to the Finance Audit log (who, which report, when, from which address). Opening a report on screen is not logged as a download.

No Paid / Partially Paid / Unpaid badges anywhere. Nothing changes on Sales Order or Gate Pass screens.

## Install (about 15 minutes)

1. Back up `apps\finance` and `templates\base.html`.
2. With the venv active, install the two report libraries (once): `pip install -r requirements_finance.txt` (reportlab for PDF, openpyxl for Excel). If you do not install them, everything still works; the PDF / Excel buttons just show a message asking for the install.
3. Replace the folder `apps\finance` and the file `templates\base.html` (from `replace_these_files`).
4. Run the tests: `python manage.py test apps.finance.tests` - expect `OK` (one may be skipped).
5. Restart the service.

## Gate checks on TEST

Use the data from the Phase 3 checks (a few advances, a dispatch, a refund, a note, a transfer, a journal).

1. Reports menu opens for the Super Admin; a normal user and an Administrator see no menu and `/finance/reports/` shows "Page not found".
2. Customer Advance Statement for one customer, whole month: closing balance equals the balance on Customer Advances. Each line's voucher number opens the voucher.
3. Trial Balance as at today: banner says it agrees. Total debits equal total credits. Click an account code: the General Ledger opens for it.
4. General Ledger of Customer Advances: closing balance (shown as credit, minus) equals the sum of all customer balances.
5. Sales and Collections for the month: dispatch sales equals the sum of your Gate Pass amounts; opening balances are NOT counted as collections.
6. Reconciliation Check: all 8 OK. Then on TEST only: switch `FINANCE_HOOKS_ENABLED=N`, post a Gate Pass, switch back - the check "No Gate Pass missed by finance" must fail and name the Gate Pass; process it from Posting Events and the check turns OK.
7. Advance Ageing: a receipt older than 90 days sits in the last column.
8. Download a PDF and an Excel file from each report. Open the Excel file: amounts are numbers (you can sum them), names starting with "=" appear as text. Finance Audit shows one ACCESS line per download.
9. Enter a wrong date (From after To): a red message, no error page.

## Decisions I made (please review)

| # | Decision | Why |
| --- | --- | --- |
| P27 | Reports include reversed entries together with their reversal (they cancel). | The books are never edited, so reports must show both to agree with the ledger. |
| P28 | "Advances collected" = advance receipts only (net of reversed receipts). Opening balances, refunds and transfers are not collections. | A collection is new money coming in. |
| P29 | "Dispatch sales" comes from posted vouchers, not from Gate Pass tables. | Reports always agree with the ledger. The Reconciliation Check is what compares with Gate Passes. |
| P30 | Debit / credit notes are shown in their own column (debit notes plus, credit notes minus). | Price corrections are visible instead of hidden inside sales. |
| P31 | Each report is limited to a 10-year range. Statements and ledgers print all lines in the range. | Stops accidental "all time" pulls on a large database. Very large ranges may be slow: use narrower dates. |
| P32 | PDF and Excel are built on the server from the same figures as the screen. | One set of numbers, so file and screen cannot disagree. |
| P33 | Only downloads are audited, not every screen view. | Keeps the audit log readable. Tell me if you want views logged too. |

## Not in Phase 4
Approvals, scheduled / emailed reports, other-user report access (rights-based, later), hardening and load / backup tests (Phase 5).

## What I could not verify here
The report SQL has not been run on a real Oracle. Sums, running balances, ageing and the 8 checks were tested without a database, and 11 deliberately broken versions of the key rules were all caught by the tests. If TEST shows an Oracle error on a report, send me the exact text from `logs\django.log`. I also could not look at the pages in a browser from here, so please check the layout and the printed PDF once.
