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

# Django
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import (
    PermissionDenied,
    ValidationError,
)
from django.db.models import Count
from django.http import Http404
from django.shortcuts import (
    get_object_or_404,
    redirect,
    render,
)
from django.utils.translation import (
    gettext as _,
    ngettext,
)
from django.views.decorators.http import (
    require_GET,
    require_http_methods,
    require_POST,
)

# wger
from wger.teams.calendar import (
    calendar_days,
    parse_date,
    team_agenda,
    user_today,
    week_start,
)
from wger.teams.forms import (
    AssignProgramForm,
    GroupForm,
)
from wger.teams.models import (
    ProgramAssignment,
    Team,
    TeamGroup,
    TeamMembership,
)
from wger.teams.services import (
    archive_assignment,
    assign_program,
    assignment_progress,
    change_member_role,
    create_group,
    create_team,
    delete_group,
    find_user,
    invite_member,
    is_assignment_coach,
    member_programs,
    remove_member,
    team_assignments,
    update_group,
)


AGENDA_WEEKS = 6
AGENDA_WEEKS_BEFORE = 1
AGENDA_STEP_WEEKS = 4


def _coach_team(request, pk: int) -> Team:
    """
    The team if the user is one of its active coaches, 404 otherwise.
    """
    return get_object_or_404(
        Team,
        pk=pk,
        memberships__user=request.user,
        memberships__role=TeamMembership.Role.COACH,
        memberships__status=TeamMembership.Status.ACTIVE,
    )


def _clean_name(request) -> str | None:
    """
    The team name from the form, with an error message if it is not usable.
    """
    name = request.POST.get('name', '').strip()
    max_length = Team._meta.get_field('name').max_length
    if not name or len(name) > max_length:
        messages.error(
            request,
            _('Please enter a name with at most %(max)d characters.') % {'max': max_length},
        )
        return None
    return name


def _run(request, action, success: str) -> None:
    """
    Runs a service call and reports the outcome as a message.
    """
    try:
        action()
    except ValidationError as exc:
        messages.error(request, ' '.join(exc.messages))
    else:
        messages.success(request, success)


@login_required
@require_POST
def team_add(request):
    name = _clean_name(request)
    if name is None:
        return redirect('teams:overview')

    team = create_team(name, request.user)
    messages.success(request, _('The team was created. Invite your athletes now.'))
    return redirect('teams:team-detail', pk=team.pk)


@login_required
@require_GET
def team_detail(request, pk: int):
    """
    The team page of a coach: members and invitations.
    """
    team = _coach_team(request, pk)
    # Active members first, coaches before athletes
    memberships = team.memberships.select_related('user').order_by(
        'status', '-role', 'user__username'
    )
    groups = [
        {
            'group': group,
            'members': [m.user.username for m in group.members.all()],
            'form': GroupForm(team=team, group=group),
        }
        for group in team.groups.prefetch_related('members__user')
    ]

    assignments = (
        team_assignments(team)
        .select_related('template', 'group', 'athlete')
        .annotate(received=Count('assigned_routines'))
        .order_by('-start_date', '-pk')
    )
    today = user_today(request.user)
    anchor = week_start(parse_date(request.GET.get('date'), today))
    agenda_start = anchor - datetime.timedelta(weeks=AGENDA_WEEKS_BEFORE)
    agenda_end = agenda_start + datetime.timedelta(weeks=AGENDA_WEEKS, days=-1)
    context = {
        'team': team,
        'memberships': memberships,
        'groups': groups,
        'group_form': GroupForm(team=team),
        'assignments': assignments,
        'agenda': team_agenda(team, agenda_start, agenda_end, today),
        'agenda_start': agenda_start,
        'agenda_end': agenda_end,
        'agenda_previous': anchor - datetime.timedelta(weeks=AGENDA_STEP_WEEKS),
        'agenda_next': anchor + datetime.timedelta(weeks=AGENDA_STEP_WEEKS),
    }
    return render(request, 'teams/team_detail.html', context)


@login_required
@require_GET
def member_detail(request, pk: int, membership_pk: int):
    """
    The profile of an active member for the coach: groups, assigned programs and the
    week with the training planned by them.
    """
    team = _coach_team(request, pk)
    membership = get_object_or_404(
        TeamMembership.objects.select_related('user__userprofile'),
        pk=membership_pk,
        team=team,
        status=TeamMembership.Status.ACTIVE,
    )
    member = membership.user
    programs = member_programs(request.user, membership)

    # The week of the member, not the one of the coach
    today = user_today(member)
    start = week_start(parse_date(request.GET.get('date'), today))
    end = start + datetime.timedelta(days=6)
    running = [
        row['assigned'].routine
        for row in programs
        if row['assigned'].routine is not None
        and row['assigned'].routine.start <= end
        and row['assigned'].routine.end >= start
    ]
    context = {
        'team': team,
        'membership': membership,
        'member': member,
        'groups': membership.groups.all(),
        'programs': programs,
        'days': calendar_days(member, start, end, programs=running),
        'start': start,
        'end': end,
        'previous': start - datetime.timedelta(days=7),
        'next': start + datetime.timedelta(days=7),
    }
    return render(request, 'teams/member_detail.html', context)


@login_required
@require_POST
def team_edit(request, pk: int):
    team = _coach_team(request, pk)
    name = _clean_name(request)
    if name is not None:
        team.name = name
        team.save(update_fields=['name'])
        messages.success(request, _('The team was renamed.'))
    return redirect('teams:team-detail', pk=team.pk)


