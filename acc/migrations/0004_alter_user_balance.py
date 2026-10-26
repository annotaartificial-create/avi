from decimal import Decimal
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('acc', '0003_user_is_marketer_user_is_ops'),
    ]

    operations = [
        migrations.AlterField(
            model_name='user',
            name='balance',
            field=models.DecimalField(
                decimal_places=2,
                default=Decimal('0.00'),
                help_text='Player available balance in KES',
                max_digits=12,
                verbose_name='wallet balance'
            ),
        ),
    ]
