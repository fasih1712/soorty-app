# Soorty ERP - Finance Module - Phase 1 (Foundation, Security, Chart of Accounts, Audit)

For @Syed Taha. Follow the steps in order, on the TEST environment first.

## What is in this package

| Path | What it is |
| --- | --- |
| `sql/01_finance_schema.sql` | Creates 7 `wst_djn_fin_*` tables and the append-only audit trigger |
| `sql/02_finance_seed.sql` | Chart of accounts (15 heads), 10 settings, 9 voucher types, 11 posting rules |
| `apps/finance/` | The new Django app (guards, data layer, views, templates, tests) |
| `replace_these_files/settings.py` | Your `settings.py` with 2 lines added (app + middleware) |
| `replace_these_files/base.html` | Your `base.html` with a Finance menu shown to the Super Admin only |

## Install

1. **Back up** `core\settings.py` and `templates\base.html`.
2. Copy the folder `apps\finance` into your project's `apps\` folder (so you have `apps\finance\views.py`).
3. Replace `core\settings.py` and `templates\base.html` with the two files in `replace_these_files`.
4. Open `core\urls.py` and add this line inside `urlpatterns`, next to the other `include(...)` lines:

   ```python
   path('finance/', include('apps.finance.urls')),
   ```

5. Run the two SQL scripts on the **test** database, in order (SQL Developer or SQL*Plus, as the APXWASTAGE owner). The last query of script 2 must show: accounts 15, settings 10, voucher_types 9, posting_rules 11.
6. Run the gate tests (no Oracle needed, they do not touch the database):

   ```
   python manage.py test apps.finance.tests.test_validators apps.finance.tests.test_access
   ```

   Expect `OK`. One test may be reported as skipped only if `apps.accounts` is missing; on your server nothing should skip.
7. Restart the service (NSSM). Do not touch production until step 8 passes on test.
8. Manual gate check (5 minutes):
   - Sign in as **djangosuperadmin**: the sidebar shows **Finance**; Overview, Chart of Accounts, Posting Rules, Finance Settings, Periods and Finance Audit all open.
   - Sign in as **any other user, including an Administrator**: no Finance menu; typing `/finance/` or `/finance/accounts/` in the address bar shows "Page not found".
   - As the Super Admin open **Finance Audit**: the blocked attempt from the step above appears as a **Denied** row.
   - Role Management: Finance must not appear anywhere in the permission matrix.

## What the gate tests prove

- All 13 finance URLs, plus any future `/finance/...` URL, return 404 for: logged-out visitors, regular users, staff, a staff user holding every Django permission, and an inactive superuser. GET and POST.
- Three independent locks, each tested alone: the middleware (even for a brand-new route whose view forgot its guard), the view decorator (even with the middleware removed), and the data layer (refuses before any database access).
- A test fails if a new finance view lacks the guard or a new data function lacks the Super Admin check.
- Finance is not in the RBAC page registry; the menu link sits only inside a Super Admin block.
- Blocked attempts by signed-in users are written to the finance audit; a database failure while auditing never breaks the page.
- I also broke each lock on purpose (5 mutations) and confirmed the tests fail every time.

## Decisions I made that you should review

| # | Decision | Why |
| --- | --- | --- |
| P1 | Finance audit goes to its own table `wst_djn_fin_audit_log`, not `wst_djn_audit_log`. | The existing Audit Log screen lists every table in `wst_djn_audit_log`, so finance entries stored there would be visible to anyone with the Audit Log permission. The new table is append-only (trigger blocks update and delete). |
| P2 | Finance is deliberately not registered in `rbac.py`. | Registered pages become assignable in Role Management. Finance must not be. |
| P3 | Blocked attempts are saved to the database only for signed-in users; logged-out probes go to the log file only. | Stops an anonymous scanner from filling the audit table. |
| P4 | Locked system heads allow a rename only (code, type, kind and key are fixed). | Posting rules point to these heads by key. |
| P5 | Months lock in order and only the latest locked month can be reopened, with a reason of 5+ characters. A future month cannot be locked. | Standard period-close discipline (decision D9). |
| P6 | `FISCAL_YEAR_START_MONTH` is seeded as 7 (July). | Pakistan convention. It only affects voucher number reset from Phase 2. Change it in Finance Settings if your financial year differs. |
| P7 | Three extra system heads: 3100 Retained Earnings, 4200 Sales Returns And Allowances, 5300 Rounding Difference. | Needed for the trial balance, credit notes and the PKR 1 tolerance (D6). |
| P8 | Primary keys use Oracle identity columns. | Safe under many users; no MAX+1 race. |
| P9 | Account names are saved in Proper Case, keeping acronyms such as WHT. | Matches the project's data-quality rule. |

## Not in Phase 1 (by design)

- Voucher, receivable and allocation tables with their "posted rows cannot change" triggers: Phase 2.
- The `payment_status_view` permission and the Paid / Partially Paid / Unpaid gateway: Phase 3, when there are receivables to report on.
- Blocking deactivation of an account that already has postings: added with the voucher tables in Phase 2.

## What I could not verify here

The Oracle SQL (`sql/*.sql` and the queries in `apps/finance/data.py`) was written to Oracle 19c syntax but has **not been run against Oracle** from this environment. The access and rule logic is tested; the database layer needs your step 5 and step 8 on the test server. If any script or screen errors, send me the exact message and I will fix it.
