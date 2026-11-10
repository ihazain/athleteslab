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

# wger
from wger.core.models import RepetitionUnit, WeightUnit
from wger.core.tests.base_testcase import WgerTestCase
from wger.manager.models import (
    Day,
    Label,
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
    TeamMembership,
)
from wger.teams.services import assign_program, copy_routine


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
            team=self.team, user=self.coach, role=TeamMembership.Role.COACH
        )
        TeamMembership.objects.create(
            team=self.team,
            user=self.athlete1,
            role=TeamMembership.Role.ATHLETE,
        )
        TeamMembership.objects.create(
            team=self.team,
            user=self.athlete2,
            role=TeamMembership.Role.ATHLETE,
        )
        TeamMembership.objects.create(
            team=self.team,
            user=self.athlete3,
            role=TeamMembership.Role.ATHLETE,
        )

        # Another team where the other coach is coach and athlete1 is athlete
        self.other_team = Team.objects.create(name='Other Team', created_by=self.other_coach)
        TeamMembership.objects.create(
            team=self.other_team,
            user=self.other_coach,
            role=TeamMembership.Role.COACH,
        )
        TeamMembership.objects.create(
            team=self.other_team,
            user=self.athlete1,
            role=TeamMembership.Role.ATHLETE,
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
            team=empty_team, user=self.coach, role=TeamMembership.Role.COACH
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
