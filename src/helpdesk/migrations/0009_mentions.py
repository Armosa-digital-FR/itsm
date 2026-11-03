# Mentions « @technicien » dans les notes internes (FR-014d).

import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('helpdesk', '0008_treatment_time'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='Mention',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(default=django.utils.timezone.now, verbose_name='mentionné le')),
                ('read_at', models.DateTimeField(blank=True, null=True, verbose_name='lue le')),
                ('account', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='mentions', to=settings.AUTH_USER_MODEL, verbose_name='technicien mentionné')),
                ('note', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='mentions', to='helpdesk.ticketnote')),
            ],
            options={
                'verbose_name': 'mention',
                'verbose_name_plural': 'mentions',
                'ordering': ['-created_at'],
                'indexes': [models.Index(fields=['account', 'read_at'], name='mention_non_lue_idx')],
                'constraints': [models.UniqueConstraint(fields=('note', 'account'), name='mention_unique_par_note')],
            },
        ),
    ]
