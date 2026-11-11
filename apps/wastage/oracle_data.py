import oracledb
import environ
import re
from pathlib import Path
from datetime import date

_BASE_DIR = Path(__file__).resolve().parent.parent.parent
_env = environ.Env()
environ.Env.read_env(_BASE_DIR / '.env')

ORACLE_USER = _env('DB_USER')
ORACLE_PASSWORD = _env('DB_PASSWORD')
ORACLE_DSN = oracledb.makedsn(
    _env('DB_HOST'),
    _env('DB_PORT'),
    service_name=_env('DB_SERVICE_NAME')
)

def to_proper_case(value):
    """Convert text to Proper Case (Title Case), safe for None/empty values."""
    if value is None:
        return value
    value = str(value).strip()
    if not value:
        return value
    return value.title()


def get_connection(username=None):
    conn = oracledb.connect(
        user=ORACLE_USER,
        password=ORACLE_PASSWORD,
        dsn=ORACLE_DSN
    )
    identifier = username if username else 'DIRECT_DB_EDIT'
    cursor = conn.cursor()
    cursor.callproc("DBMS_SESSION.SET_IDENTIFIER", [identifier])
    cursor.close()
    return conn


# ─── CATEGORIES ───────────────────────────────────────────
def fetch_all_categories(search=None):
    cols_sql = """CATEGORY_ID, CATEGORY_NAME, DESCRIPTION, PREFIX,
                  CREATED_BY, TO_CHAR(CREATED_DATE,'DD-Mon-YYYY HH24:MI') AS CREATED_DATE,
                  LAST_UPDATED_BY, TO_CHAR(LAST_UPDATED_DATE,'DD-Mon-YYYY HH24:MI') AS LAST_UPDATED_DATE"""
    if search:
        sql = f"""SELECT {cols_sql}
                  FROM wst_djn_categories
                  WHERE UPPER(CATEGORY_NAME) LIKE UPPER(:1) OR UPPER(DESCRIPTION) LIKE UPPER(:2)
                  ORDER BY CATEGORY_ID"""
        params = [f'%{search}%', f'%{search}%']
    else:
        sql = f"SELECT {cols_sql} FROM wst_djn_categories ORDER BY CATEGORY_ID"
        params = []
        
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            cols = [c[0] for c in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]

def fetch_category_by_id(cat_id):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT CATEGORY_ID, CATEGORY_NAME, DESCRIPTION, PREFIX FROM wst_djn_categories WHERE CATEGORY_ID=:1", [int(cat_id)])
            cols = [c[0] for c in cur.description]
            row = cur.fetchone()
            return dict(zip(cols, row)) if row else None

def insert_category(name, desc, prefix=None, username=None):
    with get_connection(username) as conn:  # username -> CLIENT_IDENTIFIER -> audit trigger sets CREATED_BY
        with conn.cursor() as cur:
            cur.execute("INSERT INTO wst_djn_categories (CATEGORY_NAME, DESCRIPTION, PREFIX) VALUES (:1,:2,:3)",
                        [to_proper_case(name), to_proper_case(desc), (prefix or '').strip().upper() or None])
            conn.commit()


def update_category(cat_id, name, desc, prefix=None, username=None):
    with get_connection(username) as conn:  # username -> CLIENT_IDENTIFIER -> audit trigger sets LAST_UPDATED_BY
        with conn.cursor() as cur:
            cur.execute("UPDATE wst_djn_categories SET CATEGORY_NAME=:1, DESCRIPTION=:2, PREFIX=:3 WHERE CATEGORY_ID=:4",
                        [to_proper_case(name), to_proper_case(desc), (prefix or '').strip().upper() or None, int(cat_id)])
            conn.commit()

def delete_category(cat_id, username=None):
    with get_connection(username) as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM wst_djn_categories WHERE CATEGORY_ID=:1", [int(cat_id)])
            conn.commit()


# ─── DEPARTMENTS ──────────────────────────────────────────
def _warn_short_desc_missing(where):
    import logging
    logging.getLogger('wastage').warning(
        f'{where}: wst_djn_departments has no SHORT_DESCRIPTION column in the schema this app connects to '
        f'-- run the ALTER TABLE in that schema. Short description was NOT saved/read.')


# SHORT_DESCRIPTION is a newer, optional column on wst_djn_departments (see
# the ALTER TABLE in the release notes). Every function below falls back to
# the original column list if the column isn't there yet, so deploying this
# code before/after running the ALTER can never break the screens that list
# or pick departments.
def fetch_all_departments(search=None):
    def _run(with_short):
        short_sql = "SHORT_DESCRIPTION, " if with_short else ""
        cols_sql = f"""DEPT_ID, DEPT_NAME, {short_sql}LOCATION, SUPERVISOR_ID,
                  CREATED_BY, TO_CHAR(CREATED_DATE,'DD-Mon-YYYY HH24:MI') AS CREATED_DATE,
                  LAST_UPDATED_BY, TO_CHAR(LAST_UPDATED_DATE,'DD-Mon-YYYY HH24:MI') AS LAST_UPDATED_DATE"""
        if search:
            extra = " OR UPPER(SHORT_DESCRIPTION) LIKE UPPER(:3)" if with_short else ""
            sql = f"""SELECT {cols_sql}
                      FROM wst_djn_departments
                      WHERE UPPER(DEPT_NAME) LIKE UPPER(:1) OR UPPER(LOCATION) LIKE UPPER(:2){extra}
                      ORDER BY DEPT_ID"""
            params = [f'%{search}%', f'%{search}%'] + ([f'%{search}%'] if with_short else [])
        else:
            sql = f"SELECT {cols_sql} FROM wst_djn_departments ORDER BY DEPT_ID"
            params = []
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                cols = [c[0] for c in cur.description]
                return [dict(zip(cols, row)) for row in cur.fetchall()]
    try:
        return _run(True)
    except oracledb.DatabaseError as e:
        if 'ORA-00904' not in str(e):
            raise
        _warn_short_desc_missing('fetch_all_departments')
        rows = _run(False)
        for r in rows:
            r['SHORT_DESCRIPTION'] = None
        return rows


def fetch_department_by_id(dept_id):
    with get_connection() as conn:
        with conn.cursor() as cur:
            try:
                cur.execute("SELECT DEPT_ID, DEPT_NAME, SHORT_DESCRIPTION, LOCATION, SUPERVISOR_ID FROM wst_djn_departments WHERE DEPT_ID=:1", [int(dept_id)])
            except oracledb.DatabaseError as e:
                if 'ORA-00904' not in str(e):
                    raise
                _warn_short_desc_missing('fetch_department_by_id')
                cur.execute("SELECT DEPT_ID, DEPT_NAME, LOCATION, SUPERVISOR_ID FROM wst_djn_departments WHERE DEPT_ID=:1", [int(dept_id)])
            cols = [c[0] for c in cur.description]
            row = cur.fetchone()
            rec = dict(zip(cols, row)) if row else None
            if rec is not None:
                rec.setdefault('SHORT_DESCRIPTION', None)
            return rec

def insert_department(name, location, supervisor_id, username=None, short_description=None):
    short_description = (short_description or '').strip() or None
    with get_connection(username) as conn:  # 🌟 username pass karna zaroori hai
        with conn.cursor() as cur:
            try:
                cur.execute("""INSERT INTO wst_djn_departments (DEPT_NAME, SHORT_DESCRIPTION, LOCATION, SUPERVISOR_ID)
                               VALUES (:1, :2, :3, :4)""", [name, short_description, location, supervisor_id])
            except oracledb.DatabaseError as e:
                if 'ORA-00904' not in str(e):
                    raise
                _warn_short_desc_missing('insert_department')
                cur.execute("""INSERT INTO wst_djn_departments (DEPT_NAME, LOCATION, SUPERVISOR_ID)
                               VALUES (:1, :2, :3)""", [name, location, supervisor_id])
            conn.commit()

def update_department(dept_id, name, location, supervisor_id, username=None, short_description=None):
    short_description = (short_description or '').strip() or None
    with get_connection(username) as conn:  # 🌟 username pass karna zaroori hai
        with conn.cursor() as cur:
            try:
                cur.execute("""UPDATE wst_djn_departments
                               SET DEPT_NAME=:1, SHORT_DESCRIPTION=:2, LOCATION=:3, SUPERVISOR_ID=:4
                               WHERE DEPT_ID=:5""", [name, short_description, location, supervisor_id, int(dept_id)])
            except oracledb.DatabaseError as e:
                if 'ORA-00904' not in str(e):
                    raise
                _warn_short_desc_missing('update_department')
                cur.execute("""UPDATE wst_djn_departments
                               SET DEPT_NAME=:1, LOCATION=:2, SUPERVISOR_ID=:3
                               WHERE DEPT_ID=:4""", [name, location, supervisor_id, int(dept_id)])
            conn.commit()


def delete_department(dept_id, username=None):
    with get_connection(username) as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM wst_djn_departments WHERE DEPT_ID=:1", [int(dept_id)])
            conn.commit()


# ─── VENDORS ──────────────────────────────────────────────
def fetch_all_vendors(search=None):
    cols_sql = """VENDOR_ID, VENDOR_NAME, CNIC, CNIC_ATTACHMENT_PATH, CONTACT_PERSON, PHONE, WHATSAPP_NO, EMAIL, ADDRESS, IS_ACTIVE,
              CREATED_BY, TO_CHAR(CREATED_DATE,'DD-Mon-YYYY HH24:MI') AS CREATED_DATE,
              LAST_UPDATED_BY, TO_CHAR(LAST_UPDATED_DATE,'DD-Mon-YYYY HH24:MI') AS LAST_UPDATED_DATE"""
    if search:
        sql = f"""SELECT {cols_sql}
                 FROM wst_djn_vendors
                 WHERE UPPER(VENDOR_NAME) LIKE UPPER(:1) OR UPPER(CONTACT_PERSON) LIKE UPPER(:2) OR PHONE LIKE :3
                 ORDER BY VENDOR_ID"""
        params = [f'%{search}%', f'%{search}%', f'%{search}%']
    else:
        sql = f"SELECT {cols_sql} FROM wst_djn_vendors ORDER BY VENDOR_ID"
        params = []
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            cols = [c[0] for c in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]



def fetch_vendor_by_id(vendor_id):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT VENDOR_ID, VENDOR_NAME, CNIC, CNIC_ATTACHMENT_PATH, CONTACT_PERSON, PHONE, WHATSAPP_NO, EMAIL, ADDRESS, IS_ACTIVE FROM wst_djn_vendors WHERE VENDOR_ID=:1", [int(vendor_id)])
            cols = [c[0] for c in cur.description]
            row = cur.fetchone()
            return dict(zip(cols, row)) if row else None

def insert_vendor(name, cnic, contact, phone, whatsapp, email, address, is_active,
                   cnic_attachment_path=None, username=None):
    """Returns the newly-generated VENDOR_ID (via RETURNING INTO) --
    needed by the bulk vendor_add flow, which doesn't know a vendor's ID
    until after this insert commits, but needs it to name the saved CNIC
    attachment file. Existing call sites that don't pass
    cnic_attachment_path are unaffected -- it's optional and trailing."""
    with get_connection(username) as conn:
        with conn.cursor() as cur:
            new_id = cur.var(int)
            cur.execute("""INSERT INTO wst_djn_vendors 
                (VENDOR_NAME, CONTACT_PERSON, PHONE, WHATSAPP_NO, EMAIL, ADDRESS, CNIC, CNIC_ATTACHMENT_PATH, IS_ACTIVE)
                VALUES (:1,:2,:3,:4,:5,:6,:7,:8,:9)
                RETURNING VENDOR_ID INTO :10""",
                [to_proper_case(name), to_proper_case(contact), phone, whatsapp,
                 email.strip().lower() if email else email, to_proper_case(address), cnic,
                 cnic_attachment_path, 1 if is_active else 0, new_id])
            conn.commit()
            return int(new_id.getvalue()[0])


def update_vendor(vendor_id, name, cnic, contact, phone, whatsapp, email, address, is_active,
                   cnic_attachment_path=None, username=None):
    """cnic_attachment_path: pass the vendor's EXISTING path unchanged if
    no new file was uploaded this edit -- this function always writes
    whatever value it's given, it doesn't try to detect "unchanged"
    itself. The view is responsible for fetching the current value first
    when nothing new was uploaded (same pattern already used for every
    other field on this form)."""
    with get_connection(username) as conn:
        with conn.cursor() as cur:
            cur.execute("""UPDATE wst_djn_vendors SET 
                VENDOR_NAME=:1, CONTACT_PERSON=:2, PHONE=:3,
                WHATSAPP_NO=:4, EMAIL=:5, ADDRESS=:6, CNIC=:7, CNIC_ATTACHMENT_PATH=:8, IS_ACTIVE=:9
                WHERE VENDOR_ID=:10""",
                [to_proper_case(name), to_proper_case(contact), phone, whatsapp,
                 email.strip().lower() if email else email, to_proper_case(address), cnic,
                 cnic_attachment_path, 1 if is_active else 0, int(vendor_id)])
            conn.commit()

def delete_vendor(vendor_id, username=None):
    with get_connection(username) as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM wst_djn_vendors WHERE VENDOR_ID=:1", [int(vendor_id)])
            conn.commit()


# ─── ITEMS ────────────────────────────────────────────────
def fetch_all_items(search=None):
    cols_sql = """i.ITEM_ID, i.ITEM_CODE, i.ITEM_NAME, i.UNIT, i.CONDITION, i.DESCRIPTION, i.IS_ACTIVE, c.CATEGORY_NAME,
                  i.CREATED_BY, TO_CHAR(i.CREATED_DATE,'DD-Mon-YYYY HH24:MI') AS CREATED_DATE,
                  i.LAST_UPDATED_BY, TO_CHAR(i.LAST_UPDATED_DATE,'DD-Mon-YYYY HH24:MI') AS LAST_UPDATED_DATE"""
                  
    if search:
        sql = f"""SELECT {cols_sql}
                  FROM wst_djn_items i
                  LEFT JOIN wst_djn_categories c ON i.CATEGORY_ID=c.CATEGORY_ID
                  WHERE UPPER(i.ITEM_NAME) LIKE UPPER(:1) OR UPPER(c.CATEGORY_NAME) LIKE UPPER(:2) OR UPPER(i.ITEM_CODE) LIKE UPPER(:3)
                  ORDER BY i.ITEM_ID"""
        params = [f'%{search}%', f'%{search}%', f'%{search}%']
    else:
        sql = f"""SELECT {cols_sql}
                  FROM wst_djn_items i
                  LEFT JOIN wst_djn_categories c ON i.CATEGORY_ID=c.CATEGORY_ID
                  ORDER BY i.ITEM_ID"""
        params = []
        
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            cols = [c[0] for c in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]


def fetch_item_by_id(item_id):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT ITEM_ID, ITEM_CODE, CATEGORY_ID, ITEM_NAME, UNIT, CONDITION, DESCRIPTION, IS_ACTIVE FROM wst_djn_items WHERE ITEM_ID=:1", [int(item_id)])
            cols = [c[0] for c in cur.description]
            row = cur.fetchone()
            return dict(zip(cols, row)) if row else None

def derive_sub_spec_code(item_name, category_name):
    """Derives a short sub-spec code from an item name, matching the
    Smart Structured Item Code standard.

    Rule (consistent and documented, since a handful of hand-picked
    examples don't reduce to one mechanical rule -- e.g. 'Sizing'->SZ and
    'Lead Line'->LL come from different underlying logic in the source
    examples. This implementation favors predictability going forward
    over trying to guess ad-hoc human abbreviations):
      1. Strip any words the item name shares with its category name
         (e.g. 'Waste' is redundant once the category is 'Blue Waste').
      2. If a number appears anywhere (e.g. '120 Kg'), the code is the
         first letter of the first remaining word + that number,
         zero-padded to 3 digits -- e.g. 'Plastic Drum 120 Kg' -> P120.
      3. Otherwise, if exactly one significant word remains, the code is
         that word's first 2 letters -- e.g. 'Sizing' -> SI.
      4. Otherwise (2+ words), the code is the first letter of each
         significant word (up to 4) -- e.g. 'Lead Line' -> LL.
      5. If nothing significant remains, returns '' (caller falls back to
         the plain {PREFIX}-{SEQ:03d} format)."""
    if not item_name:
        return ''
    category_words = set(w.lower() for w in re.findall(r"[A-Za-z]+", category_name or ''))
    number_match = re.search(r'\d+', item_name)
    words = [w for w in re.findall(r"[A-Za-z]+", item_name) if w.lower() not in category_words]
    if not words:
        return ''
    if number_match:
        return f"{words[0][0].upper()}{int(number_match.group()):03d}"
    if len(words) == 1:
        return words[0][:2].upper()
    return ''.join(w[0].upper() for w in words[:4])


def generate_item_code(cur, category_id, item_name):
    """Full Smart Structured Item Code: {CATEGORY_PREFIX}-{SUB_SPEC}-{SEQ:03d},
    or {CATEGORY_PREFIX}-{SEQ:03d} when no sub-spec code applies. Sequence
    is scoped to the whole category (not per sub-spec) -- matches the
    given examples where BW-SZ-001, BW-SZR-002, BW-LL-003 increment
    consecutively across different sub-specs within the same category."""
    cur.execute("SELECT PREFIX, CATEGORY_NAME FROM wst_djn_categories WHERE CATEGORY_ID=:1", [int(category_id)])
    row = cur.fetchone()
    prefix, category_name = (row[0], row[1]) if row else (None, '')
    if not prefix:
        prefix = 'GEN'  # safety net -- should not happen once every category has a prefix

    cur.execute("SELECT COUNT(*) FROM wst_djn_items WHERE CATEGORY_ID=:1", [int(category_id)])
    seq = (cur.fetchone()[0] or 0) + 1

    sub_spec = derive_sub_spec_code(item_name, category_name)
    if sub_spec:
        return f"{prefix}-{sub_spec}-{seq:03d}"
    return f"{prefix}-{seq:03d}"


def insert_item(category_id, name, unit, condition, description, is_active, username=None):
    with get_connection(username) as conn:  # username -> CLIENT_IDENTIFIER -> audit trigger sets CREATED_BY
        with conn.cursor() as cur:
            proper_name = to_proper_case(name)
            item_code = generate_item_code(cur, category_id, proper_name)
            cur.execute("""INSERT INTO wst_djn_items (CATEGORY_ID, ITEM_NAME, UNIT, CONDITION, DESCRIPTION, IS_ACTIVE, ITEM_CODE)
                VALUES (:1,:2,:3,:4,:5,:6,:7)""",
                [int(category_id), proper_name, unit, to_proper_case(condition), to_proper_case(description), 1 if is_active else 0, item_code])
            conn.commit()
            return item_code

def update_item(item_id, category_id, name, unit, condition, description, is_active, username=None):
    with get_connection(username) as conn:  # username -> CLIENT_IDENTIFIER -> audit trigger sets LAST_UPDATED_BY
        with conn.cursor() as cur:
            cur.execute("""UPDATE wst_djn_items SET CATEGORY_ID=:1, ITEM_NAME=:2,
                UNIT=:3, CONDITION=:4, DESCRIPTION=:5, IS_ACTIVE=:6 WHERE ITEM_ID=:7""",
                [int(category_id), to_proper_case(name), unit, to_proper_case(condition), to_proper_case(description), 1 if is_active else 0, int(item_id)])
            conn.commit()

def delete_item(item_id, username=None):
    with get_connection(username) as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM wst_djn_items WHERE ITEM_ID=:1", [int(item_id)])
            conn.commit()


# ─── MONTHLY STOCK LIST ───────────────────────────────────
def fetch_all_stock_list(division=None):
    """division is mandatory row-level security -- always pass request.user.division
    (or None only for sees_all_divisions users)."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            base_sql = """SELECT m.LIST_ID, i.ITEM_NAME,
                TO_CHAR(m.MONTH_YEAR,'Mon-YYYY') AS MONTH_YEAR,
                m.CLOSING_QTY, m.CONDITION, m.DISPATCHED, NVL(m.DIVISION,'08') AS DIVISION
                FROM wst_djn_monthly_stock_list m
                LEFT JOIN wst_djn_items i ON m.ITEM_ID=i.ITEM_ID"""
            if division:
                cur.execute(base_sql + " WHERE NVL(m.DIVISION,'08')=:1 ORDER BY m.LIST_ID DESC", [str(division)])
            else:
                cur.execute(base_sql + " ORDER BY m.LIST_ID DESC")
            cols = [c[0] for c in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]


def fetch_stock_list_summary(division=None):
    """Distinct-item view of the Monthly Stock List: every underlying entry
    for the same item+division+month (however many separate Stock
    Receiving events or manual Add Entry rows contributed to it) is
    collapsed into ONE row with its quantities summed -- matching 'Listed'
    as a per-item total rather than a raw log of individual entries.
    DISPATCHED becomes 'Yes' only when every contributing entry is
    dispatched, 'No' when none are, 'Partial' when mixed."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            base_sql = """SELECT i.ITEM_ID, i.ITEM_NAME,
                    TO_CHAR(m.MONTH_YEAR,'Mon-YYYY') AS MONTH_YEAR,
                    NVL(m.DIVISION,'08') AS DIVISION,
                    SUM(m.CLOSING_QTY) AS TOTAL_QTY,
                    COUNT(*) AS ENTRY_COUNT,
                    SUM(NVL(m.DISPATCHED,0)) AS DISPATCHED_COUNT
                FROM wst_djn_monthly_stock_list m
                LEFT JOIN wst_djn_items i ON m.ITEM_ID=i.ITEM_ID"""
            group_by = " GROUP BY i.ITEM_ID, i.ITEM_NAME, m.MONTH_YEAR, NVL(m.DIVISION,'08')"
            order_by = " ORDER BY m.MONTH_YEAR DESC, i.ITEM_NAME"
            if division:
                cur.execute(base_sql + " WHERE NVL(m.DIVISION,'08')=:1" + group_by + order_by, [str(division)])
            else:
                cur.execute(base_sql + group_by + order_by)
            cols = [c[0] for c in cur.description]
            rows = [dict(zip(cols, row)) for row in cur.fetchall()]
            for r in rows:
                if r['DISPATCHED_COUNT'] == 0:
                    r['DISPATCHED_STATUS'] = 'No'
                elif r['DISPATCHED_COUNT'] == r['ENTRY_COUNT']:
                    r['DISPATCHED_STATUS'] = 'Yes'
                else:
                    r['DISPATCHED_STATUS'] = 'Partial'
            return rows

def fetch_stock_list_by_id(list_id, division=None):
    """division is mandatory row-level security -- when supplied, returns None
    if the record belongs to a different division (IDOR protection)."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            base = """SELECT LIST_ID, ITEM_ID, TO_CHAR(MONTH_YEAR,'YYYY-MM-DD') AS MONTH_YEAR,
                CLOSING_QTY, CONDITION, DISPATCHED, NVL(DIVISION,'08') AS DIVISION
                FROM wst_djn_monthly_stock_list WHERE LIST_ID=:1"""
            if division:
                cur.execute(base + " AND NVL(DIVISION,'08')=:2", [int(list_id), str(division)])
            else:
                cur.execute(base, [int(list_id)])
            cols = [c[0] for c in cur.description]
            row = cur.fetchone()
            return dict(zip(cols, row)) if row else None

def insert_stock_list(item_id, month_year, closing_qty, condition, dispatched, division=None):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""INSERT INTO wst_djn_monthly_stock_list
                (ITEM_ID, MONTH_YEAR, CLOSING_QTY, CONDITION, DISPATCHED, DIVISION)
                VALUES (:1, TO_DATE(:2,'YYYY-MM-DD'), :3, :4, :5, :6)""",
                [int(item_id), str(month_year), float(closing_qty), to_proper_case(condition),
                 1 if dispatched else 0, str(division or '08')])
            conn.commit()

def update_stock_list(list_id, item_id, month_year, closing_qty, condition, dispatched, division=None):
    """Division is immutable after creation, matching the same rule used for
    Receiving/Sales -- the WHERE clause is scoped by division as
    defense-in-depth, not just an app-layer check."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            if division:
                cur.execute("""UPDATE wst_djn_monthly_stock_list SET ITEM_ID=:1,
                    MONTH_YEAR=TO_DATE(:2,'YYYY-MM-DD'), CLOSING_QTY=:3,
                    CONDITION=:4, DISPATCHED=:5 WHERE LIST_ID=:6 AND NVL(DIVISION,'08')=:7""",
                    [int(item_id), str(month_year), float(closing_qty), to_proper_case(condition),
                     1 if dispatched else 0, int(list_id), str(division)])
            else:
                cur.execute("""UPDATE wst_djn_monthly_stock_list SET ITEM_ID=:1,
                    MONTH_YEAR=TO_DATE(:2,'YYYY-MM-DD'), CLOSING_QTY=:3,
                    CONDITION=:4, DISPATCHED=:5 WHERE LIST_ID=:6""",
                    [int(item_id), str(month_year), float(closing_qty), to_proper_case(condition),
                     1 if dispatched else 0, int(list_id)])
            conn.commit()

def delete_stock_list(list_id, division=None):
    with get_connection() as conn:
        with conn.cursor() as cur:
            if division:
                cur.execute("DELETE FROM wst_djn_monthly_stock_list WHERE LIST_ID=:1 AND NVL(DIVISION,'08')=:2",
                            [int(list_id), str(division)])
            else:
                cur.execute("DELETE FROM wst_djn_monthly_stock_list WHERE LIST_ID=:1", [int(list_id)])
            conn.commit()

def upsert_monthly_stock_list_from_receiving(item_id, division, receive_date, qty_received, username=None):
    """Auto-rolling total: every time a Stock Receiving entry is posted, this
    adds the received quantity onto that item+division's CURRENT month's
    Monthly Stock List entry, creating it if this is the first receipt for
    that item this month. This is what makes "Listed" on the home page
    (and the Monthly Stock List screen itself) reflect reality without
    anyone doing a separate manual entry.

    Deliberately does NOT touch CONDITION -- assessing condition is a human
    judgment call, not something a receiving transaction can know, so a
    freshly auto-created row leaves it blank for someone to fill in later.

    Matches the same "receiving saves first, auto-post degrades gracefully"
    philosophy already used for the ledger auto-post in insert_receiving() --
    a failure here is logged but does not roll back the receiving entry
    itself, since by the time this runs the receiving row and ledger/balance
    are already committed."""
    try:
        with get_connection(username) as conn:
            with conn.cursor() as cur:
                cur.execute("""MERGE INTO wst_djn_monthly_stock_list m
                    USING (SELECT :1 AS ITEM_ID, :2 AS DIVISION,
                                  TRUNC(TO_DATE(:3,'YYYY-MM-DD'),'MM') AS MONTH_YEAR FROM DUAL) s
                    ON (m.ITEM_ID = s.ITEM_ID AND NVL(m.DIVISION,'08') = s.DIVISION
                        AND m.MONTH_YEAR = s.MONTH_YEAR)
                    WHEN MATCHED THEN UPDATE SET m.CLOSING_QTY = NVL(m.CLOSING_QTY,0) + :4
                    WHEN NOT MATCHED THEN INSERT (ITEM_ID, DIVISION, MONTH_YEAR, CLOSING_QTY, DISPATCHED)
                        VALUES (:5, :6, TRUNC(TO_DATE(:7,'YYYY-MM-DD'),'MM'), :8, 0)""",
                    [int(item_id), str(division or '08'), str(receive_date), float(qty_received),
                     int(item_id), str(division or '08'), str(receive_date), float(qty_received)])
                conn.commit()
    except oracledb.DatabaseError as e:
        print(f"WARNING: Monthly Stock List auto-rolling upsert failed (item {item_id}, div {division}): {e}")


# ─── STOCK LEDGER ─────────────────────────────────────────
def fetch_all_ledger(division=None):
    """division is mandatory row-level security — always pass request.user.division
    (or None only for sees_all_divisions users)."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            base_sql = """SELECT l.LEDGER_ID, i.ITEM_NAME,
                TO_CHAR(l.TXN_DATE,'DD-Mon-YYYY') AS TXN_DATE,
                l.TXN_TYPE, l.QTY_IN, l.QTY_OUT, l.BALANCE, NVL(l.DIVISION,'08') AS DIVISION
                FROM wst_djn_stock_ledger l
                LEFT JOIN wst_djn_items i ON l.ITEM_ID=i.ITEM_ID"""
            if division:
                cur.execute(base_sql + " WHERE NVL(l.DIVISION,'08')=:1 ORDER BY l.TXN_DATE DESC, l.LEDGER_ID DESC", [str(division)])
            else:
                cur.execute(base_sql + " ORDER BY l.TXN_DATE DESC, l.LEDGER_ID DESC")
            cols = [c[0] for c in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]

def fetch_ledger_by_id(ledger_id, division=None):
    """division is mandatory row-level security — when supplied, returns None
    if the record belongs to a different division (prevents cross-division
    access via a guessed/edited URL, i.e. an IDOR)."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            if division:
                cur.execute("""SELECT LEDGER_ID, ITEM_ID, TO_CHAR(TXN_DATE,'YYYY-MM-DD') AS TXN_DATE,
                    TXN_TYPE, QTY_IN, QTY_OUT, BALANCE, REF_ID, NVL(DIVISION,'08') AS DIVISION
                    FROM wst_djn_stock_ledger WHERE LEDGER_ID=:1 AND NVL(DIVISION,'08')=:2""",
                    [int(ledger_id), str(division)])
            else:
                cur.execute("""SELECT LEDGER_ID, ITEM_ID, TO_CHAR(TXN_DATE,'YYYY-MM-DD') AS TXN_DATE,
                    TXN_TYPE, QTY_IN, QTY_OUT, BALANCE, REF_ID
                    FROM wst_djn_stock_ledger WHERE LEDGER_ID=:1""", [int(ledger_id)])
            cols = [c[0] for c in cur.description]
            row = cur.fetchone()
            return dict(zip(cols, row)) if row else None

def insert_ledger(item_id, txn_date, txn_type, qty_in, qty_out, balance, ref_id, division=None, username=None,
                   source_table=None, source_id=None):
    """NOTE: DIVISION is a NOT NULL column on wst_djn_stock_ledger — it must always be supplied.

    Also populates the richer TRANSACTION_TYPE/SOURCE_REF/SOURCE_TABLE/
    POSTED_BY columns that Sales/Shipment/Gate Pass posting already write
    directly -- without this, rows inserted through this function (used
    by Receiving) had TRANSACTION_TYPE left NULL, so they were silently
    excluded whenever the Stock Ledger screen's own Type filter was used
    (fetch_ledger_view() filters and labels by TRANSACTION_TYPE, not
    TXN_TYPE), even though TXN_TYPE/REF_ID were always correct. Same
    graceful-fallback pattern already used elsewhere in this file for a
    schema where the richer columns don't exist yet."""
    with get_connection(username) as conn:
        with conn.cursor() as cur:
            try:
                cur.execute("""INSERT INTO wst_djn_stock_ledger
                    (ITEM_ID, TXN_DATE, TXN_TYPE, QTY_IN, QTY_OUT, BALANCE, REF_ID, DIVISION,
                     TRANSACTION_TYPE, SOURCE_REF, SOURCE_TABLE, POSTED_BY)
                    VALUES (:1, TO_DATE(:2,'YYYY-MM-DD'), :3, :4, :5, :6, :7, :8,
                            :9, :10, :11, :12)""",
                    [int(item_id), str(txn_date), txn_type,
                     float(qty_in or 0), float(qty_out or 0), float(balance or 0),
                     int(ref_id) if ref_id else None, str(division or '08'),
                     txn_type, (f'{source_table}#{ref_id}' if source_table else None),
                     source_table, username])
            except oracledb.DatabaseError:
                # Richer metadata columns not on this schema yet -- fall back
                # to the core columns this always worked with.
                cur.execute("""INSERT INTO wst_djn_stock_ledger
                    (ITEM_ID, TXN_DATE, TXN_TYPE, QTY_IN, QTY_OUT, BALANCE, REF_ID, DIVISION)
                    VALUES (:1, TO_DATE(:2,'YYYY-MM-DD'), :3, :4, :5, :6, :7, :8)""",
                    [int(item_id), str(txn_date), txn_type,
                     float(qty_in or 0), float(qty_out or 0), float(balance or 0),
                     int(ref_id) if ref_id else None, str(division or '08')])
            conn.commit()

def update_ledger(ledger_id, item_id, txn_date, txn_type, qty_in, qty_out, balance, ref_id, division=None):
    with get_connection() as conn:
        with conn.cursor() as cur:
            if division:
                # Division-scoped WHERE clause: defense-in-depth so this UPDATE physically
                # cannot touch a record outside the caller's division, even if the
                # ownership check upstream were ever bypassed.
                cur.execute("""UPDATE wst_djn_stock_ledger SET ITEM_ID=:1,
                    TXN_DATE=TO_DATE(:2,'YYYY-MM-DD'), TXN_TYPE=:3,
                    QTY_IN=:4, QTY_OUT=:5, BALANCE=:6, REF_ID=:7
                    WHERE LEDGER_ID=:8 AND NVL(DIVISION,'08')=:9""",
                    [int(item_id), str(txn_date), txn_type,
                     float(qty_in or 0), float(qty_out or 0), float(balance or 0),
                     int(ref_id) if ref_id else None, int(ledger_id), str(division)])
            else:
                cur.execute("""UPDATE wst_djn_stock_ledger SET ITEM_ID=:1,
                    TXN_DATE=TO_DATE(:2,'YYYY-MM-DD'), TXN_TYPE=:3,
                    QTY_IN=:4, QTY_OUT=:5, BALANCE=:6, REF_ID=:7
                    WHERE LEDGER_ID=:8""",
                    [int(item_id), str(txn_date), txn_type,
                     float(qty_in or 0), float(qty_out or 0), float(balance or 0),
                     int(ref_id) if ref_id else None, int(ledger_id)])
            conn.commit()

