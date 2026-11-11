from django.db import migrations, models

class Migration(migrations.Migration):
    dependencies = [('accounts', '0004_add_more_divisions')]
    operations = [
        migrations.AlterField(
            model_name='customuser', name='division',
            field=models.CharField(
                choices=[
                    ('08', 'Soorty Denim (Landhi)'),
                    ('11', 'Soorty Spinning'),
                    ('13', 'Soorty Denim (Nooriabad)'),
                    ('16', 'Soorty Sewing Thread'),
                    ('19', 'Soorty Spinning (Nooriabad)'),
                ],
                default='08', max_length=20,
                help_text='Operational division for row-level data segregation',
            ),
        ),
    ]
