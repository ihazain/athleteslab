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
from django.shortcuts import (
    get_object_or_404,
    redirect,
    render,
)
from django.utils.translation import gettext as _
from django.views.decorators.http import (
    require_GET,
    require_POST,
)

# wger
from wger.teams.models import (
    Team,
    TeamMembership,
)
from wger.teams.services import (
    change_member_role,
    create_team,
    find_user,
    invite_member,
    remove_member,
)


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
    context = {
        'team': team,
        'memberships': memberships,
        'roles': TeamMembership.Role,
    }
    return render(request, 'teams/team_detail.html', context)


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
        _('The team was deleted. The athletes keep their routines and logs.'),
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