# ─── MANUAL STOCK ADJUSTMENTS (Stock Ledger screen: Add / Edit / Delete) ───
# Receiving and Gate Pass post their own IN/OUT rows. The Stock Ledger
# screen is only for ADJUST entries -- a manual +/- correction that must
# move stock exactly like any other movement:
#   1. write (or change / remove) ONE ledger row,
#   2. re-run the running-balance for that item+division (so every
#      ledger row's BALANCE is right),
#   3. refresh wst_djn_item_balance (TOTAL_IN / TOTAL_OUT / BALANCE shown
#      on the Balance Sheet and used by Gate Pass availability checks),
# all on ONE connection: either everything is saved or nothing is.
# Previously the screen used the bare insert_ledger()/update_ledger()/
# delete_ledger() above, which stored the (read-only, always 0) "balance"
# box from the form and never recalculated anything -- so an Adjust sat in
# the ledger with BALANCE 0 and Item Balance never changed.

def _adjust_friendly_error(e):
    msg = str(e)
    if 'CK_ITEM_BALANCE_NONNEG' in msg.upper() or 'CK_STOCK_LEDGER_NONNEG' in msg.upper():
        return "This adjustment would take the item's stock below zero — nothing was changed."
    return msg


def _validate_adjust_qty(qty_in, qty_out):
    qi = float(qty_in or 0)
    qo = float(qty_out or 0)
    if qi < 0 or qo < 0:
        raise ValueError('Quantities cannot be negative.')
    if qi > 0 and qo > 0:
        raise ValueError('An adjustment is either Qty In (add stock) or Qty Out (reduce stock) — not both.')
    if qi == 0 and qo == 0:
        raise ValueError('Enter a quantity in Qty In (add stock) or Qty Out (reduce stock).')
    return qi, qo


def post_adjustment(item_id, txn_date, qty_in, qty_out, ref_id, division, username=None):
    """Adds a manual ADJUST ledger row and updates ledger balances + Item Balance atomically."""
    qi, qo = _validate_adjust_qty(qty_in, qty_out)
    division = str(division or '08')
    with get_connection(username) as conn:
        with conn.cursor() as cur:
            try:
                try:
                    cur.execute("""INSERT INTO wst_djn_stock_ledger
                        (ITEM_ID, TXN_DATE, TXN_TYPE, QTY_IN, QTY_OUT, BALANCE, REF_ID, DIVISION,
                         TRANSACTION_TYPE, SOURCE_REF, SOURCE_TABLE, POSTED_BY)
                        VALUES (:1, TO_DATE(:2,'YYYY-MM-DD'), 'ADJUST', :3, :4, 0, :5, :6,
                                'ADJUST', 'MANUAL_ADJUST', 'MANUAL_ADJUST', :7)""",
                        [int(item_id), str(txn_date), qi, qo,
                         int(ref_id) if ref_id else None, division, username])
                except oracledb.DatabaseError as e:
                    # Only fall back when the richer columns are missing; a
                    # real failure (e.g. non-negative check) must surface.
                    if 'ORA-00904' not in str(e):
                        raise
                    cur.execute("""INSERT INTO wst_djn_stock_ledger
                        (ITEM_ID, TXN_DATE, TXN_TYPE, QTY_IN, QTY_OUT, BALANCE, REF_ID, DIVISION)
                        VALUES (:1, TO_DATE(:2,'YYYY-MM-DD'), 'ADJUST', :3, :4, 0, :5, :6)""",
                        [int(item_id), str(txn_date), qi, qo,
                         int(ref_id) if ref_id else None, division])
                _recalc_item_balance(cur, item_id, division, txn_date, 'ADJUST', qi, qo)
                conn.commit()
            except Exception as e:
                conn.rollback()
                raise ValueError(_adjust_friendly_error(e))


def update_adjustment(ledger_id, item_id, txn_date, qty_in, qty_out, ref_id, division, username=None):
    """Edits a manual ADJUST row, then recalculates BOTH the old and the new
    item (if the item was changed) so no stale balance is left behind."""
    qi, qo = _validate_adjust_qty(qty_in, qty_out)
    division = str(division or '08')
    with get_connection(username) as conn:
        with conn.cursor() as cur:
            try:
                cur.execute("""SELECT ITEM_ID, TXN_TYPE FROM wst_djn_stock_ledger
                               WHERE LEDGER_ID=:1 AND NVL(DIVISION,'08')=:2""",
                            [int(ledger_id), division])
                old = cur.fetchone()
                if not old:
                    raise ValueError('Ledger entry not found.')
                if (old[1] or '').upper() != 'ADJUST':
                    raise ValueError('Only manual Adjust entries can be edited here. '
                                     'Receiving and Gate Pass movements are changed from their own screens.')
                old_item = int(old[0])
                cur.execute("""UPDATE wst_djn_stock_ledger SET ITEM_ID=:1,
                        TXN_DATE=TO_DATE(:2,'YYYY-MM-DD'), QTY_IN=:3, QTY_OUT=:4, REF_ID=:5
                        WHERE LEDGER_ID=:6 AND NVL(DIVISION,'08')=:7""",
                        [int(item_id), str(txn_date), qi, qo,
                         int(ref_id) if ref_id else None, int(ledger_id), division])
                if old_item != int(item_id):
                    _recalc_item_balance(cur, old_item, division, txn_date, 'ADJUST', 0, 0)
                _recalc_item_balance(cur, item_id, division, txn_date, 'ADJUST', qi, qo)
                conn.commit()
            except Exception as e:
                conn.rollback()
                raise ValueError(_adjust_friendly_error(e))


def delete_adjustment(ledger_id, division, username=None):
    """Deletes a manual ADJUST row (reversing its effect) and recalculates the item."""
    division = str(division or '08')
    with get_connection(username) as conn:
        with conn.cursor() as cur:
            try:
                cur.execute("""SELECT ITEM_ID, TXN_TYPE, TO_CHAR(TXN_DATE,'YYYY-MM-DD')
                               FROM wst_djn_stock_ledger
                               WHERE LEDGER_ID=:1 AND NVL(DIVISION,'08')=:2""",
                            [int(ledger_id), division])
                old = cur.fetchone()
                if not old:
                    raise ValueError('Ledger entry not found.')
                if (old[1] or '').upper() != 'ADJUST':
                    raise ValueError('Only manual Adjust entries can be deleted here. '
                                     'Receiving and Gate Pass movements are reversed from their own screens.')
                cur.execute("DELETE FROM wst_djn_stock_ledger WHERE LEDGER_ID=:1 AND NVL(DIVISION,'08')=:2",
                            [int(ledger_id), division])
                _recalc_item_balance(cur, old[0], division, old[2], 'ADJUST', 0, 0)
                conn.commit()
            except Exception as e:
                conn.rollback()
                raise ValueError(_adjust_friendly_error(e))


def delete_ledger(ledger_id, division=None):
    with get_connection() as conn:
        with conn.cursor() as cur:
            if division:
                cur.execute("DELETE FROM wst_djn_stock_ledger WHERE LEDGER_ID=:1 AND NVL(DIVISION,'08')=:2",
                            [int(ledger_id), str(division)])
            else:
                cur.execute("DELETE FROM wst_djn_stock_ledger WHERE LEDGER_ID=:1", [int(ledger_id)])
            conn.commit()


# ─── QUOTATIONS ───────────────────────────────────────────
def fetch_all_quotations():
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""SELECT q.QUOTE_ID, v.VENDOR_NAME, i.ITEM_NAME,
                q.RATE_PER_UNIT, TO_CHAR(q.QUOTE_DATE,'DD-Mon-YYYY') AS QUOTE_DATE, q.REMARKS
                FROM wst_djn_quotations q
                LEFT JOIN wst_djn_vendors v ON q.VENDOR_ID=v.VENDOR_ID
                LEFT JOIN wst_djn_items i ON q.ITEM_ID=i.ITEM_ID
                ORDER BY q.QUOTE_ID DESC""")
            cols = [c[0] for c in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]

def fetch_quotation_by_id(quote_id):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""SELECT QUOTE_ID, LIST_ID, VENDOR_ID, ITEM_ID, RATE_PER_UNIT,
                TO_CHAR(QUOTE_DATE,'YYYY-MM-DD') AS QUOTE_DATE, REMARKS
                FROM wst_djn_quotations WHERE QUOTE_ID=:1""", [int(quote_id)])
            cols = [c[0] for c in cur.description]
            row = cur.fetchone()
            return dict(zip(cols, row)) if row else None

def insert_quotation(list_id, vendor_id, item_id, rate, quote_date, remarks):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""INSERT INTO wst_djn_quotations
                (LIST_ID, VENDOR_ID, ITEM_ID, RATE_PER_UNIT, QUOTE_DATE, REMARKS)
                VALUES (:1,:2,:3,:4,TO_DATE(:5,'YYYY-MM-DD'),:6)""",
                [int(list_id), int(vendor_id), int(item_id), float(rate), str(quote_date), to_proper_case(remarks)])
            conn.commit()

def update_quotation(quote_id, list_id, vendor_id, item_id, rate, quote_date, remarks):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""UPDATE wst_djn_quotations SET LIST_ID=:1, VENDOR_ID=:2,
                ITEM_ID=:3, RATE_PER_UNIT=:4, QUOTE_DATE=TO_DATE(:5,'YYYY-MM-DD'), REMARKS=:6
                WHERE QUOTE_ID=:7""",
                [int(list_id), int(vendor_id), int(item_id), float(rate), str(quote_date), to_proper_case(remarks), int(quote_id)])
            conn.commit()

def delete_quotation(quote_id):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM wst_djn_quotations WHERE QUOTE_ID=:1", [int(quote_id)])
            conn.commit()


# ─── QUOTATION HEADER / LINE (Master-Detail) ──────────────
# Replaces the legacy flat wst_djn_quotations table above for all NEW
# quotation activity. Mirrors the Sales Header/Line architecture: a
# doc-numbered header, auto-sequenced (10,20,30...) line items.
#
# CRITICAL RULE: line items are constrained to whatever appears in the
# selected month's Monthly Stock List SNAPSHOT (wst_djn_msl_snapshot_line)
# -- fetch_quotation_available_items() is the single source of truth for
# "what's selectable", and item_code/uom/offered_qty are frozen onto each
# line at add-time from that same snapshot data.

def generate_quotation_doc_id(cur, year=None):
    """Format: QUO-YYYY-NNNN, same collision-safety note as Sales'
    generate_doc_id() -- a UNIQUE PK makes a same-instant collision a safe
    failure (retry), not a silent duplicate."""
    yr = year or date.today().year
    prefix = f'QUO-{yr}-'
    cur.execute("SELECT MAX(QUOTE_DOC_ID) FROM wst_djn_quotation_header WHERE QUOTE_DOC_ID LIKE :1", [prefix + '%'])
    row = cur.fetchone()
    last = row[0] if row else None
    last_n = int(last.split('-')[-1]) if last else 0
    return f'{prefix}{last_n + 1:04d}'


def fetch_quotation_available_items(division, target_month):
    """The CRITICAL item filter: returns only the items that were actually
    listed in the selected month's Monthly Stock List snapshot for this
    division. Returns an empty list (not an error) if no snapshot exists
    yet for that month -- the view layer is expected to tell the user to
    generate one first, since there's nothing to quote against otherwise."""
    snapshot = fetch_msl_snapshot_for_month(division, target_month)
    if not snapshot:
        return [], None
    return fetch_msl_snapshot_lines(snapshot['SNAPSHOT_ID']), snapshot


def fetch_last_month_price(item_id, division, target_month):
    """'Last Month Price' -- the most recently quoted Current Offered Price
    for this item, from any quotation header in the PREVIOUS month for
    this division. Purely a live reference lookup, not stored on the line
    itself -- it can legitimately show something different each time this
    is viewed if more quotes come in, unlike offered_qty/uom which are
    frozen at the moment a line is added."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""SELECT ql.CURRENT_OFFERED_PRICE
                FROM wst_djn_quotation_line ql
                JOIN wst_djn_quotation_header qh ON ql.QUOTE_DOC_ID = qh.QUOTE_DOC_ID
                WHERE ql.ITEM_ID = :1 AND qh.DIVISION = :2
                  AND qh.TARGET_MONTH = ADD_MONTHS(TRUNC(TO_DATE(:3,'YYYY-MM-DD'),'MM'), -1)
                ORDER BY qh.CREATED_DATE DESC
                FETCH FIRST 1 ROW ONLY""",
                [int(item_id), str(division), str(target_month)])
            row = cur.fetchone()
            return float(row[0]) if row and row[0] is not None else None


def fetch_all_quotation_headers(division=None, month=None):
    """month is 'YYYY-MM-DD' (any day within the target month, matching
    the pattern used elsewhere in this app) -- filters to headers whose
    TARGET_MONTH falls in that month."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            base_sql = """SELECT h.QUOTE_DOC_ID, h.DIVISION, h.VENDOR_ID, v.VENDOR_NAME, v.CNIC_ATTACHMENT_PATH,
                    NVL(h.STATUS,'Open') AS STATUS,
                    TO_CHAR(h.TARGET_MONTH,'Mon-YYYY') AS TARGET_MONTH_DISPLAY,
                    h.REFERENCE_NO, TO_CHAR(h.RECEIVE_DATE,'DD-Mon-YYYY') AS RECEIVE_DATE,
                    TO_CHAR(h.VALID_UNTIL,'DD-Mon-YYYY') AS VALID_UNTIL,
                    (SELECT COUNT(*) FROM wst_djn_quotation_line l WHERE l.QUOTE_DOC_ID = h.QUOTE_DOC_ID) AS LINE_COUNT
                FROM wst_djn_quotation_header h
                LEFT JOIN wst_djn_vendors v ON h.VENDOR_ID = v.VENDOR_ID"""
            where, params = [], []
            if division:
                params.append(str(division)); where.append(f"h.DIVISION = :{len(params)}")
            if month:
                params.append(str(month)); where.append(f"TRUNC(h.TARGET_MONTH,'MM') = TRUNC(TO_DATE(:{len(params)},'YYYY-MM-DD'),'MM')")
            w = (" WHERE " + " AND ".join(where)) if where else ""
            cur.execute(base_sql + w + " ORDER BY h.QUOTE_DOC_ID DESC", params)
            cols = [c[0] for c in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]


def fetch_quotation_header_by_id(doc_id, division=None):
    """division is mandatory row-level security -- when supplied, returns
    None if the header belongs to a different division (IDOR protection)."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            base = """SELECT h.QUOTE_DOC_ID, h.DIVISION, h.VENDOR_ID, v.VENDOR_NAME, NVL(h.STATUS,'Open') AS STATUS,
                    TO_CHAR(h.TARGET_MONTH,'YYYY-MM-DD') AS TARGET_MONTH,
                    TO_CHAR(h.TARGET_MONTH,'Month YYYY') AS TARGET_MONTH_DISPLAY,
                    h.REFERENCE_NO,
                    TO_CHAR(h.RECEIVE_DATE,'YYYY-MM-DD') AS RECEIVE_DATE,
                    TO_CHAR(h.VALID_UNTIL,'YYYY-MM-DD') AS VALID_UNTIL,
                    h.REMARKS, h.CREATED_BY, TO_CHAR(h.CREATED_DATE,'DD-Mon-YYYY HH24:MI') AS CREATED_DATE
                FROM wst_djn_quotation_header h LEFT JOIN wst_djn_vendors v ON h.VENDOR_ID=v.VENDOR_ID
                WHERE h.QUOTE_DOC_ID = :1"""
            if division:
                cur.execute(base + " AND h.DIVISION = :2", [doc_id, str(division)])
            else:
                cur.execute(base, [doc_id])
            cols = [c[0] for c in cur.description]
            row = cur.fetchone()
            if not row:
                return None
            result = dict(zip(cols, row))
            result['TARGET_MONTH_DISPLAY'] = result['TARGET_MONTH_DISPLAY'].strip()
            return result


def fetch_quotation_lines(doc_id, division=None, target_month=None):
    """Returns the saved lines PLUS a live-computed LAST_MONTH_PRICE for
    each (division/target_month are needed for that lookup -- if not
    supplied, LAST_MONTH_PRICE is omitted rather than guessed)."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""SELECT l.LINE_ID, l.LINE_NO, l.ITEM_ID, i.ITEM_CODE, i.ITEM_NAME,
                    l.UOM, l.OFFERED_QTY, l.CURRENT_OFFERED_PRICE, NVL(l.STATUS,'Open') AS STATUS
                FROM wst_djn_quotation_line l LEFT JOIN wst_djn_items i ON l.ITEM_ID=i.ITEM_ID
                WHERE l.QUOTE_DOC_ID = :1 ORDER BY l.LINE_NO""", [doc_id])
            cols = [c[0] for c in cur.description]
            lines = [dict(zip(cols, row)) for row in cur.fetchall()]
    if division and target_month:
        for l in lines:
            l['LAST_MONTH_PRICE'] = fetch_last_month_price(l['ITEM_ID'], division, target_month)
    return lines


def insert_quotation_header(division, target_month, vendor_id, reference_no, receive_date, valid_until, remarks, username=None):
    with get_connection(username) as conn:
        with conn.cursor() as cur:
            try:
                doc_id = generate_quotation_doc_id(cur)
                cur.execute("""INSERT INTO wst_djn_quotation_header
                    (QUOTE_DOC_ID, DIVISION, TARGET_MONTH, VENDOR_ID, REFERENCE_NO,
                     RECEIVE_DATE, VALID_UNTIL, REMARKS, CREATED_BY, CREATED_DATE)
                    VALUES (:1, :2, TRUNC(TO_DATE(:3,'YYYY-MM-DD'),'MM'), :4, :5,
                            TO_DATE(:6,'YYYY-MM-DD'), TO_DATE(:7,'YYYY-MM-DD'), :8, :9, SYSDATE)""",
                    [doc_id, str(division), str(target_month), int(vendor_id), reference_no,
                     str(receive_date), str(valid_until), to_proper_case(remarks), username])
                conn.commit()
                return doc_id
            except oracledb.DatabaseError as e:
                if 'UQ_WST_DJN_QUOTATION_HEADER' in str(e).upper():
                    # Translated, not just re-raised, so the raw Oracle
                    # constraint name never has to reach the screen --
                    # matches the same approach already used elsewhere in
                    # this file (e.g. post_gate_pass's negative-balance
                    # translation) rather than leaving this one unguarded.
                    raise ValueError(
                        'A Quotation already exists for this vendor, division, and month — '
                        'open the existing one from the Quotations list instead of creating a new one.'
                    )
                raise


def insert_quotation_line(doc_id, item_id, item_code, uom, offered_qty, current_offered_price):
    """Auto-sequences line_no = NVL(MAX(line_no),0) + 10 for this document.
    A UNIQUE constraint on (quote_doc_id, item_id) prevents the same item
    being quoted twice within one header -- callers should catch that as a
    friendly 'already quoted' message rather than a raw DB error. Refuses
    to add a line to a Locked quotation -- returns None rather than
    raising, so callers can show a friendly message."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT NVL(STATUS,'Open') FROM wst_djn_quotation_header WHERE QUOTE_DOC_ID=:1", [doc_id])
            row = cur.fetchone()
            if not row or row[0] == 'Locked':
                return None
            cur.execute("SELECT NVL(MAX(LINE_NO),0)+10 FROM wst_djn_quotation_line WHERE QUOTE_DOC_ID=:1", [doc_id])
            line_no = cur.fetchone()[0]
            cur.execute("""INSERT INTO wst_djn_quotation_line
                (QUOTE_DOC_ID, LINE_NO, ITEM_ID, ITEM_CODE, UOM, OFFERED_QTY, CURRENT_OFFERED_PRICE)
                VALUES (:1,:2,:3,:4,:5,:6,:7)""",
                [doc_id, line_no, int(item_id), item_code, uom, float(offered_qty), float(current_offered_price)])
            conn.commit()
            return line_no


def update_quotation_line_price(line_id, doc_id, current_offered_price):
    """Edits a quotation line's offered price -- covers the case where a
    vendor revises their bid upward during negotiation to win an item.
    Refuses to edit a line that is itself Locked -- checked at the LINE
    level, not the header level, matching delete_quotation_line()'s same
    reasoning: a header can be partially locked (some items already
    routed to Sales, others still open), so a line's own status is what
    actually governs whether it can still change.
    Returns False rather than raising if the line doesn't exist or is
    locked, so the view can show a friendly message."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT NVL(STATUS,'Open') FROM wst_djn_quotation_line WHERE LINE_ID=:1 AND QUOTE_DOC_ID=:2", [int(line_id), doc_id])
            row = cur.fetchone()
            if not row or row[0] == 'Locked':
                return False
            cur.execute("UPDATE wst_djn_quotation_line SET CURRENT_OFFERED_PRICE=:1 WHERE LINE_ID=:2 AND QUOTE_DOC_ID=:3",
                        [float(current_offered_price), int(line_id), doc_id])
            conn.commit()
            return True


def delete_quotation_line(line_id, doc_id):
    """Refuses to delete a line that is itself Locked -- returns False
    rather than silently doing nothing or raising. Checked at the LINE
    level, not the header level, since a header can now be partially
    locked (some items routed to Sales, others still open)."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT NVL(STATUS,'Open') FROM wst_djn_quotation_line WHERE LINE_ID=:1 AND QUOTE_DOC_ID=:2", [int(line_id), doc_id])
            row = cur.fetchone()
            if not row or row[0] == 'Locked':
                return False
            cur.execute("DELETE FROM wst_djn_quotation_line WHERE LINE_ID=:1 AND QUOTE_DOC_ID=:2", [int(line_id), doc_id])
            conn.commit()
            return True


def delete_quotation_header(doc_id, division=None):
    """Hard-deletes the header + all its lines. division is mandatory
    row-level security when supplied (IDOR protection). Also refuses to
    delete a Locked quotation."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            if division:
                cur.execute("SELECT QUOTE_DOC_ID FROM wst_djn_quotation_header WHERE QUOTE_DOC_ID=:1 AND DIVISION=:2",
                            [doc_id, str(division)])
                if not cur.fetchone():
                    return False
            cur.execute("SELECT NVL(STATUS,'Open') FROM wst_djn_quotation_header WHERE QUOTE_DOC_ID=:1", [doc_id])
            row = cur.fetchone()
            if not row or row[0] == 'Locked':
                return False
            cur.execute("DELETE FROM wst_djn_quotation_line WHERE QUOTE_DOC_ID=:1", [doc_id])
            cur.execute("DELETE FROM wst_djn_quotation_header WHERE QUOTE_DOC_ID=:1", [doc_id])
            conn.commit()
            return True


# ─── QUOTATION COMPARISON ─────────────────────────────────
# Compares every vendor's bid for each item quoted in a given
# division+month, ranks them, and lets management pick a winner --
# manually overriding the system's suggested Best Bid when needed.

def fetch_quotation_comparison_items(division, target_month):
    """Only items that actually received at least one bid this
    division+month appear (the CRITICAL item-filter rule) -- fetches every
    bid for the period in one query, then groups/ranks in Python since we
    need each item's bids sorted descending with the top 3 broken out,
    which is simpler to get right (and to test) as a grouping pass than
    as a window-function query. Returns a list of dicts, each with
    ITEM_ID/ITEM_CODE/ITEM_NAME/UOM and a BIDS list (all bidders, sorted
    highest price first)."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""SELECT ql.ITEM_ID, i.ITEM_CODE, i.ITEM_NAME, ql.UOM, ql.OFFERED_QTY,
                    v.VENDOR_ID, v.VENDOR_NAME, ql.CURRENT_OFFERED_PRICE, NVL(ql.STATUS,'Open') AS LINE_STATUS
                FROM wst_djn_quotation_line ql
                JOIN wst_djn_quotation_header qh ON ql.QUOTE_DOC_ID = qh.QUOTE_DOC_ID
                JOIN wst_djn_vendors v ON qh.VENDOR_ID = v.VENDOR_ID
                LEFT JOIN wst_djn_items i ON ql.ITEM_ID = i.ITEM_ID
                WHERE qh.DIVISION = :1 AND qh.TARGET_MONTH = TRUNC(TO_DATE(:2,'YYYY-MM-DD'),'MM')
                ORDER BY ql.ITEM_ID, ql.CURRENT_OFFERED_PRICE DESC""",
                [str(division), str(target_month)])
            cols = [c[0] for c in cur.description]
            raw_rows = [dict(zip(cols, row)) for row in cur.fetchall()]

            # For every locked item, whether its sales doc(s) this
            # division+month are still all DRAFT (=> Unlock is safe/
            # offered) or any is already POSTED (=> Unlock isn't offered;
            # cancelling the shipment is the correct path instead). An
            # item with NO sales lines at all is treated as unlockable
            # too -- nothing on the Sales side to conflict with.
            cur.execute("""SELECT sl.ITEM_ID, sh.STATUS FROM wst_djn_sales_line sl
                JOIN wst_djn_sales_header sh ON sl.DOC_ID = sh.DOC_ID
                WHERE sh.DIVISION=:1 AND sh.SOURCE_TARGET_MONTH=TRUNC(TO_DATE(:2,'YYYY-MM-DD'),'MM')
                  AND sh.STATUS != 'CANCELLED'""",
                [str(division), str(target_month)])
            non_draft_items = {row[0] for row in cur.fetchall() if row[1] != 'DRAFT'}

    items = {}
    order = []
    for r in raw_rows:
        iid = r['ITEM_ID']
        if iid not in items:
            items[iid] = {
                'ITEM_ID': iid, 'ITEM_CODE': r['ITEM_CODE'], 'ITEM_NAME': r['ITEM_NAME'], 'UOM': r['UOM'],
                'OFFERED_QTY': r['OFFERED_QTY'],
                'BIDS': [], 'IS_LOCKED': False, 'IS_UNLOCKABLE': False,
            }
            order.append(iid)
        items[iid]['BIDS'].append({'VENDOR_ID': r['VENDOR_ID'], 'VENDOR_NAME': r['VENDOR_NAME'], 'PRICE': r['CURRENT_OFFERED_PRICE']})
        if r['LINE_STATUS'] == 'Locked':
            # Consistent with generate_sales_from_comparison()'s own
            # already-locked check: if ANY bid on this item was locked, the
            # item is treated as already processed -- even if a brand new
            # bid arrives afterward, it should not reopen an item that's
            # already been routed to Sales.
            items[iid]['IS_LOCKED'] = True
            items[iid]['IS_UNLOCKABLE'] = iid not in non_draft_items
    return [items[iid] for iid in order]


def fetch_effective_winner(item_id, division, target_month):
    """The 'winner' for a given item+division+month: a manual selection
    if one was ever made, otherwise the system Best Bid (the highest
    bidder that period) as a fallback -- so Last Month Winner is always
    correct whether or not management actually overrode anything last
    month. Returns None if the item had no bids at all that period."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""SELECT v.VENDOR_NAME, s.SELECTED_PRICE
                FROM wst_djn_quote_comparison_sel s JOIN wst_djn_vendors v ON s.VENDOR_ID = v.VENDOR_ID
                WHERE s.ITEM_ID=:1 AND s.DIVISION=:2 AND s.TARGET_MONTH=TRUNC(TO_DATE(:3,'YYYY-MM-DD'),'MM')""",
                [int(item_id), str(division), str(target_month)])
            row = cur.fetchone()
            if row:
                return {'VENDOR_NAME': row[0], 'PRICE': row[1]}

            cur.execute("""SELECT v.VENDOR_NAME, ql.CURRENT_OFFERED_PRICE
                FROM wst_djn_quotation_line ql
                JOIN wst_djn_quotation_header qh ON ql.QUOTE_DOC_ID = qh.QUOTE_DOC_ID
                JOIN wst_djn_vendors v ON qh.VENDOR_ID = v.VENDOR_ID
                WHERE ql.ITEM_ID=:1 AND qh.DIVISION=:2 AND qh.TARGET_MONTH=TRUNC(TO_DATE(:3,'YYYY-MM-DD'),'MM')
                ORDER BY ql.CURRENT_OFFERED_PRICE DESC FETCH FIRST 1 ROW ONLY""",
                [int(item_id), str(division), str(target_month)])
            row = cur.fetchone()
            return {'VENDOR_NAME': row[0], 'PRICE': row[1]} if row else None


def fetch_yearly_high(item_id, year):
    """Yearly High figure + its info-modal detail, per the updated
    business rules (real dispatch price takes priority over quotation
    bids):

      1. PRIMARY -- any real Gate Pass dispatch against this item, this
         calendar year (partial or fully-completed, doesn't matter):
         highest wst_djn_sales_line.UNIT_PRICE among the sales lines
         that actually had a Gate Pass posted against them.

         RETIRED->REPLACED: this used to read wst_djn_shipment_line from
         the atomic "Ship and Post" path, since retired -- Sales Orders
         are now fulfilled exclusively via Gate Pass, so this checks
         wst_djn_gatepass_line/header instead. STATUS='Posted' AND
         GATEPASS_QTY>0 are checked together, same reasoning as before:
         a Draft Gate Pass has never moved stock, and this stays correct
         even if some future cancellation path only updates one of the
         two.

      2. FALLBACK -- nothing was actually dispatched this year (order
         never shipped, or closed/cancelled before shipping): highest
         quotation bid for this item over a rolling 12-month window
         ending at the current month.

    Both paths stay cross-division, matching this figure's original
    'Cross-Division Highest Bid' design -- only the price SOURCE
    changed, not that scope.

    Adds one new key vs. the old version: SOURCE ('Gate Pass' or
    'Quotation'), so the info modal can show which rule produced the
    figure. Purely additive -- nothing that reads the existing keys
    breaks.
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            # RETIRED->REPLACED: this used to read wst_djn_shipment_line
            # (the atomic "Ship and Post" path's own dedicated shipment
            # record). Sales Orders are now fulfilled exclusively via Gate
            # Pass, so "real shipment activity" now means a POSTED Gate
            # Pass line against this item, not a Shipment record --
            # nothing creates those anymore, so the old query would have
            # gone permanently blind to every future dispatch. The INNER
            # JOIN on gl.SO_LINE_ID naturally excludes Transfer-module gate
            # passes (SO_LINE_ID is NULL for those) -- only Shipment-module
            # gate passes tied to a real Sales Order line count here, same
            # scope as the old Shipment-based check.
            cur.execute("""SELECT gh.DIVISION, TO_CHAR(gh.GATE_PASS_DATE,'Month YYYY') AS MONTH_DISPLAY,
                    v.VENDOR_NAME, sl.UNIT_PRICE
                FROM wst_djn_gatepass_line gl
                JOIN wst_djn_gatepass_header gh ON gl.GATE_PASS_ID = gh.GATE_PASS_ID
                JOIN wst_djn_sales_line sl ON gl.SO_LINE_ID = sl.LINE_ID
                JOIN wst_djn_sales_header sah ON sl.DOC_ID = sah.DOC_ID
                JOIN wst_djn_vendors v ON sah.VENDOR_ID = v.VENDOR_ID
                WHERE gl.ITEM_ID=:1 AND gh.STATUS='Posted' AND gl.GATEPASS_QTY > 0
                  AND EXTRACT(YEAR FROM gh.GATE_PASS_DATE)=:2
                ORDER BY sl.UNIT_PRICE DESC FETCH FIRST 1 ROW ONLY""",
                [int(item_id), int(year)])
            row = cur.fetchone()
            if row:
                return {'DIVISION': row[0], 'MONTH_DISPLAY': row[1].strip(),
                        'VENDOR_NAME': row[2], 'PRICE': row[3], 'SOURCE': 'Gate Pass'}

            cur.execute("""SELECT qh.DIVISION, TO_CHAR(qh.TARGET_MONTH,'Month YYYY') AS MONTH_DISPLAY,
                    v.VENDOR_NAME, ql.CURRENT_OFFERED_PRICE
                FROM wst_djn_quotation_line ql
                JOIN wst_djn_quotation_header qh ON ql.QUOTE_DOC_ID = qh.QUOTE_DOC_ID
                JOIN wst_djn_vendors v ON qh.VENDOR_ID = v.VENDOR_ID
                WHERE ql.ITEM_ID=:1
                  AND qh.TARGET_MONTH >= ADD_MONTHS(TRUNC(SYSDATE,'MM'), -11)
                  AND qh.TARGET_MONTH <= TRUNC(SYSDATE,'MM')
                ORDER BY ql.CURRENT_OFFERED_PRICE DESC FETCH FIRST 1 ROW ONLY""",
                [int(item_id)])
            row = cur.fetchone()
            if not row:
                return None
            return {'DIVISION': row[0], 'MONTH_DISPLAY': row[1].strip(),
                    'VENDOR_NAME': row[2], 'PRICE': row[3], 'SOURCE': 'Quotation'}


def fetch_comparison_selection(item_id, division, target_month):
    """The raw manual-selection row for this exact item+period, if any --
    used to pre-select the override dropdown with whatever was last
    saved."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""SELECT VENDOR_ID, SELECTED_PRICE FROM wst_djn_quote_comparison_sel
                WHERE ITEM_ID=:1 AND DIVISION=:2 AND TARGET_MONTH=TRUNC(TO_DATE(:3,'YYYY-MM-DD'),'MM')""",
                [int(item_id), str(division), str(target_month)])
            row = cur.fetchone()
            return {'VENDOR_ID': row[0], 'SELECTED_PRICE': row[1]} if row else None


