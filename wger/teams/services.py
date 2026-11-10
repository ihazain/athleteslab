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
import copy
import logging

# Django
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction

# wger
from wger.teams.models import (
    AssignedRoutine,
    ProgramAssignment,
    TeamMembership,
)


logger = logging.getLogger(__name__)


def copy_routine(template, owner, start, end):
    """
    Deep-copy a routine template for a given athlete.

    Copies days, slots, slot entries and all change configs (weight,
    repetitions, RiR, rest, sets, and their max variants). The copy is
    always a private, non-template routine owned by ``owner``.
    """

    def copy_config(configs, slot_entry):
        for config in configs:
            config_copy = copy.copy(config)
            config_copy.pk = None
            config_copy.slot_entry = slot_entry
            config_copy.save()

    routine_copy = copy.copy(template)
    routine_copy.pk = None
    routine_copy.created = None
    routine_copy.user = owner
    routine_copy.is_template = False
    routine_copy.is_public = False
    routine_copy.start = start
    routine_copy.end = end
    routine_copy.save()

    for day in template.days.all():
        day_copy = copy.copy(day)
        day_copy.pk = None
        day_copy.routine = routine_copy
        day_copy.save()

        for current_slot in day.slots.all():
            slot_copy = copy.copy(current_slot)
            slot_copy.pk = None
            slot_copy.day = day_copy
            slot_copy.save()

            for current_entry in current_slot.entries.all():
                slot_entry_copy = copy.copy(current_entry)
                slot_entry_copy.pk = None
                slot_entry_copy.slot = slot_copy
                slot_entry_copy.save()

                copy_config(current_entry.weightconfig_set.all(), slot_entry_copy)
                copy_config(current_entry.maxweightconfig_set.all(), slot_entry_copy)
                copy_config(current_entry.repetitionsconfig_set.all(), slot_entry_copy)
                copy_config(
                    current_entry.maxrepetitionsconfig_set.all(),
                    slot_entry_copy,
                )
                copy_config(current_entry.rirconfig_set.all(), slot_entry_copy)
                copy_config(current_entry.maxrirconfig_set.all(), slot_entry_copy)
                copy_config(current_entry.restconfig_set.all(), slot_entry_copy)
                copy_config(current_entry.maxrestconfig_set.all(), slot_entry_copy)
                copy_config(current_entry.setsconfig_set.all(), slot_entry_copy)
                copy_config(current_entry.maxsetsconfig_set.all(), slot_entry_copy)

    for label in template.labels.all():
        label_copy = copy.copy(label)
        label_copy.pk = None
        label_copy.routine = routine_copy
        label_copy.save()

    return routine_copy


def _can_use_template(user, template):
    """
    A template may be used if it belongs to the user, or if it is a public
    template.
    """
    return template.user_id == user.pk or (template.is_template and template.is_public)


def assign_program(*, template, assigned_by, start_date, end_date, team=None, athlete=None):
    """
    Assign a routine template to one or more athletes.

    Exactly one of ``team`` or ``athlete`` must be given. ``assigned_by`` must
    be a coach of the target team (or a coach sharing a team with the target
    athlete). The whole assignment runs in a single transaction so it never
    ends up half-assigned.

    Returns the created ``ProgramAssignment`` instance.
    """
    if (team is None) == (athlete is None):
        raise ValidationError('Exactly one of team or athlete must be set.')

    if start_date > end_date:
        raise ValidationError('start_date must not be after end_date.')

    with transaction.atomic():
        if not _can_use_template(assigned_by, template):
            raise PermissionDenied('assigned_by may not use this template.')

        # Resolve the target athletes and check coach permission
        if team is not None:
            if not TeamMembership.objects.filter(
                team=team,
                user=assigned_by,
                role=TeamMembership.Role.COACH,
                status=TeamMembership.Status.ACTIVE,
            ).exists():
                raise PermissionDenied('assigned_by is not a coach of this team.')
            athletes = [
                membership.user
                for membership in TeamMembership.objects.filter(
                    team=team,
                    role=TeamMembership.Role.ATHLETE,
                    status=TeamMembership.Status.ACTIVE,
                ).select_related('user')
            ]
        else:
            if not TeamMembership.objects.filter(
                user=assigned_by,
                role=TeamMembership.Role.COACH,
                status=TeamMembership.Status.ACTIVE,
                team__memberships__user=athlete,
                team__memberships__role=TeamMembership.Role.ATHLETE,
                team__memberships__status=TeamMembership.Status.ACTIVE,
            ).exists():
                raise PermissionDenied('assigned_by is not a coach of this athlete.')
            athletes = [athlete]

        if not athletes:
            raise ValidationError('No athletes found for the given target.')

        # The same template may not run twice for an athlete in overlapping periods
        overlapping = AssignedRoutine.objects.filter(
            athlete__in=athletes,
            assignment__template=template,
            assignment__start_date__lte=end_date,
            assignment__end_date__gte=start_date,
        ).select_related('athlete')
        if overlapping:
            names = ', '.join(sorted({assigned.athlete.username for assigned in overlapping}))
            raise ValidationError(
                f'This template is already assigned for an overlapping period to: {names}'
            )

        assignment = ProgramAssignment.objects.create(
            template=template,
            team=team,
            athlete=athlete,
            start_date=start_date,
            end_date=end_date,
            assigned_by=assigned_by,
        )

        for athlete_user in athletes:
            routine_copy = copy_routine(
                template,
                owner=athlete_user,
                start=start_date,
                end=end_date,
            )
            AssignedRoutine.objects.create(
                assignment=assignment,
                athlete=athlete_user,
                routine=routine_copy,
            )

    return assignment
