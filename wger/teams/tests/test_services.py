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
from unittest import mock

# Django
from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection
from django.forms.models import model_to_dict
from django.test.utils import CaptureQueriesContext

# wger
from wger.core.models import RepetitionUnit, WeightUnit
from wger.core.tests.base_testcase import WgerTestCase
from wger.manager.models import (
    Day,
    Label,
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
)
from wger.teams.models import (
    AssignedRoutine,
    ProgramAssignment,
    Team,
    TeamGroup,
    TeamMembership,
)
from wger.teams.services import (
    add_routine,
    assign_program,
    copy_routine,
    create_plan,
    create_program,
)


class AssignProgramTestCase(WgerTestCase):
    """
    Tests for the assign_program service function.
    """

    def setUp(self):
        super().setUp()

        # The coach who assigns programs
        self.coach = User.objects.create_user(username='coach', email='coach@example.com')

        # Athletes
        self.athlete1 = User.objects.create_user(username='athlete1', email='athlete1@example.com')
        self.athlete2 = User.objects.create_user(username='athlete2', email='athlete2@example.com')
        self.athlete3 = User.objects.create_user(username='athlete3', email='athlete3@example.com')

        # Another coach (not a member of the team)
        self.other_coach = User.objects.create_user(
            username='othercoach', email='othercoach@example.com'
        )

        # A team with the coach and three athletes
        self.team = Team.objects.create(name='Test Team', created_by=self.coach)
        TeamMembership.objects.create(
            team=self.team,
            user=self.coach,
            role=TeamMembership.Role.COACH,
            status=TeamMembership.Status.ACTIVE,
        )
        TeamMembership.objects.create(
            team=self.team,
            user=self.athlete1,
            role=TeamMembership.Role.ATHLETE,
            status=TeamMembership.Status.ACTIVE,
        )
        TeamMembership.objects.create(
            team=self.team,
            user=self.athlete2,
            role=TeamMembership.Role.ATHLETE,
            status=TeamMembership.Status.ACTIVE,
        )
        TeamMembership.objects.create(
            team=self.team,
            user=self.athlete3,
            role=TeamMembership.Role.ATHLETE,
            status=TeamMembership.Status.ACTIVE,
        )

        # Another team where the other coach is coach and athlete1 is athlete
        self.other_team = Team.objects.create(name='Other Team', created_by=self.other_coach)
        TeamMembership.objects.create(
            team=self.other_team,
            user=self.other_coach,
            role=TeamMembership.Role.COACH,
            status=TeamMembership.Status.ACTIVE,
        )
        TeamMembership.objects.create(
            team=self.other_team,
            user=self.athlete1,
            role=TeamMembership.Role.ATHLETE,
            status=TeamMembership.Status.ACTIVE,
        )

        # A template routine owned by the coach, with one day, slot, entry,
        # config and label

        weight_unit = WeightUnit.objects.first()
        rep_unit = RepetitionUnit.objects.first()

        self.template = Routine.objects.create(
            user=self.coach,
            name='Test template',
            is_template=True,
            is_public=False,
            start=datetime.date(2026, 11, 1),
            end=datetime.date(2026, 11, 30),
        )

        day = Day.objects.create(
            routine=self.template,
            order=1,
            name='Day 1',
        )

        slot = Slot.objects.create(day=day, order=1)

        entry = SlotEntry.objects.create(
            slot=slot,
            exercise_id=1,
            repetition_unit=rep_unit,
            weight_unit=weight_unit,
            order=1,
        )

        WeightConfig.objects.create(slot_entry=entry, iteration=1, value=10.00)
        RepetitionsConfig.objects.create(slot_entry=entry, iteration=1, value=10.00)
        SetsConfig.objects.create(slot_entry=entry, iteration=1, value=3.00)
        RestConfig.objects.create(slot_entry=entry, iteration=1, value=60.00)
        RiRConfig.objects.create(slot_entry=entry, iteration=1, value=2.00)

        Label.objects.create(
            routine=self.template,
            start_offset=1,
            end_offset=7,
            label='Week 1',
        )

        self.start_date = datetime.date(2026, 11, 10)
        self.end_date = datetime.date(2026, 12, 10)

    def test_assign_to_single_athlete(self):
        """
        A coach can assign a template to a single athlete.
        """
        assignment = assign_program(
            template=self.template,
            assigned_by=self.coach,
            start_date=self.start_date,
            end_date=self.end_date,
            athlete=self.athlete1,
        )

        self.assertIsInstance(assignment, ProgramAssignment)
        self.assertEqual(assignment.athlete, self.athlete1)
        self.assertIsNone(assignment.team)
        self.assertEqual(assignment.assigned_by, self.coach)

        assigned = AssignedRoutine.objects.get(assignment=assignment, athlete=self.athlete1)
        self.assertEqual(assigned.athlete, self.athlete1)
        self.assertIsNotNone(assigned.routine)
        self.assertNotEqual(assigned.routine.pk, self.template.pk)

    def test_assign_to_team_with_three_athletes(self):
        """
        A coach can assign a template to all athletes of a team.
        """
        assignment = assign_program(
            template=self.template,
            assigned_by=self.coach,
            start_date=self.start_date,
            end_date=self.end_date,
            team=self.team,
        )

        self.assertIsInstance(assignment, ProgramAssignment)
        self.assertEqual(assignment.team, self.team)
        self.assertIsNone(assignment.athlete)

        assigned = AssignedRoutine.objects.filter(assignment=assignment)
        self.assertEqual(assigned.count(), 3)
        athletes = {a.athlete for a in assigned}
        self.assertEqual(athletes, {self.athlete1, self.athlete2, self.athlete3})

        for a in assigned:
            self.assertNotEqual(a.routine.pk, self.template.pk)

    def test_assign_neither_team_nor_athlete(self):
        """
        Assigning without a target raises ValidationError.
        """
        with self.assertRaises(ValidationError):
            assign_program(
                template=self.template,
                assigned_by=self.coach,
                start_date=self.start_date,
                end_date=self.end_date,
            )

    def test_assign_both_team_and_athlete(self):
        """
        Assigning with both team and athlete raises ValidationError.
        """
        with self.assertRaises(ValidationError):
            assign_program(
                template=self.template,
                assigned_by=self.coach,
                start_date=self.start_date,
                end_date=self.end_date,
                team=self.team,
                athlete=self.athlete1,
            )

    def test_start_date_after_end_date(self):
        """
        A start date after the end date raises ValidationError.
        """
        with self.assertRaises(ValidationError):
            assign_program(
                template=self.template,
                assigned_by=self.coach,
                start_date=self.end_date,
                end_date=self.start_date,
                athlete=self.athlete1,
            )

    def test_assign_to_empty_team(self):
        """
        A team without athletes raises ValidationError.
        """
        empty_team = Team.objects.create(name='Empty Team', created_by=self.coach)
        TeamMembership.objects.create(
            team=empty_team,
            user=self.coach,
            role=TeamMembership.Role.COACH,
            status=TeamMembership.Status.ACTIVE,
        )

        with self.assertRaises(ValidationError):
            assign_program(
                template=self.template,
                assigned_by=self.coach,
                start_date=self.start_date,
                end_date=self.end_date,
                team=empty_team,
            )

    def test_atomicity_on_copy_failure(self):
        """
        If copying fails for the second athlete, nothing is persisted.
        """
        routine_count_before = Routine.objects.count()
        assignment_count_before = ProgramAssignment.objects.count()
        assigned_count_before = AssignedRoutine.objects.count()

        # First call uses the real copy_routine, the second raises
        calls = []

        def failing_copy_routine(template, owner, start, end):
            calls.append(owner)
            if len(calls) > 1:
                raise RuntimeError('Copy failed')

            return copy_routine(template, owner, start, end)

        with mock.patch('wger.teams.services.copy_routine', side_effect=failing_copy_routine):
            with self.assertRaises(RuntimeError):
                assign_program(
                    template=self.template,
                    assigned_by=self.coach,
                    start_date=self.start_date,
                    end_date=self.end_date,
                    team=self.team,
                )

        # Nothing may have been persisted
        self.assertEqual(Routine.objects.count(), routine_count_before)
        self.assertEqual(ProgramAssignment.objects.count(), assignment_count_before)
        self.assertEqual(AssignedRoutine.objects.count(), assigned_count_before)

    def test_deep_copy_has_no_shared_rows(self):
        """
        The copy has the same structure as the template but no shared rows.
        """
        assignment = assign_program(
            template=self.template,
            assigned_by=self.coach,
            start_date=self.start_date,
            end_date=self.end_date,
            athlete=self.athlete1,
        )
        copy = AssignedRoutine.objects.get(assignment=assignment, athlete=self.athlete1).routine

        # Same counts
        self.assertEqual(copy.days.count(), self.template.days.count())
        self.assertEqual(copy.labels.count(), self.template.labels.count())

        for day_orig, day_copy in zip(self.template.days.all(), copy.days.all()):
            self.assertNotEqual(day_copy.pk, day_orig.pk)
            self.assertEqual(day_copy.routine_id, copy.pk)
            self.assertEqual(day_copy.slots.count(), day_orig.slots.count())
            for slot_orig, slot_copy in zip(day_orig.slots.all(), day_copy.slots.all()):
                self.assertNotEqual(slot_copy.pk, slot_orig.pk)
                self.assertEqual(slot_copy.entries.count(), slot_orig.entries.count())
                for entry_orig, entry_copy in zip(slot_orig.entries.all(), slot_copy.entries.all()):
                    self.assertNotEqual(entry_copy.pk, entry_orig.pk)
                    for config_type in (
                        'weightconfig_set',
                        'repetitionsconfig_set',
                        'rirconfig_set',
                        'restconfig_set',
                        'setsconfig_set',
                        'maxweightconfig_set',
                        'maxrepetitionsconfig_set',
                        'maxrirconfig_set',
                        'maxrestconfig_set',
                        'maxsetsconfig_set',
                    ):
                        self.assertEqual(
                            getattr(entry_copy, config_type).count(),
                            getattr(entry_orig, config_type).count(),
                        )
                        for cfg_orig, cfg_copy in zip(
                            getattr(entry_orig, config_type).all(),
                            getattr(entry_copy, config_type).all(),
                        ):
                            self.assertNotEqual(cfg_copy.pk, cfg_orig.pk)

    def test_snapshot_is_independent_of_template(self):
        """
        Changing the template after assignment does not affect the copy.
        """
        assignment = assign_program(
            template=self.template,
            assigned_by=self.coach,
            start_date=self.start_date,
            end_date=self.end_date,
            athlete=self.athlete1,
        )
        copy = AssignedRoutine.objects.get(assignment=assignment, athlete=self.athlete1).routine

        original_name = copy.name
        original_start = copy.start

        # Change the template
        self.template.name = 'Changed template name'
        self.template.save()

        # Refresh the copy from the DB
        copy.refresh_from_db()

        self.assertEqual(copy.name, original_name)
        self.assertEqual(copy.start, original_start)
        self.assertNotEqual(copy.name, self.template.name)

    def test_athlete_cannot_assign(self):
        """
        An athlete as assigned_by raises PermissionDenied and writes nothing.
        """
        assignment_count = ProgramAssignment.objects.count()
        assigned_count = AssignedRoutine.objects.count()

        with self.assertRaises(PermissionDenied):
            assign_program(
                template=self.template,
                assigned_by=self.athlete1,
                start_date=self.start_date,
                end_date=self.end_date,
                team=self.team,
            )

        self.assertEqual(ProgramAssignment.objects.count(), assignment_count)
        self.assertEqual(AssignedRoutine.objects.count(), assigned_count)

    def test_other_coach_cannot_assign(self):
        """
        A coach who is not a member of the team raises PermissionDenied.
        """
        assignment_count = ProgramAssignment.objects.count()
        assigned_count = AssignedRoutine.objects.count()

        with self.assertRaises(PermissionDenied):
            assign_program(
                template=self.template,
                assigned_by=self.other_coach,
                start_date=self.start_date,
                end_date=self.end_date,
                team=self.team,
            )

        self.assertEqual(ProgramAssignment.objects.count(), assignment_count)
        self.assertEqual(AssignedRoutine.objects.count(), assigned_count)

    def test_private_template_of_another_user(self):
        """
        A coach cannot use a private template owned by another user.
        """
        private_template = (
            Routine.objects.filter(is_template=True, is_public=False)
            .exclude(user=self.coach)
            .first()
        )

        assignment_count = ProgramAssignment.objects.count()
        assigned_count = AssignedRoutine.objects.count()

        with self.assertRaises(PermissionDenied):
            assign_program(
                template=private_template,
                assigned_by=self.coach,
                start_date=self.start_date,
                end_date=self.end_date,
                athlete=self.athlete1,
            )

        self.assertEqual(ProgramAssignment.objects.count(), assignment_count)
        self.assertEqual(AssignedRoutine.objects.count(), assigned_count)

    def assign(self, **kwargs):
        """
        Assigns the template with the default period, overridable per call.
        """
        params = {
            'template': self.template,
            'assigned_by': self.coach,
            'start_date': self.start_date,
            'end_date': self.end_date,
        }
        params.update(kwargs)
        return assign_program(**params)

    def test_overlapping_assignment_same_athlete(self):
        """
        The same template cannot be assigned twice to an athlete for overlapping periods.
        """
        self.assign(athlete=self.athlete1)
        assignment_count = ProgramAssignment.objects.count()
        assigned_count = AssignedRoutine.objects.count()
        routine_count = Routine.objects.count()

        with self.assertRaises(ValidationError):
            self.assign(
                athlete=self.athlete1,
                start_date=datetime.date(2026, 12, 1),
                end_date=datetime.date(2026, 12, 31),
            )

        self.assertEqual(ProgramAssignment.objects.count(), assignment_count)
        self.assertEqual(AssignedRoutine.objects.count(), assigned_count)
        self.assertEqual(Routine.objects.count(), routine_count)

    def test_overlap_boundary_days(self):
        """
        A period starting on the last day of an existing one overlaps, the day after does not.
        """
        self.assign(athlete=self.athlete1)

        with self.assertRaises(ValidationError):
            self.assign(
                athlete=self.athlete1,
                start_date=self.end_date,
                end_date=self.end_date + datetime.timedelta(days=30),
            )

        # Ending on the first day of the existing period overlaps as well
        with self.assertRaises(ValidationError):
            self.assign(
                athlete=self.athlete1,
                start_date=self.start_date - datetime.timedelta(days=30),
                end_date=self.start_date,
            )

        after = self.assign(
            athlete=self.athlete1,
            start_date=self.end_date + datetime.timedelta(days=1),
            end_date=self.end_date + datetime.timedelta(days=30),
        )
        before = self.assign(
            athlete=self.athlete1,
            start_date=self.start_date - datetime.timedelta(days=30),
            end_date=self.start_date - datetime.timedelta(days=1),
        )
        self.assertEqual(AssignedRoutine.objects.filter(assignment__in=[after, before]).count(), 2)

    def test_overlap_other_template_allowed(self):
        """
        A different template can be assigned to the same athlete for the same period.
        """
        other_template = Routine.objects.create(
            user=self.coach,
            name='Other template',
            is_template=True,
            start=datetime.date(2026, 11, 1),
            end=datetime.date(2026, 11, 30),
        )
        self.assign(athlete=self.athlete1)
        assignment = self.assign(athlete=self.athlete1, template=other_template)

        self.assertEqual(AssignedRoutine.objects.filter(assignment=assignment).count(), 1)

    def test_overlap_other_athlete_allowed(self):
        """
        The same template and period can be assigned to another athlete.
        """
        self.assign(athlete=self.athlete1)
        assignment = self.assign(athlete=self.athlete2)

        self.assertEqual(AssignedRoutine.objects.filter(assignment=assignment).count(), 1)

    def test_team_assignment_overlaps_individual_one(self):
        """
        A team assignment is rejected as a whole if one athlete already has the template.
        """
        self.assign(athlete=self.athlete2)
        assignment_count = ProgramAssignment.objects.count()
        assigned_count = AssignedRoutine.objects.count()

        with self.assertRaises(ValidationError) as context:
            self.assign(team=self.team)

        self.assertIn(self.athlete2.username, context.exception.messages[0])
        self.assertEqual(ProgramAssignment.objects.count(), assignment_count)
        self.assertEqual(AssignedRoutine.objects.count(), assigned_count)

    def test_individual_assignment_overlaps_team_one(self):
        """
        An athlete who got the template through a team cannot get it again individually.
        """
        self.assign(team=self.team)

        with self.assertRaises(ValidationError):
            self.assign(athlete=self.athlete1)

    def invite(self, user, role=TeamMembership.Role.ATHLETE, team=None):
        return TeamMembership.objects.create(team=team or self.team, user=user, role=role)

    def test_membership_is_invited_by_default(self):
        """
        A membership created without a status is an invitation.
        """
        membership = self.invite(self.other_coach)
        self.assertEqual(membership.status, TeamMembership.Status.INVITED)

    def test_invited_athlete_gets_no_copy(self):
        """
        A team assignment only reaches active athletes, not invited ones.
        """
        pending = User.objects.create_user(username='pending', email='pending@example.com')
        self.invite(pending)

        assignment = self.assign(team=self.team)

        athletes = {a.athlete for a in AssignedRoutine.objects.filter(assignment=assignment)}
        self.assertEqual(athletes, {self.athlete1, self.athlete2, self.athlete3})
        self.assertFalse(Routine.objects.filter(user=pending).exists())

    def test_team_with_only_invited_athletes(self):
        """
        A team whose athletes are all still invited has no assignment targets.
        """
        team = Team.objects.create(name='Pending Team', created_by=self.coach)
        TeamMembership.objects.create(
            team=team,
            user=self.coach,
            role=TeamMembership.Role.COACH,
            status=TeamMembership.Status.ACTIVE,
        )
        pending = User.objects.create_user(username='pending', email='pending@example.com')
        self.invite(pending, team=team)

        with self.assertRaises(ValidationError):
            self.assign(team=team)
        self.assertFalse(Routine.objects.filter(user=pending).exists())

    def test_invited_athlete_cannot_be_assigned_individually(self):
        """
        An individual assignment to an invited athlete raises PermissionDenied.
        """
        pending = User.objects.create_user(username='pending', email='pending@example.com')
        self.invite(pending)

        with self.assertRaises(PermissionDenied):
            self.assign(athlete=pending)
        self.assertFalse(Routine.objects.filter(user=pending).exists())

    def test_invited_coach_cannot_assign(self):
        """
        A coach who has not accepted the invitation cannot assign, neither to the team nor
        to one of its athletes.
        """
        template = Routine.objects.create(
            user=self.other_coach,
            name='Other coach template',
            is_template=True,
            start=datetime.date(2026, 11, 1),
            end=datetime.date(2026, 11, 30),
        )
        self.invite(self.other_coach, role=TeamMembership.Role.COACH)

        with self.assertRaises(PermissionDenied):
            self.assign(team=self.team, assigned_by=self.other_coach, template=template)
        with self.assertRaises(PermissionDenied):
            self.assign(athlete=self.athlete2, assigned_by=self.other_coach, template=template)
        self.assertEqual(AssignedRoutine.objects.count(), 0)

    def make_group(self, *users, team=None):
        """
        A group of the team with the memberships of the given users.
        """
        team = team or self.team
        group = TeamGroup.objects.create(team=team, name='Goalkeepers')
        group.members.set(TeamMembership.objects.filter(team=team, user__in=users))
        return group

    def test_assign_to_group(self):
        """
        A group assignment reaches the athletes of the group only and keeps the team.
        """
        group = self.make_group(self.athlete1, self.athlete3)

        assignment = self.assign(group=group)

        self.assertEqual(assignment.group, group)
        self.assertEqual(assignment.team, self.team)
        self.assertIsNone(assignment.athlete)
        athletes = {a.athlete for a in AssignedRoutine.objects.filter(assignment=assignment)}
        self.assertEqual(athletes, {self.athlete1, self.athlete3})
        self.assertFalse(Routine.objects.filter(user=self.athlete2).exists())

    def test_group_assignment_skips_invited_and_coaches(self):
        """
        Invited members and coaches in a group receive no copy.
        """
        pending = User.objects.create_user(username='pending', email='pending@example.com')
        self.invite(pending)
        group = self.make_group(self.athlete1, pending, self.coach)

        assignment = self.assign(group=group)

        athletes = {a.athlete for a in AssignedRoutine.objects.filter(assignment=assignment)}
        self.assertEqual(athletes, {self.athlete1})

    def test_assign_to_empty_group(self):
        """
        A group without active athletes raises ValidationError.
        """
        with self.assertRaises(ValidationError):
            self.assign(group=self.make_group())
        self.assertEqual(ProgramAssignment.objects.count(), 0)

    def test_only_coach_of_the_team_assigns_to_group(self):
        """
        A coach of another team cannot assign to a group, even with an own template.
        """
        template = Routine.objects.create(
            user=self.other_coach,
            name='Other coach template',
            is_template=True,
            start=datetime.date(2026, 11, 1),
            end=datetime.date(2026, 11, 30),
        )
        group = self.make_group(self.athlete1)

        with self.assertRaises(PermissionDenied):
            self.assign(group=group, assigned_by=self.other_coach, template=template)
        self.assertEqual(AssignedRoutine.objects.count(), 0)

    def test_group_is_an_exclusive_target(self):
        """
        A group cannot be combined with a team or an athlete.
        """
        group = self.make_group(self.athlete1)
        with self.assertRaises(ValidationError):
            self.assign(group=group, team=self.team)
        with self.assertRaises(ValidationError):
            self.assign(group=group, athlete=self.athlete1)
        self.assertEqual(ProgramAssignment.objects.count(), 0)

    def test_group_assignment_counts_for_overlap(self):
        """
        After a group assignment the team cannot get the same template for the same period.
        """
        self.assign(group=self.make_group(self.athlete1))
        with self.assertRaises(ValidationError):
            self.assign(team=self.team)