def prev_month_str(target_month):
    """target_month is 'YYYY-MM-01' (or any day of that month) -> the same
    format for the month immediately before it. Lives here rather than in
    views.py/pdf_reports.py because BOTH of those need it and both had
    their own private copy; oracle_data.py is imported by each of them and
    imports neither, so this is the only spot that breaks the duplication
    without creating a circular import."""
    d = date.fromisoformat(str(target_month)[:10])
    if d.month == 1:
        return date(d.year - 1, 12, 1).isoformat()
    return date(d.year, d.month - 1, 1).isoformat()


def build_comparison_rows(division, target_month):
    """The single source of truth for a Quotation Comparison grid.

    fetch_quotation_comparison_items() returns only the raw bids; every
    derived column the page actually shows -- VENDOR1/2/3, Last Month
    Winner, Yearly High, Best Bid and the effective manual selection --
    was previously computed in a loop inside views.quotation_comparison()
    and a SECOND, non-matching loop inside pdf_reports. That guaranteed
    the PDF could never be a true 'as-is' copy of the screen: the PDF's
    copy skipped Vendor 3 and skipped the manual selection entirely, so
    an overridden vendor showed on screen but not in the export.

    Both callers now use this, so the two can no longer drift apart.
    Returns the same list of dicts the template has always consumed --
    the keys and their meanings are unchanged."""
    prev_month = prev_month_str(target_month)
    current_year = int(str(target_month)[:4])

    items = fetch_quotation_comparison_items(division, target_month)
    for item in items:
        bids = item['BIDS']
        item['VENDOR1'] = bids[0] if len(bids) > 0 else None
        item['VENDOR2'] = bids[1] if len(bids) > 1 else None
        item['VENDOR3'] = bids[2] if len(bids) > 2 else None
        item['LAST_MONTH_WINNER'] = fetch_effective_winner(item['ITEM_ID'], division, prev_month)
        item['YEARLY_HIGH'] = fetch_yearly_high(item['ITEM_ID'], current_year)
        item['BEST_BID'] = item['VENDOR1']  # system default: the top bidder this month
        current_selection = fetch_comparison_selection(item['ITEM_ID'], division, target_month)
        item['SELECTED_VENDOR_ID'] = current_selection['VENDOR_ID'] if current_selection else None
        item['EFFECTIVE_SELECTED_VENDOR_ID'] = (
            item['SELECTED_VENDOR_ID']
            or (item['BEST_BID']['VENDOR_ID'] if item['BEST_BID'] else None)
        )
        # Resolved here rather than re-derived by each renderer: the
        # vendor/price the item would actually be routed to right now.
        item['EFFECTIVE_SELECTED_BID'] = next(
            (b for b in bids if b['VENDOR_ID'] == item['EFFECTIVE_SELECTED_VENDOR_ID']), None
        )
    return items


def save_comparison_selection(item_id, division, target_month, vendor_id, price, username=None):
    """Upsert the manual override for this item+division+month."""
    with get_connection(username) as conn:
        with conn.cursor() as cur:
            cur.execute("""SELECT SELECTION_ID FROM wst_djn_quote_comparison_sel
                WHERE ITEM_ID=:1 AND DIVISION=:2 AND TARGET_MONTH=TRUNC(TO_DATE(:3,'YYYY-MM-DD'),'MM')""",
                [int(item_id), str(division), str(target_month)])
            existing = cur.fetchone()
            if existing:
                cur.execute("""UPDATE wst_djn_quote_comparison_sel
                    SET VENDOR_ID=:1, SELECTED_PRICE=:2, UPDATED_BY=:3, UPDATED_DATE=SYSDATE
                    WHERE SELECTION_ID=:4""",
                    [int(vendor_id), float(price), username, existing[0]])
            else:
                cur.execute("""INSERT INTO wst_djn_quote_comparison_sel
                    (ITEM_ID, DIVISION, TARGET_MONTH, VENDOR_ID, SELECTED_PRICE, CREATED_BY, CREATED_DATE)
                    VALUES (:1, :2, TRUNC(TO_DATE(:3,'YYYY-MM-DD'),'MM'), :4, :5, :6, SYSDATE)""",
                    [int(item_id), str(division), str(target_month), int(vendor_id), float(price), username])
            conn.commit()


def is_period_locked(division, target_month):
    """True if ANY quotation for this division+month is already Locked --
    used both to block re-triggering Lock & Generate Sales and to decide
    whether the Comparison page should even show the action at all."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""SELECT COUNT(*) FROM wst_djn_quotation_header
                WHERE DIVISION=:1 AND TARGET_MONTH=TRUNC(TO_DATE(:2,'YYYY-MM-DD'),'MM') AND NVL(STATUS,'Open')='Locked'""",
                [str(division), str(target_month)])
            return cur.fetchone()[0] > 0


def _release_quotation_lock(cur, item_id, division, target_month):
    """Shared by every reverse-flow path that needs to release a Quotation
    Comparison lock for one item+division+month: resets that item's
    quotation lines back to Open, clears any manual selection override,
    and re-evaluates the derived header-level status for every quotation
    header touched -- the exact mirror of the locking logic in
    generate_sales_from_comparison() below. Uses the SAME connection/
    cursor as the caller's own transaction; no independent commit here,
    the caller commits once at the end alongside whatever else it's
    doing (reversing stock, deleting a sales line, etc), so a partial
    failure can't leave the quotation lock released but the sales side
    untouched, or vice versa."""
    cur.execute("""SELECT DISTINCT qh.QUOTE_DOC_ID FROM wst_djn_quotation_line ql
        JOIN wst_djn_quotation_header qh ON ql.QUOTE_DOC_ID = qh.QUOTE_DOC_ID
        WHERE ql.ITEM_ID=:1 AND qh.DIVISION=:2
          AND qh.TARGET_MONTH=TRUNC(TO_DATE(:3,'YYYY-MM-DD'),'MM')""",
        [int(item_id), str(division), str(target_month)])
    affected_header_ids = [row[0] for row in cur.fetchall()]
    if not affected_header_ids:
        return  # this item was never actually locked via the Comparison flow -- nothing to release

    cur.execute("""UPDATE wst_djn_quotation_line ql
        SET ql.STATUS='Open'
        WHERE ql.ITEM_ID=:1
          AND ql.QUOTE_DOC_ID IN (
              SELECT qh.QUOTE_DOC_ID FROM wst_djn_quotation_header qh
              WHERE qh.DIVISION=:2 AND qh.TARGET_MONTH=TRUNC(TO_DATE(:3,'YYYY-MM-DD'),'MM')
          )""",
        [int(item_id), str(division), str(target_month)])

    cur.execute("""DELETE FROM wst_djn_quote_comparison_sel
        WHERE ITEM_ID=:1 AND DIVISION=:2 AND TARGET_MONTH=TRUNC(TO_DATE(:3,'YYYY-MM-DD'),'MM')""",
        [int(item_id), str(division), str(target_month)])

    for header_doc_id in affected_header_ids:
        cur.execute("""SELECT COUNT(*), SUM(CASE WHEN NVL(STATUS,'Open')='Locked' THEN 1 ELSE 0 END)
            FROM wst_djn_quotation_line WHERE QUOTE_DOC_ID=:1""", [header_doc_id])
        total, locked_count = cur.fetchone()
        new_status = 'Locked' if total and locked_count == total else 'Open'
        cur.execute("UPDATE wst_djn_quotation_header SET STATUS=:1 WHERE QUOTE_DOC_ID=:2",
                    [new_status, header_doc_id])


def generate_sales_from_comparison(division, target_month, selections, username=None):
    """selections: list of dicts, each {'item_id', 'vendor_id', 'quantity', 'price'}.

    Header: Vendor-wise/Month-wise -- groups selections by vendor_id only,
    since the whole Comparison page (and every selection on it) is already
    scoped to one division+month. Reuses an existing Sales Header for a
    vendor+division+month if one already exists (e.g. from an earlier
    Lock & Generate Sales run against different items for that same
    vendor this month), appending new lines to it rather than creating a
    second header -- so everything for one vendor in one month always
    collapses into a single header, however many separate times items get
    locked over the course of that month. Only creates a brand new header
    when none exists yet for that combination.

    Locking is PER ITEM, not per period or per quotation header: only the
    quotation lines for the SPECIFIC items being routed (every vendor's
    bid on them, within this division+month) get marked Locked. Every
    other item -- whether untouched today, or a brand new bid arriving
    tomorrow -- stays fully open and visible on the Comparison grid,
    completely unaffected by this action.

    A quotation header's own STATUS is a derived summary, not something
    this function sets directly: after locking the relevant lines, every
    affected header is re-checked and only marked Locked if EVERY one of
    its lines is now Locked -- otherwise it stays Open, since it may still
    have other, untouched items.

    Fully atomic: one connection, one commit at the very end. Refuses the
    whole batch up front if any of the SPECIFICALLY SELECTED items are
    already locked (this is the actual duplicate-prevention check now --
    scoped to the items involved, not the whole period).

    Returns (True, [doc_ids created]) on success, (False, error_message)
    otherwise."""
    if not selections:
        return False, "No items were selected."

    with get_connection(username) as conn:
        with conn.cursor() as cur:
            try:
                item_ids = list({int(sel['item_id']) for sel in selections})

                already_locked_names = []
                for item_id in item_ids:
                    cur.execute("""SELECT i.ITEM_NAME FROM wst_djn_quotation_line ql
                        JOIN wst_djn_quotation_header qh ON ql.QUOTE_DOC_ID = qh.QUOTE_DOC_ID
                        LEFT JOIN wst_djn_items i ON ql.ITEM_ID = i.ITEM_ID
                        WHERE ql.ITEM_ID=:1 AND qh.DIVISION=:2
                          AND qh.TARGET_MONTH=TRUNC(TO_DATE(:3,'YYYY-MM-DD'),'MM')
                          AND NVL(ql.STATUS,'Open')='Locked'
                        FETCH FIRST 1 ROW ONLY""",
                        [item_id, str(division), str(target_month)])
                    row = cur.fetchone()
                    if row:
                        already_locked_names.append(row[0] or f'item #{item_id}')
                if already_locked_names:
                    return False, f"These items are already locked and can't be processed again: {', '.join(already_locked_names)}."

                by_vendor = {}
                for sel in selections:
                    by_vendor.setdefault(int(sel['vendor_id']), []).append(sel)

                created_doc_ids = []
                for vendor_id, items in by_vendor.items():
                    # Reuse an existing Sales Header for this exact
                    # vendor+division+month if one already exists (e.g.
                    # from an earlier Lock & Generate Sales run against
                    # different items for the same vendor this month),
                    # instead of always creating a new one -- this is what
                    # keeps everything for one vendor in one month under a
                    # single header, however many separate times items get
                    # locked over the course of that month. Matches on
                    # SOURCE_TARGET_MONTH specifically -- NOT DOC_DATE,
                    # which is the user's actual, editable posting date and
                    # must stay independent of which Comparison period this
                    # document originated from.
                    cur.execute("""SELECT DOC_ID FROM wst_djn_sales_header
                        WHERE DIVISION=:1 AND VENDOR_ID=:2 AND SOURCE_TARGET_MONTH=TRUNC(TO_DATE(:3,'YYYY-MM-DD'),'MM')""",
                        [str(division), vendor_id, str(target_month)])
                    existing = cur.fetchone()

                    if existing:
                        doc_id = existing[0]
                        cur.execute("SELECT NVL(MAX(LINE_NO),0) FROM wst_djn_sales_line WHERE DOC_ID=:1", [doc_id])
                        next_line_no = cur.fetchone()[0]
                    else:
                        doc_id = generate_doc_id(cur)
                        # DOC_DATE defaults to TODAY (the actual transaction
                        # date), not the target month's 1st -- that's what
                        # SOURCE_TARGET_MONTH is for. The user can still edit
                        # DOC_DATE freely afterward; that edit no longer
                        # affects this document's link back to its
                        # originating Comparison period.
                        cur.execute("""INSERT INTO wst_djn_sales_header
                            (DOC_ID, DIVISION, VENDOR_ID, DOC_DATE, SOURCE_TARGET_MONTH, INVOICE_NO, STATUS, TOTAL_AMOUNT, CREATED_BY, CREATED_DATE)
                            VALUES (:1,:2,:3,TRUNC(SYSDATE),TRUNC(TO_DATE(:4,'YYYY-MM-DD'),'MM'),NULL,'DRAFT',0,:5,SYSDATE)""",
                            [doc_id, str(division), vendor_id, str(target_month), username])
                        next_line_no = 0

                    for i, item in enumerate(items):
                        # An item can end up back here for the SAME vendor
                        # if it was locked, shipped, then the shipment was
                        # cancelled -- that reverts the header to DRAFT and
                        # releases the lock, but deliberately leaves the
                        # original line in place (so the same document can
                        # simply be re-shipped without rebuilding it). If
                        # the user instead re-locks the item through
                        # Comparison again, update that existing line
                        # in place rather than inserting a second one for
                        # the same item on the same document.
                        cur.execute("SELECT LINE_ID FROM wst_djn_sales_line WHERE DOC_ID=:1 AND ITEM_ID=:2",
                                    [doc_id, int(item['item_id'])])
                        existing_line = cur.fetchone()
                        if existing_line:
                            cur.execute("""UPDATE wst_djn_sales_line SET QUANTITY=:1, UNIT_PRICE=:2
                                WHERE LINE_ID=:3""",
                                [float(item['quantity']), float(item['price']), existing_line[0]])
                        else:
                            line_no = next_line_no + (i + 1) * 10
                            cur.execute("""INSERT INTO wst_djn_sales_line (DOC_ID, LINE_NO, ITEM_ID, QUANTITY, UNIT_PRICE)
                                VALUES (:1,:2,:3,:4,:5)""",
                                [doc_id, line_no, int(item['item_id']), float(item['quantity']), float(item['price'])])

                    _recalc_header_total(cur, doc_id)
                    created_doc_ids.append(doc_id)

                # Lock ONLY the quotation lines for these SPECIFIC items --
                # every vendor's bid on them within this division+month --
                # never the whole period and never a whole header.
                affected_header_ids = set()
                for item_id in item_ids:
                    cur.execute("""SELECT ql.QUOTE_DOC_ID FROM wst_djn_quotation_line ql
                        JOIN wst_djn_quotation_header qh ON ql.QUOTE_DOC_ID = qh.QUOTE_DOC_ID
                        WHERE ql.ITEM_ID=:1 AND qh.DIVISION=:2
                          AND qh.TARGET_MONTH=TRUNC(TO_DATE(:3,'YYYY-MM-DD'),'MM')""",
                        [item_id, str(division), str(target_month)])
                    for row in cur.fetchall():
                        affected_header_ids.add(row[0])

                    cur.execute("""UPDATE wst_djn_quotation_line ql
                        SET ql.STATUS='Locked'
                        WHERE ql.ITEM_ID=:1
                          AND ql.QUOTE_DOC_ID IN (
                              SELECT qh.QUOTE_DOC_ID FROM wst_djn_quotation_header qh
                              WHERE qh.DIVISION=:2 AND qh.TARGET_MONTH=TRUNC(TO_DATE(:3,'YYYY-MM-DD'),'MM')
                          )""",
                        [item_id, str(division), str(target_month)])

                # Recalculate each affected header's own derived STATUS --
                # Locked only if EVERY line under it is now Locked,
                # otherwise Open, since it may still have other, untouched
                # items belonging to that same vendor's quotation.
                for header_doc_id in affected_header_ids:
                    cur.execute("""SELECT COUNT(*), SUM(CASE WHEN NVL(STATUS,'Open')='Locked' THEN 1 ELSE 0 END)
                        FROM wst_djn_quotation_line WHERE QUOTE_DOC_ID=:1""", [header_doc_id])
                    total, locked_count = cur.fetchone()
                    new_status = 'Locked' if total and locked_count == total else 'Open'
                    cur.execute("UPDATE wst_djn_quotation_header SET STATUS=:1 WHERE QUOTE_DOC_ID=:2",
                                [new_status, header_doc_id])

                conn.commit()
                return True, created_doc_ids
            except Exception as e:
                conn.rollback()
                return False, str(e)


# ─── VENDOR ASSIGNMENT ────────────────────────────────────
def fetch_all_assignments():
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""SELECT a.ASSIGN_ID, v.VENDOR_NAME, i.ITEM_NAME,
                a.ASSIGNED_QTY, a.AGREED_RATE,
                TO_CHAR(a.ASSIGNED_DATE,'DD-Mon-YYYY') AS ASSIGNED_DATE
                FROM wst_djn_vendor_assignment a
                LEFT JOIN wst_djn_vendors v ON a.VENDOR_ID=v.VENDOR_ID
                LEFT JOIN wst_djn_items i ON a.ITEM_ID=i.ITEM_ID
                ORDER BY a.ASSIGN_ID DESC""")
            cols = [c[0] for c in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]

def fetch_assignment_by_id(assign_id):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""SELECT ASSIGN_ID, LIST_ID, VENDOR_ID, ITEM_ID, QUOTE_ID,
                ASSIGNED_QTY, AGREED_RATE, TO_CHAR(ASSIGNED_DATE,'YYYY-MM-DD') AS ASSIGNED_DATE
                FROM wst_djn_vendor_assignment WHERE ASSIGN_ID=:1""", [int(assign_id)])
            cols = [c[0] for c in cur.description]
            row = cur.fetchone()
            return dict(zip(cols, row)) if row else None

def insert_assignment(list_id, vendor_id, item_id, quote_id, assigned_qty, agreed_rate, assigned_date):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""INSERT INTO wst_djn_vendor_assignment
                (LIST_ID, VENDOR_ID, ITEM_ID, QUOTE_ID, ASSIGNED_QTY, AGREED_RATE, ASSIGNED_DATE)
                VALUES (:1,:2,:3,:4,:5,:6,TO_DATE(:7,'YYYY-MM-DD'))""",
                [int(list_id), int(vendor_id), int(item_id),
                 int(quote_id) if quote_id else None,
                 float(assigned_qty), float(agreed_rate), str(assigned_date)])
            conn.commit()

def update_assignment(assign_id, list_id, vendor_id, item_id, quote_id, assigned_qty, agreed_rate, assigned_date):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""UPDATE wst_djn_vendor_assignment SET LIST_ID=:1, VENDOR_ID=:2,
                ITEM_ID=:3, QUOTE_ID=:4, ASSIGNED_QTY=:5, AGREED_RATE=:6,
                ASSIGNED_DATE=TO_DATE(:7,'YYYY-MM-DD') WHERE ASSIGN_ID=:8""",
                [int(list_id), int(vendor_id), int(item_id),
                 int(quote_id) if quote_id else None,
                 float(assigned_qty), float(agreed_rate), str(assigned_date), int(assign_id)])
            conn.commit()

def delete_assignment(assign_id):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM wst_djn_vendor_assignment WHERE ASSIGN_ID=:1", [int(assign_id)])
            conn.commit()


# ─── STOCK RECEIVING ──────────────────────────────────────
def fetch_all_receiving(search=None, division=None, month=None, year=None,
                         department_ids=None, item_ids=None, date_from=None, date_to=None):
    """division is mandatory row-level security — always pass request.user.division.
    month/year default to the current calendar month when not supplied,
    UNLESS date_from/date_to are both given -- a real date range (which
    can span multiple months/years) replaces the single-month filter
    entirely rather than combining with it.
    department_ids/item_ids: optional lists of IDs -- omitted or empty
    means no filter on that dimension (all departments / all items)."""
    from datetime import datetime
    now = datetime.now()

    base_cols = """r.RECEIVE_ID, i.ITEM_NAME, i.UNIT AS UOM, d.DEPT_NAME,
                TO_CHAR(r.RECEIVE_DATE,'DD-Mon-YYYY') AS RECEIVE_DATE,
                r.QTY_RECEIVED, r.REMARKS, NVL(r.DIVISION,'08') AS DIVISION"""
    audit_cols = """,
                r.CREATED_BY, TO_CHAR(r.CREATED_DATE,'DD-Mon-YYYY HH24:MI') AS CREATED_DATE,
                r.LAST_UPDATED_BY, TO_CHAR(r.LAST_UPDATED_DATE,'DD-Mon-YYYY HH24:MI') AS LAST_UPDATED_DATE"""
    join_sql = """
                FROM wst_djn_stock_receiving r
                LEFT JOIN wst_djn_items i ON r.ITEM_ID=i.ITEM_ID
                LEFT JOIN wst_djn_departments d ON r.DEPT_ID=d.DEPT_ID"""

    conditions = []
    params = {}

    if date_from and date_to:
        conditions.append("r.RECEIVE_DATE >= TO_DATE(:p_date_from,'YYYY-MM-DD')")
        conditions.append("r.RECEIVE_DATE < TO_DATE(:p_date_to,'YYYY-MM-DD') + 1")
        params['p_date_from'] = str(date_from)
        params['p_date_to'] = str(date_to)
    elif not search:
        # FIX: previously always applied, even alongside a search term --
        # so searching for something genuinely found only "not found" if
        # the matching record's date fell outside whatever period was
        # currently selected (which defaults to the current month). A
        # search means "find this, wherever it is" -- the period filter
        # only makes sense as the default BROWSE view when there's no
        # search term narrowing things down already.
        m = int(month) if month else now.month
        y = int(year) if year else now.year
        conditions.append("EXTRACT(MONTH FROM r.RECEIVE_DATE) = :p_month")
        conditions.append("EXTRACT(YEAR FROM r.RECEIVE_DATE) = :p_year")
        params['p_month'] = m
        params['p_year'] = y

    if division:
        conditions.append("NVL(r.DIVISION,'08') = :p_div")
        params['p_div'] = str(division)
    if search:
        conditions.append("""(UPPER(i.ITEM_NAME) LIKE UPPER(:p_s1)
                   OR UPPER(d.DEPT_NAME) LIKE UPPER(:p_s2)
                   OR UPPER(r.REMARKS)   LIKE UPPER(:p_s3))""")
        params.update({'p_s1': f'%{search}%', 'p_s2': f'%{search}%', 'p_s3': f'%{search}%'})
    if department_ids:
        dept_binds = [f'p_dept_{i}' for i in range(len(department_ids))]
        conditions.append(f"r.DEPT_ID IN ({','.join(':' + b for b in dept_binds)})")
        params.update({b: int(v) for b, v in zip(dept_binds, department_ids)})
    if item_ids:
        item_binds = [f'p_item_{i}' for i in range(len(item_ids))]
        conditions.append(f"r.ITEM_ID IN ({','.join(':' + b for b in item_binds)})")
        params.update({b: int(v) for b, v in zip(item_binds, item_ids)})

    # Oracle python-oracledb supports named binds directly from a dict
    where_sql = (" WHERE " + " AND ".join(conditions)) if conditions else ""
    order_sql = " ORDER BY r.RECEIVE_ID DESC"
    with get_connection() as conn:
        with conn.cursor() as cur:
            try:
                cur.execute(f"SELECT {base_cols}{audit_cols}{join_sql}{where_sql}{order_sql}", params)
            except oracledb.DatabaseError:
                # Audit columns not yet present on this table (DDL not applied). Degrade gracefully.
                cur.execute(f"SELECT {base_cols}{join_sql}{where_sql}{order_sql}", params)
            cols = [c[0] for c in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]

