# Soorty ERP - Finance Module - Phase 3 (Adjustment tools)

For @Syed Taha. Phases 1 and 2 must already be installed. Do this on the TEST server first.

## What Phase 3 adds (Super Admin only: Finance > Adjustments)

1. **Refund unused advance** - pays back part of a customer's advance by cash or bank (Dr Customer Advances, Cr Cash/Bank). Reason required. Refused if the customer's advance is not enough.
2. **Credit / Debit note against a posted Gate Pass** - price or quantity correction.
   - Credit note (we charged too much): the sale is reduced (Dr Sales Returns, Cr Receivable) and the amount goes back to the customer as a new advance balance.
   - Debit note (we charged too little): the sale is increased and the extra is knocked off at once from the customer's advance. If the advance is not enough, it is refused and nothing is written.
   - Credit notes in total can never exceed the original sale.
3. **Transfer advance between customers** - moves advance from one customer to another. Reason required, two different customers.
4. **Manual journal voucher** - balanced debit/credit lines, mandatory narration. Customer Advances and Accounts Receivable cannot be used here, so the customer ledger always stays correct (use tools 1-3 for those).

Every adjustment is a normal voucher (CN, DN, AV, JV), is audited, cannot be edited or deleted, and can be **reversed** with a reason. A reversal of a credit/transfer is allowed only while the advance it created is still untouched; otherwise cancel the dispatches that used it first.

**No Paid / Partially Paid / Unpaid badges appear anywhere.** Sales Order and operational screens are unchanged. If a status view is wanted later, it must follow Option 1 (dispatch settlement).

## Install (about 20 minutes)

1. Back up `apps\finance` and `templates\base.html`.
2. Replace the folder `apps\finance` and the file `templates\base.html` (from `replace_these_files`). `settings.py` and the Gate Pass patch do not change.
3. Run `sql\05_finance_phase3_schema.sql`, then `sql\06_finance_phase3_seed.sql`. The last query must show posting_rules 14 (others unchanged: accounts 16, settings 12, voucher_types 9).
4. Run the tests: `python manage.py test apps.finance.tests` - expect `OK` (one may be skipped).
5. Restart the service.

## Gate checks on TEST

Start with a customer holding 10,000 advance and one posted Gate Pass of 5,000 (advance now 5,000).

1. Refund 1,000 by bank with a reason: advance 4,000; one AV voucher. Refund 9,000: refused.
2. Credit note 500 on that Gate Pass: advance 4,500. Credit note 4,600 more: refused (over the sale).
3. Debit note 300: advance 4,200. Debit note larger than the advance: refused, nothing posted.
4. Transfer 1,000 to another customer with a reason: balances 3,200 and 1,000. Same customer twice: refused.
5. Journal: Dr Bank Charges 120 / Cr Bank 120 with narration: posts. Unbalanced, no narration, or using Customer Advances: refused.
6. Reverse the refund: advance restored. Reverse a credit note after spending its advance: refused with a clear message.
7. Normal user / Administrator: no Adjustments menu, `/finance/adjustments/` shows "Page not found".
8. Finance Audit shows every step above.

## Decisions I made (please review)

| # | Decision | Why |
| --- | --- | --- |
| P21 | Journals may not touch Customer Advances or Receivable. | Keeps the customer sub-ledger equal to the control accounts. |
| P22 | A credit note returns value as a new advance (kind CREDIT), not cash. | Customers are prepaid; cash goes out only through Refund. |
| P23 | A debit note is paid from advance immediately and is refused if short. | Zero-credit rule. |
| P24 | Net credit notes (credits minus debits) may not exceed the original sale. | Prevents over-crediting. |
| P25 | Adjustment dates are today by default and must be in an open period, on/after the cut-over date. | Same period and cut-over rules as dispatches. |
| P26 | Approval workflow (maker-checker) is not built; Super Admin posts directly. | Only Super Admin has access now. Can be added when rights-based access arrives. |

## Not in Phase 3
Reports, ageing, reconciliation (Phase 4); load/backup/production hardening (Phase 5).

## What I could not verify here
The Oracle SQL in `sql\05`, `sql\06`, `posting.py` and `data.py` has not been run against a real Oracle. The rules were tested with the database replaced by recorders, and deliberately broken versions of five key rules were all caught by the tests. If TEST shows an Oracle error, send me the exact text from `logs\django.log`.
