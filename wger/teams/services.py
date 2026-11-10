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
from django.db.models import Count, Max
from django.utils import timezone

# wger
from wger.manager.models import WorkoutLog
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


def assign_program(
    *,
    template,
    assigned_by,
    start_date,
    end_date,
    team=None,
    group=None,
    athlete=None,
):
    """
    Assign a routine template to one or more athletes.

    Exactly one of ``team``, ``group`` or ``athlete`` must be given.
    ``assigned_by`` must be a coach of the target team, of the team of the
    group, or a coach sharing a team with the target athlete. The whole
    assignment runs in a single transaction so it never ends up half-assigned.

    Returns the created ``ProgramAssignment`` instance.
    """
    if sum(target is not None for target in (team, group, athlete)) != 1:
        raise ValidationError('Exactly one of team, group or athlete must be set.')

    if group is not None:
        team = group.team

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
            memberships = group.members.all() if group is not None else team.memberships.all()
            athletes = [
                membership.user
                for membership in memberships.filter(
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

        # The same template may not run twice for an athlete in overlapping periods.
        # Archived assignments and copies the athlete deleted do not count.
        overlapping = AssignedRoutine.objects.filter(
            athlete__in=athletes,
            routine__isnull=False,
            assignment__archived_at__isnull=True,
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
            group=group,
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


def archive_assignment(assignment: ProgramAssignment) -> ProgramAssignment:
    """
    Withdraw an assignment. The copies and the logs of the athletes stay.
    """
    if assignment.archived_at is not None:
        raise ValidationError('This assignment is already archived.')

    assignment.archived_at = timezone.now()
    assignment.save(update_fields=['archived_at'])
    return assignment


def assignment_progress(assignment: ProgramAssignment) -> list[dict]:
    """
    One entry per athlete of the assignment: the copy and what was logged against it.
    """
    assigned_routines = list(
        assignment.assigned_routines.select_related('athlete').order_by('athlete__username')
    )
    stats = {
        row['routine']: row
        for row in WorkoutLog.objects.filter(
            routine__in=[a.routine_id for a in assigned_routines if a.routine_id],
        )
        .values('routine')
        .annotate(
            logs=Count('pk'),
            sessions=Count('session', distinct=True),
            last_activity=Max('date'),
        )
    }

    progress = []
    for assigned in assigned_routines:
        row = stats.get(assigned.routine_id, {})
        progress.append(
            {
                'athlete': assigned.athlete_id,
                'username': assigned.athlete.username,
                'routine': assigned.routine_id,
                'logs': row.get('logs', 0),
                'sessions': row.get('sessions', 0),
                'last_activity': row.get('last_activity'),
            }
        )
    return progress