def fetch_receiving_by_id(receive_id, division=None):
    """division is mandatory row-level security — when supplied, returns None
    if the record belongs to a different division (prevents cross-division
    access via a guessed/edited URL, i.e. an IDOR)."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            if division:
                cur.execute("""SELECT RECEIVE_ID, ITEM_ID, DEPT_ID, RECEIVED_BY,
                    TO_CHAR(RECEIVE_DATE,'YYYY-MM-DD') AS RECEIVE_DATE,
                    QTY_RECEIVED, REMARKS, NVL(DIVISION,'08') AS DIVISION
                    FROM wst_djn_stock_receiving WHERE RECEIVE_ID=:1 AND NVL(DIVISION,'08')=:2""",
                    [int(receive_id), str(division)])
            else:
                cur.execute("""SELECT RECEIVE_ID, ITEM_ID, DEPT_ID, RECEIVED_BY,
                    TO_CHAR(RECEIVE_DATE,'YYYY-MM-DD') AS RECEIVE_DATE,
                    QTY_RECEIVED, REMARKS FROM wst_djn_stock_receiving WHERE RECEIVE_ID=:1""", [int(receive_id)])
            cols = [c[0] for c in cur.description]
            row = cur.fetchone()
            return dict(zip(cols, row)) if row else None

def insert_receiving(item_id, dept_id, received_by, receive_date, qty_received, remarks, division=None, username=None):
    """Insert receiving row AND auto-post an IN (+) entry to the stock ledger.
    The receiving entry saves first — if the ledger auto-post fails (e.g. DDL not yet
    applied), the receiving entry is still committed and a warning is printed."""
    div = str(division or '08')
    with get_connection(username) as conn:
        with conn.cursor() as cur:
            # Try with DIVISION column first; fall back if it doesn't exist yet
            try:
                rcv_id_var = cur.var(int)
                cur.execute("""INSERT INTO wst_djn_stock_receiving
                    (ITEM_ID, DEPT_ID, RECEIVED_BY, RECEIVE_DATE, QTY_RECEIVED, REMARKS, DIVISION)
                    VALUES (:1,:2,:3,TO_DATE(:4,'YYYY-MM-DD'),:5,:6,:7)
                    RETURNING RECEIVE_ID INTO :8""",
                    [int(item_id), int(dept_id) if dept_id else None,
                     int(received_by) if received_by else None,
                     str(receive_date), float(qty_received), to_proper_case(remarks),
                     div, rcv_id_var])
            except oracledb.DatabaseError:
                # DIVISION column may not exist yet — insert without it
                rcv_id_var = cur.var(int)
                cur.execute("""INSERT INTO wst_djn_stock_receiving
                    (ITEM_ID, DEPT_ID, RECEIVED_BY, RECEIVE_DATE, QTY_RECEIVED, REMARKS)
                    VALUES (:1,:2,:3,TO_DATE(:4,'YYYY-MM-DD'),:5,:6)
                    RETURNING RECEIVE_ID INTO :7""",
                    [int(item_id), int(dept_id) if dept_id else None,
                     int(received_by) if received_by else None,
                     str(receive_date), float(qty_received), to_proper_case(remarks),
                     rcv_id_var])
            conn.commit()
            rcv_id = rcv_id_var.getvalue()[0]

    # Auto-post IN to stock ledger (separate transaction — receiving is already saved)
    ledger_error = None
    try:
        post_ledger_entry(
            item_id=item_id, txn_date=receive_date,
            transaction_type='RECEIVE', qty_in=qty_received, qty_out=0,
            source_table='wst_djn_stock_receiving', source_id=rcv_id,
            division=div, username=username
        )
    except Exception as e:
        ledger_error = str(e)
        import logging
        logging.getLogger('wastage').warning(f'Ledger auto-post failed for receiving #{rcv_id}: {e}')

    # Auto-rolling Monthly Stock List: reflects this receipt immediately,
    # without anyone needing a separate manual "listing" step. Runs
    # regardless of whether the ledger auto-post above succeeded, since
    # the physical stock exists either way -- it's independently wrapped
    # in its own try/except inside the function itself.
    upsert_monthly_stock_list_from_receiving(item_id, div, receive_date, qty_received, username=username)

    return rcv_id, ledger_error

def update_receiving(receive_id, item_id, dept_id, received_by, receive_date, qty_received, remarks, division=None, username=None):
    """Edits a Stock Receiving entry and keeps the Stock Ledger + Item
    Balance in sync with the change -- an increase, a decrease, or even
    a change of item is reflected in both. Previously this was a bare
    UPDATE with no ledger/balance resync at all: the receiving row
    itself changed but Item Balance and Stock Ledger silently kept
    showing the pre-edit numbers (insert_receiving() already did this
    correctly via post_ledger_entry() -- only the edit path was missing
    it).

    Returns (success: bool, error: str | None) -- a change that would
    drive an item's balance negative is rejected before anything is
    written, matching the fail-closed pattern already used for Sales
    posting elsewhere in this file."""
    with get_connection(username) as conn:
        with conn.cursor() as cur:
            # Snapshot the pre-edit state first -- needed for the audit
            # log, to find the matching ledger row, and to know which
            # item+division combo(s) need recalculating afterward.
            if division:
                cur.execute("""SELECT ITEM_ID, NVL(DIVISION,'08')
                    FROM wst_djn_stock_receiving WHERE RECEIVE_ID=:1 AND NVL(DIVISION,'08')=:2""",
                    [int(receive_id), str(division)])
            else:
                cur.execute("""SELECT ITEM_ID, NVL(DIVISION,'08')
                    FROM wst_djn_stock_receiving WHERE RECEIVE_ID=:1""", [int(receive_id)])
            old_row = cur.fetchone()
            if not old_row:
                return False, 'Receiving entry not found.'
            old_item_id, old_division = old_row

            cur.execute("SELECT QTY_RECEIVED FROM wst_djn_stock_receiving WHERE RECEIVE_ID=:1", [int(receive_id)])
            old_qty_received = float(cur.fetchone()[0] or 0)

            new_division = str(division or old_division or '08')
            new_item_id = int(item_id)
            new_qty = float(qty_received)

            def _live_balance(itm, div):
                cur.execute("""SELECT NVL(SUM(QTY_IN),0) - NVL(SUM(QTY_OUT),0)
                    FROM wst_djn_stock_ledger WHERE ITEM_ID=:1 AND NVL(DIVISION,'08')=:2""",
                    [int(itm), str(div)])
                r = cur.fetchone()
                return float(r[0]) if r else 0.0

            def _item_name(itm):
                cur.execute("SELECT ITEM_NAME FROM wst_djn_items WHERE ITEM_ID=:1", [int(itm)])
                r = cur.fetchone()
                return r[0] if r else f'Item #{itm}'

            # Fail-closed negative-balance check, before writing anything.
            # Same item+division: only the delta matters (remove the old
            # qty, add the new one). Item or division changed: the OLD
            # item+division loses this quantity entirely -- check that.
            # Adding stock (increasing qty, or moving qty onto a new item)
            # can never push a balance negative, so only removal-side
            # cases need checking.
            if new_item_id == int(old_item_id) and new_division == str(old_division):
                projected = _live_balance(new_item_id, new_division) - old_qty_received + new_qty
                if projected < 0:
                    return False, (f'Changing this to {new_qty:g} would take "{_item_name(new_item_id)}" negative '
                                    f'-- other transactions already depend on the current quantity. Edit cancelled, nothing was changed.')
            else:
                old_projected = _live_balance(old_item_id, old_division) - old_qty_received
                if old_projected < 0:
                    return False, (f'Moving this off "{_item_name(old_item_id)}" would take it negative '
                                    f'-- other transactions already depend on this quantity. Edit cancelled, nothing was changed.')

            if division:
                cur.execute("""UPDATE wst_djn_stock_receiving SET ITEM_ID=:1, DEPT_ID=:2,
                    RECEIVED_BY=:3, RECEIVE_DATE=TO_DATE(:4,'YYYY-MM-DD'),
                    QTY_RECEIVED=:5, REMARKS=:6 WHERE RECEIVE_ID=:7 AND NVL(DIVISION,'08')=:8""",
                    [new_item_id, int(dept_id) if dept_id else None,
                     int(received_by) if received_by else None,
                     str(receive_date), new_qty, to_proper_case(remarks),
                     int(receive_id), str(division)])
            else:
                cur.execute("""UPDATE wst_djn_stock_receiving SET ITEM_ID=:1, DEPT_ID=:2,
                    RECEIVED_BY=:3, RECEIVE_DATE=TO_DATE(:4,'YYYY-MM-DD'),
                    QTY_RECEIVED=:5, REMARKS=:6 WHERE RECEIVE_ID=:7""",
                    [new_item_id, int(dept_id) if dept_id else None,
                     int(received_by) if received_by else None,
                     str(receive_date), new_qty, to_proper_case(remarks), int(receive_id)])

            # Find and update the matching ledger row so it mirrors the new
            # item/date/quantity/division -- self-heals by posting a fresh
            # one if the original RECEIVE post had silently failed, same
            # graceful-degradation insert_receiving() already relies on.
            cur.execute("""SELECT LEDGER_ID FROM wst_djn_stock_ledger
                WHERE REF_ID=:1 AND TXN_TYPE='RECEIVE' AND NVL(DIVISION,'08')=:2""",
                [int(receive_id), str(old_division)])
            ledger_row = cur.fetchone()
            if ledger_row:
                cur.execute("""UPDATE wst_djn_stock_ledger SET ITEM_ID=:1,
                    TXN_DATE=TO_DATE(:2,'YYYY-MM-DD'), QTY_IN=:3, DIVISION=:4
                    WHERE LEDGER_ID=:5""",
                    [new_item_id, str(receive_date), new_qty, new_division, ledger_row[0]])
            else:
                try:
                    cur.execute("""INSERT INTO wst_djn_stock_ledger
                        (ITEM_ID, TXN_DATE, TXN_TYPE, QTY_IN, QTY_OUT, BALANCE, REF_ID, DIVISION,
                         TRANSACTION_TYPE, SOURCE_TABLE, POSTED_BY)
                        VALUES (:1, TO_DATE(:2,'YYYY-MM-DD'), 'RECEIVE', :3, 0, 0, :4, :5,
                                'RECEIVE', 'wst_djn_stock_receiving', :6)""",
                        [new_item_id, str(receive_date), new_qty, int(receive_id), new_division, username])
                except oracledb.DatabaseError:
                    cur.execute("""INSERT INTO wst_djn_stock_ledger
                        (ITEM_ID, TXN_DATE, TXN_TYPE, QTY_IN, QTY_OUT, BALANCE, REF_ID, DIVISION)
                        VALUES (:1, TO_DATE(:2,'YYYY-MM-DD'), 'RECEIVE', :3, 0, 0, :4, :5)""",
                        [new_item_id, str(receive_date), new_qty, int(receive_id), new_division])

            log_audit('STOCK_RECEIVING', receive_id, 'UPDATE', username or 'SYSTEM',
                      old_data={'ITEM_ID': old_item_id, 'QTY_RECEIVED': old_qty_received, 'DIVISION': old_division},
                      new_data={'ITEM_ID': new_item_id, 'QTY_RECEIVED': new_qty, 'DIVISION': new_division})

            conn.commit()

    # Full resync, outside the write transaction -- matches the approach
    # already used throughout this file (a full recompute off the
    # ledger, not a delta patch). Covers both item+division combos if
    # either changed.
    recalculate_all_balances(item_id=old_item_id, division=old_division, username=username)
    if new_item_id != int(old_item_id) or new_division != str(old_division):
        recalculate_all_balances(item_id=new_item_id, division=new_division, username=username)

    return True, None

def delete_receiving(receive_id, division=None, username=None):
    """Deletes a Stock Receiving entry AND keeps the Stock Ledger + Item
    Balance in sync with the removal -- previously this was a bare
    DELETE on the receiving row alone: the matching ledger entry was
    left behind as an orphan, and Item Balance kept showing the deleted
    quantity as if it still existed (the exact same class of gap
    update_receiving() had before it was fixed -- this is the same
    problem on the delete path).

    Returns (success: bool, error: str | None) -- fail-closed: if other
    transactions already depend on this quantity being present (a Sale
    or Shipment that would go negative once it's removed), the delete
    is rejected before anything is written, same as an edit that would
    have the same effect."""
    with get_connection(username) as conn:
        with conn.cursor() as cur:
            if division:
                cur.execute("""SELECT ITEM_ID, QTY_RECEIVED, NVL(DIVISION,'08')
                    FROM wst_djn_stock_receiving WHERE RECEIVE_ID=:1 AND NVL(DIVISION,'08')=:2""",
                    [int(receive_id), str(division)])
            else:
                cur.execute("""SELECT ITEM_ID, QTY_RECEIVED, NVL(DIVISION,'08')
                    FROM wst_djn_stock_receiving WHERE RECEIVE_ID=:1""", [int(receive_id)])
            row = cur.fetchone()
            if not row:
                return False, 'Receiving entry not found.'
            item_id, qty_received, row_division = row
            qty_received = float(qty_received or 0)

            # Fail-closed: removing this quantity's contribution must not
            # drive the item's balance negative -- same reasoning as the
            # equivalent check in update_receiving().
            cur.execute("""SELECT NVL(SUM(QTY_IN),0) - NVL(SUM(QTY_OUT),0)
                FROM wst_djn_stock_ledger WHERE ITEM_ID=:1 AND NVL(DIVISION,'08')=:2""",
                [int(item_id), str(row_division)])
            r = cur.fetchone()
            current_balance = float(r[0]) if r else 0.0
            projected = current_balance - qty_received
            if projected < 0:
                cur.execute("SELECT ITEM_NAME FROM wst_djn_items WHERE ITEM_ID=:1", [int(item_id)])
                nm = cur.fetchone()
                item_name = nm[0] if nm else f'Item #{item_id}'
                return False, (f'Deleting this would take "{item_name}" negative '
                                f'-- other transactions already depend on this quantity. Nothing was deleted.')

            if division:
                cur.execute("DELETE FROM wst_djn_stock_receiving WHERE RECEIVE_ID=:1 AND NVL(DIVISION,'08')=:2",
                            [int(receive_id), str(division)])
            else:
                cur.execute("DELETE FROM wst_djn_stock_receiving WHERE RECEIVE_ID=:1", [int(receive_id)])

            cur.execute("""DELETE FROM wst_djn_stock_ledger
                WHERE REF_ID=:1 AND TXN_TYPE='RECEIVE' AND NVL(DIVISION,'08')=:2""",
                [int(receive_id), str(row_division)])

            log_audit('STOCK_RECEIVING', receive_id, 'DELETE', username or 'SYSTEM',
                      old_data={'ITEM_ID': item_id, 'QTY_RECEIVED': qty_received, 'DIVISION': row_division},
                      new_data=None)

            conn.commit()

    # Full resync, outside the write transaction -- same approach as
    # everywhere else in this file: a full recompute off the ledger,
    # not a delta patch. Correctly resets to zero if this was the only
    # transaction for this item+division, thanks to the same fix that
    # made update_receiving()'s item-change case work correctly.
    recalculate_all_balances(item_id=item_id, division=row_division, username=username)

    return True, None


# ─── SALES ────────────────────────────────────────────────
def fetch_all_sales(search=None, division=None):
    """division is mandatory row-level security — always pass request.user.division."""
    base_cols = """s.SALE_ID, v.VENDOR_NAME, s.INVOICE_NO,
                TO_CHAR(s.SALE_DATE,'DD-Mon-YYYY') AS SALE_DATE,
                s.TOTAL_AMOUNT, s.STATUS, NVL(s.DIVISION,'08') AS DIVISION,
                (SELECT LISTAGG(i.ITEM_NAME, ', ') WITHIN GROUP (ORDER BY i.ITEM_NAME)
                 FROM wst_djn_sale_items si
                 JOIN wst_djn_items i ON si.ITEM_ID = i.ITEM_ID
                 WHERE si.SALE_ID = s.SALE_ID) AS ITEM_NAMES"""
    audit_cols = """,
                TO_CHAR(s.CREATED_DATE,'DD-Mon-YYYY HH24:MI') AS CREATED_DATE,
                s.LAST_UPDATED_BY, TO_CHAR(s.LAST_UPDATED_DATE,'DD-Mon-YYYY HH24:MI') AS LAST_UPDATED_DATE"""
    join_sql = """
                FROM wst_djn_sales s
                LEFT JOIN wst_djn_vendors v ON s.VENDOR_ID=v.VENDOR_ID"""

    conditions = []
    params = {}
    if division:
        conditions.append("NVL(s.DIVISION,'08') = :p_div")
        params['p_div'] = str(division)
    if search:
        conditions.append("""(UPPER(v.VENDOR_NAME) LIKE UPPER(:p_s1)
                   OR UPPER(s.INVOICE_NO)  LIKE UPPER(:p_s2)
                   OR UPPER(s.STATUS)      LIKE UPPER(:p_s3))""")
        params.update({'p_s1': f'%{search}%', 'p_s2': f'%{search}%', 'p_s3': f'%{search}%'})
    where_sql = (" WHERE " + " AND ".join(conditions)) if conditions else ""
    order_sql = " ORDER BY s.SALE_ID DESC"

    with get_connection() as conn:
        with conn.cursor() as cur:
            try:
                cur.execute(f"SELECT {base_cols}{audit_cols}{join_sql}{where_sql}{order_sql}", params)
            except oracledb.DatabaseError:
                try:
                    # Audit columns not yet present (DDL not applied) — try without them
                    cur.execute(f"SELECT {base_cols}{join_sql}{where_sql}{order_sql}", params)
                except oracledb.DatabaseError:
                    # wst_djn_sale_items may not exist on very old installs — final fallback
                    base_cols_no_items = """s.SALE_ID, v.VENDOR_NAME, s.INVOICE_NO,
                        TO_CHAR(s.SALE_DATE,'DD-Mon-YYYY') AS SALE_DATE,
                        s.TOTAL_AMOUNT, s.STATUS, NVL(s.DIVISION,'08') AS DIVISION"""
                    cur.execute(f"SELECT {base_cols_no_items}{join_sql}{where_sql}{order_sql}", params)
            cols = [c[0] for c in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]

def fetch_sale_by_id(sale_id, division=None):
    """division is mandatory row-level security — when supplied, returns None if the
    record belongs to a different division (prevents cross-division access via a
    guessed/edited URL, i.e. an IDOR)."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            if division:
                cur.execute("""SELECT SALE_ID, ASSIGN_ID, VENDOR_ID, INVOICE_NO,
                    TO_CHAR(SALE_DATE,'YYYY-MM-DD') AS SALE_DATE,
                    TOTAL_AMOUNT, STATUS, NVL(DIVISION,'08') AS DIVISION
                    FROM wst_djn_sales WHERE SALE_ID=:1 AND NVL(DIVISION,'08')=:2""",
                    [int(sale_id), str(division)])
            else:
                cur.execute("""SELECT SALE_ID, ASSIGN_ID, VENDOR_ID, INVOICE_NO,
                    TO_CHAR(SALE_DATE,'YYYY-MM-DD') AS SALE_DATE,
                    TOTAL_AMOUNT, STATUS FROM wst_djn_sales WHERE SALE_ID=:1""", [int(sale_id)])
            cols = [c[0] for c in cur.description]
            row = cur.fetchone()
            return dict(zip(cols, row)) if row else None

def insert_sale(assign_id, vendor_id, item_id, qty_sold, invoice_no, sale_date, total_amount, status, created_by, division=None, username=None):
    """Insert sale row + its sale_item line, AND auto-post an OUT (−) entry to the
    stock ledger against the ACTUAL item sold (not the vendor).
    The sale saves first — if the ledger auto-post fails, the sale is still committed."""
    div = str(division or '08')
    with get_connection(username) as conn:
        with conn.cursor() as cur:
            try:
                sale_id_var = cur.var(int)
                cur.execute("""INSERT INTO wst_djn_sales
                    (ASSIGN_ID, VENDOR_ID, INVOICE_NO, SALE_DATE, TOTAL_AMOUNT, STATUS, CREATED_BY, DIVISION)
                    VALUES (:1,:2,:3,TO_DATE(:4,'YYYY-MM-DD'),:5,:6,:7,:8)
                    RETURNING SALE_ID INTO :9""",
                    [int(assign_id) if assign_id else None, int(vendor_id),
                     invoice_no, str(sale_date), float(total_amount), status,
                     int(created_by) if created_by else None,
                     div, sale_id_var])
            except oracledb.DatabaseError:
                # DIVISION column may not exist yet — insert without it
                sale_id_var = cur.var(int)
                cur.execute("""INSERT INTO wst_djn_sales
                    (ASSIGN_ID, VENDOR_ID, INVOICE_NO, SALE_DATE, TOTAL_AMOUNT, STATUS, CREATED_BY)
                    VALUES (:1,:2,:3,TO_DATE(:4,'YYYY-MM-DD'),:5,:6,:7)
                    RETURNING SALE_ID INTO :8""",
                    [int(assign_id) if assign_id else None, int(vendor_id),
                     invoice_no, str(sale_date), float(total_amount), status,
                     int(created_by) if created_by else None,
                     sale_id_var])
            conn.commit()
            sale_id = sale_id_var.getvalue()[0]

    # Record the line item (what was actually sold, how much, at what rate)
    qty = float(qty_sold or 0)
    rate = (float(total_amount) / qty) if qty else 0
    try:
        insert_sale_item(sale_id, item_id, qty, rate, total_amount)
    except Exception as e:
        import logging
        logging.getLogger('wastage').warning(f'sale_item insert failed for sale #{sale_id}: {e}')

    # Auto-post OUT to stock ledger — against the REAL item and REAL quantity sold
    ledger_error = None
    try:
        post_ledger_entry(
            item_id=item_id,
            txn_date=sale_date,
            transaction_type='SALE', qty_in=0, qty_out=qty,
            source_table='wst_djn_sales', source_id=sale_id,
            division=div, username=username
        )
    except Exception as e:
        ledger_error = str(e)
        import logging
        logging.getLogger('wastage').warning(f'Ledger auto-post failed for sale #{sale_id}: {e}')
    return sale_id, ledger_error

def update_sale(sale_id, assign_id, vendor_id, invoice_no, sale_date, total_amount, status, division=None, username=None):
    with get_connection(username) as conn:  # username -> CLIENT_IDENTIFIER -> audit trigger sets LAST_UPDATED_BY
        with conn.cursor() as cur:
            if division:
                # Division-scoped WHERE clause: defense-in-depth so this UPDATE physically
                # cannot touch a record outside the caller's division, even if the
                # ownership check upstream were ever bypassed.
                cur.execute("""UPDATE wst_djn_sales SET ASSIGN_ID=:1, VENDOR_ID=:2,
                    INVOICE_NO=:3, SALE_DATE=TO_DATE(:4,'YYYY-MM-DD'),
                    TOTAL_AMOUNT=:5, STATUS=:6 WHERE SALE_ID=:7 AND NVL(DIVISION,'08')=:8""",
                    [int(assign_id) if assign_id else None, int(vendor_id),
                     invoice_no, str(sale_date), float(total_amount), status,
                     int(sale_id), str(division)])
            else:
                cur.execute("""UPDATE wst_djn_sales SET ASSIGN_ID=:1, VENDOR_ID=:2,
                    INVOICE_NO=:3, SALE_DATE=TO_DATE(:4,'YYYY-MM-DD'),
                    TOTAL_AMOUNT=:5, STATUS=:6 WHERE SALE_ID=:7""",
                    [int(assign_id) if assign_id else None, int(vendor_id),
                     invoice_no, str(sale_date), float(total_amount), status, int(sale_id)])
            conn.commit()

def delete_sale(sale_id, division=None, username=None):
    with get_connection(username) as conn:
        with conn.cursor() as cur:
            if division:
                cur.execute("DELETE FROM wst_djn_sales WHERE SALE_ID=:1 AND NVL(DIVISION,'08')=:2",
                            [int(sale_id), str(division)])
            else:
                cur.execute("DELETE FROM wst_djn_sales WHERE SALE_ID=:1", [int(sale_id)])
            conn.commit()


# ─── SALE ITEMS ───────────────────────────────────────────
def fetch_sale_items(sale_id):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""SELECT si.SALE_ITEM_ID, i.ITEM_NAME,
                si.QTY_SOLD, si.RATE, si.AMOUNT
                FROM wst_djn_sale_items si
                LEFT JOIN wst_djn_items i ON si.ITEM_ID=i.ITEM_ID
                WHERE si.SALE_ID=:1""", [int(sale_id)])
            cols = [c[0] for c in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]

def insert_sale_item(sale_id, item_id, qty_sold, rate, amount):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""INSERT INTO wst_djn_sale_items (SALE_ID, ITEM_ID, QTY_SOLD, RATE, AMOUNT)
                VALUES (:1,:2,:3,:4,:5)""",
                [int(sale_id), int(item_id), float(qty_sold), float(rate), float(amount)])
            conn.commit()

def delete_sale_item(sale_item_id):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM wst_djn_sale_items WHERE SALE_ITEM_ID=:1", [int(sale_item_id)])
            conn.commit()


# ─── SALES HEADER / LINE (Master-Detail) ──────────────────
# Replaces the legacy SALES / SALE ITEMS section above for all NEW sales
# activity. The legacy functions above are kept only so the one-time
# migrate_legacy_sales management command has read access to the old data --
# they are not called by any current view.

def generate_ship_doc_id(cur, year=None):
    """Same pattern as generate_doc_id() above, for SHP-YYYY-NNNN shipment
    doc IDs on the SAME cursor as the shipment header insert that follows."""
    yr = year or date.today().year
    prefix = f'SHP-{yr}-'
    cur.execute("SELECT MAX(SHIP_DOC_ID) FROM wst_djn_shipment_header WHERE SHIP_DOC_ID LIKE :1", [prefix + '%'])
    row = cur.fetchone()
    last = row[0] if row else None
    last_n = int(last.split('-')[-1]) if last else 0
    return f'{prefix}{last_n + 1:04d}'


def generate_doc_id(cur, year=None):
    """Generates the next DOC-YYYY-NNNN for the given year (current year by
    default), using the SAME cursor as the header insert that follows it.
    NOTE: two requests landing in the exact same instant could both read the
    same MAX and attempt the same doc_id -- the UNIQUE PRIMARY KEY on doc_id
    makes that a SAFE failure (the second insert raises ORA-00001 and the
    caller can retry), not a silent duplicate or corruption."""
    yr = year or date.today().year
    prefix = f'DOC-{yr}-'
    cur.execute("SELECT MAX(DOC_ID) FROM wst_djn_sales_header WHERE DOC_ID LIKE :1", [prefix + '%'])
    row = cur.fetchone()
    last = row[0] if row else None
    last_n = int(last.split('-')[-1]) if last else 0
    return f'{prefix}{last_n + 1:04d}'


def fetch_all_sales_headers(division=None, search=None, month=None):
    """division is mandatory row-level security -- always pass request.user.division
    (or None only for sees_all_divisions users). month is 'YYYY-MM-DD' (any
    day within the target month, matching the pattern used elsewhere in
    this app) -- filters to headers whose DOC_DATE falls in that month."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            where, params = [], []
            if division:
                params.append(str(division)); where.append(f"h.DIVISION = :{len(params)}")
            # FIX: previously applied even alongside a search term -- so
            # searching for a party or invoice number only found it if the
            # matching document's date ALSO fell inside whatever month was
            # currently selected (default: the current calendar month). A
            # search means "find this document, whenever it's from" -- the
            # month filter is the default BROWSE view, not a constraint
            # search should be silently subjected to.
            if month and not search:
                params.append(str(month)); where.append(f"TRUNC(h.DOC_DATE,'MM') = TRUNC(TO_DATE(:{len(params)},'YYYY-MM-DD'),'MM')")
            if search:
                params.append(f'%{search}%'); c1 = f":{len(params)}"
                params.append(f'%{search}%'); c2 = f":{len(params)}"
                where.append(f"(UPPER(v.VENDOR_NAME) LIKE UPPER({c1}) OR UPPER(h.INVOICE_NO) LIKE UPPER({c2}))")
            w = (" WHERE " + " AND ".join(where)) if where else ""
            cur.execute(f"""SELECT h.DOC_ID, h.DIVISION, v.VENDOR_NAME,
                    TO_CHAR(h.DOC_DATE,'DD-Mon-YYYY') AS DOC_DATE,
                    h.INVOICE_NO, h.STATUS, h.TOTAL_AMOUNT,
                    (SELECT COUNT(*) FROM wst_djn_sales_line l WHERE l.DOC_ID = h.DOC_ID) AS LINE_COUNT
                FROM wst_djn_sales_header h
                LEFT JOIN wst_djn_vendors v ON h.VENDOR_ID = v.VENDOR_ID
                {w}
                ORDER BY h.DOC_ID DESC""", params)
            cols = [c[0] for c in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]


def fetch_sales_header_by_id(doc_id, division=None):
    """division is mandatory row-level security -- when supplied, returns None
    if the document belongs to a different division (prevents cross-division
    access via a guessed/edited URL, i.e. an IDOR)."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            base = """SELECT h.DOC_ID, h.DIVISION, h.VENDOR_ID, v.VENDOR_NAME,
                    TO_CHAR(h.DOC_DATE,'YYYY-MM-DD') AS DOC_DATE,
                    h.INVOICE_NO, h.STATUS, h.TOTAL_AMOUNT,
                    h.CREATED_BY, TO_CHAR(h.CREATED_DATE,'DD-Mon-YYYY HH24:MI') AS CREATED_DATE,
                    h.POSTED_BY, TO_CHAR(h.POSTED_DATE,'DD-Mon-YYYY HH24:MI') AS POSTED_DATE,
                    h.CANCELLED_BY, TO_CHAR(h.CANCELLED_DATE,'DD-Mon-YYYY HH24:MI') AS CANCELLED_DATE
                FROM wst_djn_sales_header h LEFT JOIN wst_djn_vendors v ON h.VENDOR_ID=v.VENDOR_ID
                WHERE h.DOC_ID = :1"""
            if division:
                cur.execute(base + " AND h.DIVISION = :2", [doc_id, str(division)])
            else:
                cur.execute(base, [doc_id])
            cols = [c[0] for c in cur.description]
            row = cur.fetchone()
            return dict(zip(cols, row)) if row else None


def fetch_sales_lines(doc_id):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""SELECT l.LINE_ID, l.LINE_NO, l.ITEM_ID, i.ITEM_CODE, i.ITEM_NAME, i.UNIT AS UOM,
                    l.QUANTITY, l.UNIT_PRICE, l.LINE_TOTAL,
                    NVL(l.SHIPPED_QTY, 0) AS SHIPPED_QTY, NVL(l.LINE_STATUS, 'Entered') AS LINE_STATUS,
                    l.QUANTITY - NVL(l.SHIPPED_QTY, 0) AS PENDING_QTY
                FROM wst_djn_sales_line l LEFT JOIN wst_djn_items i ON l.ITEM_ID=i.ITEM_ID
                WHERE l.DOC_ID = :1 ORDER BY l.LINE_NO""", [doc_id])
            cols = [c[0] for c in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]


def _recalc_header_total(cur, doc_id):
    cur.execute("""UPDATE wst_djn_sales_header SET TOTAL_AMOUNT =
        (SELECT NVL(SUM(LINE_TOTAL),0) FROM wst_djn_sales_line WHERE DOC_ID=:1)
        WHERE DOC_ID=:2""", [doc_id, doc_id])


def insert_sales_header_draft(vendor_id, doc_date, invoice_no, division, username=None):
    """Creates a new DRAFT header and returns its generated doc_id."""
    with get_connection(username) as conn:
        with conn.cursor() as cur:
            doc_id = generate_doc_id(cur)
            cur.execute("""INSERT INTO wst_djn_sales_header
                (DOC_ID, DIVISION, VENDOR_ID, DOC_DATE, INVOICE_NO, STATUS,
                 TOTAL_AMOUNT, CREATED_BY, CREATED_DATE)
                VALUES (:1,:2,:3,TO_DATE(:4,'YYYY-MM-DD'),:5,'DRAFT',0,:6,SYSDATE)""",
                [doc_id, str(division or '08'), int(vendor_id), str(doc_date), invoice_no, username])
            conn.commit()
            return doc_id


def insert_sales_line(doc_id, item_id, quantity, unit_price):
    """Auto-sequences line_no = NVL(MAX(line_no),0) + 10 for this document,
    then recalculates the header's TOTAL_AMOUNT from all its current lines."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT NVL(MAX(LINE_NO),0)+10 FROM wst_djn_sales_line WHERE DOC_ID=:1", [doc_id])
            line_no = cur.fetchone()[0]
            cur.execute("""INSERT INTO wst_djn_sales_line (DOC_ID, LINE_NO, ITEM_ID, QUANTITY, UNIT_PRICE)
                VALUES (:1,:2,:3,:4,:5)""",
                [doc_id, line_no, int(item_id), float(quantity), float(unit_price)])
            _recalc_header_total(cur, doc_id)
            conn.commit()
            return line_no


def update_sales_line(line_id, doc_id, quantity, unit_price):
    """Edits an existing line's Quantity and Unit Price. Same fail-closed
    guard as delete_sales_line() and for the same reason: once a line
    has any Gate Pass activity (LINE_STATUS != 'Entered'), its Quantity
    is no longer just this document's own number -- Gate Pass has
    already dispatched against whatever was there, so changing it here
    could silently contradict real, already-moved stock. A line stays
    editable for as long as nothing has shipped against it yet,
    regardless of what the header's own overall STATUS is (a header can
    be PARTIAL while individual lines on it are still untouched).

    LINE_TOTAL is deliberately NOT set here -- wst_djn_sales_line.
    LINE_TOTAL is a genuine Oracle virtual/computed column (derived
    automatically from QUANTITY * UNIT_PRICE), and Oracle raises
    ORA-54017 ("UPDATE operation disallowed on virtual columns") if
    anything tries to write it directly. Updating QUANTITY/UNIT_PRICE
    alone is sufficient -- Oracle recomputes LINE_TOTAL itself, in the
    same statement, and _recalc_header_total() below reads that
    already-correct value.

    Returns (True, None) or (False, error_message)."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT NVL(LINE_STATUS,'Entered') FROM wst_djn_sales_line WHERE LINE_ID=:1 AND DOC_ID=:2",
                        [int(line_id), doc_id])
            row = cur.fetchone()
            if not row:
                return False, "Line not found."
            if row[0] != 'Entered':
                return False, f"This line has already shipped against a Gate Pass ({row[0]}) and can no longer be edited here."
            try:
                qty_f = float(quantity)
                price_f = float(unit_price)
            except (TypeError, ValueError):
                return False, "Quantity and Unit Price must be numbers."
            if qty_f <= 0:
                return False, "Quantity must be greater than zero."
            if price_f < 0:
                return False, "Unit Price cannot be negative."
            cur.execute("""UPDATE wst_djn_sales_line
                SET QUANTITY=:1, UNIT_PRICE=:2
                WHERE LINE_ID=:3 AND DOC_ID=:4""",
                [qty_f, price_f, int(line_id), doc_id])
            _recalc_header_total(cur, doc_id)
            conn.commit()
            return True, None


def delete_sales_line(line_id, doc_id):
    """The view enforces that the header is still DRAFT before calling this
    -- a Posted/Cancelled document's lines are permanent history. Also
    refuses here directly if the line itself has any Gate Pass activity
    (LINE_STATUS != 'Entered') -- once a line has shipped anything, even
    partially, "removing" it would silently orphan that Gate Pass's
    reference back to a line that no longer exists. Returns True if
    deleted, False if refused."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT NVL(LINE_STATUS,'Entered') FROM wst_djn_sales_line WHERE LINE_ID=:1 AND DOC_ID=:2",
                        [int(line_id), doc_id])
            row = cur.fetchone()
            if not row:
                return False
            if row[0] != 'Entered':
                return False
            cur.execute("DELETE FROM wst_djn_sales_line WHERE LINE_ID=:1 AND DOC_ID=:2", [int(line_id), doc_id])
            _recalc_header_total(cur, doc_id)
            conn.commit()
            return True


def update_sales_header_draft(doc_id, vendor_id, doc_date, invoice_no, division=None, username=None):
    """Only takes effect while STATUS='DRAFT' -- included in the WHERE clause
    itself as defense-in-depth, since a Posted/Cancelled header must be immutable.

    vendor_id is accepted but deliberately NOT written -- once a header
    exists, its Vendor is locked, same as Division already is. This
    function is only ever called against an EXISTING doc_id (never at
    creation), so by the time it runs the vendor has already been fixed;
    changing it afterward risks a document appearing to belong to a
    different vendor than the one its lines/shipments were actually
    created and dispatched against. Kept as a parameter purely so both
    existing call sites don't need to change."""
    with get_connection(username) as conn:
        with conn.cursor() as cur:
            if division:
                cur.execute("""UPDATE wst_djn_sales_header SET
                    DOC_DATE=TO_DATE(:1,'YYYY-MM-DD'), INVOICE_NO=:2,
                    LAST_UPDATED_BY=:3, LAST_UPDATED_DATE=SYSDATE
                    WHERE DOC_ID=:4 AND DIVISION=:5 AND STATUS='DRAFT'""",
                    [str(doc_date), invoice_no, username, doc_id, str(division)])
            else:
                cur.execute("""UPDATE wst_djn_sales_header SET
                    DOC_DATE=TO_DATE(:1,'YYYY-MM-DD'), INVOICE_NO=:2,
                    LAST_UPDATED_BY=:3, LAST_UPDATED_DATE=SYSDATE
                    WHERE DOC_ID=:4 AND STATUS='DRAFT'""",
                    [str(doc_date), invoice_no, username, doc_id])
            conn.commit()


