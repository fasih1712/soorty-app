from django.db import connection
cur = connection.cursor()
cur.execute("SELECT USER FROM DUAL")
print('CONNECTED SUCCESSFULLY AS:', cur.fetchone())

