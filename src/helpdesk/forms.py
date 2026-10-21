"""Formulaires des tickets."""

from django import forms
from django.utils import timezone

from directory.models import Account, DirectoryUser, Subsidiary

from .models import Category, TechnicianGroup, Ticket, TicketNote, Tool


class MultipleFileInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class MultipleFileField(forms.FileField):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("widget", MultipleFileInput())
        kwargs.setdefault("required", False)
        super().__init__(*args, **kwargs)

    def clean(self, data, initial=None):
        if not data:
            return []
        items = data if isinstance(data, list | tuple) else [data]
        return [super(MultipleFileField, self).clean(item, initial) for item in items]


class CategoryChoiceField(forms.ModelChoiceField):
    """Catégories actives, libellées par leur chemin complet et triées par ce chemin."""

    def __init__(self, **kwargs):
        queryset = Category.objects.filter(is_active=True).select_related("parent__parent")
        super().__init__(queryset=queryset, **kwargs)

    def refresh_choices(self):
        """Calculé à l'instanciation du formulaire (jamais à l'import du module)."""
        self.choices = [("", "—")] + sorted(
            ((c.pk, c.full_path) for c in self.queryset), key=lambda item: item[1].lower()
        )


class ITSMForm(forms.Form):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            if isinstance(field, CategoryChoiceField):
                field.refresh_choices()


def technicians():
    return (
        Account.objects.filter(is_active=True)
        .exclude(roles=[])
        .select_related("directory_user")
        .order_by("directory_user__display_name", "username")
    )


class TechnicianChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        return obj.display_name


class TicketFilterForm(ITSMForm):
    STATUS_CHOICES = [("ouverts", "Ouverts"), ("tous", "Tous"), *Ticket.Status.choices]

    q = forms.CharField(
        label="Recherche",
        required=False,
        widget=forms.TextInput(attrs={"type": "search", "placeholder": "Titre, n°, demandeur…"}),
    )
    status = forms.ChoiceField(label="Statut", choices=STATUS_CHOICES, required=False)
    priority = forms.ChoiceField(
        label="Priorité", required=False, choices=[("", "Toutes"), *Ticket.Priority.choices]
    )
    assignee = forms.ChoiceField(label="Assigné", required=False)
    group = forms.ModelChoiceField(
        label="Groupe", required=False, queryset=TechnicianGroup.objects.all(), empty_label="Tous"
    )
    subsidiary = forms.ModelChoiceField(
        label="Filiale",
        required=False,
        queryset=Subsidiary.objects.filter(is_active=True),
        empty_label="Toutes",
    )
    category = CategoryChoiceField(label="Catégorie", required=False)
    tool = forms.ModelChoiceField(
        label="Outil",
        required=False,
        queryset=Tool.objects.filter(is_active=True),
        empty_label="Tous",
    )
    breached = forms.BooleanField(label="Délai dépassé", required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["assignee"].choices = [
            ("", "Tous"),
            ("moi", "Moi"),
            ("aucun", "Non affecté"),
            *[(str(a.pk), a.display_name) for a in technicians()],
        ]


class TicketCreateForm(ITSMForm):
    requester = forms.ModelChoiceField(
        label="Demandeur",
        queryset=DirectoryUser.objects.filter(is_active=True),
        widget=forms.HiddenInput,
        error_messages={"required": "Choisissez le demandeur dans l'annuaire."},
    )
    title = forms.CharField(label="Titre", max_length=255)
    description = forms.CharField(label="Description", required=False, widget=forms.Textarea)
    type = forms.ChoiceField(
        label="Type", required=False, choices=[("", "—"), *Ticket.Type.choices]
    )
    category = CategoryChoiceField(label="Catégorie", required=False)
    tool = forms.ModelChoiceField(
        label="Outil", required=False, queryset=Tool.objects.filter(is_active=True), empty_label="—"
    )
    priority = forms.ChoiceField(
        label="Priorité", choices=Ticket.Priority.choices, initial=Ticket.Priority.NORMALE
    )
    files = MultipleFileField(label="Pièces jointes")


class QualifyForm(ITSMForm):
    type = forms.ChoiceField(
        label="Type", required=False, choices=[("", "—"), *Ticket.Type.choices]
    )
    category = CategoryChoiceField(label="Catégorie", required=False)
    tool = forms.ModelChoiceField(
        label="Outil", required=False, queryset=Tool.objects.filter(is_active=True), empty_label="—"
    )
    priority = forms.ChoiceField(label="Priorité", choices=Ticket.Priority.choices)
    subsidiary = forms.ModelChoiceField(
        label="Filiale",
        required=False,
        queryset=Subsidiary.objects.filter(is_active=True),
        empty_label="—",
    )
    requester = forms.ModelChoiceField(
        label="Demandeur",
        required=False,
        widget=forms.HiddenInput,
        queryset=DirectoryUser.objects.filter(is_active=True),
    )


class StatusForm(forms.Form):
    status = forms.ChoiceField(choices=Ticket.Status.choices)
    resolution = forms.CharField(label="Résolution", required=False, widget=forms.Textarea)


class AssignForm(forms.Form):
    assignee = TechnicianChoiceField(
        label="Technicien", required=False, queryset=technicians(), empty_label="—"
    )
    group = forms.ModelChoiceField(
        label="Groupe", required=False, queryset=TechnicianGroup.objects.all(), empty_label="—"
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["assignee"].queryset = technicians()

    def clean(self):
        data = super().clean()
        if not data.get("assignee") and not data.get("group"):
            raise forms.ValidationError("Choisissez un technicien ou un groupe.")
        return data


class BulkAssignForm(AssignForm):
    from_technician = TechnicianChoiceField(label="Tickets de", queryset=technicians())

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["from_technician"].queryset = Account.objects.exclude(roles=[]).select_related(
            "directory_user"
        )


class NoteForm(forms.Form):
    visibility = forms.ChoiceField(
        label="Visibilité",
        choices=TicketNote.Visibility.choices,
        initial=TicketNote.Visibility.INTERNE,
        widget=forms.RadioSelect,
    )
    body = forms.CharField(label="Message", widget=forms.Textarea(attrs={"rows": 5}))
    files = MultipleFileField(label="Pièces jointes")


class TimeForm(forms.Form):
    date = forms.DateField(label="Date", widget=forms.DateInput(attrs={"type": "date"}))
    minutes = forms.IntegerField(label="Durée (minutes)", min_value=1, max_value=1440)
    comment = forms.CharField(label="Commentaire", required=False, max_length=500)

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("initial", {"date": timezone.localdate()})
        super().__init__(*args, **kwargs)

    def clean_date(self):
        value = self.cleaned_data["date"]
        if value > timezone.localdate():
            raise forms.ValidationError("La date ne peut pas être dans le futur.")
        return value