def delete_sales_header_draft(doc_id, division=None):
    """Only a DRAFT document may be deleted outright -- once Posted, it has
    touched the ledger and becomes a permanent record (Cancel, not Delete).
    A draft can still have locked Quotation Comparison lines if it was
    created via Lock & Generate Sales, even though nothing was ever
    posted to the ledger yet -- releases those locks too, same as
    cancelling a posted document does, so deleting a draft doesn't leave
    an item stuck Locked with no sales document left to show for it."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            try:
                if division:
                    cur.execute("SELECT STATUS, SOURCE_TARGET_MONTH FROM wst_djn_sales_header WHERE DOC_ID=:1 AND DIVISION=:2", [doc_id, str(division)])
                else:
                    cur.execute("SELECT STATUS, SOURCE_TARGET_MONTH FROM wst_djn_sales_header WHERE DOC_ID=:1", [doc_id])
                row = cur.fetchone()
                if not row or row[0] != 'DRAFT':
                    return False
                # NULL for a document created manually (not via Comparison) --
                # nothing to unlock in that case, so the release step below is
                # skipped entirely rather than crashing on strftime(None).
                target_month_str = row[1].strftime('%Y-%m-%d') if row[1] else None

                cur.execute("SELECT DIVISION FROM wst_djn_sales_header WHERE DOC_ID=:1", [doc_id])
                header_division = cur.fetchone()[0]

                cur.execute("SELECT DISTINCT ITEM_ID FROM wst_djn_sales_line WHERE DOC_ID=:1", [doc_id])
                item_ids = [r[0] for r in cur.fetchall()]

                cur.execute("DELETE FROM wst_djn_sales_line WHERE DOC_ID=:1", [doc_id])
                cur.execute("DELETE FROM wst_djn_sales_header WHERE DOC_ID=:1", [doc_id])

                for item_id in item_ids:
                    if target_month_str is not None:
                        _release_quotation_lock(cur, int(item_id), header_division, target_month_str)

                conn.commit()
                return True
            except Exception:
                conn.rollback()
                raise


def post_sales_document(doc_id, division, username=None):
    """Posts a DRAFT sales document: for EVERY line, posts an OUT ledger
    entry and recalculates that item's division-scoped balance, marks
    the header POSTED, and creates a dedicated Shipment record (header +
    one line per sales line) -- this IS the "Ship & Post" action the
    button is already labeled for. All on ONE connection/cursor,
    committed EXACTLY ONCE at the very end. If anything fails partway
    through (a bad item_id, a DB constraint, a network blip), the whole
    thing rolls back: no header status change, no ledger rows, no
    balance changes, no shipment record -- nothing half-done.
    Returns (True, ship_doc_id) on success, or (False, error_message) on
    failure; the document is left in DRAFT on failure so the user can
    fix and retry."""
    with get_connection(username) as conn:
        with conn.cursor() as cur:
            try:
                cur.execute("SELECT STATUS, DOC_DATE FROM wst_djn_sales_header WHERE DOC_ID=:1 AND DIVISION=:2",
                            [doc_id, str(division)])
                row = cur.fetchone()
                if not row:
                    return False, "Document not found, or it belongs to a different division."
                if row[0] != 'DRAFT':
                    return False, f"Only DRAFT documents can be posted (this one is {row[0]})."
                doc_date = row[1]

                cur.execute("SELECT LINE_ID, LINE_NO, ITEM_ID, QUANTITY FROM wst_djn_sales_line WHERE DOC_ID=:1 ORDER BY LINE_NO",
                            [doc_id])
                lines = cur.fetchall()
                if not lines:
                    return False, "Cannot post a document with no line items."

                # Validate stock BEFORE writing anything. Two lines could
                # reference the SAME item, so sum requested quantity per
                # item first -- checking each line in isolation would wrongly
                # allow e.g. two 8-unit lines against a stock of 10 (8 alone
                # looks fine each time, 16 combined is not).
                requested_by_item = {}
                for _line_id, _line_no, item_id, quantity in lines:
                    requested_by_item[item_id] = requested_by_item.get(item_id, 0) + float(quantity)

                for item_id, total_requested in requested_by_item.items():
                    cur.execute("SELECT BALANCE FROM wst_djn_item_balance WHERE ITEM_ID=:1 AND DIVISION=:2",
                                [int(item_id), str(division)])
                    bal_row = cur.fetchone()
                    available = float(bal_row[0]) if bal_row and bal_row[0] is not None else 0.0
                    if available <= 0:
                        cur.execute("SELECT ITEM_NAME FROM wst_djn_items WHERE ITEM_ID=:1", [int(item_id)])
                        name_row = cur.fetchone()
                        item_name = name_row[0] if name_row else f'Item #{item_id}'
                        return False, f'"{item_name}" is out of stock (0 available) — posting cancelled, nothing was changed.'
                    if total_requested > available:
                        cur.execute("SELECT ITEM_NAME FROM wst_djn_items WHERE ITEM_ID=:1", [int(item_id)])
                        name_row = cur.fetchone()
                        item_name = name_row[0] if name_row else f'Item #{item_id}'
                        return False, (f'Insufficient stock for "{item_name}": this document requests '
                                       f'{total_requested:g}, only {available:g} available — posting cancelled, nothing was changed.')

                for line_id, line_no, item_id, quantity in lines:
                    try:
                        cur.execute("""INSERT INTO wst_djn_stock_ledger
                            (ITEM_ID, TXN_DATE, TXN_TYPE, QTY_IN, QTY_OUT, BALANCE, REF_ID, DIVISION,
                             TRANSACTION_TYPE, SOURCE_REF, SOURCE_TABLE, POSTED_BY)
                            VALUES (:1, :2, 'SALE', 0, :3, 0, NULL, :4, 'SALE', :5, 'wst_djn_sales_header', :6)""",
                            [int(item_id), doc_date, float(quantity), str(division),
                             f'{doc_id}#{line_no}', username])
                    except oracledb.DatabaseError:
                        # One or more of the richer metadata columns (TRANSACTION_TYPE /
                        # SOURCE_REF / SOURCE_TABLE / POSTED_BY) don't exist on this schema
                        # yet -- fall back to the core columns that Receiving already relies
                        # on successfully (same pattern used elsewhere in this file).
                        cur.execute("""INSERT INTO wst_djn_stock_ledger
                            (ITEM_ID, TXN_DATE, TXN_TYPE, QTY_IN, QTY_OUT, BALANCE, REF_ID, DIVISION)
                            VALUES (:1, :2, 'SALE', 0, :3, 0, NULL, :4)""",
                            [int(item_id), doc_date, float(quantity), str(division)])
                    _recalc_item_balance(cur, item_id, division, doc_date, 'SALE', 0, quantity)

                try:
                    cur.execute("""UPDATE wst_djn_sales_header
                        SET STATUS='CLOSED', POSTED_BY=:1, POSTED_DATE=SYSDATE
                        WHERE DOC_ID=:2""", [username, doc_id])
                except oracledb.DatabaseError:
                    # POSTED_BY/POSTED_DATE not on this schema yet -- STATUS is the
                    # one column that matters for the app's own logic, so at minimum
                    # that must succeed.
                    cur.execute("UPDATE wst_djn_sales_header SET STATUS='CLOSED' WHERE DOC_ID=:1", [doc_id])

                # Ship & Post ships every line on the document for its full
                # quantity in one atomic action -- so every line becomes
                # fully Closed here, keeping the Gate Pass tracking columns
                # (added in Phase 1) consistent regardless of which of the
                # two parallel posting paths a document went through.
                for line_id, line_no, item_id, quantity in lines:
                    cur.execute("""UPDATE wst_djn_sales_line
                        SET SHIPPED_QTY=:1, LINE_STATUS='Closed' WHERE LINE_ID=:2""",
                        [float(quantity), int(line_id)])

                # Dedicated physical Shipment record for this Ship & Post
                # event -- required so a later shipment cancellation has
                # its own real row to act on, independent of the sales
                # document's own header/line rows.
                ship_doc_id = generate_ship_doc_id(cur)
                cur.execute("""INSERT INTO wst_djn_shipment_header
                    (SHIP_DOC_ID, SALES_DOC_ID, DIVISION, SHIP_DATE, STATUS, CREATED_BY, CREATED_DATE)
                    VALUES (:1, :2, :3, SYSDATE, 'Shipped', :4, SYSDATE)""",
                    [ship_doc_id, doc_id, str(division), username])
                for line_id, line_no, item_id, quantity in lines:
                    cur.execute("""INSERT INTO wst_djn_shipment_line
                        (SHIP_DOC_ID, SALES_LINE_ID, ITEM_ID, QUANTITY)
                        VALUES (:1, :2, :3, :4)""",
                        [ship_doc_id, int(line_id), int(item_id), float(quantity)])

                conn.commit()
                return True, ship_doc_id
            except Exception as e:
                conn.rollback()
                msg = str(e)
                # Friendly translation for the rare case where the DB-level
                # non-negative constraint fires -- should basically never
                # happen since the check above already screens for this,
                # but translate it if it ever does rather than leaking a
                # raw ORA-02290 message to the user.
                if 'CK_ITEM_BALANCE_NONNEG' in msg.upper() or 'CK_STOCK_LEDGER_NONNEG' in msg.upper():
                    msg = "This would take an item's stock below zero — posting cancelled, nothing was changed."
                return False, msg


def cancel_sales_document(doc_id, division, username=None):
    """Cancels a POSTED document: for every line, posts a REVERSING IN entry
    (restoring the stock that the original posting took out) and
    recalculates balance, marks the header CANCELLED, releases the
    Quotation Comparison lock for every item on this document (so the
    vendor selection is fully undone, not just the stock movement -- the
    item becomes available to lock again, to the same or a different
    vendor), and marks any associated Shipment record Cancelled too so it
    doesn't sit there claiming Shipped against a now-cancelled sale. Same
    one-connection, commit-once-at-the-end atomicity as
    post_sales_document()."""
    with get_connection(username) as conn:
        with conn.cursor() as cur:
            try:
                cur.execute("SELECT STATUS, SOURCE_TARGET_MONTH FROM wst_djn_sales_header WHERE DOC_ID=:1 AND DIVISION=:2",
                            [doc_id, str(division)])
                row = cur.fetchone()
                if not row:
                    return False, "Document not found, or it belongs to a different division."
                if row[0] != 'CLOSED':
                    return False, f"Only CLOSED documents can be cancelled (this one is {row[0]})."

                # FIX: this function's reversal logic assumes the FULL
                # ordered QUANTITY was deducted via post_sales_document()'s
                # own atomic Ship & Post path -- it has no way to reverse
                # a document that reached CLOSED gradually through Gate
                # Pass shipments instead, and blindly crediting back the
                # full quantity regardless of what was actually shipped
                # would be wrong. post_sales_document() is the only thing
                # that ever creates a wst_djn_shipment_header row for this
                # doc -- if none exists, this document was fulfilled via
                # Gate Pass, and cancellation belongs there instead
                # (cancel_gate_pass(), which already reverses the correct,
                # actual shipped quantities).
                cur.execute("SELECT COUNT(*) FROM wst_djn_shipment_header WHERE SALES_DOC_ID=:1", [doc_id])
                if cur.fetchone()[0] == 0:
                    return False, (f'{doc_id} was fulfilled via Gate Pass, not "Ship & Post" -- '
                                    f'cancel the relevant Gate Pass(es) instead, not this document directly.')

                target_month = row[1]  # NULL for documents created manually (not via Comparison) -- nothing to unlock in that case

                cur.execute("SELECT LINE_ID, LINE_NO, ITEM_ID, QUANTITY FROM wst_djn_sales_line WHERE DOC_ID=:1 ORDER BY LINE_NO",
                            [doc_id])
                lines = cur.fetchall()
                today = date.today().isoformat()

                for line_id, line_no, item_id, quantity in lines:
                    try:
                        cur.execute("""INSERT INTO wst_djn_stock_ledger
                            (ITEM_ID, TXN_DATE, TXN_TYPE, QTY_IN, QTY_OUT, BALANCE, REF_ID, DIVISION,
                             TRANSACTION_TYPE, SOURCE_REF, SOURCE_TABLE, POSTED_BY)
                            VALUES (:1, TO_DATE(:2,'YYYY-MM-DD'), 'SALE_REVERSAL', :3, 0, 0, NULL, :4,
                                    'SALE_REVERSAL', :5, 'wst_djn_sales_header', :6)""",
                            [int(item_id), today, float(quantity), str(division),
                             f'{doc_id}#{line_no}-REV', username])
                    except oracledb.DatabaseError:
                        # Same fallback as post_sales_document() -- richer metadata
                        # columns may not exist on this schema yet.
                        cur.execute("""INSERT INTO wst_djn_stock_ledger
                            (ITEM_ID, TXN_DATE, TXN_TYPE, QTY_IN, QTY_OUT, BALANCE, REF_ID, DIVISION)
                            VALUES (:1, TO_DATE(:2,'YYYY-MM-DD'), 'SALE_REVERSAL', :3, 0, 0, NULL, :4)""",
                            [int(item_id), today, float(quantity), str(division)])
                    _recalc_item_balance(cur, item_id, division, today, 'SALE_REVERSAL', quantity, 0)
                    cur.execute("""UPDATE wst_djn_sales_line
                        SET SHIPPED_QTY=0, LINE_STATUS='Entered' WHERE LINE_ID=:1""", [int(line_id)])

                try:
                    cur.execute("""UPDATE wst_djn_sales_header
                        SET STATUS='CANCELLED', CANCELLED_BY=:1, CANCELLED_DATE=SYSDATE
                        WHERE DOC_ID=:2""", [username, doc_id])
                except oracledb.DatabaseError:
                    cur.execute("UPDATE wst_djn_sales_header SET STATUS='CANCELLED' WHERE DOC_ID=:1", [doc_id])

                if target_month is not None:
                    target_month_str = target_month.strftime('%Y-%m-%d')
                    for item_id in {int(item_id) for _line_no, item_id, _quantity in lines}:
                        _release_quotation_lock(cur, item_id, division, target_month_str)

                try:
                    cur.execute("""UPDATE wst_djn_shipment_header
                        SET STATUS='Cancelled', CANCELLED_BY=:1, CANCELLED_DATE=SYSDATE
                        WHERE SALES_DOC_ID=:2 AND STATUS='Shipped'""", [username, doc_id])
                except oracledb.DatabaseError:
                    pass  # shipment table may not exist yet on an un-migrated schema

                conn.commit()
                return True, None
            except Exception as e:
                conn.rollback()
                msg = str(e)
                # Friendly translation for the rare case where the DB-level
                # non-negative constraint fires -- should basically never
                # happen since the check above already screens for this,
                # but translate it if it ever does rather than leaking a
                # raw ORA-02290 message to the user.
                if 'CK_ITEM_BALANCE_NONNEG' in msg.upper() or 'CK_STOCK_LEDGER_NONNEG' in msg.upper():
                    msg = "This would take an item's stock below zero — posting cancelled, nothing was changed."
                return False, msg


def fetch_all_shipments(division=None, status=None, month=None):
    """List-fetch for the Shipments screen -- every shipment (Shipped and
    Cancelled both included by default) with its originating vendor and
    line count, so Cancelled shipments have an actual place to show up
    rather than only being visible one-at-a-time on whatever Sales
    document they happened to belong to. Most recent first."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            base_sql = """SELECT sh.SHIP_DOC_ID, sh.SALES_DOC_ID, sh.DIVISION,
                    TO_CHAR(sh.SHIP_DATE,'DD-Mon-YYYY') AS SHIP_DATE, sh.STATUS,
                    v.VENDOR_NAME, sh.CREATED_BY,
                    TO_CHAR(sh.CANCELLED_DATE,'DD-Mon-YYYY') AS CANCELLED_DATE, sh.CANCELLED_BY,
                    (SELECT COUNT(*) FROM wst_djn_shipment_line sl WHERE sl.SHIP_DOC_ID = sh.SHIP_DOC_ID) AS LINE_COUNT
                FROM wst_djn_shipment_header sh
                LEFT JOIN wst_djn_sales_header sah ON sh.SALES_DOC_ID = sah.DOC_ID
                LEFT JOIN wst_djn_vendors v ON sah.VENDOR_ID = v.VENDOR_ID"""
            where, params = [], []
            if division:
                params.append(str(division)); where.append(f"sh.DIVISION = :{len(params)}")
            if status and status != 'ALL':
                params.append(str(status)); where.append(f"sh.STATUS = :{len(params)}")
            if month:
                params.append(str(month)); where.append(f"TRUNC(sh.SHIP_DATE,'MM') = TRUNC(TO_DATE(:{len(params)},'YYYY-MM-DD'),'MM')")
            w = (" WHERE " + " AND ".join(where)) if where else ""
            try:
                cur.execute(base_sql + w + " ORDER BY sh.CREATED_DATE DESC, sh.SHIP_DOC_ID DESC", params)
                cols = [c[0] for c in cur.description]
                return [dict(zip(cols, row)) for row in cur.fetchall()]
            except oracledb.DatabaseError:
                return []  # shipment table not migrated onto this schema yet


def fetch_shipment_by_sales_doc_id(doc_id):
    """The shipment (if any) for a given Sales document, for display on
    the Sales detail page -- a doc that's never been Ship & Posted simply
    has none yet. Only the most recent shipment is returned, since a
    Sales doc can be shipped, cancelled, and re-shipped more than once
    over its life (each cancellation reverts the header to DRAFT,
    allowing exactly that)."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            try:
                cur.execute("""SELECT SHIP_DOC_ID, TO_CHAR(SHIP_DATE,'DD-Mon-YYYY') AS SHIP_DATE, STATUS
                    FROM wst_djn_shipment_header WHERE SALES_DOC_ID=:1
                    ORDER BY CREATED_DATE DESC FETCH FIRST 1 ROW ONLY""", [doc_id])
                row = cur.fetchone()
                if not row:
                    return None
                return {'SHIP_DOC_ID': row[0], 'SHIP_DATE': row[1], 'STATUS': row[2]}
            except oracledb.DatabaseError:
                return None  # shipment table not migrated onto this schema yet


def cancel_shipment(ship_doc_id, division, username=None):
    """Cancels a Shipped shipment: soft-deletes the shipment record
    (STATUS='Cancelled', row stays for the audit trail -- it now shows up
    under Cancelled Shipments rather than Shipped), reverses the stock
    the original Ship & Post took out, reverts the Sales Header back to
    DRAFT -- re-editable and re-shippable, NOT a terminal CANCELLED
    state -- and releases the Quotation Comparison lock for every item
    on the shipment, so it's immediately available to lock again (to the
    same or a different vendor). Same one-connection, commit-once-at-
    the-end atomicity as the other lifecycle functions in this file."""
    with get_connection(username) as conn:
        with conn.cursor() as cur:
            try:
                cur.execute("""SELECT SALES_DOC_ID, STATUS FROM wst_djn_shipment_header
                    WHERE SHIP_DOC_ID=:1 AND DIVISION=:2""", [ship_doc_id, str(division)])
                row = cur.fetchone()
                if not row:
                    return False, "Shipment not found, or it belongs to a different division."
                sales_doc_id, ship_status = row
                if ship_status != 'Shipped':
                    return False, f"Only a Shipped shipment can be cancelled (this one is {ship_status})."

                cur.execute("""SELECT sl.SALES_LINE_ID, sl.ITEM_ID, sl.QUANTITY FROM wst_djn_shipment_line sl
                    WHERE sl.SHIP_DOC_ID=:1""", [ship_doc_id])
                ship_lines = cur.fetchall()
                today = date.today().isoformat()

                for sales_line_id, item_id, quantity in ship_lines:
                    try:
                        cur.execute("""INSERT INTO wst_djn_stock_ledger
                            (ITEM_ID, TXN_DATE, TXN_TYPE, QTY_IN, QTY_OUT, BALANCE, REF_ID, DIVISION,
                             TRANSACTION_TYPE, SOURCE_REF, SOURCE_TABLE, POSTED_BY)
                            VALUES (:1, TO_DATE(:2,'YYYY-MM-DD'), 'SHIPMENT_REVERSAL', :3, 0, 0, NULL, :4,
                                    'SHIPMENT_REVERSAL', :5, 'wst_djn_shipment_header', :6)""",
                            [int(item_id), today, float(quantity), str(division),
                             f'{ship_doc_id}-REV', username])
                    except oracledb.DatabaseError:
                        cur.execute("""INSERT INTO wst_djn_stock_ledger
                            (ITEM_ID, TXN_DATE, TXN_TYPE, QTY_IN, QTY_OUT, BALANCE, REF_ID, DIVISION)
                            VALUES (:1, TO_DATE(:2,'YYYY-MM-DD'), 'SHIPMENT_REVERSAL', :3, 0, 0, NULL, :4)""",
                            [int(item_id), today, float(quantity), str(division)])
                    _recalc_item_balance(cur, item_id, division, today, 'SHIPMENT_REVERSAL', quantity, 0)
                    if sales_line_id is not None:
                        cur.execute("""UPDATE wst_djn_sales_line
                            SET SHIPPED_QTY=0, LINE_STATUS='Entered' WHERE LINE_ID=:1""", [int(sales_line_id)])

                cur.execute("""UPDATE wst_djn_shipment_header
                    SET STATUS='Cancelled', CANCELLED_BY=:1, CANCELLED_DATE=SYSDATE
                    WHERE SHIP_DOC_ID=:2""", [username, ship_doc_id])

                cur.execute("SELECT SOURCE_TARGET_MONTH FROM wst_djn_sales_header WHERE DOC_ID=:1", [sales_doc_id])
                doc_date_row = cur.fetchone()
                target_month_str = doc_date_row[0].strftime('%Y-%m-%d') if doc_date_row and doc_date_row[0] else None

                try:
                    cur.execute("""UPDATE wst_djn_sales_header
                        SET STATUS='DRAFT', POSTED_BY=NULL, POSTED_DATE=NULL
                        WHERE DOC_ID=:1""", [sales_doc_id])
                except oracledb.DatabaseError:
                    cur.execute("UPDATE wst_djn_sales_header SET STATUS='DRAFT' WHERE DOC_ID=:1", [sales_doc_id])

                if target_month_str:
                    for _sales_line_id, item_id, _quantity in ship_lines:
                        _release_quotation_lock(cur, int(item_id), division, target_month_str)

                conn.commit()
                return True, sales_doc_id
            except Exception as e:
                conn.rollback()
                msg = str(e)
                if 'CK_ITEM_BALANCE_NONNEG' in msg.upper() or 'CK_STOCK_LEDGER_NONNEG' in msg.upper():
                    msg = "This would take an item's stock below zero — cancellation stopped, nothing was changed."
                return False, msg


# ═══════════════════════════════════════════════════════════════════
# GATE PASS MODULE
# FRD: "Gate Pass Module & Sales Order Integration"
# ═══════════════════════════════════════════════════════════════════

def generate_gatepass_id(cur, year=None):
    """Same pattern as generate_doc_id()/generate_ship_doc_id() -- GP-YYYY-NNNN,
    using the SAME cursor as the header insert that follows it."""
    yr = year or date.today().year
    prefix = f'GP-{yr}-'
    cur.execute("SELECT MAX(GATE_PASS_ID) FROM wst_djn_gatepass_header WHERE GATE_PASS_ID LIKE :1", [prefix + '%'])
    row = cur.fetchone()
    last = row[0] if row else None
    last_n = int(last.split('-')[-1]) if last else 0
    return f'{prefix}{last_n + 1:04d}'


