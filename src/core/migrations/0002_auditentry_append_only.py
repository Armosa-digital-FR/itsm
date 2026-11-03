"""Journal d'audit en ajout seul : un déclencheur refuse UPDATE et DELETE (research R14).

Seule exception : la purge de rétention, qui positionne `itsm.audit_purge = 'on'` dans la
transaction (voir core.audit.purge_before).
"""

from django.db import migrations

CREATE = """
CREATE OR REPLACE FUNCTION core_auditentry_protect() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'DELETE' AND current_setting('itsm.audit_purge', true) = 'on' THEN
        RETURN OLD;
    END IF;
    RAISE EXCEPTION 'Le journal d''audit est en ajout seul (% refusé).', TG_OP
        USING ERRCODE = 'insufficient_privilege';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER core_auditentry_protect
    BEFORE UPDATE OR DELETE ON core_auditentry
    FOR EACH ROW EXECUTE FUNCTION core_auditentry_protect();
"""

DROP = """
DROP TRIGGER IF EXISTS core_auditentry_protect ON core_auditentry;
DROP FUNCTION IF EXISTS core_auditentry_protect();
"""


class Migration(migrations.Migration):
    dependencies = [("core", "0001_initial")]

    operations = [migrations.RunSQL(CREATE, reverse_sql=DROP)]