class CopyRoutineTestCase(WgerTestCase):
    """
    Tests for the copy_routine service function.
    """

    CONFIG_MODELS = (
        WeightConfig,
        MaxWeightConfig,
        RepetitionsConfig,
        MaxRepetitionsConfig,
        SetsConfig,
        MaxSetsConfig,
        RestConfig,
        MaxRestConfig,
        RiRConfig,
        MaxRiRConfig,
    )

    def setUp(self):
        super().setUp()
        self.coach = User.objects.create_user(username='coach', email='coach@example.com')
        self.athlete = User.objects.create_user(username='athlete', email='athlete@example.com')
        self.template = Routine.objects.create(
            user=self.coach,
            name='Template',
            description='Description',
            is_template=True,
            is_public=True,
            start=datetime.date(2026, 11, 1),
            end=datetime.date(2026, 11, 30),
        )
        self.start = datetime.date(2026, 12, 1)
        self.end = datetime.date(2026, 12, 31)

    def add_day(self, order: int, entries: int) -> Day:
        """
        A day with one slot per entry, each entry with two iterations of every config type.
        """
        day = Day.objects.create(routine=self.template, order=order, name=f'Day {order}')
        for slot_order in range(1, entries + 1):
            slot = Slot.objects.create(day=day, order=slot_order, comment=f'Slot {slot_order}')
            entry = SlotEntry.objects.create(
                slot=slot,
                exercise_id=1,
                repetition_unit=RepetitionUnit.objects.first(),
                weight_unit=WeightUnit.objects.first(),
                order=1,
                comment=f'Entry {order}/{slot_order}',
            )
            for number, model in enumerate(self.CONFIG_MODELS):
                model.objects.create(slot_entry=entry, iteration=1, value=number % 3 + 1)
                model.objects.create(slot_entry=entry, iteration=3, value=1, operation='+')
        return day

    @staticmethod
    def tree(routine: Routine) -> list:
        """
        The content of a routine without ids and parent references, in order.
        """

        def content(instance, *parents):
            return model_to_dict(instance, exclude=['id', *parents])

        result = [content(routine, 'user', 'start', 'end', 'is_template', 'is_public')]
        result.append([content(label, 'routine') for label in routine.labels.order_by('pk')])
        for day in routine.days.order_by('pk'):
            result.append(content(day, 'routine'))
            for slot in day.slots.order_by('pk'):
                result.append(content(slot, 'day'))
                for entry in slot.entries.order_by('pk'):
                    result.append(content(entry, 'slot'))
                    for model in CopyRoutineTestCase.CONFIG_MODELS:
                        configs = model.objects.filter(slot_entry=entry).order_by('pk')
                        result.append(
                            [model.__name__] + [content(c, 'slot_entry') for c in configs]
                        )
        return result

    def test_copy_has_the_same_content(self):
        """
        The copy has the content of the template in the same order, for all ten config
        types, and is a private routine of the new owner with the new period.
        """
        self.add_day(1, entries=3)
        self.add_day(2, entries=2)
        Label.objects.create(routine=self.template, start_offset=1, end_offset=7, label='Week 1')
        routine_copy = copy_routine(self.template, self.athlete, self.start, self.end)

        self.assertEqual(self.tree(routine_copy), self.tree(self.template))
        self.assertEqual(len(self.tree(self.template)), 2 + 2 + 5 * 12)
        self.assertEqual(routine_copy.user, self.athlete)
        self.assertEqual((routine_copy.start, routine_copy.end), (self.start, self.end))
        self.assertFalse(routine_copy.is_template)
        self.assertFalse(routine_copy.is_public)

        # Nothing was moved away from the template, every row exists twice
        for routine in (self.template, routine_copy):
            self.assertEqual(routine.days.count(), 2)
            self.assertEqual(SlotEntry.objects.filter(slot__day__routine=routine).count(), 5)
            for model in self.CONFIG_MODELS:
                configs = model.objects.filter(slot_entry__slot__day__routine=routine)
                self.assertEqual(configs.count(), 10, model.__name__)

    def test_copy_query_count_does_not_grow_with_the_template(self):
        """
        Copying a bigger template needs the same number of queries as a small one.
        """
        self.add_day(1, entries=1)
        with CaptureQueriesContext(connection) as small:
            copy_routine(self.template, self.athlete, self.start, self.end)

        self.add_day(2, entries=4)
        self.add_day(3, entries=4)
        with CaptureQueriesContext(connection) as big:
            copy_routine(self.template, self.athlete, self.start, self.end)

        self.assertEqual(len(big), len(small))

    def test_copy_of_empty_template(self):
        """
        A template without days can be copied.
        """
        routine_copy = copy_routine(self.template, self.athlete, self.start, self.end)
        self.assertEqual(routine_copy.days.count(), 0)
        self.assertEqual(routine_copy.name, self.template.name)

    def test_copy_falls_back_to_rounding_of_the_owner(self):
        """
        Entries without rounding get the rounding of the new owner, others keep theirs.
        """
        day = self.add_day(1, entries=2)
        without, with_rounding = SlotEntry.objects.filter(slot__day=day).order_by('pk')
        SlotEntry.objects.filter(pk=without.pk).update(
            repetition_rounding=None, weight_rounding=None
        )
        SlotEntry.objects.filter(pk=with_rounding.pk).update(
            repetition_rounding=2, weight_rounding=5
        )
        profile = self.athlete.userprofile
        profile.repetitions_rounding = 1
        profile.weight_rounding = 2.5
        profile.save()

        routine_copy = copy_routine(self.template, self.athlete, self.start, self.end)

        entries = SlotEntry.objects.filter(slot__day__routine=routine_copy).order_by('pk')
        self.assertEqual(
            [(entry.repetition_rounding, entry.weight_rounding) for entry in entries],
            [(1, 2.5), (2, 5)],
        )

    # --- create_program ---

    @staticmethod
    def day_content(day: Day) -> list:
        """
        The content of a day without ids, parent references and its order number.
        """

        def content(instance, *exclude):
            return model_to_dict(instance, exclude=['id', *exclude])

        result = [content(day, 'routine', 'order')]
        for slot in day.slots.order_by('pk'):
            result.append(content(slot, 'day'))
            for entry in slot.entries.order_by('pk'):
                result.append(content(entry, 'slot'))
                for model in CopyRoutineTestCase.CONFIG_MODELS:
                    configs = model.objects.filter(slot_entry=entry).order_by('pk')
                    result.append([model.__name__] + [content(c, 'slot_entry') for c in configs])
        return result

    def new_program(self, **kwargs) -> Routine:
        params = {
            'user': self.athlete,
            'name': 'My program',
            'start_date': self.start,
            'end_date': self.end,
        }
        params.update(kwargs)
        return create_program(**params)

    def own_routine(self, name: str, *day_names: str) -> list:
        """
        A program of the athlete with one day per name, each with one exercise.
        """
        routine = Routine.objects.create(
            user=self.athlete, name=name, start=self.start, end=self.end
        )
        days = []
        for order, day_name in enumerate(day_names, start=1):
            day = Day.objects.create(routine=routine, order=order, name=day_name)
            slot = Slot.objects.create(day=day, order=1)
            entry = SlotEntry.objects.create(
                slot=slot,
                exercise_id=1,
                repetition_unit=RepetitionUnit.objects.first(),
                weight_unit=WeightUnit.objects.first(),
                order=1,
            )
            WeightConfig.objects.create(slot_entry=entry, iteration=1, value=order)
            days.append(day)
        return days

    def test_program_from_plan(self):
        """
        A program from a public plan has the content of the plan, the given name and period
        and belongs to the user. The plan stays untouched.
        """
        self.add_day(1, entries=2)
        self.add_day(2, entries=1)
        before = self.tree(self.template)

        program = self.new_program(plan=self.template)

        self.assertEqual(self.tree(program)[1:], before[1:])
        self.assertEqual(program.name, 'My program')
        self.assertEqual(program.user, self.athlete)
        self.assertEqual((program.start, program.end), (self.start, self.end))
        self.assertFalse(program.is_template or program.is_public)
        self.assertEqual(self.tree(self.template), before)
        self.assertEqual(self.template.name, 'Template')

    def test_program_from_single_routines(self):
        """
        A program from single routines has copies of exactly these days in the order given,
        numbered from one. The originals stay where they are.
        """
        push, pull, legs = self.own_routine('Source', 'Push', 'Pull', 'Legs')

        program = self.new_program(days=[legs, push])

        days = list(program.days.order_by('order'))
        self.assertEqual([(d.name, d.order) for d in days], [('Legs', 1), ('Push', 2)])
        self.assertEqual(self.day_content(days[0]), self.day_content(legs))
        self.assertEqual(self.day_content(days[1]), self.day_content(push))
        self.assertEqual(len(self.day_content(legs)), 3 + len(self.CONFIG_MODELS))
        self.assertTrue({d.pk for d in days}.isdisjoint({push.pk, pull.pk, legs.pk}))
        self.assertEqual(push.routine.days.count(), 3)
        self.assertEqual(Slot.objects.filter(day__routine=program).count(), 2)

    def test_program_from_plan_and_routines(self):
        """
        With a plan and routines the days of the plan come first, the routines follow.
        """
        self.add_day(1, entries=1)
        self.add_day(2, entries=1)
        push, pull = self.own_routine('Source', 'Push', 'Pull')

        program = self.new_program(plan=self.template, days=[pull, push])

        self.assertEqual(
            [(d.name, d.order) for d in program.days.order_by('order')],
            [('Day 1', 1), ('Day 2', 2), ('Pull', 3), ('Push', 4)],
        )
        self.assertEqual(self.template.days.count(), 2)

    def test_program_needs_a_source(self):
        """
        Without a plan and without routines nothing is created.
        """
        count = Routine.objects.count()
        with self.assertRaises(ValidationError):
            self.new_program()
        self.assertEqual(Routine.objects.count(), count)

    def test_program_only_from_allowed_sources(self):
        """
        A private plan of another user and routines of another user cannot be used, also
        not mixed with allowed ones. Nothing is created.
        """
        self.add_day(1, entries=1)
        Routine.objects.filter(pk=self.template.pk).update(is_public=False)
        self.template.refresh_from_db()
        foreign_day = Day.objects.create(routine=self.template, order=5, name='Coach day')
        (own_day,) = self.own_routine('Source', 'Push')
        count = Routine.objects.count()
        day_count = Day.objects.count()

        with self.assertRaises(PermissionDenied):
            self.new_program(plan=self.template)
        with self.assertRaises(PermissionDenied):
            self.new_program(days=[own_day, foreign_day])

        self.assertEqual(Routine.objects.count(), count)
        self.assertEqual(Day.objects.count(), day_count)

        # The owner can use the own private plan
        program = self.new_program(user=self.coach, plan=self.template)
        self.assertEqual(program.user, self.coach)

    def test_program_period_limits(self):
        """
        The end must not be before the start and the program at most 120 days long.
        """
        self.add_day(1, entries=1)
        day = datetime.timedelta(days=1)
        limit = datetime.timedelta(days=Routine.MAX_DURATION_DAYS)
        count = Routine.objects.count()

        for end in (self.start - day, self.start + limit + day):
            with self.assertRaises(ValidationError):
                self.new_program(plan=self.template, end_date=end)
        self.assertEqual(Routine.objects.count(), count)

        for end in (self.start, self.start + limit):
            self.assertEqual(self.new_program(plan=self.template, end_date=end).end, end)

    def test_program_query_count_does_not_grow_with_the_routines(self):
        """
        Creating a program from many routines needs the same number of queries as from one.
        """
        days = self.own_routine('Source', 'A', 'B', 'C', 'D', 'E')

        with CaptureQueriesContext(connection) as small:
            self.new_program(days=days[:1])
        with CaptureQueriesContext(connection) as big:
            self.new_program(days=days)

        self.assertEqual(len(big), len(small))

    # --- create_plan and add_routine ---

    def test_plan_from_routines(self):
        """
        A plan from routines is a private template of the user with copies of the routines.
        Without a source nothing is created.
        """
        push, pull = self.own_routine('Source', 'Push', 'Pull')

        plan = create_plan(user=self.athlete, name='My plan', days=[pull, push])

        self.assertTrue(plan.is_template)
        self.assertFalse(plan.is_public)
        self.assertEqual((plan.user, plan.name), (self.athlete, 'My plan'))
        self.assertEqual([d.name for d in plan.days.order_by('order')], ['Pull', 'Push'])
        self.assertEqual(push.routine.days.count(), 2)

        count = Routine.objects.count()
        with self.assertRaises(ValidationError):
            create_plan(user=self.athlete, name='Empty')
        self.assertEqual(Routine.objects.count(), count)

    def test_plan_from_plan_is_a_template(self):
        """
        A plan made from another plan is a template again, not a program.
        """
        self.add_day(1, entries=1)
        plan = create_plan(user=self.athlete, name='Copy', plan=self.template)

        self.assertTrue(plan.is_template)
        self.assertFalse(plan.is_public)
        self.assertEqual(plan.user, self.athlete)
        self.assertEqual(plan.days.count(), 1)

    def test_add_empty_routine_to_program(self):
        """
        An empty routine is appended to the own program and shows up in its schedule, which
        was cached before.
        """
        push, pull = self.own_routine('Source', 'Push', 'Pull')
        program = push.routine
        self.assertEqual({d.day.name for d in program.date_sequence if d.day}, {'Push', 'Pull'})

        day = add_routine(user=self.athlete, name='Legs', program=program)

        self.assertEqual((day.routine, day.name, day.order), (program, 'Legs', 3))
        self.assertFalse(day.is_rest)
        self.assertEqual(day.slots.count(), 0)
        program.refresh_from_db()
        self.assertEqual(
            {d.day.name for d in program.date_sequence if d.day}, {'Push', 'Pull', 'Legs'}
        )

    def test_add_copied_routine_to_program(self):
        """
        A routine copied from an own routine has its content and the new name, the schedule
        of the program is refreshed and the source stays untouched.
        """
        (source,) = self.own_routine('Source', 'Push')
        (other,) = self.own_routine('Target', 'Pull')
        program = other.routine
        list(program.date_sequence)
        before = self.day_content(source)

        day = add_routine(user=self.athlete, name='Push heavy', program=program, source=source)

        self.assertEqual((day.routine, day.name, day.order), (program, 'Push heavy', 2))
        self.assertEqual(self.day_content(day)[1:], before[1:])
        self.assertNotEqual(day.pk, source.pk)
        self.assertEqual(self.day_content(source), before)
        self.assertEqual(source.routine.days.count(), 1)
        self.assertEqual(
            {d.day.name for d in program.date_sequence if d.day}, {'Pull', 'Push heavy'}
        )

    def test_add_routine_creates_a_program_if_none_is_given(self):
        """
        Without a program the routine gets a new four-week program of the user with its name.
        """
        day = add_routine(user=self.athlete, name='Solo session')

        program = day.routine
        self.assertEqual((program.user, program.name), (self.athlete, 'Solo session'))
        self.assertFalse(program.is_template)
        self.assertEqual((program.end - program.start).days, 27)
        self.assertEqual([d.name for d in program.days.all()], ['Solo session'])

    def test_add_routine_only_to_own_programs_and_from_own_routines(self):
        """
        Programs of others, plans (also own ones) and routines of others are refused,
        nothing is created.
        """
        (own_day,) = self.own_routine('Source', 'Push')
        own_plan = create_plan(user=self.athlete, name='Own plan', days=[own_day])
        foreign_program = Routine.objects.create(
            user=self.coach, name='Coach program', start=self.start, end=self.end
        )
        foreign_day = Day.objects.create(routine=foreign_program, order=1, name='Coach day')
        days, routines = Day.objects.count(), Routine.objects.count()

        for kwargs in (
            {'program': foreign_program},
            {'program': own_plan},
            {'program': self.template},
            {'program': own_day.routine, 'source': foreign_day},
            {'source': foreign_day},
        ):
            with self.assertRaises(PermissionDenied):
                add_routine(user=self.athlete, name='Nope', **kwargs)

        self.assertEqual((Day.objects.count(), Routine.objects.count()), (days, routines))