def fetch_gatepass_senders():
    """Active senders for the Sender Name dropdown."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT SENDER_ID, SENDER_NAME FROM wst_djn_gatepass_senders WHERE IS_ACTIVE=1 ORDER BY SENDER_NAME")
            cols = [c[0] for c in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]


def add_gatepass_sender(sender_name, username=None):
    """Inline add for the Sender Name dropdown's '+' button (Section 4).
    Returns the new SENDER_ID."""
    with get_connection(username) as conn:
        with conn.cursor() as cur:
            cur.execute("""INSERT INTO wst_djn_gatepass_senders (SENDER_NAME, CREATED_BY)
                VALUES (:1, :2)""", [sender_name.strip(), username])
            cur.execute("SELECT MAX(SENDER_ID) FROM wst_djn_gatepass_senders WHERE SENDER_NAME=:1", [sender_name.strip()])
            new_id = cur.fetchone()[0]
            conn.commit()
            return new_id


def fetch_vendors_with_open_so(division, month):
    """Scenario 1 (Shipment module), Section 3B: unique vendors with at
    least one Sales Order line not yet fully Closed, for this division +
    month. Filters on LINE_STATUS directly rather than the header's own
    aggregate STATUS -- more precise, since a single OPEN header can mix
    Closed and still-open lines, and this only needs to know "does this
    vendor have anything left to dispatch", which is a line-level fact."""
    month_first = f'{month}-01' if len(str(month)) == 7 else str(month)
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""SELECT DISTINCT sh.VENDOR_ID, v.VENDOR_NAME
                FROM wst_djn_sales_header sh
                JOIN wst_djn_sales_line sl ON sl.DOC_ID = sh.DOC_ID
                JOIN wst_djn_vendors v ON v.VENDOR_ID = sh.VENDOR_ID
                WHERE sh.DIVISION=:1
                  AND TRUNC(sh.DOC_DATE,'MM') = TRUNC(TO_DATE(:2,'YYYY-MM-DD'),'MM')
                  AND sh.STATUS != 'CANCELLED'
                  AND NVL(sl.LINE_STATUS,'Entered') IN ('Entered','Partial')
                ORDER BY v.VENDOR_NAME""",
                [str(division), month_first])
            cols = [c[0] for c in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]


def fetch_open_so_lines_for_vendor(vendor_id, division, month, exclude_so_line_ids=None):
    """Scenario 1, Section 3B: every not-yet-Closed line across ALL of this
    vendor's Sales Orders for the division+month -- "Multi-Order & Line
    Grid Loading" and the "Closed Line Exclusion Rule" together. Includes
    REMAINING_QTY (QUANTITY - SHIPPED_QTY) alongside the original
    SO_ORDER_QTY the FRD's grid column calls for, since Gate Pass Qty must
    validate against what's actually still owed on the line, not its
    original full quantity.

    exclude_so_line_ids: when editing an existing Draft, pass the
    so_line_ids already sitting in that draft's "Already in This Draft"
    table here. A Draft hasn't touched SHIPPED_QTY yet, so those lines
    would otherwise still show LINE_STATUS 'Entered'/'Partial' and
    appear a SECOND time as "available to add" -- letting the same SO
    line get selected twice in one submission, which would double its
    SHIPPED_QTY increment when posted."""
    month_first = f'{month}-01' if len(str(month)) == 7 else str(month)
    with get_connection() as conn:
        with conn.cursor() as cur:
            exclude_clause = ""
            params = [str(division), vendor_id, month_first]
            if exclude_so_line_ids:
                binds = [f':ex{i}' for i in range(len(exclude_so_line_ids))]
                exclude_clause = f" AND sl.LINE_ID NOT IN ({','.join(binds)})"
                params += [int(x) for x in exclude_so_line_ids]
            cur.execute(f"""SELECT sl.LINE_ID AS SO_LINE_ID, sl.LINE_NO AS SO_LINE_NO, sh.DOC_ID AS SO_DOC_ID,
                    sl.ITEM_ID, i.ITEM_NAME, i.UNIT AS UOM, i.ITEM_CODE, c.PREFIX,
                    sl.QUANTITY AS SO_ORDER_QTY, NVL(sl.SHIPPED_QTY,0) AS SHIPPED_QTY,
                    sl.QUANTITY - NVL(sl.SHIPPED_QTY,0) AS REMAINING_QTY,
                    NVL(sl.LINE_STATUS,'Entered') AS LINE_STATUS
                FROM wst_djn_sales_header sh
                JOIN wst_djn_sales_line sl ON sl.DOC_ID = sh.DOC_ID
                LEFT JOIN wst_djn_items i ON i.ITEM_ID = sl.ITEM_ID
                LEFT JOIN wst_djn_categories c ON c.CATEGORY_ID = i.CATEGORY_ID
                WHERE sh.DIVISION=:1 AND sh.VENDOR_ID=:2
                  AND TRUNC(sh.DOC_DATE,'MM') = TRUNC(TO_DATE(:3,'YYYY-MM-DD'),'MM')
                  AND sh.STATUS != 'CANCELLED'
                  AND NVL(sl.LINE_STATUS,'Entered') IN ('Entered','Partial'){exclude_clause}
                ORDER BY sh.DOC_ID, sl.LINE_NO""",
                params)
            cols = [c[0] for c in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]


def _recalc_sales_header_status(cur, doc_id):
    """Recomputes the header's aggregate STATUS fresh from its own lines'
    actual SHIPPED_QTY, every time -- same 'always recompute from
    source, never increment' philosophy as _recalc_item_balance(),
    rather than trying to reason out each individual transition.

    FIX: previously returned immediately whenever the header was still
    DRAFT, which meant a document fulfilled via Gate Pass (this
    function's only caller) could never leave DRAFT at all -- nothing
    else ever moves it out. DRAFT is still the required precondition
    for post_sales_document()'s own atomic "Ship & Post" button (see
    its own STATUS != 'DRAFT' check), so once a document has ANY real
    Gate Pass shipment activity against it, it's correctly no longer a
    candidate for that atomic path either -- shipping through both
    mechanisms on the same document would risk double-fulfillment.
    CANCELLED is still left untouched -- a cancelled document's status
    is a terminal state this function has no business overriding.

    Three real states now, computed from SHIPPED_QTY directly rather
    than trusting LINE_STATUS labels alone (belt and suspenders --
    these should always agree, but SHIPPED_QTY is the actual number
    Gate Pass writes):
      OPEN    -- no line has shipped anything yet
      PARTIAL -- at least one line has shipped something, but not
                 every line is fully shipped
      CLOSED  -- every line is fully shipped
    """
    cur.execute("SELECT STATUS FROM wst_djn_sales_header WHERE DOC_ID=:1", [doc_id])
    row = cur.fetchone()
    if not row or row[0] == 'CANCELLED':
        return
    cur.execute("SELECT QUANTITY, NVL(SHIPPED_QTY,0) FROM wst_djn_sales_line WHERE DOC_ID=:1", [doc_id])
    line_rows = cur.fetchall()
    if not line_rows:
        return
    any_shipped = any(float(shipped) > 0 for _qty, shipped in line_rows)
    all_closed = all(float(shipped) >= float(qty) for qty, shipped in line_rows)
    if all_closed:
        new_status = 'CLOSED'
    elif any_shipped:
        new_status = 'PARTIAL'
    else:
        new_status = 'OPEN'
    cur.execute("UPDATE wst_djn_sales_header SET STATUS=:1 WHERE DOC_ID=:2", [new_status, doc_id])


def recalculate_all_sales_header_statuses(username=None):
    """One-time catch-up: _recalc_sales_header_status() only runs
    reactively, as part of post_gate_pass() -- it has no way to reach
    back and fix a header whose lines were already updated by a PAST
    gate pass posting that ran before this function's own DRAFT-early-
    return bug was fixed. Any such header is permanently stuck showing
    DRAFT/Open no matter how much of it has actually shipped, until
    something re-triggers a recalc. This runs it once, immediately, for
    every existing header (except CANCELLED, which the underlying
    function already leaves alone). Safe to run more than once -- it's
    the same idempotent recompute-from-source logic either way.
    Returns the number of headers whose status actually changed."""
    with get_connection(username) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT DOC_ID, STATUS FROM wst_djn_sales_header WHERE STATUS != 'CANCELLED'")
            headers = cur.fetchall()
            changed = 0
            for doc_id, old_status in headers:
                _recalc_sales_header_status(cur, doc_id)
                cur.execute("SELECT STATUS FROM wst_djn_sales_header WHERE DOC_ID=:1", [doc_id])
                new_status = cur.fetchone()[0]
                if new_status != old_status:
                    changed += 1
            conn.commit()
            return changed


def save_gate_pass_draft(header, lines, gate_pass_id=None, username=None):
    """Section 6A, Draft path: saves header + line details WITHOUT any
    stock movement -- no ledger entry, no balance change, no SO
    SHIPPED_QTY update. Deliberately does NOT run the stock-availability
    check either (that belongs to posting, not drafting) -- the whole
    point of a draft is to let someone save progress freely and come
    back to it, not to gate it on the same validation posting requires.

    gate_pass_id=None -> creates a brand new Draft.
    gate_pass_id given -> updates an EXISTING Draft's header and
    replaces its lines with the given set. Refuses (fail-closed) if that
    record isn't actually still a Draft -- editing something already
    Posted or Cancelled through this path would silently bypass the
    stock logic that's supposed to gate any change to a live document.

    Returns (True, gate_pass_id) or (False, error_message)."""
    division = header['division']
    module_type = header['module_type']

    with get_connection(username) as conn:
        with conn.cursor() as cur:
            try:
                if not lines:
                    return False, "Cannot save a Gate Pass with no line items."

                today = date.today().isoformat()
                gp_date = header.get('gate_pass_date') or today

                if gate_pass_id:
                    cur.execute("SELECT STATUS FROM wst_djn_gatepass_header WHERE GATE_PASS_ID=:1 AND DIVISION=:2",
                                [gate_pass_id, str(division)])
                    row = cur.fetchone()
                    if not row:
                        return False, "Gate Pass not found, or it belongs to a different division."
                    if row[0] != 'Draft':
                        return False, f"Only a Draft can be saved this way (this one is {row[0]}) -- use Ship & Post or Cancel instead."

                    cur.execute("""UPDATE wst_djn_gatepass_header SET
                        MODULE_TYPE=:1, GATE_PASS_DATE=TO_DATE(:2,'YYYY-MM-DD'), DOCUMENT_TYPE=:3,
                        SENDER_ID=:4, SHIP_TO=:5, SENDER_DEPARTMENT_ID=:6, VEHICLE_TYPE=:7,
                        VEHICLE_NO=:8, DRIVER_NAME=:9, RECEIVER_NAME=:10, REMARKS=:11
                        WHERE GATE_PASS_ID=:12""",
                        [module_type, gp_date, header.get('document_type') or 'Waste',
                         header.get('sender_id'), header.get('ship_to'), header.get('sender_department_id'),
                         header.get('vehicle_type'), header.get('vehicle_no'), header.get('driver_name'),
                         header.get('receiver_name'), header.get('remarks'), gate_pass_id])
                    cur.execute("DELETE FROM wst_djn_gatepass_line WHERE GATE_PASS_ID=:1", [gate_pass_id])
                else:
                    gate_pass_id = generate_gatepass_id(cur)
                    cur.execute("""INSERT INTO wst_djn_gatepass_header
                        (GATE_PASS_ID, MODULE_TYPE, DIVISION, GATE_PASS_DATE, DOCUMENT_TYPE,
                         SENDER_ID, SHIP_TO, SENDER_DEPARTMENT_ID, VEHICLE_TYPE, VEHICLE_NO,
                         DRIVER_NAME, RECEIVER_NAME, REMARKS, STATUS, CREATED_BY, CREATED_DATE)
                        VALUES (:1,:2,:3,TO_DATE(:4,'YYYY-MM-DD'),:5,:6,:7,:8,:9,:10,:11,:12,:13,'Draft',:14,SYSDATE)""",
                        [gate_pass_id, module_type, str(division), gp_date, header.get('document_type') or 'Waste',
                         header.get('sender_id'), header.get('ship_to'), header.get('sender_department_id'),
                         header.get('vehicle_type'), header.get('vehicle_no'), header.get('driver_name'),
                         header.get('receiver_name'), header.get('remarks'), username])

                for i, ln in enumerate(lines):
                    item_id = int(ln['item_id'])
                    qty = float(ln['gatepass_qty'])
                    so_doc_id = ln.get('so_doc_id')
                    so_line_id = ln.get('so_line_id')

                    cur.execute("""SELECT c.PREFIX, i.ITEM_CODE, i.ITEM_NAME, i.UNIT FROM wst_djn_items i
                        LEFT JOIN wst_djn_categories c ON c.CATEGORY_ID = i.CATEGORY_ID
                        WHERE i.ITEM_ID=:1""", [item_id])
                    item_row = cur.fetchone()
                    prefix, item_code, description, uom = item_row if item_row else (None, None, None, None)
                    so_order_qty = None
                    if so_line_id:
                        cur.execute("SELECT QUANTITY FROM wst_djn_sales_line WHERE LINE_ID=:1", [int(so_line_id)])
                        q = cur.fetchone()
                        so_order_qty = float(q[0]) if q else None

                    cur.execute("""INSERT INTO wst_djn_gatepass_line
                        (GATE_PASS_ID, LINE_NO, SO_DOC_ID, SO_LINE_ID, ITEM_ID,
                         ITEM_PREFIX, ITEM_CODE, ITEM_DESCRIPTION, UOM, SO_ORDER_QTY, GATEPASS_QTY, REMARKS)
                        VALUES (:1,:2,:3,:4,:5,:6,:7,:8,:9,:10,:11,:12)""",
                        [gate_pass_id, (i + 1) * 10, so_doc_id, so_line_id, item_id,
                         prefix, item_code, description, uom, so_order_qty, qty, ln.get('remarks')])

                conn.commit()
                return True, gate_pass_id
            except Exception as e:
                conn.rollback()
                return False, str(e)


def post_gate_pass(header, lines, gate_pass_id=None, username=None):
    """The main 'Ship & Post' transaction (Section 6A/6B). Stock
    validation, ledger deduction, and SO SHIPPED_QTY updates -- the
    logic this whole module exists for -- run ONLY here, never in
    save_gate_pass_draft(), so a draft can never move stock no matter
    what else changes about it.

    gate_pass_id=None -> creates and posts a brand new Gate Pass in one
    step (skip drafting entirely).
    gate_pass_id given -> posts an EXISTING Draft: replaces its header
    and lines with the given (final) set, THEN runs the exact same
    validation and stock deduction as the direct-post path, and flips
    STATUS to 'Posted'. Refuses (fail-closed) if that record isn't
    actually still a Draft -- posting something already Posted or
    Cancelled again would double-deduct stock.

    Returns (True, gate_pass_id) or (False, error_message). Same
    one-connection, commit-once-at-the-end atomicity as
    post_sales_document()."""
    division = header['division']
    module_type = header['module_type']

    with get_connection(username) as conn:
        with conn.cursor() as cur:
            try:
                if not lines:
                    return False, "Cannot post a Gate Pass with no line items."

                # Defense in depth: the same so_line_id must never appear
                # twice in one submission -- editing a Draft's "Already in
                # This Draft" table alongside "Select Lines to Ship" is
                # exactly the scenario this could otherwise slip through
                # in (both sides read from wst_djn_sales_line.LINE_STATUS,
                # which a Draft never changes). Catching it here as well,
                # not just in fetch_open_so_lines_for_vendor()'s exclusion
                # list, means a template/JS bug can't silently double a
                # SHIPPED_QTY increment.
                so_line_id_counts = {}
                for ln in lines:
                    slid = ln.get('so_line_id')
                    if slid:
                        so_line_id_counts[slid] = so_line_id_counts.get(slid, 0) + 1
                dup_so_lines = [k for k, v in so_line_id_counts.items() if v > 1]
                if dup_so_lines:
                    return False, (f"Sales Order line #{dup_so_lines[0]} appears more than once in this "
                                    f"submission -- refusing to post to avoid double-counting it. Reload the page and try again.")

                is_promoting_draft = bool(gate_pass_id)
                if is_promoting_draft:
                    cur.execute("SELECT STATUS FROM wst_djn_gatepass_header WHERE GATE_PASS_ID=:1 AND DIVISION=:2",
                                [gate_pass_id, str(division)])
                    row = cur.fetchone()
                    if not row:
                        return False, "Gate Pass not found, or it belongs to a different division."
                    if row[0] != 'Draft':
                        return False, f"Only a Draft can be posted (this one is already {row[0]})."

                # Stock validation FIRST, before writing anything -- same
                # pattern as post_sales_document(): sum requested quantity
                # per item first, since two lines could reference the same
                # item (e.g. dispatching against two different SOs for the
                # same item in one Gate Pass).
                requested_by_item = {}
                for ln in lines:
                    requested_by_item[ln['item_id']] = requested_by_item.get(ln['item_id'], 0) + float(ln['gatepass_qty'])

                for item_id, total_requested in requested_by_item.items():
                    cur.execute("SELECT BALANCE FROM wst_djn_item_balance WHERE ITEM_ID=:1 AND DIVISION=:2",
                                [int(item_id), str(division)])
                    bal_row = cur.fetchone()
                    available = float(bal_row[0]) if bal_row and bal_row[0] is not None else 0.0
                    if total_requested > available:
                        cur.execute("SELECT ITEM_NAME FROM wst_djn_items WHERE ITEM_ID=:1", [int(item_id)])
                        name_row = cur.fetchone()
                        item_name = name_row[0] if name_row else f'Item #{item_id}'
                        return False, (f'Entered quantity exceeds available stock balance for "{item_name}": '
                                       f'requested {total_requested:g}, only {available:g} available.')

                # For Shipment-module lines, also validate against what's
                # actually still owed on the SO line -- not stated as an
                # explicit rule in the FRD (only the stock-balance check
                # is), but shipping more than an SO ever ordered would be
                # a genuine data-integrity problem, so this is enforced as
                # a necessary safety rail rather than left as a silent gap.
                if module_type == 'Shipment':
                    for ln in lines:
                        if not ln.get('so_line_id'):
                            continue
                        cur.execute("""SELECT sl.QUANTITY, NVL(sl.SHIPPED_QTY,0), sh.STATUS, sh.DOC_ID
                            FROM wst_djn_sales_line sl
                            JOIN wst_djn_sales_header sh ON sh.DOC_ID = sl.DOC_ID
                            WHERE sl.LINE_ID=:1""", [int(ln['so_line_id'])])
                        so_row = cur.fetchone()
                        if not so_row:
                            return False, f"Sales Order line #{ln['so_line_id']} not found."
                        so_qty, already_shipped, so_status, so_doc_id = so_row
                        so_qty, already_shipped = float(so_qty), float(already_shipped or 0)
                        # FIX: previously only checked remaining quantity on
                        # the LINE -- never the parent Sales Order's own
                        # STATUS, so a Gate Pass could ship against a line
                        # whose order had already been Cancelled. A
                        # cancelled order's lines are reset to
                        # SHIPPED_QTY=0 by cancel_sales_document(), so
                        # "remaining" alone looked completely normal and
                        # let it through.
                        if so_status == 'CANCELLED':
                            return False, (f'Sales Order {so_doc_id} has been cancelled -- '
                                           f'cannot ship against it. Nothing was posted.')
                        remaining = so_qty - already_shipped
                        if float(ln['gatepass_qty']) > remaining + 0.0001:
                            cur.execute("SELECT ITEM_NAME FROM wst_djn_items WHERE ITEM_ID=:1", [int(ln['item_id'])])
                            name_row = cur.fetchone()
                            item_name = name_row[0] if name_row else f"Item #{ln['item_id']}"
                            return False, (f'Gate Pass Qty for "{item_name}" exceeds what remains on its Sales '
                                           f'Order line: {remaining:g} remaining, {float(ln["gatepass_qty"]):g} entered.')

                today = date.today().isoformat()
                gp_date = header.get('gate_pass_date') or today

                if is_promoting_draft:
                    cur.execute("""UPDATE wst_djn_gatepass_header SET
                        MODULE_TYPE=:1, GATE_PASS_DATE=TO_DATE(:2,'YYYY-MM-DD'), DOCUMENT_TYPE=:3,
                        SENDER_ID=:4, SHIP_TO=:5, SENDER_DEPARTMENT_ID=:6, VEHICLE_TYPE=:7,
                        VEHICLE_NO=:8, DRIVER_NAME=:9, RECEIVER_NAME=:10, REMARKS=:11,
                        STATUS='Posted'
                        WHERE GATE_PASS_ID=:12""",
                        [module_type, gp_date, header.get('document_type') or 'Waste',
                         header.get('sender_id'), header.get('ship_to'), header.get('sender_department_id'),
                         header.get('vehicle_type'), header.get('vehicle_no'), header.get('driver_name'),
                         header.get('receiver_name'), header.get('remarks'), gate_pass_id])
                    cur.execute("DELETE FROM wst_djn_gatepass_line WHERE GATE_PASS_ID=:1", [gate_pass_id])
                else:
                    gate_pass_id = generate_gatepass_id(cur)
                    cur.execute("""INSERT INTO wst_djn_gatepass_header
                        (GATE_PASS_ID, MODULE_TYPE, DIVISION, GATE_PASS_DATE, DOCUMENT_TYPE,
                         SENDER_ID, SHIP_TO, SENDER_DEPARTMENT_ID, VEHICLE_TYPE, VEHICLE_NO,
                         DRIVER_NAME, RECEIVER_NAME, REMARKS, STATUS, CREATED_BY, CREATED_DATE)
                        VALUES (:1,:2,:3,TO_DATE(:4,'YYYY-MM-DD'),:5,:6,:7,:8,:9,:10,:11,:12,:13,'Posted',:14,SYSDATE)""",
                        [gate_pass_id, module_type, str(division), gp_date, header.get('document_type') or 'Waste',
                         header.get('sender_id'), header.get('ship_to'), header.get('sender_department_id'),
                         header.get('vehicle_type'), header.get('vehicle_no'), header.get('driver_name'),
                         header.get('receiver_name'), header.get('remarks'), username])

                touched_doc_ids = set()
                for i, ln in enumerate(lines):
                    item_id = int(ln['item_id'])
                    qty = float(ln['gatepass_qty'])
                    so_doc_id = ln.get('so_doc_id')
                    so_line_id = ln.get('so_line_id')

                    cur.execute("""SELECT c.PREFIX, i.ITEM_CODE, i.ITEM_NAME, i.UNIT FROM wst_djn_items i
                        LEFT JOIN wst_djn_categories c ON c.CATEGORY_ID = i.CATEGORY_ID
                        WHERE i.ITEM_ID=:1""", [item_id])
                    item_row = cur.fetchone()
                    prefix, item_code, description, uom = item_row if item_row else (None, None, None, None)
                    so_order_qty = None
                    if so_line_id:
                        cur.execute("SELECT QUANTITY FROM wst_djn_sales_line WHERE LINE_ID=:1", [int(so_line_id)])
                        q = cur.fetchone()
                        so_order_qty = float(q[0]) if q else None

                    cur.execute("""INSERT INTO wst_djn_gatepass_line
                        (GATE_PASS_ID, LINE_NO, SO_DOC_ID, SO_LINE_ID, ITEM_ID,
                         ITEM_PREFIX, ITEM_CODE, ITEM_DESCRIPTION, UOM, SO_ORDER_QTY, GATEPASS_QTY, REMARKS)
                        VALUES (:1,:2,:3,:4,:5,:6,:7,:8,:9,:10,:11,:12)""",
                        [gate_pass_id, (i + 1) * 10, so_doc_id, so_line_id, item_id,
                         prefix, item_code, description, uom, so_order_qty, qty, ln.get('remarks')])

                    # Ledger + balance: a genuine physical dispatch either
                    # way (Shipment or Transfer) -- distinct TXN_TYPEs so an
                    # auditor scanning the ledger sees exactly what moved
                    # the stock, and so Phase 4's reversal can target the
                    # right entries precisely.
                    txn_type = 'GATEPASS_SHIPMENT' if module_type == 'Shipment' else 'GATEPASS_TRANSFER'
                    narration = f'Shipped via Gate Pass #{gate_pass_id}'
                    try:
                        cur.execute("""INSERT INTO wst_djn_stock_ledger
                            (ITEM_ID, TXN_DATE, TXN_TYPE, QTY_IN, QTY_OUT, BALANCE, REF_ID, DIVISION,
                             TRANSACTION_TYPE, SOURCE_REF, SOURCE_TABLE, POSTED_BY)
                            VALUES (:1, TO_DATE(:2,'YYYY-MM-DD'), :3, 0, :4, 0, NULL, :5, :6, :7, 'wst_djn_gatepass_header', :8)""",
                            [item_id, gp_date, txn_type, qty, str(division), txn_type, narration, username])
                    except oracledb.DatabaseError:
                        cur.execute("""INSERT INTO wst_djn_stock_ledger
                            (ITEM_ID, TXN_DATE, TXN_TYPE, QTY_IN, QTY_OUT, BALANCE, REF_ID, DIVISION)
                            VALUES (:1, TO_DATE(:2,'YYYY-MM-DD'), :3, 0, :4, 0, NULL, :5)""",
                            [item_id, gp_date, txn_type, qty, str(division)])
                    _recalc_item_balance(cur, item_id, division, gp_date, txn_type, 0, qty)

                    if so_line_id:
                        cur.execute("""UPDATE wst_djn_sales_line
                            SET SHIPPED_QTY = NVL(SHIPPED_QTY,0) + :1,
                                LINE_STATUS = CASE WHEN NVL(SHIPPED_QTY,0) + :2 >= QUANTITY THEN 'Closed' ELSE 'Partial' END
                            WHERE LINE_ID=:3""", [qty, qty, int(so_line_id)])
                        touched_doc_ids.add(so_doc_id)

                for doc_id in touched_doc_ids:
                    _recalc_sales_header_status(cur, doc_id)

                conn.commit()
                return True, gate_pass_id
            except Exception as e:
                conn.rollback()
                msg = str(e)
                if 'CK_ITEM_BALANCE_NONNEG' in msg.upper() or 'CK_STOCK_LEDGER_NONNEG' in msg.upper():
                    msg = "This would take an item's stock below zero — posting cancelled, nothing was changed."
                return False, msg


def delete_gate_pass_draft(gate_pass_id, division, username=None):
    """Section 6A, Draft deletion: permanently removes a Draft Gate Pass
    and its lines. Refuses (fail-closed) unless the record is still a
    Draft -- a Posted Gate Pass has already moved stock and can only be
    undone through cancel_gate_pass()'s proper reversal, never a bare
    delete. Returns (True, None) or (False, error_message)."""
    with get_connection(username) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT STATUS FROM wst_djn_gatepass_header WHERE GATE_PASS_ID=:1 AND DIVISION=:2",
                        [gate_pass_id, str(division)])
            row = cur.fetchone()
            if not row:
                return False, "Gate Pass not found, or it belongs to a different division."
            if row[0] != 'Draft':
                return False, f"Only a Draft can be deleted directly (this one is {row[0]}) -- use Cancel Gate Pass instead."
            cur.execute("DELETE FROM wst_djn_gatepass_line WHERE GATE_PASS_ID=:1", [gate_pass_id])
            cur.execute("DELETE FROM wst_djn_gatepass_header WHERE GATE_PASS_ID=:1", [gate_pass_id])
            conn.commit()
            return True, None


def archive_gate_pass(gate_pass_id, division, username=None):
    """Soft-delete for an already-Cancelled Gate Pass: hides it from
    fetch_all_gate_passes() (and so from the list screen) without
    touching the row, its lines, or a single ledger entry -- the record
    and its full stock-movement history (original deduction +
    cancellation reversal) stay exactly as they are, permanently
    available for audit. Deliberately NOT a hard delete: gate pass
    ledger entries link back by narration text ("Shipped via Gate Pass
    #...", "...due to GP Cancellation - GP #..."), not a structured
    foreign key, so actually removing the header would leave those
    entries pointing at a document number that no longer resolves to
    anything -- exactly the audit-trail gap this function exists to
    avoid.

    Refuses (fail-closed) unless the record is Cancelled -- Draft has
    its own hard-delete path (delete_gate_pass_draft), and Posted must
    go through cancel_gate_pass() first; archiving is only ever the
    LAST step after cancellation, never a substitute for it. Also
    refuses to re-archive an already-archived record. Returns
    (True, None) or (False, error_message)."""
    with get_connection(username) as conn:
        with conn.cursor() as cur:
            try:
                cur.execute("SELECT STATUS, ARCHIVED_DATE FROM wst_djn_gatepass_header WHERE GATE_PASS_ID=:1 AND DIVISION=:2",
                            [gate_pass_id, str(division)])
                row = cur.fetchone()
            except oracledb.DatabaseError:
                return False, "This instance doesn't have the archiving column yet -- run the schema migration first."
            if not row:
                return False, "Gate Pass not found, or it belongs to a different division."
            status, archived_date = row
            if status != 'Cancelled':
                return False, f"Only a Cancelled Gate Pass can be archived this way (this one is {status})."
            if archived_date is not None:
                return False, "This Gate Pass is already archived."
            cur.execute("""UPDATE wst_djn_gatepass_header
                SET ARCHIVED_BY=:1, ARCHIVED_DATE=SYSDATE
                WHERE GATE_PASS_ID=:2""", [username, gate_pass_id])
            conn.commit()
            return True, None


def fetch_all_gate_passes(division=None, status=None, month=None):
    """List-fetch for the Gate Pass screen, matching fetch_all_shipments()'s
    pattern. Most recent first. Archived records (soft-deleted Cancelled
    Gate Passes -- see archive_gate_pass()) are always excluded here,
    regardless of any other filter -- they still exist, with their full
    ledger trail intact, just never shown on this list."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            select_cols = """SELECT gp.GATE_PASS_ID, gp.MODULE_TYPE, gp.DIVISION,
                    TO_CHAR(gp.GATE_PASS_DATE,'DD-Mon-YYYY') AS GATE_PASS_DATE, gp.STATUS,
                    s.SENDER_NAME, gp.SHIP_TO, gp.RECEIVER_NAME, gp.CREATED_BY,
                    TO_CHAR(gp.CANCELLED_DATE,'DD-Mon-YYYY') AS CANCELLED_DATE,
                    {manual_no_col}
                    (SELECT COUNT(*) FROM wst_djn_gatepass_line gl WHERE gl.GATE_PASS_ID = gp.GATE_PASS_ID) AS LINE_COUNT
                FROM wst_djn_gatepass_header gp
                LEFT JOIN wst_djn_gatepass_senders s ON s.SENDER_ID = gp.SENDER_ID"""
            where, params = [], []
            if division:
                params.append(str(division)); where.append(f"gp.DIVISION = :{len(params)}")
            if status and status != 'ALL':
                params.append(str(status)); where.append(f"gp.STATUS = :{len(params)}")
            if month:
                params.append(str(month)); where.append(f"TRUNC(gp.GATE_PASS_DATE,'MM') = TRUNC(TO_DATE(:{len(params)},'YYYY-MM-DD'),'MM')")

            w = (" WHERE " + " AND ".join(where + ["gp.ARCHIVED_DATE IS NULL"])) if where else " WHERE gp.ARCHIVED_DATE IS NULL"
            w_fallback = (" WHERE " + " AND ".join(where)) if where else ""
            order_sql = " ORDER BY gp.CREATED_DATE DESC, gp.GATE_PASS_ID DESC"

            # Two independent, unrelated schema gaps this defends against:
            # ARCHIVED_DATE (older, near-certainly already deployed) and
            # MANUAL_GATE_PASS_NO (new). Tried together first; each falls
            # back independently so either one being missing doesn't take
            # down the whole screen -- exactly the failure mode a plain,
            # undefended SELECT would have had the moment this column was
            # added to the code before the migration that creates it runs.
            base_sql = select_cols.format(manual_no_col='gp.MANUAL_GATE_PASS_NO,')
            try:
                cur.execute(base_sql + w + order_sql, params)
            except oracledb.DatabaseError:
                try:
                    cur.execute(base_sql + w_fallback + order_sql, params)
                except oracledb.DatabaseError:
                    base_sql = select_cols.format(manual_no_col='')
                    try:
                        cur.execute(base_sql + w + order_sql, params)
                    except oracledb.DatabaseError:
                        cur.execute(base_sql + w_fallback + order_sql, params)
            cols = [c[0] for c in cur.description]
            rows = [dict(zip(cols, row)) for row in cur.fetchall()]
            for r in rows:
                r.setdefault('MANUAL_GATE_PASS_NO', None)
            return rows


def fetch_gate_pass_by_id(gate_pass_id, division=None):
    with get_connection() as conn:
        with conn.cursor() as cur:
            sql = """SELECT gp.GATE_PASS_ID, gp.MODULE_TYPE, gp.DIVISION,
                    TO_CHAR(gp.GATE_PASS_DATE,'DD-Mon-YYYY') AS GATE_PASS_DATE,
                    TO_CHAR(gp.GATE_PASS_DATE,'YYYY-MM-DD') AS GATE_PASS_DATE_ISO, gp.DOCUMENT_TYPE,
                    gp.SENDER_ID, s.SENDER_NAME, gp.SHIP_TO, gp.SENDER_DEPARTMENT_ID, d.DEPT_NAME,
                    gp.VEHICLE_TYPE, gp.VEHICLE_NO, gp.DRIVER_NAME, gp.RECEIVER_NAME, gp.REMARKS,
                    gp.STATUS, gp.CREATED_BY, TO_CHAR(gp.CREATED_DATE,'DD-Mon-YYYY HH24:MI') AS CREATED_DATE,
                    gp.CANCELLED_BY, TO_CHAR(gp.CANCELLED_DATE,'DD-Mon-YYYY HH24:MI') AS CANCELLED_DATE,
                    {manual_no_col}
                FROM wst_djn_gatepass_header gp
                LEFT JOIN wst_djn_gatepass_senders s ON s.SENDER_ID = gp.SENDER_ID
                LEFT JOIN wst_djn_departments d ON d.DEPT_ID = gp.SENDER_DEPARTMENT_ID
                WHERE gp.GATE_PASS_ID=:1"""
            params = [gate_pass_id]
            if division:
                sql += " AND gp.DIVISION=:2"
                params.append(str(division))
            try:
                cur.execute(sql.format(manual_no_col='gp.MANUAL_GATE_PASS_NO'), params)
            except oracledb.DatabaseError:
                # MANUAL_GATE_PASS_NO not on this schema yet -- degrade
                # rather than break the whole page; see the identical
                # fallback and full rationale in fetch_all_gate_passes().
                cur.execute(sql.format(manual_no_col='NULL AS MANUAL_GATE_PASS_NO'), params)
            cols = [c[0] for c in cur.description]
            row = cur.fetchone()
            return dict(zip(cols, row)) if row else None


def fetch_gate_pass_lines(gate_pass_id):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""SELECT gl.LINE_ID, gl.LINE_NO, gl.SO_DOC_ID, gl.SO_LINE_ID, sl.LINE_NO AS SO_LINE_NO,
                    gl.ITEM_ID, gl.ITEM_PREFIX, gl.ITEM_CODE, gl.ITEM_DESCRIPTION, gl.UOM,
                    gl.SO_ORDER_QTY, gl.GATEPASS_QTY, gl.REMARKS
                FROM wst_djn_gatepass_line gl
                LEFT JOIN wst_djn_sales_line sl ON sl.LINE_ID = gl.SO_LINE_ID
                WHERE gl.GATE_PASS_ID=:1 ORDER BY gl.LINE_NO""", [gate_pass_id])
            cols = [c[0] for c in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]


def set_manual_gate_pass_no(gate_pass_id, manual_no, division=None, username=None):
    """Sets the manually-assigned Gate Pass number -- written by gate/
    security staff once the physical dispatch has actually happened.
    Fail-closed on status: only a Posted Gate Pass has physically left
    yet (a Draft hasn't moved anything, a Cancelled one's dispatch was
    reversed), so this is refused for either of those rather than
    silently accepted. Division-scoped like every other by-ID fetch/
    update in this file, so a guessed/edited URL can't touch a Gate
    Pass belonging to a division this account isn't authorized for.
    Returns (True, None) or (False, error_message)."""
    with get_connection(username) as conn:
        with conn.cursor() as cur:
            sql = "SELECT STATUS FROM wst_djn_gatepass_header WHERE GATE_PASS_ID=:1"
            params = [gate_pass_id]
            if division:
                sql += " AND DIVISION=:2"
                params.append(str(division))
            cur.execute(sql, params)
            row = cur.fetchone()
            if not row:
                return False, "Gate Pass not found, or it belongs to a different division."
            if row[0] != 'Posted':
                return False, f"This Gate Pass is {row[0]}, not Posted -- the manual number can only be entered once it has actually been dispatched."
            manual_no = (manual_no or '').strip()
            if not manual_no:
                return False, "Manual Gate Pass No. cannot be blank."
            cur.execute("UPDATE wst_djn_gatepass_header SET MANUAL_GATE_PASS_NO=:1 WHERE GATE_PASS_ID=:2",
                        [manual_no, gate_pass_id])
            conn.commit()
            return True, None


def cancel_gate_pass(gate_pass_id, division, username=None):
    """Section 6B: cancelling a Gate Pass triggers an immediate reversal.

    For every line: restores the stock (Inward ledger entry, "Shipment
    Reversal due to GP Cancellation - GP #[GP Number]"), and for
    Shipment-module lines, DECREMENTS (not resets) the SO line's
    SHIPPED_QTY -- a single SO line can be dispatched across several
    separate Gate Passes, so cancelling ONE of them must only undo that
    Gate Pass's own contribution, not the line's entire shipped history.

    The Quotation Comparison lock only releases once a line's
    SHIPPED_QTY fully returns to zero -- explicit sign-off on this: if
    Gate Pass #1 shipped 4,000 of 5,000 and Gate Pass #2 later shipped
    the remaining 1,000 (closing the line), cancelling #2 alone must
    leave the line Partial and the Quotation still locked, not release
    it just because the most recent Gate Pass was undone.

    Transfer-module lines reverse the same way but never touch an SO or
    a Quotation lock -- there isn't one to release.

    Same one-connection, commit-once-at-the-end atomicity as the other
    lifecycle functions in this file."""
    with get_connection(username) as conn:
        with conn.cursor() as cur:
            try:
                cur.execute("""SELECT STATUS, MODULE_TYPE FROM wst_djn_gatepass_header
                    WHERE GATE_PASS_ID=:1 AND DIVISION=:2""", [gate_pass_id, str(division)])
                row = cur.fetchone()
                if not row:
                    return False, "Gate Pass not found, or it belongs to a different division."
                gp_status, module_type = row
                if gp_status != 'Posted':
                    return False, f"Only a Posted Gate Pass can be cancelled (this one is {gp_status})."

                cur.execute("""SELECT ITEM_ID, SO_DOC_ID, SO_LINE_ID, GATEPASS_QTY
                    FROM wst_djn_gatepass_line WHERE GATE_PASS_ID=:1""", [gate_pass_id])
                gp_lines = cur.fetchall()
                today = date.today().isoformat()
                touched_doc_ids = set()
                unlock_candidates = []  # (item_id, so_doc_id) pairs to check once all decrements are applied

                for item_id, so_doc_id, so_line_id, quantity in gp_lines:
                    txn_type = 'GATEPASS_REVERSAL' if so_line_id else 'GATEPASS_TRANSFER_REVERSAL'
                    narration = f'Shipment Reversal due to GP Cancellation - GP #{gate_pass_id}'
                    try:
                        cur.execute("""INSERT INTO wst_djn_stock_ledger
                            (ITEM_ID, TXN_DATE, TXN_TYPE, QTY_IN, QTY_OUT, BALANCE, REF_ID, DIVISION,
                             TRANSACTION_TYPE, SOURCE_REF, SOURCE_TABLE, POSTED_BY)
                            VALUES (:1, TO_DATE(:2,'YYYY-MM-DD'), :3, :4, 0, 0, NULL, :5, :6, :7, 'wst_djn_gatepass_header', :8)""",
                            [int(item_id), today, txn_type, float(quantity), str(division), txn_type, narration, username])
                    except oracledb.DatabaseError:
                        cur.execute("""INSERT INTO wst_djn_stock_ledger
                            (ITEM_ID, TXN_DATE, TXN_TYPE, QTY_IN, QTY_OUT, BALANCE, REF_ID, DIVISION)
                            VALUES (:1, TO_DATE(:2,'YYYY-MM-DD'), :3, :4, 0, 0, NULL, :5)""",
                            [int(item_id), today, txn_type, float(quantity), str(division)])
                    _recalc_item_balance(cur, item_id, division, today, txn_type, quantity, 0)

                    if so_line_id:
                        cur.execute("""UPDATE wst_djn_sales_line
                            SET SHIPPED_QTY = GREATEST(NVL(SHIPPED_QTY,0) - :1, 0),
                                LINE_STATUS = CASE
                                    WHEN GREATEST(NVL(SHIPPED_QTY,0) - :2, 0) <= 0 THEN 'Entered'
                                    WHEN GREATEST(NVL(SHIPPED_QTY,0) - :3, 0) >= QUANTITY THEN 'Closed'
                                    ELSE 'Partial'
                                END
                            WHERE LINE_ID=:4""", [float(quantity), float(quantity), float(quantity), int(so_line_id)])
                        touched_doc_ids.add(so_doc_id)
                        unlock_candidates.append((int(item_id), so_doc_id, int(so_line_id)))

                for doc_id in touched_doc_ids:
                    _recalc_sales_header_status(cur, doc_id)

                # Only NOW, after every decrement above has actually been
                # applied, check which lines are fully back to zero -- a
                # single Gate Pass can touch the same SO line's item only
                # once here (one row per line), so this is a direct
                # per-line check, not a running tally.
                for item_id, so_doc_id, so_line_id in unlock_candidates:
                    cur.execute("SELECT NVL(SHIPPED_QTY,0), SOURCE_TARGET_MONTH FROM wst_djn_sales_line sl "
                                "JOIN wst_djn_sales_header sh ON sh.DOC_ID = sl.DOC_ID "
                                "WHERE sl.LINE_ID=:1", [so_line_id])
                    check_row = cur.fetchone()
                    if not check_row:
                        continue
                    remaining_shipped, target_month = check_row
                    if remaining_shipped and float(remaining_shipped) > 0:
                        continue  # still partially shipped from ANOTHER Gate Pass -- lock stays
                    if target_month is None:
                        continue  # manually-created SO, never linked to a Comparison lock
                    _release_quotation_lock(cur, item_id, division, target_month.strftime('%Y-%m-%d'))

                cur.execute("""UPDATE wst_djn_gatepass_header
                    SET STATUS='Cancelled', CANCELLED_BY=:1, CANCELLED_DATE=SYSDATE
                    WHERE GATE_PASS_ID=:2""", [username, gate_pass_id])

                conn.commit()
                return True, None
            except Exception as e:
                conn.rollback()
                msg = str(e)
                if 'CK_ITEM_BALANCE_NONNEG' in msg.upper() or 'CK_STOCK_LEDGER_NONNEG' in msg.upper():
                    msg = "This would take an item's stock below zero — cancellation stopped, nothing was changed."
                return False, msg


def unlock_comparison_item(item_id, division, target_month, username=None):
    """Manual 'Unlock' action on the Quotation Comparison grid: only
    offered (and only allowed here) while the item's associated Sales
    document is still DRAFT AND has never been shipped -- i.e. no stock
    has moved for it yet, so undoing the vendor selection is a clean,
    safe operation with no stock movement to reverse. Once a document
    has been Ship & Posted, cancelling the SHIPMENT is the correct path
    instead (cancel_shipment() releases this same lock automatically as
    part of that cancellation, alongside reversing the stock) --
    refuses here rather than duplicating that reversal a second way.
    Removes the draft sales line (and the whole draft header, if that was
    its only line) alongside releasing the lock, so nothing is left
    orphaned on the Sales side. Returns (True, None) on success or
    (False, error_message)."""
    with get_connection(username) as conn:
        with conn.cursor() as cur:
            try:
                cur.execute("""SELECT NVL(ql.STATUS,'Open') FROM wst_djn_quotation_line ql
                    JOIN wst_djn_quotation_header qh ON ql.QUOTE_DOC_ID = qh.QUOTE_DOC_ID
                    WHERE ql.ITEM_ID=:1 AND qh.DIVISION=:2
                      AND qh.TARGET_MONTH=TRUNC(TO_DATE(:3,'YYYY-MM-DD'),'MM')
                      AND NVL(ql.STATUS,'Open')='Locked' FETCH FIRST 1 ROW ONLY""",
                    [int(item_id), str(division), str(target_month)])
                if not cur.fetchone():
                    return False, "This item isn't currently locked."

                # Find the DRAFT sales doc (if any) this item's lock routed
                # to, scoped by division + the dedicated linkage column
                # Comparison-generated docs record, independent of whatever
                # posting date the document's own DOC_DATE now holds.
                cur.execute("""SELECT sl.LINE_ID, sh.DOC_ID, sh.STATUS FROM wst_djn_sales_line sl
                    JOIN wst_djn_sales_header sh ON sl.DOC_ID = sh.DOC_ID
                    WHERE sl.ITEM_ID=:1 AND sh.DIVISION=:2
                      AND sh.SOURCE_TARGET_MONTH=TRUNC(TO_DATE(:3,'YYYY-MM-DD'),'MM')
                      AND sh.STATUS != 'CANCELLED'""",
                    [int(item_id), str(division), str(target_month)])
                sales_rows = cur.fetchall()

                non_draft = [r for r in sales_rows if r[2] != 'DRAFT']
                if non_draft:
                    return False, ("This item has already been Ship & Posted -- unlock isn't available here. "
                                    "Cancel the shipment from the Sales document instead if you need to undo it.")

                for line_id, sales_doc_id, _status in sales_rows:
                    cur.execute("DELETE FROM wst_djn_sales_line WHERE LINE_ID=:1", [line_id])
                    _recalc_header_total(cur, sales_doc_id)
                    cur.execute("SELECT COUNT(*) FROM wst_djn_sales_line WHERE DOC_ID=:1", [sales_doc_id])
                    if cur.fetchone()[0] == 0:
                        cur.execute("DELETE FROM wst_djn_sales_header WHERE DOC_ID=:1", [sales_doc_id])

                _release_quotation_lock(cur, item_id, division, target_month)

                conn.commit()
                return True, None
            except Exception as e:
                conn.rollback()
                return False, str(e)


# ─── WHATSAPP LOG ─────────────────────────────────────────
def fetch_all_whatsapp_logs():
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""SELECT w.LOG_ID, v.VENDOR_NAME,
                TO_CHAR(w.SENT_AT,'DD-Mon-YYYY HH24:MI') AS SENT_AT,
                w.STATUS, w.MESSAGE_TEXT
                FROM wst_djn_whatsapp_log w
                LEFT JOIN wst_djn_vendors v ON w.VENDOR_ID=v.VENDOR_ID
                ORDER BY w.LOG_ID DESC""")
            cols = [c[0] for c in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]

def insert_whatsapp_log(list_id, vendor_id, status, message_text):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""INSERT INTO wst_djn_whatsapp_log
                (LIST_ID, VENDOR_ID, SENT_AT, STATUS, MESSAGE_TEXT)
                VALUES (:1,:2,SYSTIMESTAMP,:3,:4)""",
                [int(list_id), int(vendor_id), status, message_text])
            conn.commit()



# ─── USER GENERIC GROUP TYPE (Master) ─────────────────────
def fetch_all_group_types():
    base_cols = "GROUP_CODE, SHORT_DESC"
    audit_cols = """,
                CREATED_BY, TO_CHAR(CREATED_DATE,'DD-Mon-YYYY HH24:MI') AS CREATED_DATE,
                LAST_UPDATED_BY, TO_CHAR(LAST_UPDATED_DATE,'DD-Mon-YYYY HH24:MI') AS LAST_UPDATED_DATE"""
    from_sql = " FROM wst_djn_user_generic_group_type ORDER BY GROUP_CODE"
    with get_connection() as conn:
        with conn.cursor() as cur:
            try:
                cur.execute(f"SELECT {base_cols}{audit_cols}{from_sql}")
            except oracledb.DatabaseError:
                # Audit columns not yet present on this table (DDL not applied). Degrade gracefully.
                cur.execute(f"SELECT {base_cols}{from_sql}")
            cols = [c[0] for c in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]

def fetch_group_type_by_id(group_code):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT GROUP_CODE, SHORT_DESC FROM wst_djn_user_generic_group_type WHERE GROUP_CODE=:1", [group_code])
            cols = [c[0] for c in cur.description]
            row = cur.fetchone()
            return dict(zip(cols, row)) if row else None

def insert_group_type(group_code, short_desc, username=None):
    with get_connection(username) as conn:  # username -> CLIENT_IDENTIFIER -> audit trigger sets CREATED_BY
        with conn.cursor() as cur:
            cur.execute("INSERT INTO wst_djn_user_generic_group_type (GROUP_CODE, SHORT_DESC) VALUES (:1,:2)",
                        [group_code.upper(), to_proper_case(short_desc)])
            conn.commit()

def update_group_type(group_code, short_desc, username=None):
    with get_connection(username) as conn:  # username -> CLIENT_IDENTIFIER -> audit trigger sets LAST_UPDATED_BY
        with conn.cursor() as cur:
            cur.execute("UPDATE wst_djn_user_generic_group_type SET SHORT_DESC=:1 WHERE GROUP_CODE=:2",
                        [to_proper_case(short_desc), group_code])
            conn.commit()

def delete_group_type(group_code, username=None):
    with get_connection(username) as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM wst_djn_user_generic_group_type WHERE GROUP_CODE=:1", [group_code])
            conn.commit()


