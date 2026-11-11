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
import calendar as month_calendar
import datetime

# Django
from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.views.decorators.http import require_GET

# wger
from wger.teams.calendar import (
    calendar_days,
    parse_date,
    parse_year,
    user_programs,
    user_today,
    week_start,
)
from wger.teams.models import AssignedRoutine


TIMELINE_WEEKS = 12
TIMELINE_WEEKS_BEFORE = 2


@login_required
@require_GET
def week(request):
    """
    The seven days of a week with the planned routine and the sessions done.
    """
    today = user_today(request.user)
    start = week_start(parse_date(request.GET.get('date'), today))
    end = start + datetime.timedelta(days=6)
    context = {
        'view': 'week',
        'days': calendar_days(request.user, start, end),
        'start': start,
        'end': end,
        'previous': start - datetime.timedelta(days=7),
        'next': start + datetime.timedelta(days=7),
        'today': today,
    }
    return render(request, 'calendar/week.html', context)


@login_required
@require_GET
def timeline(request):
    """
    The programs of the user as bars over twelve weeks.
    """
    today = user_today(request.user)
    anchor = week_start(parse_date(request.GET.get('date'), today))
    start = anchor - datetime.timedelta(weeks=TIMELINE_WEEKS_BEFORE)
    days = TIMELINE_WEEKS * 7
    end = start + datetime.timedelta(days=days - 1)

    programs = list(user_programs(request.user, start, end))
    assigned = {
        a.routine_id: a.assignment
        for a in AssignedRoutine.objects.filter(routine__in=programs).select_related(
            'assignment__team', 'assignment__assigned_by'
        )
    }
    rows = []
    for program in programs:
        first = max(program.start, start)
        last = min(program.end, end)
        rows.append(
            {
                'program': program,
                'assignment': assigned.get(program.pk),
                'weeks': round(((program.end - program.start).days + 1) / 7),
                # CSS grid lines start at 1
                'column': (first - start).days + 1,
                'span': (last - first).days + 1,
                'starts_before': program.start < start,
                'ends_after': program.end > end,
                'is_current': program.start <= today <= program.end,
            }
        )

    context = {
        'view': 'timeline',
        'rows': rows,
        'weeks': [start + datetime.timedelta(weeks=index) for index in range(TIMELINE_WEEKS)],
        'days': days,
        'start': start,
        'end': end,
        'anchor': anchor,
        'previous': anchor - datetime.timedelta(weeks=4),
        'next': anchor + datetime.timedelta(weeks=4),
        'today': today,
        'today_column': (today - start).days + 1 if start <= today <= end else None,
    }
    return render(request, 'calendar/timeline.html', context)


@login_required
@require_GET
def year(request):
    """
    All days of a year, month by month, with what was planned and what was trained.
    """
    today = user_today(request.user)
    selected = parse_year(request.GET.get('year'), today.year)
    start = datetime.date(selected, 1, 1)
    end = datetime.date(selected, 12, 31)
    by_date = {day.date: day for day in calendar_days(request.user, start, end)}

    months = []
    for number in range(1, 13):
        weeks = [
            [by_date[date] if date.month == number else None for date in dates]
            for dates in month_calendar.Calendar(firstweekday=0).monthdatescalendar(
                selected, number
            )
        ]
        in_month = [day for row in weeks for day in row if day is not None]
        months.append(
            {
                'first': datetime.date(selected, number, 1),
                'weeks': weeks,
                'trained': sum(1 for day in in_month if day.sessions),
                'planned': sum(1 for day in in_month if day.planned),
            }
        )

    context = {
        'view': 'year',
        'year': selected,
        'months': months,
        'trained': sum(month['trained'] for month in months),
        'planned': sum(month['planned'] for month in months),
        'previous': selected - 1,
        'next': selected + 1,
        'today': today,
        # Monday to Sunday of any week, for the column heads
        'weekdays': [datetime.date(2024, 1, 1) + datetime.timedelta(days=i) for i in range(7)],
    }
    return render(request, 'calendar/year.html', context)
