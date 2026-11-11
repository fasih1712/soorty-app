from django.conf import settings
pw = settings.DATABASES['default']['PASSWORD']
print('Password length as Django sees it:', len(pw))
print('Contains a literal $:', '$' in pw)
print('First 3 characters:', pw[:3])
print('Expected: length 11, contains $ = True, first 3 = apx')

