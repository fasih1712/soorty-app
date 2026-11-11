"""
One-time script to convert existing varchar data in wst_djn_ tables to Proper Case.
Run once: python fix_proper_case.py
"""
import oracledb

DB_HOST = '10.8.5.97'
DB_PORT = '1521'
DB_SERVICE = 'test1'
DB_USER = 'apxprod'
DB_PASSWORD = 'apxprod'


def to_proper_case(value):
    if value is None:
        return value
    value = str(value).strip()
    if not value:
        return value
    return value.title()


def get_connection():
    return oracledb.connect(
        user=DB_USER, password=DB_PASSWORD,
        dsn=f"{DB_HOST}:{DB_PORT}/{DB_SERVICE}"
    )


TABLES_FIELDS = {
    'wst_djn_categories': {'pk': 'CATEGORY_ID', 'fields': ['CATEGORY_NAME', 'DESCRIPTION']},
    'wst_djn_departments': {'pk': 'DEPT_ID', 'fields': ['DEPT_NAME', 'LOCATION']},
    'wst_djn_vendors': {'pk': 'VENDOR_ID', 'fields': ['VENDOR_NAME', 'CONTACT_PERSON', 'ADDRESS']},
    'wst_djn_items': {'pk': 'ITEM_ID', 'fields': ['ITEM_NAME', 'CONDITION', 'DESCRIPTION']},
    'wst_djn_monthly_stock_list': {'pk': 'LIST_ID', 'fields': ['CONDITION']},
    'wst_djn_quotations': {'pk': 'QUOTE_ID', 'fields': ['REMARKS']},
    'wst_djn_stock_receiving': {'pk': 'RECEIVE_ID', 'fields': ['REMARKS']},
    'wst_djn_user_generic_group_type': {'pk': 'GROUP_CODE', 'fields': ['SHORT_DESC']},
    'wst_djn_user_generic_group': {'pk': 'CODE', 'fields': ['DESCRIPTION']},
}


def run():
    conn = get_connection()
    cur = conn.cursor()
    total_updated = 0

    for table, info in TABLES_FIELDS.items():
        pk = info['pk']
        fields = info['fields']
        select_cols = ', '.join([pk] + fields)
        cur.execute(f"SELECT {select_cols} FROM {table}")
        rows = cur.fetchall()

        for row in rows:
            pk_val = row[0]
            changed = False
            set_clauses = []
            params = []
            for idx, field in enumerate(fields, start=1):
                old_val = row[idx]
                new_val = to_proper_case(old_val)
                if old_val != new_val:
                    changed = True
                set_clauses.append(f"{field}=:{idx}")
                params.append(new_val)

            if changed:
                params.append(pk_val)
                update_sql = f"UPDATE {table} SET {', '.join(set_clauses)} WHERE {pk}=:{len(fields)+1}"
                cur.execute(update_sql, params)
                total_updated += 1

        print(f"{table}: processed {len(rows)} rows")

    conn.commit()
    cur.close()
    conn.close()
    print(f"\n✅ Done. Total rows updated: {total_updated}")


if __name__ == '__main__':
    run()