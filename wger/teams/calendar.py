#  This file is part of wger Workout Manager <https://github.com/wger-project>.
#  Copyright (C) 2013 - 2021 wger Team
#
#  wger Workout Manager is free software: you can redistribute it and/or modify
#  it under the terms of the GNU Affero General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#
#  wger Workout Manager is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU Affero General Public License for more details.
#
#  You should have received a copy of the GNU Affero General Public License
#  along with this program.  If not, see <http://www.gnu.org/licenses/>.

# Standard Library
import datetime
from dataclasses import (
    dataclass,
    field,
)

# Django
from django.utils import timezone

# wger
from wger.manager.models import (
    Routine,
    WorkoutSession,
)


@dataclass
class PlannedTraining:
    """
    The routine (one training day) a program schedules on a date.
    """

    program: Routine
    name: str


@dataclass
class CalendarDay:
    date: datetime.date
    planned: list[PlannedTraining] = field(default_factory=list)
    sessions: int = 0
    is_today: bool = False
    is_past: bool = False

    @property
    def state(self) -> str:
        """
        trained, missed (planned in the past, nothing logged), planned or free.
        """
        if self.sessions:
            return 'trained'
        if self.planned:
            return 'missed' if self.is_past else 'planned'
        return 'free'


def user_today(user) -> datetime.date:
    """
    Today's date in the time zone of the user.
    """
    return timezone.now().astimezone(user.userprofile.zone_info).date()


def user_programs(user, start: datetime.date, end: datetime.date):
    """
    The programs (dated routines, no templates) of the user that touch the period.
    """
    return Routine.objects.filter(
        user=user,
        is_template=False,
        start__lte=end,
        end__gte=start,
    ).order_by('start', 'pk')


def calendar_days(user, start: datetime.date, end: datetime.date) -> list[CalendarDay]:
    """
    One entry per date of the period with the planned training and the sessions done.

    Dates are calendar days of the user: sessions count for the day they
    started on in the user's time zone.
    """
    today = user_today(user)
    days = {}
    current = start
    while current <= end:
        days[current] = CalendarDay(
            date=current, is_today=current == today, is_past=current < today
        )
        current += datetime.timedelta(days=1)

    for program in user_programs(user, start, end):
        for entry in program.date_sequence:
            if entry.date in days and entry.day is not None and not entry.day.is_rest:
                days[entry.date].planned.append(
                    PlannedTraining(program=program, name=entry.day.name or program.name)
                )

    # A day of margin on both sides: the UTC instant and the local day can differ
    zone = user.userprofile.zone_info
    margin = datetime.timedelta(days=1)
    sessions = WorkoutSession.objects.filter(
        user=user,
        datetime_start__date__gte=start - margin,
        datetime_start__date__lte=end + margin,
    )
    for session in sessions:
        local_day = session.local_day_in(zone)
        if local_day in days:
            days[local_day].sessions += 1

    return list(days.values())


def parse_date(value: str | None, default: datetime.date) -> datetime.date:
    """
    The ISO date from a query parameter, or the default if it is missing or malformed.
    """
    try:
        return datetime.date.fromisoformat(value or '')
    except ValueError:
        return default


def parse_year(value: str | None, default: int) -> int:
    try:
        year = int(value or '')
    except ValueError:
        return default
    return year if 2000 <= year <= 2100 else default


def week_start(date: datetime.date) -> datetime.date:
    """
    The Monday of the week of the date.
    """
    return date - datetime.timedelta(days=date.weekday())
