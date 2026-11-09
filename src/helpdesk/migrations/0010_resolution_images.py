# Images dans la résolution d'un ticket (FR-032a).

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('helpdesk', '0009_mentions'),
    ]

    operations = [
        migrations.AddField(
            model_name='attachment',
            name='in_resolution',
            field=models.BooleanField(default=False, verbose_name='image de la résolution'),
        ),
        migrations.AddField(
            model_name='ticket',
            name='resolution_html',
            field=models.TextField(blank=True, verbose_name='résolution HTML (assainie)'),
        ),
    ]
