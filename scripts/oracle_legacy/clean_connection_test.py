import oracledb
from django.conf import settings

db = settings.DATABASES['default']
print('Connecting as:', db['USER'], '  Host:', db['HOST'], '  Port:', db['PORT'], '  Service:', db.get('NAME'))
print('-' * 60)

try:
    conn = oracledb.connect(
        user=db['USER'],
        password=db['PASSWORD'],
        dsn=f"{db['HOST']}:{db['PORT']}/{db.get('NAME')}",
    )
    cur = conn.cursor()
    cur.execute("SELECT USER FROM DUAL")
    print('SUCCESS -- connected as:', cur.fetchone())
except Exception as e:
    print('FAILED WITH THIS EXACT ERROR:')
    print(type(e).__name__, ':', e)

