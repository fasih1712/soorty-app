import oracledb
print('oracledb is running in thin mode:', oracledb.is_thin_mode())
print()

import environ
from pathlib import Path
base_dir = Path(r'D:\apps\soorty - apxprod')
env = environ.Env()
environ.Env.read_env(base_dir / '.env')

user = env('DB_USER')
password = env('DB_PASSWORD')
host = env('DB_HOST')
port = env('DB_PORT')
service_name = env('DB_SERVICE_NAME')
print('DB_HOST:', host)
print('DB_PORT:', port)
print('DB_SERVICE_NAME:', repr(service_name))

dsn = oracledb.makedsn(host, port, service_name=service_name)
print('Constructed DSN:', dsn)
print()

try:
    conn = oracledb.connect(user=user, password=password, dsn=dsn)
    cur = conn.cursor()
    cur.execute("SELECT USER FROM DUAL")
    print('SUCCESS:', cur.fetchone())
except Exception as e:
    print('FAILED:')
    print(type(e).__name__, ':', e)

