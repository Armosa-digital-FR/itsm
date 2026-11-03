"""Calendrier ouvré : plages horaires, jours fériés français, jours de fermeture (research R12).

Les calculs se font en heure de Paris et les résultats sont renvoyés en UTC.
"""

from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import holidays

PARIS = ZoneInfo("Europe/Paris")


@dataclass(frozen=True)
class Calendar:
    days: frozenset[int] = frozenset({0, 1, 2, 3, 4})
    start: time = time(9, 0)
    end: time = time(18, 0)
    closures: frozenset[date] = frozenset()
    tz: ZoneInfo = PARIS
    _holidays: holidays.HolidayBase = field(
        default_factory=lambda: holidays.country_holidays("FR"), compare=False, hash=False
    )

    @property
    def day_minutes(self) -> int:
        return (self.end.hour * 60 + self.end.minute) - (self.start.hour * 60 + self.start.minute)

    def is_business_day(self, d: date) -> bool:
        return d.weekday() in self.days and d not in self.closures and d not in self._holidays

    def window(self, d: date) -> tuple[datetime, datetime]:
        return (
            datetime.combine(d, self.start, tzinfo=self.tz),
            datetime.combine(d, self.end, tzinfo=self.tz),
        )


def get_calendar() -> Calendar:
    """Calendrier construit à partir des paramètres et des jours de fermeture en base."""
    from .models import ClosureDay, Settings

    conf = Settings.load()
    return Calendar(
        days=frozenset(conf.business_days),
        start=conf.business_start,
        end=conf.business_end,
        closures=frozenset(ClosureDay.objects.values_list("date", flat=True)),
    )


def _local(dt: datetime, cal: Calendar) -> datetime:
    if dt.tzinfo is None:
        raise ValueError("Une date-heure avec fuseau horaire est attendue.")
    return dt.astimezone(cal.tz)


def is_business_time(dt: datetime, cal: Calendar | None = None) -> bool:
    cal = cal or get_calendar()
    local = _local(dt, cal)
    if not cal.is_business_day(local.date()):
        return False
    start, end = cal.window(local.date())
    return start <= local < end


def add_business_minutes(start: datetime, minutes: int, cal: Calendar | None = None) -> datetime:
    """Instant atteint après `minutes` minutes ouvrées à partir de `start`."""
    cal = cal or get_calendar()
    if minutes < 0:
        raise ValueError("La durée doit être positive.")
    if cal.day_minutes <= 0 or not cal.days:
        raise ValueError("Le calendrier ouvré est vide.")
    remaining = timedelta(minutes=minutes)
    cursor = _local(start, cal)
    day = cursor.date()
    for _ in range(3660):  # garde-fou : 10 ans de jours calendaires
        if cal.is_business_day(day):
            open_, close = cal.window(day)
            begin = max(cursor, open_)
            if begin < close:
                available = close - begin
                if remaining <= available:
                    return (begin + remaining).astimezone(UTC)
                remaining -= available
        day += timedelta(days=1)
        cursor = datetime.combine(day, time(0, 0), tzinfo=cal.tz)
    raise ValueError("Aucun créneau ouvré trouvé dans les 10 prochaines années.")


def business_minutes_between(start: datetime, end: datetime, cal: Calendar | None = None) -> int:
    """Nombre de minutes ouvrées entre deux instants (0 si `end` ≤ `start`)."""
    return business_seconds_between(start, end, cal) // 60


def business_seconds_between(start: datetime, end: datetime, cal: Calendar | None = None) -> int:
    """Nombre de secondes ouvrées entre deux instants (0 si `end` ≤ `start`)."""
    cal = cal or get_calendar()
    begin, finish = _local(start, cal), _local(end, cal)
    if finish <= begin:
        return 0
    total = timedelta()
    day = begin.date()
    while day <= finish.date():
        if cal.is_business_day(day):
            open_, close = cal.window(day)
            overlap = min(close, finish) - max(open_, begin)
            if overlap > timedelta():
                total += overlap
        day += timedelta(days=1)
    return int(total.total_seconds())


def window_end(dt: datetime, cal: Calendar | None = None) -> datetime | None:
    """Fin de la plage ouvrée en cours à `dt`, ou None si `dt` est hors heures ouvrées."""
    cal = cal or get_calendar()
    if not is_business_time(dt, cal):
        return None
    return cal.window(_local(dt, cal).date())[1].astimezone(UTC)


def add_business_days(start: datetime, days: int, cal: Calendar | None = None) -> datetime:
    """Ajoute `days` jours ouvrés, comptés en durée ouvrée (1 jour = une journée complète)."""
    cal = cal or get_calendar()
    return add_business_minutes(start, days * cal.day_minutes, cal)
