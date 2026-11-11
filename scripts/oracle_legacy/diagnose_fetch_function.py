from apps.wastage.oracle_data import fetch_all_sales_headers
rows = fetch_all_sales_headers(division='08')
for r in rows:
    if r.get('DOC_ID') in ('DOC-2026-0003', 'DOC-2026-0001'):
        print('FUNCTION RETURNS:', r.get('DOC_ID'), '->', r.get('STATUS'))

import apps.wastage.oracle_data as od
print('THIS FILE IS ACTUALLY LOADED FROM:', od.__file__)

