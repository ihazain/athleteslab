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
from drf_spectacular.utils import extend_schema
from rest_framework import (
    exceptions,
    status,
    viewsets,
)
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

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

    Members see teams they belong to. Coaches can modify them.
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
        ).distinct()

    def perform_create(self, serializer):
        with transaction.atomic():
            team = serializer.save(created_by=self.request.user)
            TeamMembership.objects.create(
                team=team,
                user=self.request.user,
                role=TeamMembership.Role.COACH,
                status=TeamMembership.Status.ACTIVE,
            )


class TeamMembershipViewSet(viewsets.ModelViewSet):
    """
    API endpoint for team membership objects.

    Only coaches of a team can manage its memberships. A new membership is an
    invitation that only the invited user can accept or decline. The last
    active coach of a team cannot be removed or demoted.
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
            models.Q(user=self.request.user)
            | models.Q(
                team__memberships__user=self.request.user,
                team__memberships__role=TeamMembership.Role.COACH,
                team__memberships__status=TeamMembership.Status.ACTIVE,
            )
        ).distinct()

    def perform_create(self, serializer):
        team = serializer.validated_data.get('team')
        if not TeamMembership.objects.filter(
            team=team,
            user=self.request.user,
            role=TeamMembership.Role.COACH,
            status=TeamMembership.Status.ACTIVE,
        ).exists():
            raise exceptions.PermissionDenied('Only a coach of this team can add memberships.')
        serializer.save(status=TeamMembership.Status.INVITED)

    def perform_update(self, serializer):
        instance = serializer.instance
        new_role = serializer.validated_data.get('role', instance.role)
        if self._is_last_active_coach(instance) and new_role != TeamMembership.Role.COACH:
            raise exceptions.ValidationError('A team needs at least one coach.')
        serializer.save()

    def perform_destroy(self, instance):
        if self._is_last_active_coach(instance):
            raise exceptions.ValidationError('The last coach of a team cannot be removed.')
        super().perform_destroy(instance)

    @staticmethod
    def _is_last_active_coach(membership: TeamMembership) -> bool:
        if (
            membership.role != TeamMembership.Role.COACH
            or membership.status != TeamMembership.Status.ACTIVE
        ):
            return False
        return (
            not TeamMembership.objects.filter(
                team=membership.team,
                role=TeamMembership.Role.COACH,
                status=TeamMembership.Status.ACTIVE,
            )
            .exclude(pk=membership.pk)
            .exists()
        )

    def _get_own_invitation(self) -> TeamMembership:
        """
        Returns the open invitation of the requesting user, coaches cannot answer for others.
        """
        membership = self.get_object()
        if membership.user_id != self.request.user.pk:
            raise exceptions.PermissionDenied('Only the invited user can answer an invitation.')
        if membership.status != TeamMembership.Status.INVITED:
            raise exceptions.ValidationError('This membership is not an open invitation.')
        return membership

    @extend_schema(request=None, responses=TeamMembershipSerializer)
    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated])
    def accept(self, request, pk=None):
        """
        Accept the invitation, the membership becomes active.
        """
        membership = self._get_own_invitation()
        membership.status = TeamMembership.Status.ACTIVE
        membership.save(update_fields=['status'])
        return Response(self.get_serializer(membership).data)

    @extend_schema(request=None, responses={204: None})
    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated])
    def decline(self, request, pk=None):
        """
        Decline the invitation, the membership is removed.
        """
        self._get_own_invitation().delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


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

        # Active members see the assignments of their teams. Assignments to a
        # single athlete are visible to that athlete and to their coaches.
        coached_athletes = TeamMembership.objects.filter(
            role=TeamMembership.Role.ATHLETE,
            status=TeamMembership.Status.ACTIVE,
            team__in=TeamMembership.objects.filter(
                user=user,
                role=TeamMembership.Role.COACH,
                status=TeamMembership.Status.ACTIVE,
            ).values('team'),
        ).values('user')

        return ProgramAssignment.objects.filter(
            models.Q(athlete=user)
            | models.Q(athlete__in=coached_athletes)
            | models.Q(
                team__memberships__user=user,
                team__memberships__status=TeamMembership.Status.ACTIVE,
            )
        ).distinct()

    def perform_create(self, serializer):
        try:
            serializer.save(assigned_by=self.request.user)
        except DjangoValidationError as exc:
            raise exceptions.ValidationError(
                detail=exc.messages if hasattr(exc, 'messages') else [str(exc)]
            )
