"""Vues du parc et des licences (contracts/ui-routes.md, section Parc)."""

import csv

from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from core.auth import technician_required
from directory.models import DirectoryUser

from .forms import (
    EquipmentAssignForm,
    EquipmentCreateForm,
    EquipmentEditForm,
    EquipmentFilterForm,
    LicenceForm,
)
from .models import Equipment, Licence
from .services import equipment as svc
from .services import licences

PAGE_SIZE = 50


def is_htmx(request) -> bool:
    return request.headers.get("HX-Request") == "true"


def filtered_equipment(form: EquipmentFilterForm):
    qs = Equipment.objects.select_related("type", "site__subsidiary", "assigned_to__subsidiary")
    data = form.cleaned_data if form.is_valid() else {}
    for name in ("type", "status", "site", "source"):
        if data.get(name):
            qs = qs.filter(**{name: data[name]})
    if data.get("subsidiary"):
        sub = data["subsidiary"]
        qs = qs.filter(Q(site__subsidiary=sub) | Q(assigned_to__subsidiary=sub))
    if data.get("retire"):
        qs = qs.filter(intune_removed_at__isnull=False)
    if query := (data.get("q") or "").strip():
        qs = qs.filter(
            Q(name__icontains=query)
            | Q(serial_number__icontains=query.replace(" ", ""))
            | Q(model__icontains=query)
            | Q(assigned_to__display_name__icontains=query)
        )
    return qs.order_by("type__name", "name")


@technician_required
def equipment_list(request):
    form = EquipmentFilterForm(request.GET or None)
    page = Paginator(filtered_equipment(form), PAGE_SIZE).get_page(request.GET.get("page"))
    query = request.GET.copy()
    query.pop("page", None)
    context = {"form": form, "page": page, "query": query.urlencode()}
    template = (
        "inventory/partials/equipment_table.html"
        if is_htmx(request)
        else ("inventory/equipment_list.html")
    )
    return render(request, template, context)


@technician_required
def equipment_export(request):
    form = EquipmentFilterForm(request.GET or None)
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = (
        f'attachment; filename="parc-{timezone.localdate():%Y%m%d}.csv"'
    )
    response.write("﻿")
    writer = csv.writer(response, delimiter=";")
    writer.writerow(
        [
            "Nom",
            "Type",
            "Source",
            "Statut",
            "Entité",
            "Site",
            "Affecté à",
            "Fabricant",
            "Modèle",
            "N° de série",
            "Système",
            "Retiré d'Intune",
            "Fin de garantie",
        ]
    )
    for e in filtered_equipment(form).iterator(chunk_size=500):
        writer.writerow(
            [
                e.name,
                e.type,
                e.get_source_display(),
                e.get_status_display(),
                e.site.subsidiary or "",
                e.site,
                e.assigned_to or "",
                e.manufacturer,
                e.model,
                e.serial_number,
                f"{e.os} {e.os_version}".strip(),
                e.intune_removed_at.strftime("%d/%m/%Y") if e.intune_removed_at else "",
                e.warranty_end.strftime("%d/%m/%Y") if e.warranty_end else "",
            ]
        )
    return response


@technician_required
def equipment_new(request):
    form = EquipmentCreateForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        data = dict(form.cleaned_data)
        equipment = svc.create_manual(
            request.user,
            type=data.pop("type"),
            site=data.pop("site"),
            status=data.pop("status"),
            name=data.pop("name"),
            assigned_to=data.pop("assigned_to"),
            **data,
        )
        messages.success(request, f"{equipment.type} « {equipment} » ajouté au parc.")
        return redirect("inventory:equipment_detail", pk=equipment.pk)
    selected = form.cleaned_data.get("assigned_to") if form.is_bound and form.is_valid() else None
    return render(request, "inventory/equipment_new.html", {"form": form, "selected": selected})


@technician_required
def equipment_detail(request, pk: int):
    equipment = get_object_or_404(
        Equipment.objects.select_related(
            "type", "site__subsidiary", "assigned_to__subsidiary", "intune_primary_user"
        ),
        pk=pk,
    )
    form = EquipmentEditForm(request.POST or None, instance=Equipment.objects.get(pk=pk))
    if request.method == "POST" and form.is_valid():
        changed = svc.update(equipment, request.user, form.cleaned_data)
        if changed:
            messages.success(request, "Équipement mis à jour.")
        return redirect("inventory:equipment_detail", pk=pk)
    return render(
        request,
        "inventory/equipment_detail.html",
        {
            "equipment": equipment,
            "form": form,
            "assign_form": EquipmentAssignForm(initial={"assigned_to": equipment.assigned_to_id}),
            "events": equipment.events.select_related("actor__directory_user").order_by("-at"),
            "tickets": equipment.tickets.order_by("-created_at")[:20],
            "licences": licences.with_usage(equipment.licences.all()),
        },
        status=422 if request.method == "POST" else 200,
    )


@technician_required
def equipment_assign(request, pk: int):
    equipment = get_object_or_404(Equipment, pk=pk)
    form = EquipmentAssignForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        svc.assign(
            equipment,
            request.user,
            form.cleaned_data["assigned_to"],
            back_to_stock=form.cleaned_data["back_to_stock"],
        )
        messages.success(request, "Affectation enregistrée.")
    return redirect("inventory:equipment_detail", pk=pk)


@technician_required
def person_equipment_choices(request):
    """Cases à cocher des équipements du demandeur (création manuelle de ticket, FR-017)."""
    person = DirectoryUser.objects.filter(pk=request.GET.get("requester") or None).first()
    items = person.equipment.select_related("type").order_by("type__name", "name") if person else []
    return render(
        request,
        "inventory/partials/person_equipment_choices.html",
        {"items": items, "person": person},
    )


# --- Licences -----------------------------------------------------------------------


@technician_required
def licence_list(request):
    rows = list(licences.with_usage().select_related("subsidiary").order_by("name"))
    limit = licences.expiry_limit()
    for licence in rows:
        licence.state = licences.licence_state(licence, limit)
    return render(request, "inventory/licence_list.html", {"licences": rows})


@technician_required
def licence_new(request):
    form = LicenceForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        licence = form.save()
        svc.record_event(licence, "creation", request.user, "", licence.name)
        messages.success(request, f"Licence « {licence} » créée.")
        return redirect("inventory:licence_detail", pk=licence.pk)
    return render(request, "inventory/licence_form.html", {"form": form, "licence": None})


@technician_required
def licence_detail(request, pk: int):
    licence = get_object_or_404(Licence, pk=pk)
    form = LicenceForm(request.POST or None, instance=licence)
    if request.method == "POST" and form.is_valid():
        form.save()
        svc.record_event(licence, "modification", request.user, "", ", ".join(form.changed_data))
        messages.success(request, "Licence mise à jour.")
        return redirect("inventory:licence_detail", pk=pk)
    licence.state = licences.licence_state(licence)
    return render(
        request,
        "inventory/licence_form.html",
        {
            "form": form,
            "licence": licence,
            "users": licence.assigned_users.select_related("subsidiary", "site"),
            "equipment": licence.assigned_equipment.select_related("type", "site"),
            "events": licence.events.select_related("actor__directory_user").order_by("-at"),
        },
    )
