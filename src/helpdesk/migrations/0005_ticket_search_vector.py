"""Recherche plein texte de la base de résolution (US6, research R3).

Configuration « french_unaccent » (racinisation française + accents ignorés) et colonne
générée `search_vector`. La colonne est créée en SQL : l'expression produite par Django
convertit la configuration avec `::regconfig`, ce que PostgreSQL refuse dans une colonne
générée (expression non immuable). L'état Django déclare un GeneratedField pour que l'ORM
ne tente jamais d'écrire la colonne.
"""

import django.contrib.postgres.search
from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.search import SearchVector
from django.db import migrations, models

CONFIG = """
CREATE TEXT SEARCH CONFIGURATION french_unaccent (COPY = french);
ALTER TEXT SEARCH CONFIGURATION french_unaccent
    ALTER MAPPING FOR hword, hword_part, word WITH unaccent, french_stem;
"""
DROP_CONFIG = "DROP TEXT SEARCH CONFIGURATION IF EXISTS french_unaccent;"

COLUMN = """
ALTER TABLE helpdesk_ticket ADD COLUMN search_vector tsvector GENERATED ALWAYS AS (
    setweight(to_tsvector('french_unaccent', coalesce(title, '')), 'A') ||
    setweight(to_tsvector('french_unaccent', coalesce(resolution, '')), 'B') ||
    setweight(to_tsvector('french_unaccent', coalesce(description, '')), 'C')
) STORED;
CREATE INDEX ticket_search_vector ON helpdesk_ticket USING gin (search_vector);
"""
DROP_COLUMN = """
DROP INDEX IF EXISTS ticket_search_vector;
ALTER TABLE helpdesk_ticket DROP COLUMN IF EXISTS search_vector;
"""


class Migration(migrations.Migration):
    dependencies = [
        ("helpdesk", "0004_ticket_equipment"),
        ("directory", "0001_initial"),  # extension unaccent (correctif D1)
    ]

    operations = [
        migrations.RunSQL(CONFIG, reverse_sql=DROP_CONFIG),
        migrations.SeparateDatabaseAndState(
            database_operations=[migrations.RunSQL(COLUMN, reverse_sql=DROP_COLUMN)],
            state_operations=[
                migrations.AddField(
                    model_name="ticket",
                    name="search_vector",
                    field=models.GeneratedField(
                        db_persist=True,
                        expression=SearchVector("title", "resolution", "description"),
                        output_field=django.contrib.postgres.search.SearchVectorField(),
                    ),
                ),
                migrations.AddIndex(
                    model_name="ticket",
                    index=GinIndex(fields=["search_vector"], name="ticket_search_vector"),
                ),
            ],
        ),
    ]
