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

# Third Party
from rest_framework import permissions

# wger
from wger.teams.models import Team, TeamMembership


class IsTeamCoach(permissions.BasePermission):
    """
    Allows access to members of a team for safe methods, and to coaches for
    write methods.

    Used for Team and TeamMembership objects. Foreign objects yield 404
    (via queryset filtering), not 403, so their existence is not leaked.
    """

    def has_permission(self, request, view):
        return request.user and request.user.is_authenticated

    def has_object_permission(self, request, view, obj):
        if isinstance(obj, Team):
            team = obj
        elif isinstance(obj, TeamMembership):
            team = obj.team
        else:
            return False

        if request.method in permissions.SAFE_METHODS:
            # Any member can read
            return TeamMembership.objects.filter(team=team, user=request.user).exists()

        # Only coaches can write
        return TeamMembership.objects.filter(
            team=team,
            user=request.user,
            role=TeamMembership.Role.COACH,
        ).exists()


class IsAssignmentCoach(permissions.BasePermission):
    """
    Allows access only to coaches who can use the assignment's template.

    Used for ProgramAssignment objects. The assignment's team (or the team
    shared with the athlete) determines whether the requesting user is a
    coach.
    """

    def has_permission(self, request, view):
        return request.user and request.user.is_authenticated

    def has_object_permission(self, request, view, obj):
        assignment = obj

        if assignment.team is not None:
            return TeamMembership.objects.filter(
                team=assignment.team,
                user=request.user,
                role=TeamMembership.Role.COACH,
            ).exists()

        # Single-athlete assignment: requesting user must be a coach sharing
        # a team with the athlete.
        return TeamMembership.objects.filter(
            user=request.user,
            role=TeamMembership.Role.COACH,
            team__memberships__user=assignment.athlete,
            team__memberships__role=TeamMembership.Role.ATHLETE,
        ).exists()
