from django.db import migrations, models

class Migration(migrations.Migration):
    dependencies = [('accounts', '0001_initial')]
    operations = [
        migrations.AddField(
            model_name='customuser', name='division',
            field=models.CharField(choices=[('08','Division 08'),('13','Division 13')],
                                   default='08', help_text='Operational division for row-level data segregation',
                                   max_length=20),
        ),
    ]
