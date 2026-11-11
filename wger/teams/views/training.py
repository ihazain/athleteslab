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

# Django
from django.contrib.auth.decorators import login_required
from django.db.models import (
    Count,
    Q,
)
from django.shortcuts import render
from django.views.decorators.http import require_GET

# wger
from wger.manager.models import (
    Day,
    Routine,
)
from wger.teams.calendar import user_today
from wger.teams.models import AssignedRoutine


def _weeks(routine: Routine) -> int:
    return max(1, round(((routine.end - routine.start).days + 1) / 7))


@login_required
@require_GET
def programs(request):
    """
    Programs: the plans the user trains over a period of weeks, own and assigned ones.
    """
    today = user_today(request.user)
    routines = list(
        Routine.objects.filter(user=request.user, is_template=False)
        .annotate(training_days=Count('days', filter=Q(days__is_rest=False)))
        .order_by('-start', '-pk')
    )
    assigned = {
        a.routine_id: a.assignment
        for a in AssignedRoutine.objects.filter(routine__in=routines).select_related(
            'assignment__team', 'assignment__group', 'assignment__assigned_by'
        )
    }
    entries = []
    for routine in routines:
        if routine.end < today:
            status = 'finished'
        elif routine.start > today:
            status = 'upcoming'
        else:
            status = 'current'
        entries.append(
            {
                'program': routine,
                'weeks': _weeks(routine),
                'status': status,
                'assignment': assigned.get(routine.pk),
            }
        )

    # Running programs first, then the coming ones (next one first), then the finished
    # ones (latest first)
    order = {'current': 0, 'upcoming': 1, 'finished': 2}
    entries.sort(
        key=lambda entry: (
            order[entry['status']],
            entry['program'].start.toordinal() * (-1 if entry['status'] == 'finished' else 1),
        )
    )
    return render(request, 'training/programs.html', {'tab': 'programs', 'entries': entries})


@login_required
@require_GET
def plans(request):
    """
    Plans: reusable sets of training days without a period (templates).
    """
    templates = (
        Routine.objects.filter(user=request.user, is_template=True)
        .annotate(training_days=Count('days', filter=Q(days__is_rest=False)))
        .order_by('name', 'pk')
    )
    return render(request, 'training/plans.html', {'tab': 'plans', 'plans': templates})


@login_required
@require_GET
def routines(request):
    """
    Routines: the single training days of the user's plans and programs.
    """
    days = (
        Day.objects.filter(routine__user=request.user, is_rest=False)
        .select_related('routine')
        .annotate(exercises=Count('slots__entries'))
        .order_by('routine__is_template', 'routine__name', 'routine__pk', 'order', 'pk')
    )
    return render(request, 'training/routines.html', {'tab': 'routines', 'days': days})