@login_required
@require_POST
def team_delete(request, pk: int):
    team = _coach_team(request, pk)
    team.delete()
    messages.success(
        request,
        _('The team was deleted. The athletes keep their programs and logs.'),
    )
    return redirect('teams:overview')


@login_required
@require_POST
def member_invite(request, pk: int):
    team = _coach_team(request, pk)
    user = find_user(request.POST.get('identifier', ''))
    if user is None:
        messages.error(request, _('No user with this username or e-mail address was found.'))
    else:
        _run(
            request,
            lambda: invite_member(team, request.user, user, request.POST.get('role', '')),
            _('%(user)s was invited and has to accept the invitation.') % {'user': user.username},
        )
    return redirect('teams:team-detail', pk=team.pk)


@login_required
@require_POST
def member_role(request, pk: int, membership_pk: int):
    team = _coach_team(request, pk)
    membership = get_object_or_404(TeamMembership, pk=membership_pk, team=team)
    _run(
        request,
        lambda: change_member_role(membership, request.user, request.POST.get('role', '')),
        _('The role was changed.'),
    )
    return redirect('teams:team-detail', pk=team.pk)


@login_required
@require_POST
def member_remove(request, pk: int, membership_pk: int):
    team = _coach_team(request, pk)
    membership = get_object_or_404(TeamMembership, pk=membership_pk, team=team)
    username = membership.user.username
    _run(
        request,
        lambda: remove_member(membership, request.user),
        _('%(user)s was removed from the team.') % {'user': username},
    )
    return redirect('teams:team-detail', pk=team.pk)


def _form_errors(request, form) -> None:
    for field, errors in form.errors.items():
        label = form.fields[field].label if field in form.fields else ''
        for error in errors:
            messages.error(request, f'{label}: {error}' if label else error)


@login_required
@require_POST
def group_add(request, pk: int):
    team = _coach_team(request, pk)
    form = GroupForm(request.POST, team=team)
    if form.is_valid():
        _run(
            request,
            lambda: create_group(
                team, request.user, form.cleaned_data['name'], form.cleaned_data['members']
            ),
            _('The group was created.'),
        )
    else:
        _form_errors(request, form)
    return redirect('teams:team-detail', pk=team.pk)


@login_required
@require_POST
def group_edit(request, pk: int, group_pk: int):
    team = _coach_team(request, pk)
    group = get_object_or_404(TeamGroup, pk=group_pk, team=team)
    form = GroupForm(request.POST, team=team, group=group)
    if form.is_valid():
        _run(
            request,
            lambda: update_group(
                group, request.user, form.cleaned_data['name'], form.cleaned_data['members']
            ),
            _('The group was saved.'),
        )
    else:
        _form_errors(request, form)
    return redirect('teams:team-detail', pk=team.pk)


@login_required
@require_POST
def group_delete(request, pk: int, group_pk: int):
    team = _coach_team(request, pk)
    group = get_object_or_404(TeamGroup, pk=group_pk, team=team)
    _run(request, lambda: delete_group(group, request.user), _('The group was deleted.'))
    return redirect('teams:team-detail', pk=team.pk)


@login_required
@require_http_methods(['GET', 'POST'])
def assign(request, pk: int):
    """
    Assign a program to the team, one of its groups or one of its athletes.
    """
    team = _coach_team(request, pk)
    form = AssignProgramForm(request.POST or None, team=team, user=request.user)
    if request.method == 'POST' and form.is_valid():
        try:
            assignment = assign_program(
                template=form.cleaned_data['template'],
                assigned_by=request.user,
                start_date=form.cleaned_data['start_date'],
                end_date=form.cleaned_data['end_date'],
                **form.target_kwargs(),
            )
        except ValidationError as exc:
            form.add_error(None, exc.messages)
        except PermissionDenied:
            form.add_error(None, _('You are not allowed to make this assignment.'))
        else:
            received = assignment.assigned_routines.count()
            messages.success(
                request,
                ngettext(
                    'The program was assigned, %(count)d athlete received a copy.',
                    'The program was assigned, %(count)d athletes received a copy.',
                    received,
                )
                % {'count': received},
            )
            return redirect('teams:assignment-detail', pk=assignment.pk)

    return render(request, 'teams/assign.html', {'team': team, 'form': form})


def _coach_assignment(request, pk: int) -> ProgramAssignment:
    """
    The assignment if the user is a coach for it, 404 otherwise.
    """
    assignment = get_object_or_404(
        ProgramAssignment.objects.select_related(
            'team', 'group', 'athlete', 'template', 'assigned_by'
        ),
        pk=pk,
    )
    if not is_assignment_coach(request.user, assignment):
        raise Http404
    return assignment


@login_required
@require_GET
def assignment_detail(request, pk: int):
    """
    Who received the assignment and who trained with it.
    """
    assignment = _coach_assignment(request, pk)
    progress = assignment_progress(assignment)
    context = {
        'assignment': assignment,
        'progress': progress,
        'trained': sum(1 for row in progress if row['logs']),
    }
    return render(request, 'teams/assignment_detail.html', context)


@login_required
@require_POST
def assignment_archive(request, pk: int):
    assignment = _coach_assignment(request, pk)
    _run(
        request,
        lambda: archive_assignment(assignment),
        _('The assignment was withdrawn. The athletes keep their programs and logs.'),
    )
    return redirect('teams:assignment-detail', pk=assignment.pk)
