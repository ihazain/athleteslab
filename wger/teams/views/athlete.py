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
from wger.teams.calendar import user_today
from wger.teams.models import (
    AssignedRoutine,
    TeamMembership,
)
from wger.teams.services import (
    accept_invitation,
    coach_dashboard,
    decline_invitation,
)


@login_required
@require_GET
def overview(request):
    """
    The teams page of a user: open invitations, teams and assigned programs.
    """
    memberships = TeamMembership.objects.filter(user=request.user).select_related('team')
    programs = (
        AssignedRoutine.objects.filter(athlete=request.user)
        .select_related(
            'routine',
            'assignment__template',
            'assignment__team',
            'assignment__group',
            'assignment__assigned_by',
        )
        .order_by('-assignment__start_date', '-pk')
    )
    context = {
        'invitations': memberships.filter(status=TeamMembership.Status.INVITED),
        'memberships': memberships.filter(status=TeamMembership.Status.ACTIVE),
        'programs': programs,
        'dashboard': coach_dashboard(request.user, user_today(request.user)),
    }
    return render(request, 'teams/overview.html', context)


def _answer_invitation(request, pk: int, answer, success: str):
    """
    Lets the user answer an own invitation and returns to the teams page.
    """
    membership = get_object_or_404(TeamMembership, pk=pk, user=request.user)
    team = membership.team
    try:
        answer(membership, request.user)
    except ValidationError as exc:
        messages.error(request, ' '.join(exc.messages))
    else:
        messages.success(request, success % {'team': team.name})
    return redirect('teams:overview')


@login_required
@require_POST
def invitation_accept(request, pk: int):
    return _answer_invitation(
        request,
        pk,
        accept_invitation,
        _('You are now a member of %(team)s.'),
    )


@login_required
@require_POST
def invitation_decline(request, pk: int):
    return _answer_invitation(
        request,
        pk,
        decline_invitation,
        _('You declined the invitation to %(team)s.'),
    )
