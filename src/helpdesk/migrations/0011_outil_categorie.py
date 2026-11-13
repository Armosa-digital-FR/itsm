# Outil rattaché à une catégorie (FR-017a).

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('helpdesk', '0010_resolution_images'),
    ]

    operations = [
        migrations.AddField(
            model_name='tool',
            name='category',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='tools', to='helpdesk.category', verbose_name='catégorie'),
        ),
    ]