# ─── USER GENERIC GROUP (Child) ───────────────────────────
def fetch_all_generic_groups():
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT g.CODE, g.GROUP_CODE, g.DESCRIPTION, t.SHORT_DESC
                FROM wst_djn_user_generic_group g
                LEFT JOIN wst_djn_user_generic_group_type t ON g.GROUP_CODE = t.GROUP_CODE
                ORDER BY g.GROUP_CODE, g.CODE
            """)
            cols = [c[0] for c in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]

def fetch_generic_group_by_id(code):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT CODE, GROUP_CODE, DESCRIPTION FROM wst_djn_user_generic_group WHERE CODE=:1", [code])
            cols = [c[0] for c in cur.description]
            row = cur.fetchone()
            return dict(zip(cols, row)) if row else None

def insert_generic_group(code, group_code, description):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO wst_djn_user_generic_group (CODE, GROUP_CODE, DESCRIPTION) VALUES (:1,:2,:3)",
                        [code, group_code, to_proper_case(description)])
            conn.commit()

def update_generic_group(code, group_code, description):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE wst_djn_user_generic_group SET GROUP_CODE=:1, DESCRIPTION=:2 WHERE CODE=:3",
                        [group_code, to_proper_case(description), code])
            conn.commit()

def delete_generic_group(code):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM wst_djn_user_generic_group WHERE CODE=:1", [code])
            conn.commit()

def fetch_groups_by_type(group_code):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT CODE, GROUP_CODE, DESCRIPTION
                FROM wst_djn_user_generic_group
                WHERE GROUP_CODE = :1
                ORDER BY CODE, DESCRIPTION
            """, [group_code])
            cols = [c[0] for c in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]

# ─── AUDIT LOG ────────────────────────────────────────────
def log_audit(table_name, record_id, action, changed_by, old_data=None, new_data=None):
    """Log create/edit/delete actions to audit table"""
    with get_connection() as conn:
        with conn.cursor() as cur:
            if action == 'DELETE':
                cur.execute("""
                    INSERT INTO wst_djn_audit_log 
                    (TABLE_NAME, RECORD_ID, ACTION, FIELD_NAME, OLD_VALUE, NEW_VALUE, CHANGED_BY)
                    VALUES (:1,:2,:3,'ALL',TO_CHAR(:4),'DELETED',:5)
                """, [table_name, str(record_id), action, str(old_data), changed_by])
            elif old_data and new_data:
                for key in new_data:
                    old_val = str(old_data.get(key, '')) if old_data else ''
                    new_val = str(new_data.get(key, ''))
                    if old_val != new_val:
                        cur.execute("""
                            INSERT INTO wst_djn_audit_log 
                            (TABLE_NAME, RECORD_ID, ACTION, FIELD_NAME, OLD_VALUE, NEW_VALUE, CHANGED_BY)
                            VALUES (:1,:2,:3,:4,:5,:6,:7)
                        """, [table_name, str(record_id), action, key, old_val, new_val, changed_by])
            else:
                cur.execute("""
                    INSERT INTO wst_djn_audit_log 
                    (TABLE_NAME, RECORD_ID, ACTION, FIELD_NAME, OLD_VALUE, NEW_VALUE, CHANGED_BY)
                    VALUES (:1,:2,:3,'ALL','','CREATED',:4)
                """, [table_name, str(record_id), action, changed_by])
            conn.commit()


def fetch_audit_logs(table_name=None, limit=200):
    sql = """
        SELECT LOG_ID, TABLE_NAME, RECORD_ID, ACTION, FIELD_NAME,
               OLD_VALUE, NEW_VALUE, CHANGED_BY,
               TO_CHAR(CHANGED_AT, 'DD-Mon-YYYY HH24:MI:SS') AS CHANGED_AT
        FROM wst_djn_audit_log
        {}
        ORDER BY LOG_ID DESC
        FETCH FIRST :1 ROWS ONLY
    """.format("WHERE TABLE_NAME = :2" if table_name else "")
    with get_connection() as conn:
        with conn.cursor() as cur:
            if table_name:
                cur.execute(sql, [limit, table_name])
            else:
                cur.execute(sql, [limit])
            cols = [c[0] for c in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]


# ─── DUPLICATE CHECKS ─────────────────────────────────────
def check_duplicate(table_name, column_name, value, exclude_value=None):
    """Returns True if duplicate exists"""
    if exclude_value:
        sql = f"SELECT COUNT(*) FROM {table_name} WHERE {column_name}=:1 AND {column_name}!=:2"
        params = [value, exclude_value]
    else:
        sql = f"SELECT COUNT(*) FROM {table_name} WHERE {column_name}=:1"
        params = [value]
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            count = cur.fetchone()[0]
            return count > 0


# ─── AUDIT LOG ────────────────────────────────────────────
def log_audit(table_name, record_id, action, changed_by, old_data=None, new_data=None):
    with get_connection() as conn:
        with conn.cursor() as cur:
            if action == 'DELETE':
                cur.execute("""
                    INSERT INTO wst_djn_audit_log 
                    (TABLE_NAME, RECORD_ID, ACTION, FIELD_NAME, OLD_VALUE, NEW_VALUE, CHANGED_BY)
                    VALUES (:1,:2,:3,'ALL',:4,'DELETED',:5)
                """, [table_name, str(record_id), action, str(old_data)[:1900], changed_by])
            elif old_data and new_data:
                changed_any = False
                for key in new_data:
                    old_val = str(old_data.get(key, '')) if old_data else ''
                    new_val = str(new_data.get(key, ''))
                    if old_val != new_val:
                        changed_any = True
                        cur.execute("""
                            INSERT INTO wst_djn_audit_log 
                            (TABLE_NAME, RECORD_ID, ACTION, FIELD_NAME, OLD_VALUE, NEW_VALUE, CHANGED_BY)
                            VALUES (:1,:2,:3,:4,:5,:6,:7)
                        """, [table_name, str(record_id), action, key, old_val[:1900], new_val[:1900], changed_by])
                if not changed_any:
                    pass
            else:
                cur.execute("""
                    INSERT INTO wst_djn_audit_log 
                    (TABLE_NAME, RECORD_ID, ACTION, FIELD_NAME, OLD_VALUE, NEW_VALUE, CHANGED_BY)
                    VALUES (:1,:2,:3,'ALL','','CREATED',:4)
                """, [table_name, str(record_id), action, changed_by])
            conn.commit()


def fetch_audit_logs(table_name=None, limit=200):
    if table_name:
        sql = """
            SELECT LOG_ID, TABLE_NAME, RECORD_ID, ACTION, FIELD_NAME,
                   OLD_VALUE, NEW_VALUE, CHANGED_BY,
                   TO_CHAR(CHANGED_AT, 'DD-Mon-YYYY HH24:MI:SS') AS CHANGED_AT
            FROM wst_djn_audit_log
            WHERE TABLE_NAME = :1
            ORDER BY LOG_ID DESC
            FETCH FIRST :2 ROWS ONLY
        """
        params = [table_name, limit]
    else:
        sql = """
            SELECT LOG_ID, TABLE_NAME, RECORD_ID, ACTION, FIELD_NAME,
                   OLD_VALUE, NEW_VALUE, CHANGED_BY,
                   TO_CHAR(CHANGED_AT, 'DD-Mon-YYYY HH24:MI:SS') AS CHANGED_AT
            FROM wst_djn_audit_log
            ORDER BY LOG_ID DESC
            FETCH FIRST :1 ROWS ONLY
        """
        params = [limit]
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            cols = [c[0] for c in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]


# ─── DUPLICATE CHECKS ─────────────────────────────────────
def check_duplicate(table_name, column_name, value, exclude_value=None, exclude_pk_col=None):
    if exclude_value and exclude_pk_col:
        sql = f"SELECT COUNT(*) FROM {table_name} WHERE UPPER({column_name})=UPPER(:1) AND {exclude_pk_col}!=:2"
        params = [value, exclude_value]
    else:
        sql = f"SELECT COUNT(*) FROM {table_name} WHERE UPPER({column_name})=UPPER(:1)"
        params = [value]
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchone()[0] > 0


def check_duplicate_combo(table_name, col1, val1, col2, val2, exclude_value=None, exclude_pk_col=None):
    if exclude_value and exclude_pk_col:
        sql = f"SELECT COUNT(*) FROM {table_name} WHERE {col1}=:1 AND {col2}=:2 AND {exclude_pk_col}!=:3"
        params = [val1, val2, exclude_value]
    else:
        sql = f"SELECT COUNT(*) FROM {table_name} WHERE {col1}=:1 AND {col2}=:2"
        params = [val1, val2]
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchone()[0] > 0

def fetch_group_types_paginated(search=None, page=1, page_size=7):
    offset = (page - 1) * page_size
    audit_cols = """,
                 CREATED_BY, TO_CHAR(CREATED_DATE,'DD-Mon-YYYY HH24:MI') AS CREATED_DATE,
                 LAST_UPDATED_BY, TO_CHAR(LAST_UPDATED_DATE,'DD-Mon-YYYY HH24:MI') AS LAST_UPDATED_DATE"""
    if search:
        count_sql = """SELECT COUNT(*) FROM wst_djn_user_generic_group_type
                       WHERE UPPER(GROUP_CODE) LIKE UPPER(:1) OR UPPER(SHORT_DESC) LIKE UPPER(:2)"""
        count_params = [f'%{search}%', f'%{search}%']
        sql = """SELECT GROUP_CODE, SHORT_DESC{cols} FROM wst_djn_user_generic_group_type
                 WHERE UPPER(GROUP_CODE) LIKE UPPER(:1) OR UPPER(SHORT_DESC) LIKE UPPER(:2)
                 ORDER BY GROUP_CODE
                 OFFSET :3 ROWS FETCH NEXT :4 ROWS ONLY"""
        params = [f'%{search}%', f'%{search}%', offset, page_size]
    else:
        count_sql = "SELECT COUNT(*) FROM wst_djn_user_generic_group_type"
        count_params = []
        sql = """SELECT GROUP_CODE, SHORT_DESC{cols} FROM wst_djn_user_generic_group_type
                 ORDER BY GROUP_CODE
                 OFFSET :1 ROWS FETCH NEXT :2 ROWS ONLY"""
        params = [offset, page_size]

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(count_sql, count_params)
            total = cur.fetchone()[0]
            try:
                cur.execute(sql.format(cols=audit_cols), params)
            except oracledb.DatabaseError:
                # Audit columns not yet present on this table (DDL not applied). Degrade gracefully.
                cur.execute(sql.format(cols=""), params)
            cols = [c[0] for c in cur.description]
            records = [dict(zip(cols, row)) for row in cur.fetchall()]
            return records, total

# ─── HOME DASHBOARD AGGREGATES (cached) ───────────────────
from django.core.cache import cache as _wh_cache

def fetch_home_summary():
    """Cached (~60s) aggregate counts for the Wastage landing page funnel +
    catalogue metrics. Each count is isolated so one failure degrades to 0."""
    cached = _wh_cache.get('wastage:home_summary')
    if cached is not None:
        return cached
    s = {'listed': 0, 'quoted': 0, 'assigned': 0, 'sold': 0,
         'categories': 0, 'active_items': 0, 'active_vendors': 0}
    counts = {
        'listed':         """SELECT
                                (SELECT COUNT(*) FROM wst_djn_monthly_stock_list) +
                                (SELECT COUNT(*) FROM wst_djn_msl_snapshot_line)
                             FROM DUAL""",
        # FIX (previously a real bug): wst_djn_quotations is a dead,
        # orphaned table -- insert_quotation(), the only function that
        # would ever write a NEW row to it, is never called anywhere in
        # the codebase. The real, active quotation workflow (everything
        # under the actual Quotations screens, including Comparison)
        # writes to wst_djn_quotation_header/wst_djn_quotation_line
        # instead. This always showed 0 (or a stale historical count)
        # regardless of how many quotations were genuinely being created.
        'quoted':         "SELECT COUNT(*) FROM wst_djn_quotation_line",
        # FIX (previously pointing at the wrong table entirely, confirmed
        # directly against generate_sales_from_comparison()): the real
        # signal for "locked/awarded via Quotation Comparison" is
        # wst_djn_quotation_line.STATUS='Locked' -- set on every
        # vendor's bid line for an item the moment it's locked, not
        # just the winning vendor's. wst_djn_vendor_assignment is a
        # genuinely separate, still-reachable screen (confirmed live in
        # views.py), but it's a different workflow entirely, tied to
        # Stock Lists rather than Quotation Comparison. COUNT(DISTINCT
        # ITEM_ID), not COUNT(*), since multiple vendors' bids on the
        # SAME item all get marked Locked together -- a plain row count
        # would overcount an item with several competing bids.
        'assigned':       "SELECT COUNT(DISTINCT ITEM_ID) FROM wst_djn_quotation_line WHERE STATUS='Locked'",
        # FIX (previously a real bug, same class as the 'quoted' fix
        # above): the second half of this query added rows from
        # wst_djn_sales -- confirmed genuinely orphaned, since
        # insert_sale(), the only function that would ever write a new
        # row there, is never called anywhere in the live app (checked
        # directly against views.py). That addition only ever
        # contributed stale, irrelevant historical noise -- never a
        # reflection of real, current sales activity. STATUS='CLOSED'
        # against wst_djn_sales_header is the real, correct signal,
        # matching the "Invoiced to buyers" label -- only fully
        # completed sales count as sold, not ones still Open/Partial.
        'sold':           "SELECT COUNT(*) FROM wst_djn_sales_header WHERE STATUS='CLOSED'",
        'categories':     "SELECT COUNT(*) FROM wst_djn_categories",
        'active_items':   "SELECT COUNT(*) FROM wst_djn_items WHERE IS_ACTIVE=1",
        'active_vendors': "SELECT COUNT(*) FROM wst_djn_vendors WHERE IS_ACTIVE=1",
    }
    with get_connection() as conn:
        with conn.cursor() as cur:
            for key, sql in counts.items():
                try:
                    cur.execute(sql); s[key] = cur.fetchone()[0]
                except oracledb.DatabaseError:
                    pass
    _wh_cache.set('wastage:home_summary', s, 60)
    return s


def fetch_home_dashboard(division=None):
    """Live stock widgets for the Wastage home page (cached ~60s per division).
    Every block is isolated: if one query fails, only that widget goes empty.
    Quantity totals are KG-only (summing kg + pcs + drums would be meaningless);
    per-item lists show each item's own unit."""
    from datetime import date as _d, timedelta as _td
    key = f'wastage:home_dash:{division or "ALL"}'
    cached = _wh_cache.get(key)
    if cached is not None:
        return cached

    today = _d.today()
    month_start = today.replace(day=1)
    d = {'stock_kg': 0.0, 'items_in_stock': 0, 'items_negative': 0,
         'month_received_kg': 0.0, 'month_dispatched_kg': 0.0,
         'trend': [], 'top_items': [], 'recent': []}
    div_l = " AND NVL(l.DIVISION,'08') = :div" if division else ""
    div_b = " AND NVL(b.DIVISION,'08') = :div" if division else ""
    dp = {'div': str(division)} if division else {}
    KG = "UPPER(i.UNIT) IN ('KG','KGS')"

    with get_connection() as conn:
        with conn.cursor() as cur:
            # Stock on hand + counts (from the Item Balance table)
            try:
                cur.execute(f"""SELECT NVL(SUM(CASE WHEN {KG} THEN b.BALANCE END),0),
                                       NVL(SUM(CASE WHEN b.BALANCE > 0 THEN 1 END),0),
                                       NVL(SUM(CASE WHEN b.BALANCE < 0 THEN 1 END),0)
                                FROM wst_djn_item_balance b
                                JOIN wst_djn_items i ON i.ITEM_ID = b.ITEM_ID
                                WHERE 1=1 {div_b}""", dp)
                r = cur.fetchone()
                d['stock_kg'], d['items_in_stock'], d['items_negative'] = float(r[0]), int(r[1]), int(r[2])
            except oracledb.DatabaseError:
                pass

            # 6-month receiving vs dispatch trend (kg) from the ledger
            try:
                first = month_start
                for _ in range(5):
                    first = (first.replace(day=1) - _td(days=1)).replace(day=1)
                cur.execute(f"""SELECT TO_CHAR(TRUNC(l.TXN_DATE,'MM'),'YYYY-MM') AS M,
                                       NVL(SUM(CASE WHEN l.TXN_TYPE='RECEIVE' THEN l.QTY_IN END),0),
                                       NVL(SUM(CASE WHEN l.TXN_TYPE LIKE 'GATEPASS%' THEN l.QTY_OUT END),0)
                                FROM wst_djn_stock_ledger l
                                JOIN wst_djn_items i ON i.ITEM_ID = l.ITEM_ID
                                WHERE {KG} AND l.TXN_DATE >= TO_DATE(:f,'YYYY-MM-DD') {div_l}
                                GROUP BY TRUNC(l.TXN_DATE,'MM')""", {**dp, 'f': first.strftime('%Y-%m-%d')})
                got = {m: (float(a), float(b)) for m, a, b in cur.fetchall()}
                months, cursor_m = [], first
                for _ in range(6):
                    k = cursor_m.strftime('%Y-%m')
                    rec, out = got.get(k, (0.0, 0.0))
                    months.append({'label': cursor_m.strftime('%b'), 'received': rec, 'dispatched': out})
                    cursor_m = (cursor_m.replace(day=28) + _td(days=4)).replace(day=1)
                peak = max([m['received'] for m in months] + [m['dispatched'] for m in months] + [1])
                for m in months:
                    m['rec_pct'] = round(m['received'] * 100 / peak, 1)
                    m['out_pct'] = round(m['dispatched'] * 100 / peak, 1)
                d['trend'] = months
                d['month_received_kg'] = months[-1]['received']
                d['month_dispatched_kg'] = months[-1]['dispatched']
            except oracledb.DatabaseError:
                pass

            # Top items by current balance
            try:
                cur.execute(f"""SELECT * FROM (
                                  SELECT i.ITEM_NAME, i.UNIT, b.BALANCE
                                  FROM wst_djn_item_balance b
                                  JOIN wst_djn_items i ON i.ITEM_ID = b.ITEM_ID
                                  WHERE b.BALANCE > 0 {div_b}
                                  ORDER BY b.BALANCE DESC) WHERE ROWNUM <= 6""", dp)
                rows = cur.fetchall()
                top = max([float(r[2]) for r in rows] + [1])
                d['top_items'] = [{'name': r[0], 'unit': (r[1] or '').lower(), 'balance': float(r[2]),
                                   'pct': round(float(r[2]) * 100 / top, 1)} for r in rows]
            except oracledb.DatabaseError:
                pass

            # Recent movements
            try:
                cur.execute(f"""SELECT * FROM (
                                  SELECT i.ITEM_NAME, i.UNIT, l.TXN_TYPE, l.QTY_IN, l.QTY_OUT,
                                         TO_CHAR(l.TXN_DATE,'DD-Mon-YYYY')
                                  FROM wst_djn_stock_ledger l
                                  JOIN wst_djn_items i ON i.ITEM_ID = l.ITEM_ID
                                  WHERE 1=1 {div_l}
                                  ORDER BY l.TXN_DATE DESC, l.LEDGER_ID DESC) WHERE ROWNUM <= 8""", dp)
                for name, unit, ttype, qin, qout, tdate in cur.fetchall():
                    qin, qout = float(qin or 0), float(qout or 0)
                    ttype = ttype or ''
                    label = {'RECEIVE': 'Received', 'ADJUST': 'Adjust In' if qin > 0 else 'Adjust Out'}.get(
                        ttype, 'Dispatched' if ttype.startswith('GATEPASS') else ttype.title())
                    d['recent'].append({'item': name, 'unit': (unit or '').lower(), 'label': label,
                                        'is_in': qin > 0, 'qty': qin if qin > 0 else qout, 'date': tdate})
            except oracledb.DatabaseError:
                pass

    _wh_cache.set(key, d, 60)
    return d


# ═══════════════════════════════════════════════════════════════════════
# STOCK LEDGER AUTO-POSTING ENGINE & ITEM BALANCE
# ═══════════════════════════════════════════════════════════════════════

def _generate_voucher_ref(prefix, source_id, txn_date):
    """Generate a traceable voucher reference: RCV-2025-06-031 or SLE-2025-06-018."""
    from datetime import datetime
    if isinstance(txn_date, str):
        for fmt in ('%Y-%m-%d', '%d-%b-%Y', '%d-%m-%Y'):
            try: txn_date = datetime.strptime(txn_date, fmt); break
            except ValueError: pass
    yr = txn_date.year if hasattr(txn_date, 'year') else 2025
    mo = txn_date.month if hasattr(txn_date, 'month') else 1
    return f"{prefix}-{yr}-{mo:02d}-{source_id:03d}" if source_id else f"{prefix}-{yr}-{mo:02d}-000"


def _recalc_item_balance(cur, item_id, division, txn_date, transaction_type, qty_in, qty_out):
    """Division-safe balance recalculation, operating on an ALREADY-OPEN cursor
    (no connection/commit of its own) so callers can compose this into a
    larger atomic transaction. Used by both post_ledger_entry() (its own
    connection, Receiving/legacy path) and the Sales Header/Line atomic
    post/cancel functions (shared connection across every line in a document).

    FIX (previously a real bug): both the ledger running-balance recalc and
    the item_balance aggregate were NOT filtered by division -- an item that
    exists in more than one division had its balance silently polluted by
    every OTHER division's transactions too. Both queries below are now
    scoped to (ITEM_ID, DIVISION), matching the already-correct pattern used
    in recalculate_all_balances().

    FIX (previously a real bug): txn_date arrives as a plain 'YYYY-MM-DD'
    string from most callers, but post_sales_document() passes back a value
    it just re-fetched from the database (DOC_DATE), which oracledb returns
    as a Python datetime object, not a string. str() on that object produces
    "2026-08-11 00:00:00" -- the extra time portion doesn't match the
    TO_DATE(...,'YYYY-MM-DD') format mask below, which raised ORA-01861 on
    every Sale post. That exception was being silently swallowed by the
    except clause that follows (written for the different, narrower case of
    wst_djn_item_balance not existing yet), so Sales transactions posted to
    the Stock Ledger correctly but never updated the Item Balance summary at
    all -- until some LATER transaction for the same item (a shipment
    reversal, whose own txn_date happened to already be a plain string)
    triggered a fresh, full recompute that picked up the earlier missed
    Sale and the reversal together at once, looking like the balance had
    "caught up" retroactively. Normalizing explicitly here fixes it for
    every caller, present and future, rather than requiring each call site
    to remember to pre-format its date correctly.
    """
    div = str(division or '08')
    txn_date_str = txn_date.strftime('%Y-%m-%d') if hasattr(txn_date, 'strftime') else str(txn_date)

    cur.execute("""SELECT LEDGER_ID, QTY_IN, QTY_OUT
                   FROM wst_djn_stock_ledger
                   WHERE ITEM_ID = :1 AND NVL(DIVISION,'08') = :2
                   ORDER BY TXN_DATE, LEDGER_ID""",
                [int(item_id), div])
    running = 0
    updates = []
    for row in cur.fetchall():
        running += (row[1] or 0) - (row[2] or 0)
        updates.append((running, row[0]))
    if updates:
        cur.executemany(
            "UPDATE wst_djn_stock_ledger SET BALANCE = :1 WHERE LEDGER_ID = :2",
            updates)

    cur.execute("""SELECT NVL(SUM(QTY_IN),0), NVL(SUM(QTY_OUT),0)
                   FROM wst_djn_stock_ledger
                   WHERE ITEM_ID = :1 AND NVL(DIVISION,'08') = :2""",
                [int(item_id), div])
    agg = cur.fetchone()
    tot_in  = agg[0] if agg else 0
    tot_out = agg[1] if agg else 0
    live_bal = tot_in - tot_out

    try:
        # FIX (previously a real, silent production bug -- ORA-01400
        # "cannot insert NULL into BALANCE_ID"): wst_djn_item_balance's
        # BALANCE_ID has no sequence, trigger, or default of any kind
        # behind it (confirmed directly against the schema) -- it has to
        # be supplied explicitly on every insert. The WHEN NOT MATCHED
        # branch below never did, so any item+division's very FIRST
        # balance row (a brand-new item's first-ever receiving) failed
        # here every time -- silently, since this whole block is wrapped
        # in the except clause further down, which only logs a warning.
        # The ledger itself still saved correctly (that's a separate,
        # already-committed step), so nothing looked wrong until stock
        # for that item mysteriously failed to show up anywhere that
        # reads from wst_djn_item_balance -- the Balance Sheet screen,
        # and the stock-availability check gate passes rely on before
        # allowing a dispatch. A plain MAX(BALANCE_ID)+1 subquery is
        # used rather than inventing a new sequence, matching the same
        # pattern already accepted elsewhere in this file for this
        # exact class of ID (generate_doc_id() and friends).
        cur.execute("""MERGE INTO wst_djn_item_balance b
            USING (SELECT :1 AS ITEM_ID, :2 AS DIVISION FROM DUAL) s
            ON (b.ITEM_ID = s.ITEM_ID AND b.DIVISION = s.DIVISION)
            WHEN MATCHED THEN UPDATE SET
                b.TOTAL_IN = :3, b.TOTAL_OUT = :4, b.BALANCE = :5,
                b.LAST_TXN_DATE = TO_DATE(:6,'YYYY-MM-DD'),
                b.LAST_TXN_TYPE = :7, b.LAST_TXN_QTY = :8
            WHEN NOT MATCHED THEN INSERT
                (BALANCE_ID, ITEM_ID, DIVISION, TOTAL_IN, TOTAL_OUT, BALANCE,
                 LAST_TXN_DATE, LAST_TXN_TYPE, LAST_TXN_QTY)
                VALUES ((SELECT NVL(MAX(BALANCE_ID),0)+1 FROM wst_djn_item_balance),
                        :9, :10, :11, :12, :13,
                        TO_DATE(:14,'YYYY-MM-DD'), :15, :16)""",
            [int(item_id), div,
             tot_in, tot_out, live_bal,
             txn_date_str, transaction_type,
             float(qty_in or qty_out or 0),
             int(item_id), div,
             tot_in, tot_out, live_bal,
             txn_date_str, transaction_type,
             float(qty_in or qty_out or 0)])
    except oracledb.DatabaseError as e:
        # Genuinely missing wst_djn_item_balance table degrades safely either
        # way (the ledger row itself is already saved) -- but ANY OTHER
        # failure here (a bad date format, a constraint violation, etc.)
        # deserves to be visible rather than silently vanishing, which is
        # exactly what let the datetime-vs-string bug above go undetected.
        import logging
        logging.getLogger('wastage').warning(
            f'_recalc_item_balance: item_balance MERGE failed for item {item_id}, '
            f'division {div}, transaction_type={transaction_type}: {e}')


def post_ledger_entry(item_id, txn_date, transaction_type, qty_in, qty_out,
                      source_table, source_id, division, username=None):
    """Auto-post a ledger row using the existing insert_ledger function,
    then recalculate the running balance for this item+division.
    Used by Receiving. Sales now posts via post_sales_document() instead,
    which shares _recalc_item_balance() but keeps every line of a document
    on ONE connection for true atomicity."""

    insert_ledger(
        item_id=item_id,
        txn_date=txn_date,
        txn_type=transaction_type,
        qty_in=float(qty_in or 0),
        qty_out=float(qty_out or 0),
        balance=0,  # will be recalculated below
        ref_id=source_id,
        division=division,
        username=username,
        source_table=source_table,
        source_id=source_id,
    )

    with get_connection(username) as conn:
        with conn.cursor() as cur:
            _recalc_item_balance(cur, item_id, division, txn_date, transaction_type, qty_in, qty_out)
            conn.commit()


def recalculate_all_balances(item_id=None, division=None, username=None):
    """Full recalculation of running balances + item_balance for one or all items.
    Called on delete/update of ledger rows or as a maintenance task.

    FIX (previously a real bug, caught by testing update_receiving()'s
    item-change path): when both item_id AND division are given as a
    single specific target, the combo list used to be derived by
    querying DISTINCT straight off the ledger -- so a combo that had
    every one of its ledger rows just moved away (e.g. a Stock Receiving
    edit that changes which item a receipt belongs to) had ZERO
    matching rows and was silently skipped entirely, leaving a stale
    item_balance row behind showing its old, no-longer-true balance
    instead of resetting to zero. When a specific single target is
    given, it's now used directly as the one combo to process,
    regardless of whether it currently has any ledger rows at all."""
    with get_connection(username) as conn:
        with conn.cursor() as cur:
            if item_id and division:
                combos = [(int(item_id), str(division))]
            else:
                where = []
                params = []
                if item_id:
                    where.append("ITEM_ID = :1"); params.append(int(item_id))
                if division:
                    where.append("NVL(DIVISION,'08') = :2"); params.append(str(division))
                w = (" WHERE " + " AND ".join(where)) if where else ""

                # Get distinct item+division combos to recalc
                cur.execute(f"SELECT DISTINCT ITEM_ID, NVL(DIVISION,'08') FROM wst_djn_stock_ledger{w}", params)
                combos = cur.fetchall()

            for itm, div in combos:
                cur.execute("""SELECT LEDGER_ID, QTY_IN, QTY_OUT
                               FROM wst_djn_stock_ledger
                               WHERE ITEM_ID = :1 AND NVL(DIVISION,'08') = :2
                               ORDER BY TXN_DATE, LEDGER_ID""", [itm, div])
                running = 0
                updates = []
                for row in cur.fetchall():
                    running += (row[1] or 0) - (row[2] or 0)
                    updates.append((running, row[0]))
                if updates:
                    cur.executemany("UPDATE wst_djn_stock_ledger SET BALANCE = :1 WHERE LEDGER_ID = :2", updates)

                cur.execute("""SELECT NVL(SUM(QTY_IN),0), NVL(SUM(QTY_OUT),0)
                               FROM wst_djn_stock_ledger
                               WHERE ITEM_ID = :1 AND NVL(DIVISION,'08') = :2""", [itm, div])
                tot_in, tot_out = cur.fetchone()
                live_bal = tot_in - tot_out

                # FIX: was unguarded SELECT ... TRANSACTION_TYPE with no
                # fallback, unlike almost every other reference to this
                # column elsewhere in the file -- ORA-00904 here aborted
                # the WHOLE balance recalc before it ever reached the
                # MERGE below, leaving wst_djn_item_balance stale even
                # though the ledger row itself was already correct.
                # TXN_TYPE is used instead: it's the one column every
                # ledger-insert path in this file has always written,
                # old and new, so it can't have the same gap -- wrapped
                # in try/except regardless, as defense in depth.
                try:
                    cur.execute("""SELECT TXN_DATE, TXN_TYPE, QTY_IN, QTY_OUT
                                   FROM wst_djn_stock_ledger
                                   WHERE ITEM_ID=:1 AND NVL(DIVISION,'08')=:2
                                   ORDER BY TXN_DATE DESC, LEDGER_ID DESC
                                   FETCH FIRST 1 ROW ONLY""", [itm, div])
                    last = cur.fetchone()
                except oracledb.DatabaseError as e:
                    import logging
                    logging.getLogger('wastage').warning(
                        f'recalculate_all_balances: last-transaction lookup failed for '
                        f'item {itm}, division {div}: {e}')
                    last = None

                # FIX (previously a real, silent production bug -- see
                # the identical fix and full explanation in
                # _recalc_item_balance() above, which has the same
                # MERGE against the same table): BALANCE_ID has no
                # sequence/trigger/default at all, confirmed directly
                # against the schema, so the INSERT branch must supply
                # it explicitly -- it never did, so this function's own
                # WHEN NOT MATCHED branch failed with ORA-01400 for
                # exactly the same reason, for any item+division that
                # didn't already have a balance row.
                cur.execute("""MERGE INTO wst_djn_item_balance b
                    USING (SELECT :1 AS ITEM_ID, :2 AS DIVISION FROM DUAL) s
                    ON (b.ITEM_ID = s.ITEM_ID AND b.DIVISION = s.DIVISION)
                    WHEN MATCHED THEN UPDATE SET
                        b.TOTAL_IN=:3, b.TOTAL_OUT=:4, b.BALANCE=:5,
                        b.LAST_TXN_DATE=:6, b.LAST_TXN_TYPE=:7,
                        b.LAST_TXN_QTY=:8
                    WHEN NOT MATCHED THEN INSERT
                        (BALANCE_ID, ITEM_ID,DIVISION,TOTAL_IN,TOTAL_OUT,BALANCE,
                         LAST_TXN_DATE,LAST_TXN_TYPE,LAST_TXN_QTY)
                        VALUES((SELECT NVL(MAX(BALANCE_ID),0)+1 FROM wst_djn_item_balance),
                               :9,:10,:11,:12,:13,:14,:15,:16)""",
                    [itm, div, tot_in, tot_out, live_bal,
                     last[0] if last else None, last[1] if last else None,
                     float(last[2] or last[3] or 0) if last else 0,
                     itm, div, tot_in, tot_out, live_bal,
                     last[0] if last else None, last[1] if last else None,
                     float(last[2] or last[3] or 0) if last else 0])
            conn.commit()


# ── Ledger View (read-only, month-wise, division-filtered) ──

