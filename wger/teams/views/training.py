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
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db.models import (
    Count,
    Q,
)
from django.shortcuts import (
    redirect,
    render,
)
from django.utils.translation import gettext as _
from django.views.decorators.http import (
    require_GET,
    require_http_methods,
)

# wger
from wger.manager.models import (
    Day,
    Routine,
)
from wger.teams.calendar import user_today
from wger.teams.forms import (
    NewPlanForm,
    NewProgramForm,
    NewRoutineForm,
)
from wger.teams.models import AssignedRoutine
from wger.teams.services import (
    add_routine,
    create_plan,
    create_program,
)


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


@login_required
@require_http_methods(['GET', 'POST'])
def program_new(request):
    """
    Create a program from an existing plan and/or single routines, then open it in the editor.
    """
    form = NewProgramForm(request.POST or None, user=request.user)
    if request.method == 'POST' and form.is_valid():
        try:
            program = create_program(
                user=request.user,
                name=form.cleaned_data['name'],
                start_date=form.cleaned_data['start_date'],
                end_date=form.cleaned_data['end_date'],
                plan=form.cleaned_data['plan'],
                days=form.cleaned_data['routines'],
            )
        except ValidationError as exc:
            form.add_error(None, exc.messages)
        else:
            messages.success(request, _('The program was created. You can adjust it here.'))
            return redirect('manager:routine:edit', pk=program.pk)

    return render(request, 'training/program_new.html', {'tab': 'programs', 'form': form})


@login_required
@require_http_methods(['GET', 'POST'])
def plan_new(request):
    """
    Create a plan from an existing plan and/or single routines.
    """
    form = NewPlanForm(request.POST or None, user=request.user)
    if request.method == 'POST' and form.is_valid():
        try:
            plan = create_plan(
                user=request.user,
                name=form.cleaned_data['name'],
                plan=form.cleaned_data['plan'],
                days=form.cleaned_data['routines'],
            )
        except ValidationError as exc:
            form.add_error(None, exc.messages)
        else:
            messages.success(request, _('The plan was created.'))
            return redirect('manager:template:view', pk=plan.pk)

    return render(request, 'training/plan_new.html', {'tab': 'plans', 'form': form})


@login_required
@require_http_methods(['GET', 'POST'])
def routine_new(request):
    """
    Create a routine in one of the user's programs, then open that program in the editor.
    """
    form = NewRoutineForm(request.POST or None, user=request.user)
    if request.method == 'POST' and form.is_valid():
        day = add_routine(
            user=request.user,
            name=form.cleaned_data['name'],
            program=form.target_program(),
            source=form.cleaned_data['source'],
        )
        messages.success(request, _('The routine was created. Add its exercises here.'))
        return redirect('manager:routine:edit', pk=day.routine_id)

    return render(request, 'training/routine_new.html', {'tab': 'routines', 'form': form})
