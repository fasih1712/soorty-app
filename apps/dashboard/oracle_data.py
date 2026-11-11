from core import db
from django.conf import settings

def get_connection():
    return db.connect()


def fetch_sales_summary():
    sql = """
        SELECT 
            COUNT(*) AS total_orders,
            ROUND(SUM(NET_AMOUNT), 0) AS total_amount,
            COUNT(DISTINCT CUSTOMER_NAME) AS total_customers
        FROM apxprod.APX_EBS_ORDER_SALES_VW
        WHERE ORDERED_DATE >= ADD_MONTHS(LOCALTIMESTAMP(0), -1)
    """
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(sql)
            columns = [col[0] for col in cursor.description]
            row = cursor.fetchone()
            return dict(zip(columns, row)) if row else {}


def fetch_recent_orders(limit=10):
    sql = """
        SELECT 
            ORDER_NUMBER, CUSTOMER_NAME, ORDERED_ITEM,
            ORDERED_QUANTITY, NET_AMOUNT, FLOW_STATUS_CODE, ORDERED_DATE
        FROM apxprod.APX_EBS_ORDER_SALES_VW
        ORDER BY ORDERED_DATE DESC
        FETCH FIRST :1 ROWS ONLY
    """
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(sql, [limit])
            columns = [col[0] for col in cursor.description]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]


def fetch_employee_summary():
    sql = """
        SELECT 
            COUNT(*) AS total_emp,
            COUNT(DISTINCT DEPTNO) AS total_depts,
            ROUND(AVG(SAL), 0) AS avg_salary
        FROM apxprod.EMP
    """
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(sql)
            columns = [col[0] for col in cursor.description]
            row = cursor.fetchone()
            return dict(zip(columns, row)) if row else {}


def fetch_all_employees():
    sql = """
        SELECT 
            e.EMPNO, e.ENAME, e.JOB, e.MGR,
            TO_CHAR(e.HIREDATE, 'DD-Mon-YYYY') AS HIREDATE,
            e.SAL, e.COMM,
            d.DNAME, d.LOC
        FROM apxprod.EMP e
        LEFT JOIN apxprod.DEPT d ON e.DEPTNO = d.DEPTNO
        ORDER BY e.EMPNO
    """
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(sql)
            columns = [col[0] for col in cursor.description]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]


def fetch_emp_by_id(empno):
    sql = """
        SELECT e.EMPNO, e.ENAME, e.JOB, e.MGR,
               TO_CHAR(e.HIREDATE, 'YYYY-MM-DD') AS HIREDATE,
               e.SAL, e.COMM, e.DEPTNO
        FROM apxprod.EMP e
        WHERE e.EMPNO = :1
    """
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(sql, [int(empno)])
            columns = [col[0] for col in cursor.description]
            row = cursor.fetchone()
            return dict(zip(columns, row)) if row else None


def insert_emp(ename, job, mgr, hiredate, sal, comm, deptno):
    sql = """
        INSERT INTO apxprod.EMP (EMPNO, ENAME, JOB, MGR, HIREDATE, SAL, COMM, DEPTNO)
        VALUES (nextval('apxprod.emp_seq'), :1, :2, :3, TO_DATE(:4, 'YYYY-MM-DD'), :5, :6, :7)
    """
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(sql, [
                str(ename).upper(),
                str(job),
                int(mgr) if mgr else None,
                str(hiredate),
                float(str(sal)),
                float(str(comm)) if comm else None,
                int(str(deptno)),
            ])
            conn.commit()


def update_emp(empno, ename, job, mgr, hiredate, sal, comm, deptno):
    sql = """
        UPDATE apxprod.EMP SET
            ENAME    = :1,
            JOB      = :2,
            MGR      = :3,
            HIREDATE = TO_DATE(:4, 'YYYY-MM-DD'),
            SAL      = :5,
            COMM     = :6,
            DEPTNO   = :7
        WHERE EMPNO  = :8
    """
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(sql, [
                str(ename).upper(),
                str(job),
                int(mgr) if mgr else None,
                str(hiredate),
                float(str(sal)),
                float(str(comm)) if comm else None,
                int(str(deptno)),
                int(empno),
            ])
            conn.commit()


def delete_emp(empno):
    sql = "DELETE FROM apxprod.EMP WHERE EMPNO = :1"
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(sql, [int(empno)])
            conn.commit()