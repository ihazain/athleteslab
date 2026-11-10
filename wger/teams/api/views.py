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
import logging

# Django
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import models, transaction

# Third Party
from rest_framework import (
    exceptions,
    viewsets,
)

# wger
from wger.teams.api.permissions import IsAssignmentCoach, IsTeamCoach
from wger.teams.api.serializers import (
    ProgramAssignmentSerializer,
    TeamMembershipSerializer,
    TeamSerializer,
)
from wger.teams.models import (
    ProgramAssignment,
    Team,
    TeamMembership,
)


logger = logging.getLogger(__name__)


class TeamViewSet(viewsets.ModelViewSet):
    """
    API endpoint for team objects.

    Coaches see only teams they coach. Athletes see no teams through this
    endpoint (they see their memberships through the team-membership endpoint).
    """

    serializer_class = TeamSerializer
    permission_classes = [IsTeamCoach]
    ordering_fields = '__all__'
    filterset_fields = ('name', 'created')
    http_method_names = ['get', 'post', 'put', 'patch', 'delete']

    def get_queryset(self):
        if getattr(self, 'swagger_fake_view', False):
            return Team.objects.none()

        return Team.objects.filter(
            memberships__user=self.request.user,
            memberships__role=TeamMembership.Role.COACH,
        ).distinct()

    def perform_create(self, serializer):
        with transaction.atomic():
            team = serializer.save(created_by=self.request.user)
            TeamMembership.objects.create(
                team=team,
                user=self.request.user,
                role=TeamMembership.Role.COACH,
            )


class TeamMembershipViewSet(viewsets.ModelViewSet):
    """
    API endpoint for team membership objects.

    Only coaches of a team can manage its memberships. The last coach of a
    team cannot remove themselves.
    """

    serializer_class = TeamMembershipSerializer
    permission_classes = [IsTeamCoach]
    ordering_fields = '__all__'
    filterset_fields = ('team', 'user', 'role')
    http_method_names = ['get', 'post', 'put', 'patch', 'delete']

    def get_queryset(self):
        if getattr(self, 'swagger_fake_view', False):
            return TeamMembership.objects.none()

        return TeamMembership.objects.filter(
            team__memberships__user=self.request.user,
            team__memberships__role=TeamMembership.Role.COACH,
        ).distinct()

    def perform_create(self, serializer):
        team = serializer.validated_data.get('team')
        if not TeamMembership.objects.filter(
            team=team,
            user=self.request.user,
            role=TeamMembership.Role.COACH,
        ).exists():
            raise exceptions.PermissionDenied('Only a coach of this team can add memberships.')
        serializer.save()

    def perform_destroy(self, instance):
        team = instance.team
        if (
            instance.role == TeamMembership.Role.COACH
            and TeamMembership.objects.filter(
                team=team,
                role=TeamMembership.Role.COACH,
            ).count()
            <= 1
        ):
            raise exceptions.ValidationError('The last coach of a team cannot be removed.')
        super().perform_destroy(instance)


class ProgramAssignmentViewSet(viewsets.ModelViewSet):
    """
    API endpoint for program assignment objects.

    Creation calls ``assign_program`` which deep-copies the template for each
    athlete inside a transaction. Assignments are create-only: PUT/PATCH/
    DELETE are not allowed because copies already exist that athletes may
    have logged against.
    """

    serializer_class = ProgramAssignmentSerializer
    permission_classes = [IsAssignmentCoach]
    ordering_fields = '__all__'
    filterset_fields = ('template', 'team', 'athlete', 'assigned_by')
    http_method_names = ['get', 'post']

    def get_queryset(self):
        if getattr(self, 'swagger_fake_view', False):
            return ProgramAssignment.objects.none()

        user = self.request.user

        # Coaches see assignments for teams they coach, or assignments where
        # they coach the athlete through a shared team.
        # Athletes see only their own assignments.
        return ProgramAssignment.objects.filter(
            models.Q(
                team__memberships__user=user,
                team__memberships__role=TeamMembership.Role.COACH,
            )
            | models.Q(athlete=user)
        ).distinct()

    def perform_create(self, serializer):
        try:
            serializer.save(assigned_by=self.request.user)
        except DjangoValidationError as exc:
            raise exceptions.ValidationError(
                detail=exc.messages if hasattr(exc, 'messages') else [str(exc)]
            )
