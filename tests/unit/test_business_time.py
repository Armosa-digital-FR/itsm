"""Calendrier ouvré (research R12) : test obligatoire du calcul des délais."""

from datetime import UTC, date, datetime, time

import pytest

from core.business_time import (
    PARIS,
    Calendar,
    add_business_days,
    add_business_minutes,
    business_minutes_between,
    is_business_time,
)

CAL = Calendar()


def paris(*args) -> datetime:
    return datetime(*args, tzinfo=PARIS)


def test_vendredi_17h30_plus_une_heure_donne_lundi_9h30():
    # 2026-10-23 est un vendredi.
    due = add_business_minutes(paris(2026, 10, 23, 17, 30), 60, CAL)
    assert due == paris(2026, 10, 26, 9, 30).astimezone(UTC)


def test_creation_un_samedi_demarre_lundi_9h():
    due = add_business_minutes(paris(2026, 10, 24, 14, 0), 0, CAL)
    assert due == paris(2026, 10, 26, 9, 0).astimezone(UTC)


def test_avant_ouverture_demarre_a_9h():
    due = add_business_minutes(paris(2026, 10, 21, 7, 0), 240, CAL)
    assert due == paris(2026, 10, 21, 13, 0).astimezone(UTC)


def test_jour_ferie_saute():
    # Vendredi 1er mai 2026 férié : jeudi 30 avril 17:00 + 2 h → lundi 4 mai 10:00.
    due = add_business_minutes(paris(2026, 4, 30, 17, 0), 120, CAL)
    assert due == paris(2026, 5, 4, 10, 0).astimezone(UTC)


def test_jour_de_fermeture_saute():
    cal = Calendar(closures=frozenset({date(2026, 10, 26)}))
    due = add_business_minutes(paris(2026, 10, 23, 17, 30), 60, cal)
    assert due == paris(2026, 10, 27, 9, 30).astimezone(UTC)


def test_passage_heure_hiver():
    # Changement d'heure dans la nuit du 24 au 25 octobre 2026.
    due = add_business_minutes(paris(2026, 10, 23, 17, 0), 120, CAL)
    assert due == paris(2026, 10, 26, 10, 0).astimezone(UTC)
    assert business_minutes_between(paris(2026, 10, 23, 17, 0), due, CAL) == 120


def test_passage_heure_ete():
    # Changement d'heure dans la nuit du 28 au 29 mars 2026.
    start = paris(2026, 3, 27, 17, 0)
    due = add_business_minutes(start, 120, CAL)
    assert due == paris(2026, 3, 30, 10, 0).astimezone(UTC)


def test_un_jour_ouvre_vaut_une_journee():
    due = add_business_days(paris(2026, 10, 21, 10, 0), 1, CAL)
    assert due == paris(2026, 10, 22, 10, 0).astimezone(UTC)


def test_deux_jours_ouvres_sautent_le_week_end():
    due = add_business_days(paris(2026, 10, 22, 15, 0), 2, CAL)
    assert due == paris(2026, 10, 26, 15, 0).astimezone(UTC)


@pytest.mark.parametrize(
    "start,minutes",
    [
        ((2026, 10, 21, 8, 0), 30),
        ((2026, 10, 21, 10, 15), 540),
        ((2026, 10, 23, 17, 59), 1),
        ((2026, 10, 24, 12, 0), 600),
        ((2026, 12, 24, 16, 0), 1200),
    ],
)
def test_between_est_symetrique_de_add(start, minutes):
    begin = paris(*start)
    end = add_business_minutes(begin, minutes, CAL)
    assert business_minutes_between(begin, end, CAL) == minutes


def test_between_negatif_vaut_zero():
    assert business_minutes_between(paris(2026, 10, 22, 10), paris(2026, 10, 21, 10), CAL) == 0


def test_is_business_time():
    assert is_business_time(paris(2026, 10, 21, 9, 0), CAL)
    assert not is_business_time(paris(2026, 10, 21, 18, 0), CAL)
    assert not is_business_time(paris(2026, 10, 24, 10, 0), CAL)
    assert not is_business_time(paris(2026, 5, 1, 10, 0), CAL)


def test_date_naive_refusee():
    with pytest.raises(ValueError):
        add_business_minutes(datetime(2026, 10, 21, 10, 0), 10, CAL)


def test_plage_horaire_personnalisee():
    cal = Calendar(days=frozenset({0, 1, 2, 3}), start=time(8, 30), end=time(12, 30))
    # Jeudi 11:30 + 2 h → lundi 9:30 (vendredi non ouvré).
    due = add_business_minutes(paris(2026, 10, 22, 11, 30), 120, cal)
    assert due == paris(2026, 10, 26, 9, 30).astimezone(UTC)
