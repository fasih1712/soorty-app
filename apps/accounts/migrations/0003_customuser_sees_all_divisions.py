from django.db import migrations, models

class Migration(migrations.Migration):
    dependencies = [('accounts', '0002_customuser_division')]
    operations = [
        migrations.AddField(
            model_name='customuser', name='sees_all_divisions',
            field=models.BooleanField(
                default=False,
                help_text='Grants cross-division visibility (view, edit, delete across ALL '
                          'divisions, and choose the division when creating records). '
                          'Independent of role — grant this only to specific trusted '
                          'users/admins who genuinely need it.',
            ),
        ),
    ]