def fetch_ledger_view(division, month=None, year=None, item_id=None, txn_type=None):
    """Fetch ledger rows for the Stock Ledger screen.
    Defaults to current month. Returns rows with running balance.
    division=None means no division filter — only pass None for users with
    sees_all_divisions=True; everyone else must pass their own division."""
    from datetime import datetime
    now = datetime.now()
    m = int(month) if month else now.month
    y = int(year) if year else now.year

    sql = """SELECT l.LEDGER_ID, TO_CHAR(l.TXN_DATE,'DD Mon') AS TXN_DATE_DISP,
                    l.SOURCE_REF, l.TRANSACTION_TYPE, i.ITEM_NAME, i.UNIT AS ITEM_UNIT,
                    l.QTY_IN, l.QTY_OUT, l.BALANCE, l.POSTED_BY,
                    l.SOURCE_TABLE, l.SOURCE_ID, NVL(l.DIVISION,'08') AS DIVISION
             FROM wst_djn_stock_ledger l
             LEFT JOIN wst_djn_items i ON l.ITEM_ID = i.ITEM_ID
             WHERE EXTRACT(MONTH FROM l.TXN_DATE) = :p_m
               AND EXTRACT(YEAR FROM l.TXN_DATE) = :p_y"""
    params = {'p_m': m, 'p_y': y}
    if division:
        sql += " AND NVL(l.DIVISION,'08') = :p_div"
        params['p_div'] = str(division)
    if item_id:
        sql += " AND l.ITEM_ID = :p_item"
        params['p_item'] = int(item_id)
    if txn_type and txn_type != 'ALL':
        sql += " AND l.TRANSACTION_TYPE = :p_type"
        params['p_type'] = txn_type
    sql += " ORDER BY l.TXN_DATE DESC, l.LEDGER_ID DESC"

    with get_connection() as conn:
        with conn.cursor() as cur:
            try:
                cur.execute(sql, params)
                cols = [c[0] for c in cur.description]
                rows = [dict(zip(cols, row)) for row in cur.fetchall()]
                # Adjust In/Adjust Out display rewrite: the stored value is
                # (and stays) plain 'ADJUST' -- direction is derived here
                # from which quantity column is populated, purely for
                # display. Filtering on TRANSACTION_TYPE='ADJUST' above is
                # unaffected since it matches the raw stored value, not
                # this display-only relabel.
                for r in rows:
                    if r.get('TRANSACTION_TYPE') == 'ADJUST':
                        r['TRANSACTION_TYPE'] = 'Adjust In' if (r.get('QTY_IN') or 0) > 0 else 'Adjust Out'
                return rows
            except oracledb.DatabaseError:
                # Graceful fallback if new columns don't exist yet
                return []


def fetch_ledger_report(division, month, year, item_id=None, txn_type=None):
    """Rows for the Stock Ledger PDF report (one month, optional division /
    item / type filters), oldest first so the running balance reads top-down.

    Why this exists instead of reusing fetch_ledger_view(): that query also
    selects l.SOURCE_ID, a column no ledger INSERT in this file ever writes,
    and it turns ANY Oracle error into an empty list -- so a missing column
    shows up as 'no records' with no clue why. This query only touches
    columns the ledger writers actually populate, falls back to the core
    columns on schemas without the richer metadata, and -- unlike the
    screen query -- lets a genuine database error surface instead of
    printing an empty report.
    division=None means no division filter (sees_all_divisions users only)."""
    m, y = int(month), int(year)
    where = """ WHERE EXTRACT(MONTH FROM l.TXN_DATE) = :p_m
                  AND EXTRACT(YEAR FROM l.TXN_DATE) = :p_y"""
    params = {'p_m': m, 'p_y': y}
    if division:
        where += " AND NVL(l.DIVISION,'08') = :p_div"
        params['p_div'] = str(division)
    if item_id:
        where += " AND l.ITEM_ID = :p_item"
        params['p_item'] = int(item_id)
    order = " ORDER BY l.TXN_DATE ASC, l.LEDGER_ID ASC"

    rich_sql = """SELECT l.LEDGER_ID, TO_CHAR(l.TXN_DATE,'DD-Mon-YYYY') AS TXN_DATE_DISP,
                    l.SOURCE_REF, NVL(l.TRANSACTION_TYPE, l.TXN_TYPE) AS TRANSACTION_TYPE,
                    i.ITEM_NAME, l.QTY_IN, l.QTY_OUT, l.BALANCE, l.POSTED_BY,
                    NVL(l.DIVISION,'08') AS DIVISION
                  FROM wst_djn_stock_ledger l
                  LEFT JOIN wst_djn_items i ON l.ITEM_ID = i.ITEM_ID""" + where
    core_sql = """SELECT l.LEDGER_ID, TO_CHAR(l.TXN_DATE,'DD-Mon-YYYY') AS TXN_DATE_DISP,
                    TO_CHAR(l.REF_ID) AS SOURCE_REF, l.TXN_TYPE AS TRANSACTION_TYPE,
                    i.ITEM_NAME, l.QTY_IN, l.QTY_OUT, l.BALANCE, NULL AS POSTED_BY,
                    NVL(l.DIVISION,'08') AS DIVISION
                  FROM wst_djn_stock_ledger l
                  LEFT JOIN wst_djn_items i ON l.ITEM_ID = i.ITEM_ID""" + where
    if txn_type and txn_type != 'ALL':
        rich_sql += " AND NVL(l.TRANSACTION_TYPE, l.TXN_TYPE) = :p_type"
        core_sql += " AND l.TXN_TYPE = :p_type"
        params['p_type'] = txn_type

    with get_connection() as conn:
        with conn.cursor() as cur:
            try:
                cur.execute(rich_sql + order, params)
            except oracledb.DatabaseError:
                # Richer metadata columns not on this schema -- core columns only.
                cur.execute(core_sql + order, params)
            cols = [c[0] for c in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]


def fetch_ledger_items(division):
    """Distinct items that have ledger entries for the filter dropdown.
    division=None means no division filter (sees_all_divisions users)."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            try:
                if division:
                    cur.execute("""SELECT DISTINCT i.ITEM_ID, i.ITEM_NAME
                        FROM wst_djn_stock_ledger l
                        JOIN wst_djn_items i ON l.ITEM_ID = i.ITEM_ID
                        WHERE NVL(l.DIVISION,'08') = :1
                        ORDER BY i.ITEM_NAME""", [str(division)])
                else:
                    cur.execute("""SELECT DISTINCT i.ITEM_ID, i.ITEM_NAME
                        FROM wst_djn_stock_ledger l
                        JOIN wst_djn_items i ON l.ITEM_ID = i.ITEM_ID
                        ORDER BY i.ITEM_NAME""")
                cols = [c[0] for c in cur.description]
                return [dict(zip(cols, row)) for row in cur.fetchall()]
            except oracledb.DatabaseError:
                return []


# ── Item Balance Sheet (live position, division-filtered) ──

def fetch_item_available_balance(item_id, division):
    """Returns the current available BALANCE for one item in one division,
    or 0 if no balance row exists yet (the item has never been received
    into this division, so nothing is available to sell). Used by the Sales
    flow to validate quantity BEFORE adding a line and again BEFORE posting,
    so stock can never go negative."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            try:
                cur.execute("SELECT BALANCE FROM wst_djn_item_balance WHERE ITEM_ID=:1 AND DIVISION=:2",
                            [int(item_id), str(division)])
                row = cur.fetchone()
                return float(row[0]) if row and row[0] is not None else 0.0
            except oracledb.DatabaseError:
                return 0.0  # wst_djn_item_balance not created yet -- nothing available


def fetch_item_balance_sheet(division):
    """Live stock position per item for the Balance Sheet screen.
    division=None means no division filter (sees_all_divisions users)."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            try:
                base_sql = """SELECT b.BALANCE_ID, i.ITEM_ID,
                        LPAD(i.ITEM_ID, 3, '0') AS ITEM_CODE,
                        i.ITEM_NAME, i.UNIT,
                        b.TOTAL_IN, b.TOTAL_OUT, b.BALANCE,
                        b.MIN_THRESHOLD, b.DIVISION,
                        TO_CHAR(b.LAST_TXN_DATE,'DD Mon') AS LAST_TXN_DATE_DISP,
                        b.LAST_TXN_TYPE, b.LAST_TXN_QTY
                    FROM wst_djn_item_balance b
                    JOIN wst_djn_items i ON b.ITEM_ID = i.ITEM_ID"""
                if division:
                    cur.execute(base_sql + " WHERE b.DIVISION = :1 ORDER BY i.ITEM_NAME", [str(division)])
                else:
                    cur.execute(base_sql + " ORDER BY i.ITEM_NAME")
                cols = [c[0] for c in cur.description]
                rows = [dict(zip(cols, row)) for row in cur.fetchall()]

                # Direction of each item's LAST movement, read from the latest
                # ledger row itself (Qty In > 0 => IN, otherwise OUT). The old
                # label logic treated ONLY 'RECEIVE' as IN, so an Adjust In,
                # Gate Pass Reversal, etc. wrongly showed as "OUT".
                last_dir = {}
                try:
                    cur.execute("""SELECT ITEM_ID, DIV, QTY_IN FROM (
                                     SELECT ITEM_ID, NVL(DIVISION,'08') AS DIV, QTY_IN,
                                            ROW_NUMBER() OVER (PARTITION BY ITEM_ID, NVL(DIVISION,'08')
                                                               ORDER BY TXN_DATE DESC, LEDGER_ID DESC) AS RN
                                     FROM wst_djn_stock_ledger) WHERE RN = 1""")
                    for itm, dv, qin in cur.fetchall():
                        last_dir[(itm, str(dv))] = 'IN' if (qin or 0) > 0 else 'OUT'
                except oracledb.DatabaseError:
                    last_dir = {}   # fall back to the type-based guess below
                _IN_TYPES = {'RECEIVE', 'IN', 'GATEPASS_REVERSAL', 'SALE_REVERSAL', 'SHIPMENT_REVERSAL'}

                # compute status
                for r in rows:
                    bal = r.get('BALANCE') or 0
                    thresh = r.get('MIN_THRESHOLD') or 0
                    if bal <= 0:
                        r['STATUS'] = 'Zero'
                    elif thresh > 0 and bal <= thresh:
                        r['STATUS'] = 'Low'
                    else:
                        r['STATUS'] = 'OK'
                    # last movement display
                    if r.get('LAST_TXN_DATE_DISP') and r.get('LAST_TXN_TYPE'):
                        tag = last_dir.get((r.get('ITEM_ID'), str(r.get('DIVISION'))))
                        if tag is None:
                            tag = 'IN' if r['LAST_TXN_TYPE'] in _IN_TYPES else 'OUT'
                        r['LAST_MOVEMENT'] = f"{r['LAST_TXN_DATE_DISP']} — {tag} {int(r.get('LAST_TXN_QTY') or 0)}"
                    else:
                        r['LAST_MOVEMENT'] = '—'
                return rows
            except oracledb.DatabaseError:
                return []


def fetch_balance_csv_data(division):
    """Same as balance sheet but as flat rows for CSV/Excel export."""
    return fetch_item_balance_sheet(division)


# ─── HISTORICAL STOCK BALANCE REPORT ──────────────────────
# Given a "Transaction Date" (as-of date), computes each item's cumulative
# stock balance from the ledger as it stood at the end of that day:
#   Closing Balance = SUM(QTY_IN) - SUM(QTY_OUT)
#   for every ledger row with TXN_DATE <= as_of_date
# This is always computed live from the ledger, never cached/stored -- so
# the report is guaranteed accurate to the current ledger state at the
# moment it's generated, not a stale snapshot from some earlier run.

def generate_stock_balance_doc_no(cur, year=None):
    """Generates the next RPT-YYYY-NNNN for the given year (current year by
    default), using the SAME cursor as the log-row insert that follows it.
    Same collision-safety note as generate_doc_id(): a UNIQUE constraint on
    doc_no makes a same-instant collision a safe failure (retry), not a
    silent duplicate."""
    yr = year or date.today().year
    prefix = f'RPT-{yr}-'
    cur.execute("SELECT MAX(DOC_NO) FROM wst_djn_stock_bal_report_log WHERE DOC_NO LIKE :1", [prefix + '%'])
    row = cur.fetchone()
    last = row[0] if row else None
    last_n = int(last.split('-')[-1]) if last else 0
    return f'{prefix}{last_n + 1:04d}'


def log_stock_balance_report(as_of_date, division, username=None):
    """Logs one report-generation instance as audit metadata (who, when,
    what as-of date/division, under what doc number) and returns that
    metadata for display on the report header. Does NOT store the actual
    balance figures -- those are always (re)computed live, see
    fetch_historical_stock_balance().

    FIX (previously a real bug, same root cause as the earlier
    wst_djn_item_balance.BALANCE_ID incident): REPORT_ID has no
    sequence, trigger, or default of any kind (confirmed directly
    against the schema) -- it must be supplied explicitly on every
    insert, which this never did, so EVERY report generation failed
    with ORA-01400 until now. Same MAX(REPORT_ID)+1 pattern already
    used elsewhere in this file for this class of ID."""
    with get_connection(username) as conn:
        with conn.cursor() as cur:
            doc_no = generate_stock_balance_doc_no(cur)
            cur.execute("""INSERT INTO wst_djn_stock_bal_report_log
                (REPORT_ID, DOC_NO, DIVISION, AS_OF_DATE, CREATED_BY, CREATED_DATE)
                VALUES ((SELECT NVL(MAX(REPORT_ID),0)+1 FROM wst_djn_stock_bal_report_log),
                        :1, :2, TO_DATE(:3,'YYYY-MM-DD'), :4, SYSDATE)""",
                [doc_no, str(division) if division else None, str(as_of_date), username])
            conn.commit()
            cur.execute("""SELECT TO_CHAR(CREATED_DATE,'DD-Mon-YYYY HH24:MI:SS') FROM wst_djn_stock_bal_report_log
                WHERE DOC_NO=:1""", [doc_no])
            created_date_disp = cur.fetchone()[0]
            return {'DOC_NO': doc_no, 'CREATED_DATE': created_date_disp}


def fetch_historical_stock_balance(as_of_date, division=None):
    """Core report query: closing balance per item, from the ledger, as of
    (and including) the given date. Items with no ledger activity on or
    before as_of_date are naturally excluded (a plain GROUP BY aggregate
    only returns items that actually have matching rows) -- they simply
    didn't exist as inventory yet at that point in time."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            base_sql = """SELECT i.ITEM_ID, i.ITEM_CODE,
                    i.ITEM_NAME, i.UNIT,
                    NVL(SUM(l.QTY_IN),0) - NVL(SUM(l.QTY_OUT),0) AS BALANCE
                FROM wst_djn_stock_ledger l
                JOIN wst_djn_items i ON l.ITEM_ID = i.ITEM_ID
                WHERE l.TXN_DATE <= TO_DATE(:1,'YYYY-MM-DD')"""
            params = [str(as_of_date)]
            if division:
                base_sql += " AND NVL(l.DIVISION,'08') = :2"
                params.append(str(division))
            base_sql += " GROUP BY i.ITEM_ID, i.ITEM_CODE, i.ITEM_NAME, i.UNIT ORDER BY i.ITEM_NAME"
            cur.execute(base_sql, params)
            cols = [c[0] for c in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]


# ─── MONTHLY STOCK REPORT (Reports section) ────────────
# Mirrors the Historical Stock Balance Report's philosophy exactly:
# nothing is stored except the log-row audit trail (who/when/doc_no) --
# every figure is (re)computed live, every time, from the ledger,
# receiving, and gate pass data that already exists. Column set and
# section totals match the paper form this replaces: Opening, one
# column per Department ("received from"), Adjust, Sale Out, Closing.

def generate_monthly_stock_report_doc_no(cur, year=None):
    """Generates the next MSR-YYYY-NNNN for the given year (current year
    by default). Same pattern as generate_stock_balance_doc_no(), a
    different prefix (MSR, not RPT) so the two reports' document
    numbers can never collide or be confused with each other."""
    yr = year or date.today().year
    prefix = f'MSR-{yr}-'
    cur.execute("SELECT MAX(DOC_NO) FROM wst_djn_monthly_stock_report_log WHERE DOC_NO LIKE :1", [prefix + '%'])
    row = cur.fetchone()
    last = row[0] if row else None
    last_n = int(last.split('-')[-1]) if last else 0
    return f'{prefix}{last_n + 1:04d}'


def log_monthly_stock_report(division, target_month, username=None):
    """Logs one report-generation instance (who, when, division, target
    month, doc number) for display on the report header -- does NOT
    store the actual figures, see fetch_monthly_stock_report().

    target_month is normalized to a full 'YYYY-MM-DD' before it ever
    reaches TO_DATE(): the on-screen picker is an HTML <input
    type="month">, which submits bare 'YYYY-MM' (no day) -- passed
    straight through, that's ORA-01840 (input value not long enough
    for date format), since 'YYYY-MM-DD' expects a full 10-character
    string. The day itself is never used for anything (only the
    month matters, for display), so '-01' is a safe, arbitrary pick."""
    target_month = str(target_month)
    if len(target_month) < 10:
        target_month = target_month[:7] + '-01'
    with get_connection(username) as conn:
        with conn.cursor() as cur:
            doc_no = generate_monthly_stock_report_doc_no(cur)
            cur.execute("""INSERT INTO wst_djn_monthly_stock_report_log
                (DOC_NO, DIVISION, TARGET_MONTH, CREATED_BY, CREATED_DATE)
                VALUES (:1, :2, TO_DATE(:3,'YYYY-MM-DD'), :4, SYSDATE)""",
                [doc_no, str(division) if division else None, str(target_month), username])
            conn.commit()
            cur.execute("""SELECT TO_CHAR(CREATED_DATE,'DD-Mon-YYYY HH24:MI:SS') FROM wst_djn_monthly_stock_report_log
                WHERE DOC_NO=:1""", [doc_no])
            created_date_disp = cur.fetchone()[0]
            return {'DOC_NO': doc_no, 'CREATED_DATE': created_date_disp}


import re


def _abbreviate_dept_name(name, max_len=8):
    """Deterministic short form for a department name, used as the
    column header on the Monthly Stock Report -- with a real department
    count in the high teens, full names ('Research & Development
    (R&D;)') made every column far too wide, running the whole table
    well past a landscape page's actual width. An already-short name
    passes through untouched. A longer one checks for a parenthetical
    short form first -- often already a ready-made abbreviation, like
    the '(R&D)' in "Research & Development (R&D)" -- and falls back to
    a straight prefix truncation otherwise, which is simpler and more
    predictable than trying to build "smart" acronyms that risk
    colliding between two different departments."""
    name = (name or '').strip()
    if len(name) <= max_len:
        return name
    paren_match = re.search(r'\(([^)]+)\)', name)
    if paren_match:
        short = paren_match.group(1).strip().rstrip(';,. ')
        if 0 < len(short) <= max_len:
            return short
    base = re.sub(r'\s*\([^)]*\)', '', name).strip()
    return base[:max_len].rstrip()


def fetch_monthly_stock_report(division, target_month):
    """target_month: 'YYYY-MM-DD' (any day within the target month --
    only the year/month are used). Returns (rows, department_columns):

    department_columns -- only the Departments that have Stock Receiving
    entries in the selected month, in DEPT_ID order, each as {'DEPT_ID',
    'DEPT_NAME', 'DEPT_SHORT_NAME'}. DEPT_SHORT_NAME is the department's
    Short Description when filled in, otherwise the auto abbreviation.

    rows -- one dict per item that had ANY activity up to and including
    this month (opening balance, something received, an adjustment, or
    a sale) -- an item with zero activity anywhere simply isn't
    meaningful on this report, same "naturally excluded" philosophy as
    fetch_historical_stock_balance(). Each row:
      ITEM_ID, ITEM_CODE, ITEM_NAME, UOM
      OPENING       -- ledger balance strictly BEFORE this month started
      RECEIVED      -- {DEPT_ID: qty, ...} -- only depts with a nonzero
                       sum appear; look up with .get(dept_id, 0) when
                       rendering so every column always has a value
      ADJUST        -- net ADJUST-type ledger movement this month
                       (QTY_IN - QTY_OUT for TXN_TYPE='ADJUST' rows --
                       positive means net Adjust In, negative net Adjust
                       Out, matching the ledger screen's own display
                       convention)
      SALE_OUT      -- total Gate Pass dispatch this month (POSTED gate
                       passes only -- a Draft has never moved stock, a
                       Cancelled one's had it reversed)
      CLOSING       -- ledger balance as of month end (Opening + all
                       ledger movement this month, computed independently
                       from the ledger rather than derived by addition,
                       so it's correct even if some other transaction
                       type this report doesn't otherwise surface moved
                       the item too)
    """
    from datetime import date as _date
    import calendar as _calendar

    target_month = str(target_month)
    year, month = int(target_month[:4]), int(target_month[5:7])
    month_start = f'{year:04d}-{month:02d}-01'
    last_day = _calendar.monthrange(year, month)[1]
    month_end = f'{year:04d}-{month:02d}-{last_day:02d}'

    departments = fetch_all_departments()
    dept_columns = [
        {'DEPT_ID': d['DEPT_ID'], 'DEPT_NAME': d['DEPT_NAME'], 'DEPT_SHORT_NAME': ((d.get('SHORT_DESCRIPTION') or '').strip().strip('-—').strip() or _abbreviate_dept_name(d['DEPT_NAME'])).upper()}
        for d in departments
    ]

    with get_connection() as conn:
        with conn.cursor() as cur:
            div_clause = " AND NVL(DIVISION,'08') = :div" if division else ""
            div_params = {'div': str(division)} if division else {}

            # Opening -- ledger balance strictly before month start
            cur.execute(f"""SELECT ITEM_ID, NVL(SUM(QTY_IN),0) - NVL(SUM(QTY_OUT),0) AS BAL
                FROM wst_djn_stock_ledger
                WHERE TXN_DATE < TO_DATE(:month_start,'YYYY-MM-DD') {div_clause}
                GROUP BY ITEM_ID""",
                {**div_params, 'month_start': month_start})
            opening = {r[0]: float(r[1]) for r in cur.fetchall()}

            # Closing -- ledger balance through month end (inclusive)
            cur.execute(f"""SELECT ITEM_ID, NVL(SUM(QTY_IN),0) - NVL(SUM(QTY_OUT),0) AS BAL
                FROM wst_djn_stock_ledger
                WHERE TXN_DATE < TO_DATE(:month_end,'YYYY-MM-DD') + 1 {div_clause}
                GROUP BY ITEM_ID""",
                {**div_params, 'month_end': month_end})
            closing = {r[0]: float(r[1]) for r in cur.fetchall()}

            # Received, by department, this month
            cur.execute(f"""SELECT ITEM_ID, DEPT_ID, NVL(SUM(QTY_RECEIVED),0) AS QTY
                FROM wst_djn_stock_receiving
                WHERE RECEIVE_DATE >= TO_DATE(:month_start,'YYYY-MM-DD')
                  AND RECEIVE_DATE < TO_DATE(:month_end,'YYYY-MM-DD') + 1 {div_clause}
                GROUP BY ITEM_ID, DEPT_ID""",
                {**div_params, 'month_start': month_start, 'month_end': month_end})
            received = {}
            for item_id, dept_id, qty in cur.fetchall():
                received.setdefault(item_id, {})[dept_id] = float(qty)

            # Only departments that actually have Stock Receiving entries in
            # the selected month (and division) get a column. Everyone else
            # in the Department master is left out of the report.
            active_dept_ids = {d for per_item in received.values() for d in per_item}
            dept_columns = [d for d in dept_columns if d['DEPT_ID'] in active_dept_ids]

            # Adjust -- net ADJUST-type ledger movement this month
            cur.execute(f"""SELECT ITEM_ID, NVL(SUM(QTY_IN),0) - NVL(SUM(QTY_OUT),0) AS NET
                FROM wst_djn_stock_ledger
                WHERE TXN_TYPE = 'ADJUST'
                  AND TXN_DATE >= TO_DATE(:month_start,'YYYY-MM-DD')
                  AND TXN_DATE < TO_DATE(:month_end,'YYYY-MM-DD') + 1 {div_clause}
                GROUP BY ITEM_ID""",
                {**div_params, 'month_start': month_start, 'month_end': month_end})
            adjust = {r[0]: float(r[1]) for r in cur.fetchall()}

            # Sale Out -- Gate Pass dispatch this month, Posted only
            cur.execute(f"""SELECT gl.ITEM_ID, NVL(SUM(gl.GATEPASS_QTY),0) AS QTY
                FROM wst_djn_gatepass_line gl
                JOIN wst_djn_gatepass_header gh ON gl.GATE_PASS_ID = gh.GATE_PASS_ID
                WHERE gh.STATUS = 'Posted'
                  AND gh.GATE_PASS_DATE >= TO_DATE(:month_start,'YYYY-MM-DD')
                  AND gh.GATE_PASS_DATE < TO_DATE(:month_end,'YYYY-MM-DD') + 1
                  {div_clause.replace('DIVISION', 'gh.DIVISION')}
                GROUP BY gl.ITEM_ID""",
                {**div_params, 'month_start': month_start, 'month_end': month_end})
            sale_out = {r[0]: float(r[1]) for r in cur.fetchall()}

            item_ids = set(opening) | set(closing) | set(received) | set(adjust) | set(sale_out)
            if not item_ids:
                return [], dept_columns

            placeholders = ','.join(f':id{i}' for i in range(len(item_ids)))
            id_params = {f'id{i}': int(iid) for i, iid in enumerate(item_ids)}
            cur.execute(f"""SELECT ITEM_ID, ITEM_CODE, ITEM_NAME, UNIT
                FROM wst_djn_items WHERE ITEM_ID IN ({placeholders})""", id_params)
            item_meta = {r[0]: {'ITEM_CODE': r[1], 'ITEM_NAME': r[2], 'UOM': r[3]} for r in cur.fetchall()}

    rows = []
    for item_id in item_ids:
        meta = item_meta.get(item_id, {'ITEM_CODE': None, 'ITEM_NAME': f'Item #{item_id}', 'UOM': None})
        rows.append({
            'ITEM_ID': item_id, 'ITEM_CODE': meta['ITEM_CODE'], 'ITEM_NAME': meta['ITEM_NAME'], 'UOM': meta['UOM'],
            'OPENING': opening.get(item_id, 0.0),
            'RECEIVED': received.get(item_id, {}),
            'ADJUST': adjust.get(item_id, 0.0),
            'SALE_OUT': sale_out.get(item_id, 0.0),
            'CLOSING': closing.get(item_id, 0.0),
        })
    rows.sort(key=lambda r: (r['ITEM_NAME'] or ''))
    return rows, dept_columns



# Distinct from the ad-hoc Reports-module report above, which always
# recalculates live and stays untouched. This is a PERMANENT, IMMUTABLE
# once-per-month archive: generated once per (division, month), then
# frozen -- viewing a past month always loads the saved record, never
# silently recalculates it.

def generate_msl_doc_no(cur, division, target_month):
    """Format: MSL-YYYY-MM-NNN. target_month is a 'YYYY-MM-DD' string (or
    any string starting with that), matching how it's used everywhere else
    in this module -- no need to parse it into a date object just to read
    the year/month back out. The NNN naturally lands on 001 in the normal
    case (only one snapshot can exist per division+month at a time,
    enforced by a UNIQUE DB constraint) -- it only climbs past 001 if that
    month's snapshot was Force Deleted and regenerated, since a hard
    delete leaves no earlier row to count against for this month."""
    yr = str(target_month)[:4]
    mo = str(target_month)[5:7]
    prefix = f'MSL-{yr}-{mo}-'
    cur.execute("""SELECT COUNT(*) FROM wst_djn_msl_snapshot_header
                   WHERE DOC_NO LIKE :1 AND DIVISION = :2""", [prefix + '%', str(division)])
    count = cur.fetchone()[0] or 0
    return f'{prefix}{count + 1:03d}'


def fetch_msl_snapshot_for_month(division, target_month):
    """Returns the saved snapshot header for this (division, month), or
    None if that month has not been generated yet. target_month can be any
    date within the month -- it's truncated to the 1st for comparison."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""SELECT SNAPSHOT_ID, DOC_NO, DIVISION,
                    TO_CHAR(TARGET_MONTH,'YYYY-MM-DD') AS TARGET_MONTH,
                    TO_CHAR(TARGET_MONTH,'Month YYYY') AS MONTH_DISPLAY,
                    TO_CHAR(CUTOFF_DATE,'YYYY-MM-DD') AS CUTOFF_DATE,
                    TO_CHAR(CUTOFF_DATE,'DD-Mon-YYYY') AS CUTOFF_DATE_DISPLAY,
                    CREATED_BY, TO_CHAR(CREATED_DATE,'DD-Mon-YYYY HH24:MI:SS') AS CREATED_DATE
                FROM wst_djn_msl_snapshot_header
                WHERE DIVISION = :1 AND TARGET_MONTH = TRUNC(TO_DATE(:2,'YYYY-MM-DD'),'MM')""",
                [str(division), str(target_month)])
            cols = [c[0] for c in cur.description]
            row = cur.fetchone()
            if not row:
                return None
            result = dict(zip(cols, row))
            result['MONTH_DISPLAY'] = result['MONTH_DISPLAY'].strip()
            return result


def fetch_msl_snapshot_by_id(snapshot_id, division=None):
    """IDOR-protected single-snapshot fetch, used by delete/PDF-export."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            base = """SELECT SNAPSHOT_ID, DOC_NO, DIVISION,
                    TO_CHAR(TARGET_MONTH,'Month YYYY') AS MONTH_DISPLAY,
                    TO_CHAR(CUTOFF_DATE,'DD-Mon-YYYY') AS CUTOFF_DATE_DISPLAY,
                    CREATED_BY, TO_CHAR(CREATED_DATE,'DD-Mon-YYYY HH24:MI:SS') AS CREATED_DATE
                FROM wst_djn_msl_snapshot_header WHERE SNAPSHOT_ID=:1"""
            if division:
                cur.execute(base + " AND DIVISION=:2", [int(snapshot_id), str(division)])
            else:
                cur.execute(base, [int(snapshot_id)])
            cols = [c[0] for c in cur.description]
            row = cur.fetchone()
            if not row:
                return None
            result = dict(zip(cols, row))
            result['MONTH_DISPLAY'] = result['MONTH_DISPLAY'].strip()
            return result


def fetch_msl_snapshot_lines(snapshot_id):
    """The frozen item rows for a saved snapshot (item_name/uom as they
    were AT GENERATION TIME, not looked up live -- matching the immutable
    historical record requirement). ITEM_ID is included so callers (e.g.
    the Quotation module) can build FK references / de-duplicate against
    it, in addition to the existing display-only usage of this function."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""SELECT LINE_ID, ITEM_ID, ITEM_CODE, ITEM_NAME, UOM, CLOSING_BALANCE
                FROM wst_djn_msl_snapshot_line WHERE SNAPSHOT_ID=:1 ORDER BY ITEM_NAME""",
                [int(snapshot_id)])
            cols = [c[0] for c in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]


def generate_msl_snapshot(division, target_month, cutoff_date, username=None):
    """Generates and PERMANENTLY saves one monthly snapshot. Atomic: header
    + every line are written on one connection, committed exactly once at
    the end -- a failure partway through rolls back everything, leaving no
    half-saved snapshot behind. Returns (True, snapshot_id) on success, or
    (False, error_message) if this (division, month) already has an active
    snapshot or anything else fails."""
    # Read the live balance data BEFORE opening the write transaction --
    # this is a point-in-time snapshot by definition, so reading it a
    # moment before the atomic write begins is exactly what's intended.
    balance_rows = fetch_historical_stock_balance(cutoff_date, division=division)

    with get_connection(username) as conn:
        with conn.cursor() as cur:
            try:
                cur.execute("""SELECT COUNT(*) FROM wst_djn_msl_snapshot_header
                               WHERE DIVISION=:1 AND TARGET_MONTH=TRUNC(TO_DATE(:2,'YYYY-MM-DD'),'MM')""",
                            [str(division), str(target_month)])
                if cur.fetchone()[0] > 0:
                    return False, "This month already has an active snapshot. Force Delete it first if you need to regenerate."

                doc_no = generate_msl_doc_no(cur, division, target_month)
                cur.execute("""INSERT INTO wst_djn_msl_snapshot_header
                    (DOC_NO, DIVISION, TARGET_MONTH, CUTOFF_DATE, CREATED_BY, CREATED_DATE)
                    VALUES (:1, :2, TRUNC(TO_DATE(:3,'YYYY-MM-DD'),'MM'), TO_DATE(:4,'YYYY-MM-DD'), :5, SYSDATE)""",
                    [doc_no, str(division), str(target_month), str(cutoff_date), username])

                cur.execute("SELECT SNAPSHOT_ID FROM wst_djn_msl_snapshot_header WHERE DOC_NO=:1", [doc_no])
                snapshot_id = cur.fetchone()[0]

                for r in balance_rows:
                    cur.execute("""INSERT INTO wst_djn_msl_snapshot_line
                        (SNAPSHOT_ID, ITEM_ID, ITEM_CODE, ITEM_NAME, UOM, CLOSING_BALANCE)
                        VALUES (:1, :2, :3, :4, :5, :6)""",
                        [snapshot_id, r['ITEM_ID'], r['ITEM_CODE'], r['ITEM_NAME'], r['UNIT'], r['BALANCE']])

                conn.commit()
                return True, snapshot_id
            except Exception as e:
                conn.rollback()
                return False, str(e)


def delete_msl_snapshot(snapshot_id, division=None):
    """Force Delete: hard-removes the header + all its lines. division is
    mandatory row-level security when supplied (IDOR protection) -- refuses
    to delete a snapshot belonging to a different division."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            if division:
                cur.execute("SELECT SNAPSHOT_ID FROM wst_djn_msl_snapshot_header WHERE SNAPSHOT_ID=:1 AND DIVISION=:2",
                            [int(snapshot_id), str(division)])
                if not cur.fetchone():
                    return False
            cur.execute("DELETE FROM wst_djn_msl_snapshot_line WHERE SNAPSHOT_ID=:1", [int(snapshot_id)])
            cur.execute("DELETE FROM wst_djn_msl_snapshot_header WHERE SNAPSHOT_ID=:1", [int(snapshot_id)])
            conn.commit()
            return True
