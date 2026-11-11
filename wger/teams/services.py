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
import datetime
import logging

# Django
from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Count, Max
from django.utils import timezone
from django.utils.translation import gettext as _

# wger
from wger.manager.helpers import reset_routine_cache
from wger.manager.models import (
    Day,
    MaxRepetitionsConfig,
    MaxRestConfig,
    MaxRiRConfig,
    MaxSetsConfig,
    MaxWeightConfig,
    RepetitionsConfig,
    RestConfig,
    RiRConfig,
    Routine,
    SetsConfig,
    Slot,
    SlotEntry,
    WeightConfig,
    WorkoutLog,
)
from wger.teams.models import (
    AssignedRoutine,
    ProgramAssignment,
    Team,
    TeamGroup,
    TeamMembership,
)


logger = logging.getLogger(__name__)


CONFIG_MODELS = (
    WeightConfig,
    MaxWeightConfig,
    RepetitionsConfig,
    MaxRepetitionsConfig,
    RiRConfig,
    MaxRiRConfig,
    RestConfig,
    MaxRestConfig,
    SetsConfig,
    MaxSetsConfig,
)


def _copy_rows(rows, parent_field: str, parent_copies: dict, prepare=None) -> dict:
    """
    Copies the rows below the copies of their parents with a single insert.

    Returns the copies by the pk of their original. bulk_create sends no
    signals: saving row by row resets the routine cache for every row, which
    walks the whole routine each time. ``prepare(copy, index)`` can change a
    copy before it is written.
    """
    originals = list(rows)
    copies = []
    for index, row in enumerate(originals):
        row_copy = copy.copy(row)
        row_copy.pk = None
        setattr(row_copy, parent_field, parent_copies[getattr(row, f'{parent_field}_id')])
        if prepare is not None:
            prepare(row_copy, index)
        copies.append(row_copy)

    if copies:
        type(copies[0]).objects.bulk_create(copies)
    return {row.pk: row_copy for row, row_copy in zip(originals, copies)}


def copy_days(days, routine, owner, first_order: int | None = None) -> None:
    """
    Copy training days with their slots, entries and configs into the routine.

    The days keep their order number, or are numbered from ``first_order`` on
    in the order given.
    """
    days = list(days)
    day_pks = [day.pk for day in days]

    def renumber(day_copy, index):
        if first_order is not None:
            day_copy.order = first_order + index

    day_copies = _copy_rows(days, 'routine', {day.routine_id: routine for day in days}, renumber)
    slots = _copy_rows(Slot.objects.filter(day__in=day_pks).order_by('pk'), 'day', day_copies)

    # Like SlotEntry.save() does for new entries, fall back to the rounding of the owner
    profile = owner.userprofile
    entries = SlotEntry.objects.filter(slot__day__in=day_pks).order_by('pk')
    entry_copies = _copy_rows(entries, 'slot', slots)
    SlotEntry.objects.filter(
        pk__in=[entry.pk for entry in entry_copies.values()],
        repetition_rounding__isnull=True,
    ).update(repetition_rounding=profile.repetitions_rounding)
    SlotEntry.objects.filter(
        pk__in=[entry.pk for entry in entry_copies.values()],
        weight_rounding__isnull=True,
    ).update(weight_rounding=profile.weight_rounding)

    for model in CONFIG_MODELS:
        configs = model.objects.filter(slot_entry__slot__day__in=day_pks).order_by('pk')
        _copy_rows(configs, 'slot_entry', entry_copies)


def copy_routine(template, owner, start, end):
    """
    Deep-copy a routine template for a given athlete.

    Copies days, slots, slot entries and all change configs (weight,
    repetitions, RiR, rest, sets, and their max variants). The copy is
    always a private, non-template routine owned by ``owner``.
    """
    routine_copy = copy.copy(template)
    routine_copy.pk = None
    routine_copy.created = None
    routine_copy.user = owner
    routine_copy.is_template = False
    routine_copy.is_public = False
    routine_copy.start = start
    routine_copy.end = end
    routine_copy.save()

    _copy_rows(template.labels.order_by('pk'), 'routine', {template.pk: routine_copy})
    copy_days(template.days.order_by('pk'), routine_copy, owner)

    return routine_copy


def _check_period(start_date: datetime.date, end_date: datetime.date) -> None:
    if start_date > end_date:
        raise ValidationError(_('The end date must not be before the start date.'))
    if (end_date - start_date).days > Routine.MAX_DURATION_DAYS:
        raise ValidationError(
            _('A program cannot be longer than %(days)d days.')
            % {'days': Routine.MAX_DURATION_DAYS}
        )


