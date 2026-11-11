from django.conf import settings
db = settings.DATABASES['default']
print('Django is using this as the service name:', repr(db.get('NAME')))
print('Expected (known-working):', repr('apxdb.seltech.com'))
print('Match:', db.get('NAME') == 'apxdb.seltech.com')
print()
from django.db import connection
try:
    cur = connection.cursor()
    cur.execute("SELECT USER FROM DUAL")
    print('CONNECTION SUCCESS:', cur.fetchone())
except Exception as e:
    print('CONNECTION FAILED:')
    print(type(e).__name__, ':', e)

