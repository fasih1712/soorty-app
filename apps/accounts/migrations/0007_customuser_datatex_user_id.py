from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0006_pagepermissionanchor_pageregistry_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='customuser',
            name='datatex_user_id',
            field=models.CharField(
                blank=True, max_length=50, null=True, unique=True,
                help_text='Maps this local account to its ID_ row in the centralized '
                           'ACT_ID_USER_VW view. Leave blank for local-only accounts '
                           '(e.g. Django superusers) -- CustomDatatexAuthBackend uses '
                           'the presence of this field, not is_superuser directly, to '
                           'decide whether a login attempt is checked against the '
                           'centralized view or against the local Django password.'
            ),
        ),
    ]