def create_program(
    *,
    user,
    name: str,
    start_date,
    end_date,
    plan=None,
    days=(),
    is_template: bool = False,
):
    """
    Create a program for the user from an existing plan, single routines (days) or both.

    The plan may be an own routine or a public template, the days must be the
    user's own. Everything is copied: the program starts with the days of the
    plan, followed by the chosen days in the order given. With ``is_template``
    the result is a plan (a reusable template) instead of a program.
    """
    _check_period(start_date, end_date)
    days = list(days)
    if plan is None and not days:
        raise ValidationError(_('Pick a plan or at least one routine.'))
    if plan is not None and not _can_use_template(user, plan):
        raise PermissionDenied('The user may not use this plan.')
    if any(day.routine.user_id != user.pk for day in days):
        raise PermissionDenied('The user may only use own routines.')

    with transaction.atomic():
        if plan is not None:
            program = copy_routine(plan, user, start_date, end_date)
            program.name = name
            program.is_template = is_template
            program.save(update_fields=['name', 'is_template'])
        else:
            program = Routine.objects.create(
                user=user,
                name=name,
                start=start_date,
                end=end_date,
                is_template=is_template,
            )

        if days:
            last = program.days.order_by('-order').values_list('order', flat=True).first() or 0
            copy_days(days, program, user, first_order=last + 1)

    return program


def default_period(user) -> tuple[datetime.date, datetime.date]:
    """
    Four weeks from today in the time zone of the user.
    """
    today = timezone.now().astimezone(user.userprofile.zone_info).date()
    return today, today + datetime.timedelta(days=27)


def create_plan(*, user, name: str, plan=None, days=()):
    """
    Create a plan (a reusable template) from an existing plan, single routines or both.
    """
    start_date, end_date = default_period(user)
    return create_program(
        user=user,
        name=name,
        start_date=start_date,
        end_date=end_date,
        plan=plan,
        days=days,
        is_template=True,
    )


def add_routine(*, user, name: str, program=None, source=None) -> Day:
    """
    Add a routine (a training day) to one of the user's programs.

    Without ``program`` a new four-week program with the name of the routine
    is created for it. With ``source`` the routine is a copy of that own
    routine, otherwise it is empty. Plans are frozen and cannot take routines.
    """
    if program is not None and (program.user_id != user.pk or program.is_template):
        raise PermissionDenied('The user may only add routines to own programs.')
    if source is not None and source.routine.user_id != user.pk:
        raise PermissionDenied('The user may only use own routines.')

    with transaction.atomic():
        if program is None:
            start_date, end_date = default_period(user)
            max_length = Routine._meta.get_field('name').max_length
            program = Routine.objects.create(
                user=user,
                name=name[:max_length],
                start=start_date,
                end=end_date,
            )

        last = program.days.order_by('-order').values_list('order', flat=True).first() or 0
        if source is not None:
            copy_days([source], program, user, first_order=last + 1)
            day = program.days.get(order=last + 1)
            day.name = name
            day.is_rest = False
            day.save(update_fields=['name', 'is_rest'])
        else:
            day = Day.objects.create(routine=program, order=last + 1, name=name)

    # The copy is written without signals, the cached schedule of the program is stale
    reset_routine_cache(program)
    return day


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

    _check_period(start_date, end_date)

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
            raise ValidationError(_('There are no active athletes in the selected target.'))

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
                _('This program is already assigned for an overlapping period to: %(names)s')
                % {'names': names}
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
        raise ValidationError(_('This assignment was already withdrawn.'))

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


def _own_open_invitation(membership: TeamMembership, user) -> None:
    if membership.user_id != user.pk:
        raise PermissionDenied('Only the invited user can answer an invitation.')
    if membership.status != TeamMembership.Status.INVITED:
        raise ValidationError(_('This is not an open invitation.'))


def accept_invitation(membership: TeamMembership, user) -> TeamMembership:
    """
    The invited user accepts, the membership becomes active.
    """
    _own_open_invitation(membership, user)
    membership.status = TeamMembership.Status.ACTIVE
    membership.save(update_fields=['status'])
    return membership


def decline_invitation(membership: TeamMembership, user) -> None:
    """
    The invited user declines, the membership is removed.
    """
    _own_open_invitation(membership, user)
    membership.delete()


def is_team_coach(user, team: Team) -> bool:
    """
    True if the user is an active coach of the team.
    """
    return TeamMembership.objects.filter(
        team=team,
        user=user,
        role=TeamMembership.Role.COACH,
        status=TeamMembership.Status.ACTIVE,
    ).exists()


def is_last_active_coach(membership: TeamMembership) -> bool:
    """
    True if the team would have no active coach without this membership.
    """
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


def _require_coach(user, team: Team) -> None:
    if not is_team_coach(user, team):
        raise PermissionDenied('Only a coach of this team can do this.')


def create_team(name: str, created_by) -> Team:
    """
    Create a team with its creator as the first active coach.
    """
    with transaction.atomic():
        team = Team.objects.create(name=name, created_by=created_by)
        TeamMembership.objects.create(
            team=team,
            user=created_by,
            role=TeamMembership.Role.COACH,
            status=TeamMembership.Status.ACTIVE,
        )
    return team


def find_user(identifier: str) -> User | None:
    """
    The active user with this username or e-mail address, ignoring case.
    """
    identifier = identifier.strip()
    if not identifier:
        return None

    users = User.objects.filter(is_active=True)
    return (
        users.filter(username__iexact=identifier).first()
        or users.filter(email__iexact=identifier).order_by('pk').first()
    )


