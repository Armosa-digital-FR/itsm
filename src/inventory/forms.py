"""Formulaires du parc et des licences."""

from django import forms

from directory.models import DirectoryUser, Site, Subsidiary

from .models import Equipment, EquipmentType, Licence

DATE = {"widget": forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"})}


class TeamViewerIdField(forms.CharField):
    """Accepte « 123 456 789 » : les espaces sont retirés avant validation."""

    def to_python(self, value):
        return "".join((super().to_python(value) or "").split())

    def widget_attrs(self, widget):
        attrs = super().widget_attrs(widget)
        attrs.pop("maxlength", None)  # « 123 456 789 » doit pouvoir être saisi
        attrs.update({"inputmode": "numeric", "autocomplete": "off"})
        return attrs


def active_sites():
    return Site.objects.filter(is_active=True)


class EquipmentFilterForm(forms.Form):
    q = forms.CharField(
        label="Recherche",
        required=False,
        widget=forms.TextInput(
            attrs={"type": "search", "placeholder": "Nom, n° de série, utilisateur…"}
        ),
    )
    type = forms.ModelChoiceField(
        label="Type",
        required=False,
        empty_label="Tous",
        queryset=EquipmentType.objects.filter(is_active=True),
    )
    status = forms.ChoiceField(
        label="Statut", required=False, choices=[("", "Tous"), *Equipment.Status.choices]
    )
    subsidiary = forms.ModelChoiceField(
        label="Entité",
        required=False,
        empty_label="Toutes",
        queryset=Subsidiary.objects.filter(is_active=True),
    )
    site = forms.ModelChoiceField(
        label="Site", required=False, empty_label="Tous", queryset=active_sites()
    )
    source = forms.ChoiceField(
        label="Source", required=False, choices=[("", "Toutes"), *Equipment.Source.choices]
    )
    retire = forms.BooleanField(label="Retirés d'Intune", required=False)


class EquipmentCreateForm(forms.ModelForm):
    assigned_to = forms.ModelChoiceField(
        label="Affecté à",
        required=False,
        widget=forms.HiddenInput,
        queryset=DirectoryUser.objects.filter(is_active=True),
    )

    class Meta:
        model = Equipment
        fields = [
            "type",
            "name",
            "site",
            "status",
            "manufacturer",
            "model",
            "serial_number",
            "teamviewer_id",
            "purchase_date",
            "warranty_end",
            "notes",
            "assigned_to",
        ]
        field_classes = {"teamviewer_id": TeamViewerIdField}
        widgets = {
            "purchase_date": DATE["widget"],
            "warranty_end": DATE["widget"],
            "notes": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["type"].queryset = EquipmentType.objects.filter(is_active=True)
        self.fields["site"].queryset = active_sites()


class EquipmentEditForm(forms.ModelForm):
    """Champs ITSM ; champs descriptifs seulement pour une saisie manuelle (FR-062)."""

    class Meta:
        model = Equipment
        fields = [
            "type",
            "name",
            "manufacturer",
            "model",
            "serial_number",
            "site",
            "status",
            "teamviewer_id",
            "purchase_date",
            "warranty_end",
            "notes",
        ]
        field_classes = {"teamviewer_id": TeamViewerIdField}
        widgets = {
            "purchase_date": DATE["widget"],
            "warranty_end": DATE["widget"],
            "notes": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["site"].queryset = active_sites()
        if self.instance.is_from_intune:
            for name in ("type", "name", "manufacturer", "model", "serial_number"):
                del self.fields[name]


class EquipmentAssignForm(forms.Form):
    assigned_to = forms.ModelChoiceField(
        label="Affecter à",
        required=False,
        widget=forms.HiddenInput,
        queryset=DirectoryUser.objects.filter(is_active=True),
    )
    back_to_stock = forms.BooleanField(
        label="Repasser en stock si l'affectation est retirée", required=False, initial=True
    )


class LicenceForm(forms.ModelForm):
    class Meta:
        model = Licence
        fields = [
            "name",
            "vendor",
            "seats",
            "expires_at",
            "subsidiary",
            "assigned_users",
            "assigned_equipment",
            "notes",
        ]
        widgets = {
            "expires_at": DATE["widget"],
            "notes": forms.Textarea(attrs={"rows": 3}),
            "assigned_users": forms.SelectMultiple(attrs={"size": 8}),
            "assigned_equipment": forms.SelectMultiple(attrs={"size": 8}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["assigned_users"].queryset = DirectoryUser.objects.filter(is_active=True)
        self.fields["assigned_equipment"].queryset = Equipment.objects.select_related("type")
        self.fields["subsidiary"].empty_label = "—"
        self.fields["assigned_users"].required = False
        self.fields["assigned_equipment"].required = False
