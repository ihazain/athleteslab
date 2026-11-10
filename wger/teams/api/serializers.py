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
from rest_framework import serializers

# wger
from wger.teams.models import (
    AssignedRoutine,
    ProgramAssignment,
    Team,
    TeamMembership,
)


class TeamSerializer(serializers.ModelSerializer):
    """
    Serializer for Team objects.
    """

    class Meta:
        model = Team
        fields = ('id', 'name', 'created_by', 'created')
        read_only_fields = ('created_by', 'created')


class TeamMembershipSerializer(serializers.ModelSerializer):
    """
    Serializer for TeamMembership objects.
    """

    class Meta:
        model = TeamMembership
        fields = ('id', 'team', 'user', 'role')

    def validate(self, attrs):
        if self.instance is not None:
            for field in ('team', 'user'):
                if field in attrs and attrs[field] != getattr(self.instance, field):
                    raise serializers.ValidationError({field: 'This field cannot be changed.'})
        return attrs


class ProgramAssignmentSerializer(serializers.ModelSerializer):
    """
    Serializer for ProgramAssignment objects.

    The ``team`` and ``athlete`` fields are mutually exclusive: exactly one
    must be set. The actual assignment logic (deep copy, transaction, audit
    log) lives in ``wger.teams.services.assign_program``; this serializer only
    validates the input and delegates to it.
    """

    class Meta:
        model = ProgramAssignment
        fields = (
            'id',
            'template',
            'team',
            'athlete',
            'start_date',
            'end_date',
            'assigned_by',
            'created',
        )
        read_only_fields = ('assigned_by', 'created')

    def validate(self, attrs):
        team = attrs.get('team')
        athlete = attrs.get('athlete')

        if (team is None) == (athlete is None):
            raise serializers.ValidationError('Exactly one of team or athlete must be set.')

        if attrs.get('start_date') > attrs.get('end_date'):
            raise serializers.ValidationError('start_date must not be after end_date.')

        return attrs

    def create(self, validated_data):
        assigned_by = validated_data.pop('assigned_by', None)
        if assigned_by is None:
            assigned_by = self.context['request'].user

        # wger
        from wger.teams.services import assign_program

        return assign_program(
            template=validated_data['template'],
            assigned_by=assigned_by,
            start_date=validated_data['start_date'],
            end_date=validated_data['end_date'],
            team=validated_data.get('team'),
            athlete=validated_data.get('athlete'),
        )


class AssignedRoutineSerializer(serializers.ModelSerializer):
    """
    Serializer for AssignedRoutine objects (read-only).
    """

    class Meta:
        model = AssignedRoutine
        fields = ('id', 'assignment', 'athlete', 'routine')
        read_only_fields = fields