def invite_member(team: Team, invited_by, user, role: str) -> TeamMembership:
    """
    Invite a user into the team. The user has to accept before the membership counts.
    """
    _require_coach(invited_by, team)
    if role not in TeamMembership.Role.values:
        raise ValidationError(_('Please select a valid role.'))

    membership, created = TeamMembership.objects.get_or_create(
        team=team,
        user=user,
        defaults={'role': role, 'status': TeamMembership.Status.INVITED},
    )
    if not created:
        raise ValidationError(_('This user is already a member of the team or invited to it.'))
    return membership


def change_member_role(membership: TeamMembership, changed_by, role: str) -> TeamMembership:
    """
    Change the role of a member. The last active coach stays coach.
    """
    _require_coach(changed_by, membership.team)
    if role not in TeamMembership.Role.values:
        raise ValidationError(_('Please select a valid role.'))
    if role != TeamMembership.Role.COACH and is_last_active_coach(membership):
        raise ValidationError(_('A team needs at least one coach.'))

    membership.role = role
    membership.save(update_fields=['role'])
    return membership


def remove_member(membership: TeamMembership, removed_by) -> None:
    """
    Remove a member or withdraw an invitation. The last active coach stays.
    """
    _require_coach(removed_by, membership.team)
    if is_last_active_coach(membership):
        raise ValidationError(_('The last coach of a team cannot be removed.'))
    membership.delete()


def is_assignment_coach(user, assignment: ProgramAssignment) -> bool:
    """
    True for an active coach of the assignment's team, or of a team of its athlete.
    """
    if assignment.team is not None:
        return is_team_coach(user, assignment.team)

    return TeamMembership.objects.filter(
        user=user,
        role=TeamMembership.Role.COACH,
        status=TeamMembership.Status.ACTIVE,
        team__memberships__user=assignment.athlete,
        team__memberships__role=TeamMembership.Role.ATHLETE,
        team__memberships__status=TeamMembership.Status.ACTIVE,
    ).exists()


def active_athletes(memberships):
    """
    The memberships that receive a copy when a program is assigned.
    """
    return memberships.filter(
        role=TeamMembership.Role.ATHLETE,
        status=TeamMembership.Status.ACTIVE,
    )


def _check_group(team: Team, user, name: str, memberships, group: TeamGroup | None) -> None:
    _require_coach(user, team)
    if any(membership.team_id != team.pk for membership in memberships):
        raise ValidationError(_('All members must belong to the team of the group.'))

    same_name = TeamGroup.objects.filter(team=team, name=name)
    if group is not None:
        same_name = same_name.exclude(pk=group.pk)
    if same_name.exists():
        raise ValidationError(_('The team already has a group with this name.'))


def create_group(team: Team, user, name: str, memberships) -> TeamGroup:
    """
    Create a group of the team with the given memberships.
    """
    _check_group(team, user, name, memberships, None)
    with transaction.atomic():
        group = TeamGroup.objects.create(team=team, name=name)
        group.members.set(memberships)
    return group


def update_group(group: TeamGroup, user, name: str, memberships) -> TeamGroup:
    """
    Rename a group and replace its members.
    """
    _check_group(group.team, user, name, memberships, group)
    with transaction.atomic():
        group.name = name
        group.save(update_fields=['name'])
        group.members.set(memberships)
    return group


def delete_group(group: TeamGroup, user) -> None:
    """
    Delete a group. Its assignments and their copies stay.
    """
    _require_coach(user, group.team)
    group.delete()


def coach_dashboard(user, today: datetime.date) -> dict:
    """
    Numbers for the teams the user coaches: athletes, open invitations, running
    assignments and how many athletes logged training for them in the last seven days.
    """
    since = timezone.now() - datetime.timedelta(days=7)
    teams = []
    athletes = set()
    for team in Team.objects.filter(
        memberships__user=user,
        memberships__role=TeamMembership.Role.COACH,
        memberships__status=TeamMembership.Status.ACTIVE,
    ).order_by('name', 'pk'):
        members = set(active_athletes(team.memberships).values_list('user', flat=True))
        athletes |= members
        teams.append(
            {
                'team': team,
                'athletes': len(members),
                'invited': team.memberships.filter(status=TeamMembership.Status.INVITED).count(),
                'running': ProgramAssignment.objects.filter(
                    team=team,
                    archived_at__isnull=True,
                    start_date__lte=today,
                    end_date__gte=today,
                ).count(),
                'trained': WorkoutLog.objects.filter(
                    routine__assignedroutine__assignment__team=team,
                    user__in=members,
                    date__gte=since,
                )
                .values('user')
                .distinct()
                .count(),
            }
        )

    return {
        'teams': teams,
        'athletes': len(athletes),
        'invited': sum(entry['invited'] for entry in teams),
        'running': sum(entry['running'] for entry in teams),
    }
