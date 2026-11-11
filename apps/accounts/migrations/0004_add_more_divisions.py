from django.db import migrations, models

class Migration(migrations.Migration):
    dependencies = [('accounts', '0003_customuser_sees_all_divisions')]
    operations = [
        migrations.AlterField(
            model_name='customuser', name='division',
            field=models.CharField(
                choices=[
                    ('08', 'Division 08'),
                    ('11', 'Division 11'),
                    ('13', 'Division 13'),
                    ('16', 'Division 16'),
                    ('19', 'Division 19'),
                ],
                default='08', max_length=20,
                help_text='Operational division for row-level data segregation',
            ),
        ),
    ]
