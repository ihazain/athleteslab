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

# Django
from django.contrib.auth.models import User
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_datetime

# Third Party
from rest_framework import status
from rest_framework.test import APIClient

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
    WorkoutLog,
)
from wger.teams.models import (
    AssignedRoutine,
    ProgramAssignment,
    Team,
    TeamMembership,
)


class TeamApiTestCase(WgerTestCase):
    """
    Tests for the teams REST API endpoints.
    """

    def setUp(self):
        super().setUp()
        self.client = APIClient()

        # Users
        self.coach = User.objects.create_user(username='coach', email='coach@example.com')
        self.other_coach = User.objects.create_user(
            username='othercoach', email='othercoach@example.com'
        )
        self.athlete1 = User.objects.create_user(username='athlete1', email='athlete1@example.com')
        self.athlete2 = User.objects.create_user(username='athlete2', email='athlete2@example.com')

        # A template routine owned by the coach
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

    def authenticate(self, user):
        self.client.force_authenticate(user=user)

    # --- Team endpoint ---

    def test_coach_creates_team(self):
        """
        A coach can create a team and is automatically its coach.
        """
        self.authenticate(self.coach)
        response = self.client.post(
            reverse('team-list'),
            {'name': 'Test Team'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        team = Team.objects.get(name='Test Team')
        self.assertEqual(team.created_by, self.coach)
        self.assertTrue(
            TeamMembership.objects.filter(
                team=team, user=self.coach, role=TeamMembership.Role.COACH
            ).exists()
        )

    def test_anonymous_cannot_create_team(self):
        """
        An unauthenticated user cannot create a team.
        """
        response = self.client.post(
            reverse('team-list'),
            {'name': 'Test Team'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_foreign_coach_sees_no_team(self):
        """
        A foreign coach gets 404 for a team they do not coach.
        """
        team = Team.objects.create(name='Secret Team', created_by=self.coach)
        TeamMembership.objects.create(
            team=team,
            user=self.coach,
            role=TeamMembership.Role.COACH,
            status=TeamMembership.Status.ACTIVE,
        )

        self.authenticate(self.other_coach)
        response = self.client.get(reverse('team-detail', kwargs={'pk': team.pk}))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_coach_sees_own_team(self):
        """
        A coach can retrieve their own team.
        """
        team = Team.objects.create(name='My Team', created_by=self.coach)
        TeamMembership.objects.create(
            team=team,
            user=self.coach,
            role=TeamMembership.Role.COACH,
            status=TeamMembership.Status.ACTIVE,
        )

        self.authenticate(self.coach)
        response = self.client.get(reverse('team-detail', kwargs={'pk': team.pk}))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['name'], 'My Team')

    # --- Team membership endpoint ---

    def test_coach_adds_membership(self):
        """
        A coach can add an athlete to their team.
        """
        team = Team.objects.create(name='Test Team', created_by=self.coach)
        TeamMembership.objects.create(
            team=team,
            user=self.coach,
            role=TeamMembership.Role.COACH,
            status=TeamMembership.Status.ACTIVE,
        )

        self.authenticate(self.coach)
        response = self.client.post(
            reverse('team-membership-list'),
            {
                'team': team.pk,
                'user': self.athlete1.pk,
                'role': TeamMembership.Role.ATHLETE,
            },
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(
            TeamMembership.objects.filter(
                team=team, user=self.athlete1, role=TeamMembership.Role.ATHLETE
            ).exists()
        )

    def test_athlete_cannot_add_membership(self):
        """
        An athlete cannot add a membership to a team they do not coach.
        """
        team = Team.objects.create(name='Test Team', created_by=self.coach)
        TeamMembership.objects.create(
            team=team,
            user=self.coach,
            role=TeamMembership.Role.COACH,
            status=TeamMembership.Status.ACTIVE,
        )

        self.authenticate(self.athlete1)
        response = self.client.post(
            reverse('team-membership-list'),
            {
                'team': team.pk,
                'user': self.athlete2.pk,
                'role': TeamMembership.Role.COACH,
            },
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_foreign_coach_cannot_add_membership(self):
        """
        A foreign coach cannot add a membership to another team.
        """
        team = Team.objects.create(name='Test Team', created_by=self.coach)
        TeamMembership.objects.create(
            team=team,
            user=self.coach,
            role=TeamMembership.Role.COACH,
            status=TeamMembership.Status.ACTIVE,
        )

        self.authenticate(self.other_coach)
        response = self.client.post(
            reverse('team-membership-list'),
            {
                'team': team.pk,
                'user': self.athlete1.pk,
                'role': TeamMembership.Role.ATHLETE,
            },
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_remove_last_coach(self):
        """
        The last coach of a team cannot remove themselves.
        """
        team = Team.objects.create(name='Test Team', created_by=self.coach)
        membership = TeamMembership.objects.create(
            team=team,
            user=self.coach,
            role=TeamMembership.Role.COACH,
            status=TeamMembership.Status.ACTIVE,
        )

        self.authenticate(self.coach)
        response = self.client.delete(
            reverse('team-membership-detail', kwargs={'pk': membership.pk})
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    # --- Program assignment endpoint ---

    def test_coach_assigns_to_team(self):
        """
        A coach can assign a template to a team, creating one copy per athlete.
        """
        team = Team.objects.create(name='Test Team', created_by=self.coach)
        TeamMembership.objects.create(
            team=team,
            user=self.coach,
            role=TeamMembership.Role.COACH,
            status=TeamMembership.Status.ACTIVE,
        )
        TeamMembership.objects.create(
            team=team,
            user=self.athlete1,
            role=TeamMembership.Role.ATHLETE,
            status=TeamMembership.Status.ACTIVE,
        )
        TeamMembership.objects.create(
            team=team,
            user=self.athlete2,
            role=TeamMembership.Role.ATHLETE,
            status=TeamMembership.Status.ACTIVE,
        )

        self.authenticate(self.coach)
        response = self.client.post(
            reverse('program-assignment-list'),
            {
                'template': self.template.pk,
                'team': team.pk,
                'start_date': '2026-11-10',
                'end_date': '2026-12-10',
            },
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        assignment = ProgramAssignment.objects.get(pk=response.data['id'])
        self.assertEqual(assignment.team, team)
        self.assertIsNone(assignment.athlete)

        copies = AssignedRoutine.objects.filter(assignment=assignment)
        self.assertEqual(copies.count(), 2)
        athletes = {c.athlete for c in copies}
        self.assertEqual(athletes, {self.athlete1, self.athlete2})

    def test_overlapping_assignment(self):
        """
        Assigning the same template to the same athlete for an overlapping period returns 400.
        """
        team = Team.objects.create(name='Test Team', created_by=self.coach)
        TeamMembership.objects.create(
            team=team,
            user=self.coach,
            role=TeamMembership.Role.COACH,
            status=TeamMembership.Status.ACTIVE,
        )
        TeamMembership.objects.create(
            team=team,
            user=self.athlete1,
            role=TeamMembership.Role.ATHLETE,
            status=TeamMembership.Status.ACTIVE,
        )

        self.authenticate(self.coach)
        payload = {
            'template': self.template.pk,
            'athlete': self.athlete1.pk,
            'start_date': '2026-11-10',
            'end_date': '2026-12-10',
        }
        response = self.client.post(reverse('program-assignment-list'), payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        payload.update({'start_date': '2026-12-10', 'end_date': '2026-12-31'})
        response = self.client.post(reverse('program-assignment-list'), payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(AssignedRoutine.objects.filter(athlete=self.athlete1).count(), 1)

        payload.update({'start_date': '2026-12-11', 'end_date': '2026-12-31'})
        response = self.client.post(reverse('program-assignment-list'), payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_private_template_stays_hidden_from_athlete(self):
        """
        A private template can be assigned, the athlete gets the copy but never sees the template.
        """
        self.assertFalse(self.template.is_public)
        team = Team.objects.create(name='Test Team', created_by=self.coach)
        TeamMembership.objects.create(
            team=team,
            user=self.coach,
            role=TeamMembership.Role.COACH,
            status=TeamMembership.Status.ACTIVE,
        )
        TeamMembership.objects.create(
            team=team,
            user=self.athlete1,
            role=TeamMembership.Role.ATHLETE,
            status=TeamMembership.Status.ACTIVE,
        )

        self.authenticate(self.coach)
        response = self.client.post(
            reverse('program-assignment-list'),
            {
                'template': self.template.pk,
                'team': team.pk,
                'start_date': '2026-11-10',
                'end_date': '2026-12-10',
            },
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        copy = AssignedRoutine.objects.get(athlete=self.athlete1).routine

        self.authenticate(self.athlete1)
        response = self.client.get(reverse('routine-detail', kwargs={'pk': self.template.pk}))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

        response = self.client.get(reverse('routine-detail', kwargs={'pk': copy.pk}))
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        for name in ('routine-list', 'templates-list', 'public-templates-list'):
            response = self.client.get(reverse(name), {'limit': 1000})
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            ids = {r['id'] for r in response.data['results']}
            self.assertNotIn(self.template.pk, ids, name)

    def test_athlete_cannot_assign(self):
        """
        An athlete cannot assign a program.
        """
        team = Team.objects.create(name='Test Team', created_by=self.coach)
        TeamMembership.objects.create(
            team=team,
            user=self.coach,
            role=TeamMembership.Role.COACH,
            status=TeamMembership.Status.ACTIVE,
        )

        self.authenticate(self.athlete1)
        response = self.client.post(
            reverse('program-assignment-list'),
            {
                'template': self.template.pk,
                'team': team.pk,
                'start_date': '2026-11-10',
                'end_date': '2026-12-10',
            },
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_assign_invalid_team_id(self):
        """
        An invalid team ID returns 400, not 500.
        """
        self.authenticate(self.coach)
        response = self.client.post(
            reverse('program-assignment-list'),
            {
                'template': self.template.pk,
                'team': 'abc',
                'start_date': '2026-11-10',
                'end_date': '2026-12-10',
            },
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_assign_start_after_end(self):
        """
        start_date after end_date returns 400.
        """
        team = Team.objects.create(name='Test Team', created_by=self.coach)
        TeamMembership.objects.create(
            team=team,
            user=self.coach,
            role=TeamMembership.Role.COACH,
            status=TeamMembership.Status.ACTIVE,
        )

        self.authenticate(self.coach)
        response = self.client.post(
            reverse('program-assignment-list'),
            {
                'template': self.template.pk,
                'team': team.pk,
                'start_date': '2026-12-10',
                'end_date': '2026-11-10',
            },
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_assignment_create_only(self):
        """
        PUT/PATCH/DELETE on a program assignment return 405.
        """
        team = Team.objects.create(name='Test Team', created_by=self.coach)
        TeamMembership.objects.create(
            team=team,
            user=self.coach,
            role=TeamMembership.Role.COACH,
            status=TeamMembership.Status.ACTIVE,
        )
        TeamMembership.objects.create(
            team=team,
            user=self.athlete1,
            role=TeamMembership.Role.ATHLETE,
            status=TeamMembership.Status.ACTIVE,
        )

        self.authenticate(self.coach)
        response = self.client.post(
            reverse('program-assignment-list'),
            {
                'template': self.template.pk,
                'team': team.pk,
                'start_date': '2026-11-10',
                'end_date': '2026-12-10',
            },
            format='json',
        )
        assignment_id = response.data['id']

        detail_url = reverse('program-assignment-detail', kwargs={'pk': assignment_id})

        for method, call in (
            ('put', self.client.put),
            ('patch', self.client.patch),
            ('delete', self.client.delete),
        ):
            response = call(detail_url, {'name': 'x'}, format='json')
            self.assertEqual(
                response.status_code,
                status.HTTP_405_METHOD_NOT_ALLOWED,
                f'{method.upper()} should return 405',
            )

    def test_coach_can_assign_to_own_team(self):
        """
        A coach can assign to their own team through the assignment endpoint.
        """
        team = Team.objects.create(name='Test Team', created_by=self.coach)
        TeamMembership.objects.create(
            team=team,
            user=self.coach,
            role=TeamMembership.Role.COACH,
            status=TeamMembership.Status.ACTIVE,
        )
        TeamMembership.objects.create(
            team=team,
            user=self.athlete1,
            role=TeamMembership.Role.ATHLETE,
            status=TeamMembership.Status.ACTIVE,
        )

        self.authenticate(self.coach)
        response = self.client.post(
            reverse('program-assignment-list'),
            {
                'template': self.template.pk,
                'team': team.pk,
                'start_date': '2026-11-10',
                'end_date': '2026-12-10',
            },
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    # --- Hardening: membership updates ---

    def test_patch_last_coach_to_athlete(self):
        """
        Downgrading the last coach to athlete returns 400.
        """
        team = Team.objects.create(name='Test Team', created_by=self.coach)
        membership = TeamMembership.objects.create(
            team=team,
            user=self.coach,
            role=TeamMembership.Role.COACH,
            status=TeamMembership.Status.ACTIVE,
        )

        self.authenticate(self.coach)
        response = self.client.patch(
            reverse('team-membership-detail', kwargs={'pk': membership.pk}),
            {'role': TeamMembership.Role.ATHLETE},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_patch_membership_change_team(self):
        """
        Changing the team of a membership returns 400.
        """
        team = Team.objects.create(name='Test Team', created_by=self.coach)
        TeamMembership.objects.create(
            team=team,
            user=self.coach,
            role=TeamMembership.Role.COACH,
            status=TeamMembership.Status.ACTIVE,
        )
        membership = TeamMembership.objects.create(
            team=team,
            user=self.athlete1,
            role=TeamMembership.Role.ATHLETE,
            status=TeamMembership.Status.ACTIVE,
        )
        other_team = Team.objects.create(name='Other Team', created_by=self.coach)
        TeamMembership.objects.create(
            team=other_team,
            user=self.coach,
            role=TeamMembership.Role.COACH,
            status=TeamMembership.Status.ACTIVE,
        )

        self.authenticate(self.coach)
        response = self.client.patch(
            reverse('team-membership-detail', kwargs={'pk': membership.pk}),
            {'team': other_team.pk},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_patch_membership_change_user(self):
        """
        Changing the user of a membership returns 400.
        """
        team = Team.objects.create(name='Test Team', created_by=self.coach)
        TeamMembership.objects.create(
            team=team,
            user=self.coach,
            role=TeamMembership.Role.COACH,
            status=TeamMembership.Status.ACTIVE,
        )
        membership = TeamMembership.objects.create(
            team=team,
            user=self.athlete1,
            role=TeamMembership.Role.ATHLETE,
            status=TeamMembership.Status.ACTIVE,
        )

        self.authenticate(self.coach)
        response = self.client.patch(
            reverse('team-membership-detail', kwargs={'pk': membership.pk}),
            {'user': self.athlete2.pk},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    # --- Hardening: athlete read access ---

    def test_athlete_sees_own_teams(self):
        """
        An athlete sees the teams they are a member of.
        """
        team = Team.objects.create(name='Test Team', created_by=self.coach)
        TeamMembership.objects.create(
            team=team,
            user=self.coach,
            role=TeamMembership.Role.COACH,
            status=TeamMembership.Status.ACTIVE,
        )
        TeamMembership.objects.create(
            team=team,
            user=self.athlete1,
            role=TeamMembership.Role.ATHLETE,
            status=TeamMembership.Status.ACTIVE,
        )

        self.authenticate(self.athlete1)
        response = self.client.get(reverse('team-list'), format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        names = {t['name'] for t in response.data.get('results', response.data)}
        self.assertIn('Test Team', names)

    def test_athlete_sees_own_memberships(self):
        """
        An athlete sees their own memberships.
        """
        team = Team.objects.create(name='Test Team', created_by=self.coach)
        TeamMembership.objects.create(
            team=team,
            user=self.coach,
            role=TeamMembership.Role.COACH,
            status=TeamMembership.Status.ACTIVE,
        )
        membership = TeamMembership.objects.create(
            team=team,
            user=self.athlete1,
            role=TeamMembership.Role.ATHLETE,
            status=TeamMembership.Status.ACTIVE,
        )

        self.authenticate(self.athlete1)
        response = self.client.get(reverse('team-membership-list'), format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ids = {m['id'] for m in response.data.get('results', response.data)}
        self.assertIn(membership.pk, ids)

    def test_athlete_sees_own_assignments(self):
        """
        An athlete sees only their own program assignments.
        """
        team = Team.objects.create(name='Test Team', created_by=self.coach)
        TeamMembership.objects.create(
            team=team,
            user=self.coach,
            role=TeamMembership.Role.COACH,
            status=TeamMembership.Status.ACTIVE,
        )
        TeamMembership.objects.create(
            team=team,
            user=self.athlete1,
            role=TeamMembership.Role.ATHLETE,
            status=TeamMembership.Status.ACTIVE,
        )

        self.authenticate(self.coach)
        self.client.post(
            reverse('program-assignment-list'),
            {
                'template': self.template.pk,
                'team': team.pk,
                'start_date': '2026-11-10',
                'end_date': '2026-12-10',
            },
            format='json',
        )

        self.authenticate(self.athlete1)
        response = self.client.get(reverse('program-assignment-list'), format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ids = {a['id'] for a in response.data.get('results', response.data)}
        self.assertGreaterEqual(len(ids), 1)

    # --- Hardening: athlete write access ---

    def test_athlete_cannot_write_team(self):
        """
        An athlete who is a member (not coach) cannot modify a team.
        """
        team = Team.objects.create(name='Test Team', created_by=self.coach)
        TeamMembership.objects.create(
            team=team,
            user=self.coach,
            role=TeamMembership.Role.COACH,
            status=TeamMembership.Status.ACTIVE,
        )
        TeamMembership.objects.create(
            team=team,
            user=self.athlete1,
            role=TeamMembership.Role.ATHLETE,
            status=TeamMembership.Status.ACTIVE,
        )

        self.authenticate(self.athlete1)
        response = self.client.put(
            reverse('team-detail', kwargs={'pk': team.pk}),
            {'name': 'Hacked'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_athlete_cannot_write_membership(self):
        """
        An athlete cannot create a membership for a team they do not coach.
        """
        team = Team.objects.create(name='Test Team', created_by=self.coach)
        TeamMembership.objects.create(
            team=team,
            user=self.coach,
            role=TeamMembership.Role.COACH,
            status=TeamMembership.Status.ACTIVE,
        )

        self.authenticate(self.athlete1)
        response = self.client.post(
            reverse('team-membership-list'),
            {
                'team': team.pk,
                'user': self.athlete2.pk,
                'role': TeamMembership.Role.ATHLETE,
            },
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    # --- Hardening: foreign coach sees no assignment ---

    def test_foreign_coach_sees_no_assignment(self):
        """
        A coach of another team gets 404 for a foreign assignment.
        """
        team = Team.objects.create(name='Test Team', created_by=self.coach)
        TeamMembership.objects.create(
            team=team,
            user=self.coach,
            role=TeamMembership.Role.COACH,
            status=TeamMembership.Status.ACTIVE,
        )
        TeamMembership.objects.create(
            team=team,
            user=self.athlete1,
            role=TeamMembership.Role.ATHLETE,
            status=TeamMembership.Status.ACTIVE,
        )

        self.authenticate(self.coach)
        response = self.client.post(
            reverse('program-assignment-list'),
            {
                'template': self.template.pk,
                'team': team.pk,
                'start_date': '2026-11-10',
                'end_date': '2026-12-10',
            },
            format='json',
        )
        assignment_id = response.data['id']

        other_team = Team.objects.create(name='Other Team', created_by=self.other_coach)
        TeamMembership.objects.create(
            team=other_team,
            user=self.other_coach,
            role=TeamMembership.Role.COACH,
            status=TeamMembership.Status.ACTIVE,
        )

        self.authenticate(self.other_coach)
        response = self.client.get(
            reverse('program-assignment-detail', kwargs={'pk': assignment_id})
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    # --- Hardening: template deletion keeps assignment ---

    def test_delete_template_keeps_assignment(self):
        """
        Deleting the template keeps the assignment and copies; template is NULL.
        """
        team = Team.objects.create(name='Test Team', created_by=self.coach)
        TeamMembership.objects.create(
            team=team,
            user=self.coach,
            role=TeamMembership.Role.COACH,
            status=TeamMembership.Status.ACTIVE,
        )
        TeamMembership.objects.create(
            team=team,
            user=self.athlete1,
            role=TeamMembership.Role.ATHLETE,
            status=TeamMembership.Status.ACTIVE,
        )

        self.authenticate(self.coach)
        response = self.client.post(
            reverse('program-assignment-list'),
            {
                'template': self.template.pk,
                'team': team.pk,
                'start_date': '2026-11-10',
                'end_date': '2026-12-10',
            },
            format='json',
        )
        assignment_id = response.data['id']
        assignment = ProgramAssignment.objects.get(pk=assignment_id)
        self.assertIsNotNone(assignment.template)

        self.template.delete()

        assignment.refresh_from_db()
        self.assertIsNone(assignment.template)
        self.assertEqual(AssignedRoutine.objects.filter(assignment=assignment).count(), 1)

    # --- Deletion ---

    def test_delete_team_keeps_copies_and_logs(self):
        """
        Deleting a team removes its assignments, the athletes keep their copies and logs.
        """
        team = Team.objects.create(name='Test Team', created_by=self.coach)
        TeamMembership.objects.create(
            team=team,
            user=self.coach,
            role=TeamMembership.Role.COACH,
            status=TeamMembership.Status.ACTIVE,
        )
        TeamMembership.objects.create(
            team=team,
            user=self.athlete1,
            role=TeamMembership.Role.ATHLETE,
            status=TeamMembership.Status.ACTIVE,
        )

        self.authenticate(self.coach)
        response = self.client.post(
            reverse('program-assignment-list'),
            {
                'template': self.template.pk,
                'team': team.pk,
                'start_date': '2026-11-10',
                'end_date': '2026-12-10',
            },
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        assignment_id = response.data['id']
        copy = AssignedRoutine.objects.get(athlete=self.athlete1).routine
        log = WorkoutLog.objects.create(
            user=self.athlete1,
            routine=copy,
            exercise_id=1,
            weight=10,
            repetitions=10,
            date=timezone.now(),
        )

        response = self.client.delete(reverse('team-detail', kwargs={'pk': team.pk}))
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

        self.assertFalse(Team.objects.filter(pk=team.pk).exists())
        self.assertFalse(ProgramAssignment.objects.filter(pk=assignment_id).exists())
        self.assertFalse(AssignedRoutine.objects.filter(athlete=self.athlete1).exists())

        copy.refresh_from_db()
        self.assertEqual(copy.user, self.athlete1)
        self.assertEqual(copy.days.count(), self.template.days.count())
        log.refresh_from_db()
        self.assertEqual(log.routine, copy)
        self.assertTrue(Routine.objects.filter(pk=self.template.pk).exists())

    def test_athlete_cannot_delete_team(self):
        """
        An athlete cannot delete a team.
        """
        team = Team.objects.create(name='Test Team', created_by=self.coach)
        TeamMembership.objects.create(
            team=team,
            user=self.coach,
            role=TeamMembership.Role.COACH,
            status=TeamMembership.Status.ACTIVE,
        )
        TeamMembership.objects.create(
            team=team,
            user=self.athlete1,
            role=TeamMembership.Role.ATHLETE,
            status=TeamMembership.Status.ACTIVE,
        )

        self.authenticate(self.athlete1)
        response = self.client.delete(reverse('team-detail', kwargs={'pk': team.pk}))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertTrue(Team.objects.filter(pk=team.pk).exists())

    def test_delete_coach_account_keeps_team_and_assignment(self):
        """
        Deleting the account of the coach keeps the team, the assignment and the copies.
        """
        team = Team.objects.create(name='Test Team', created_by=self.coach)
        TeamMembership.objects.create(
            team=team,
            user=self.coach,
            role=TeamMembership.Role.COACH,
            status=TeamMembership.Status.ACTIVE,
        )
        TeamMembership.objects.create(
            team=team,
            user=self.other_coach,
            role=TeamMembership.Role.COACH,
            status=TeamMembership.Status.ACTIVE,
        )
        TeamMembership.objects.create(
            team=team,
            user=self.athlete1,
            role=TeamMembership.Role.ATHLETE,
            status=TeamMembership.Status.ACTIVE,
        )

        self.authenticate(self.coach)
        response = self.client.post(
            reverse('program-assignment-list'),
            {
                'template': self.template.pk,
                'team': team.pk,
                'start_date': '2026-11-10',
                'end_date': '2026-12-10',
            },
            format='json',
        )
        assignment_id = response.data['id']
        copy = AssignedRoutine.objects.get(athlete=self.athlete1).routine

        self.coach.delete()

        team.refresh_from_db()
        self.assertIsNone(team.created_by)
        assignment = ProgramAssignment.objects.get(pk=assignment_id)
        self.assertIsNone(assignment.assigned_by)
        self.assertIsNone(assignment.template)
        self.assertTrue(Routine.objects.filter(pk=copy.pk).exists())

        self.authenticate(self.other_coach)
        response = self.client.get(
            reverse('program-assignment-detail', kwargs={'pk': assignment_id})
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsNone(response.data['assigned_by'])

    # --- Invitations ---

    def make_team(self):
        """
        A team with the coach as active coach.
        """
        team = Team.objects.create(name='Test Team', created_by=self.coach)
        TeamMembership.objects.create(
            team=team,
            user=self.coach,
            role=TeamMembership.Role.COACH,
            status=TeamMembership.Status.ACTIVE,
        )
        return team

    def invite(self, team, user, role=TeamMembership.Role.ATHLETE):
        return TeamMembership.objects.create(team=team, user=user, role=role)

    def assign_to_team(self, team):
        return self.client.post(
            reverse('program-assignment-list'),
            {
                'template': self.template.pk,
                'team': team.pk,
                'start_date': '2026-11-10',
                'end_date': '2026-12-10',
            },
            format='json',
        )

    def test_team_creator_is_active_coach(self):
        """
        The creator of a team is an active coach without accepting anything.
        """
        self.authenticate(self.coach)
        response = self.client.post(reverse('team-list'), {'name': 'New Team'}, format='json')
        membership = TeamMembership.objects.get(team_id=response.data['id'], user=self.coach)
        self.assertEqual(membership.status, TeamMembership.Status.ACTIVE)

    def test_new_membership_is_an_invitation(self):
        """
        A membership added by a coach is invited, a status in the payload is ignored.
        """
        team = self.make_team()
        self.authenticate(self.coach)
        response = self.client.post(
            reverse('team-membership-list'),
            {
                'team': team.pk,
                'user': self.athlete1.pk,
                'role': TeamMembership.Role.ATHLETE,
                'status': TeamMembership.Status.ACTIVE,
            },
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['status'], TeamMembership.Status.INVITED)
        membership = TeamMembership.objects.get(pk=response.data['id'])
        self.assertEqual(membership.status, TeamMembership.Status.INVITED)

    def test_coach_cannot_activate_membership(self):
        """
        A coach cannot set the status of a membership, only the invited user accepts.
        """
        team = self.make_team()
        membership = self.invite(team, self.athlete1)

        self.authenticate(self.coach)
        detail = reverse('team-membership-detail', kwargs={'pk': membership.pk})
        self.client.patch(detail, {'status': TeamMembership.Status.ACTIVE}, format='json')
        membership.refresh_from_db()
        self.assertEqual(membership.status, TeamMembership.Status.INVITED)

        response = self.client.post(reverse('team-membership-accept', kwargs={'pk': membership.pk}))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        membership.refresh_from_db()
        self.assertEqual(membership.status, TeamMembership.Status.INVITED)

    def test_accept_invitation(self):
        """
        Only after accepting the invitation an athlete receives copies of team assignments.
        """
        team = self.make_team()
        self.invite(team, self.athlete2).delete()
        TeamMembership.objects.create(
            team=team,
            user=self.athlete2,
            role=TeamMembership.Role.ATHLETE,
            status=TeamMembership.Status.ACTIVE,
        )
        membership = self.invite(team, self.athlete1)

        self.authenticate(self.coach)
        response = self.assign_to_team(team)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertFalse(AssignedRoutine.objects.filter(athlete=self.athlete1).exists())
        self.assertFalse(Routine.objects.filter(user=self.athlete1).exists())

        self.authenticate(self.athlete1)
        response = self.client.post(reverse('team-membership-accept', kwargs={'pk': membership.pk}))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['status'], TeamMembership.Status.ACTIVE)
        membership.refresh_from_db()
        self.assertEqual(membership.status, TeamMembership.Status.ACTIVE)

        # Accepting twice is an error
        response = self.client.post(reverse('team-membership-accept', kwargs={'pk': membership.pk}))
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        self.authenticate(self.coach)
        response = self.client.post(
            reverse('program-assignment-list'),
            {
                'template': self.template.pk,
                'athlete': self.athlete1.pk,
                'start_date': '2026-11-10',
                'end_date': '2026-12-10',
            },
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(AssignedRoutine.objects.filter(athlete=self.athlete1).count(), 1)

    def test_decline_invitation(self):
        """
        Declining removes the invitation, an active membership cannot be declined.
        """
        team = self.make_team()
        membership = self.invite(team, self.athlete1)

        self.authenticate(self.athlete1)
        response = self.client.post(
            reverse('team-membership-decline', kwargs={'pk': membership.pk})
        )
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(TeamMembership.objects.filter(pk=membership.pk).exists())

        active = TeamMembership.objects.create(
            team=team,
            user=self.athlete1,
            role=TeamMembership.Role.ATHLETE,
            status=TeamMembership.Status.ACTIVE,
        )
        response = self.client.post(reverse('team-membership-decline', kwargs={'pk': active.pk}))
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertTrue(TeamMembership.objects.filter(pk=active.pk).exists())

    def test_foreign_user_cannot_answer_invitation(self):
        """
        The invitation of another user cannot be accepted or declined (404).
        """
        team = self.make_team()
        membership = self.invite(team, self.athlete1)

        self.authenticate(self.athlete2)
        for name in ('team-membership-accept', 'team-membership-decline'):
            response = self.client.post(reverse(name, kwargs={'pk': membership.pk}))
            self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND, name)

        membership.refresh_from_db()
        self.assertEqual(membership.status, TeamMembership.Status.INVITED)

    def test_invited_user_sees_invitation_but_no_team_data(self):
        """
        An invited user sees the own invitation and the team, but no assignments and no
        other members.
        """
        team = self.make_team()
        membership = self.invite(team, self.athlete1)
        TeamMembership.objects.create(
            team=team,
            user=self.athlete2,
            role=TeamMembership.Role.ATHLETE,
            status=TeamMembership.Status.ACTIVE,
        )
        self.authenticate(self.coach)
        assignment_id = self.assign_to_team(team).data['id']

        self.authenticate(self.athlete1)
        response = self.client.get(reverse('team-membership-list'))
        self.assertEqual([m['id'] for m in response.data['results']], [membership.pk])

        response = self.client.get(reverse('team-detail', kwargs={'pk': team.pk}))
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        response = self.client.get(reverse('program-assignment-list'))
        self.assertEqual(response.data['results'], [])
        response = self.client.get(
            reverse('program-assignment-detail', kwargs={'pk': assignment_id})
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_invited_coach_has_no_coach_rights(self):
        """
        A coach who has not accepted yet cannot change the team, manage members or assign.
        """
        team = self.make_team()
        TeamMembership.objects.create(
            team=team,
            user=self.athlete1,
            role=TeamMembership.Role.ATHLETE,
            status=TeamMembership.Status.ACTIVE,
        )
        self.invite(team, self.other_coach, role=TeamMembership.Role.COACH)
        template = Routine.objects.create(
            user=self.other_coach,
            name='Other coach template',
            is_template=True,
            start=datetime.date(2026, 11, 1),
            end=datetime.date(2026, 11, 30),
        )

        self.authenticate(self.other_coach)
        response = self.client.patch(
            reverse('team-detail', kwargs={'pk': team.pk}), {'name': 'Taken over'}, format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

        response = self.client.post(
            reverse('team-membership-list'),
            {'team': team.pk, 'user': self.athlete2.pk, 'role': TeamMembership.Role.ATHLETE},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

        response = self.client.get(reverse('team-membership-list'))
        self.assertEqual(len(response.data['results']), 1)

        response = self.client.post(
            reverse('program-assignment-list'),
            {
                'template': template.pk,
                'team': team.pk,
                'start_date': '2026-11-10',
                'end_date': '2026-12-10',
            },
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(AssignedRoutine.objects.count(), 0)

    def test_invited_coach_does_not_count_as_coach(self):
        """
        The last active coach cannot be removed or demoted while the other coach is invited.
        """
        team = self.make_team()
        self.invite(team, self.other_coach, role=TeamMembership.Role.COACH)
        membership = TeamMembership.objects.get(team=team, user=self.coach)
        detail = reverse('team-membership-detail', kwargs={'pk': membership.pk})

        self.authenticate(self.coach)
        response = self.client.delete(detail)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        response = self.client.patch(detail, {'role': TeamMembership.Role.ATHLETE}, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        membership.refresh_from_db()
        self.assertEqual(membership.role, TeamMembership.Role.COACH)

    # --- Reading assignments ---

    def test_individual_assignment_is_visible_to_coach_and_athlete(self):
        """
        An assignment to a single athlete can be read by the athlete and the coaches of the
        athlete, as list and as detail. Other users get 404.
        """
        team = self.make_team()
        for user in (self.athlete1, self.athlete2):
            TeamMembership.objects.create(
                team=team,
                user=user,
                role=TeamMembership.Role.ATHLETE,
                status=TeamMembership.Status.ACTIVE,
            )

        self.authenticate(self.coach)
        response = self.client.post(
            reverse('program-assignment-list'),
            {
                'template': self.template.pk,
                'athlete': self.athlete1.pk,
                'start_date': '2026-11-10',
                'end_date': '2026-12-10',
            },
            format='json',
        )
        assignment_id = response.data['id']
        detail = reverse('program-assignment-detail', kwargs={'pk': assignment_id})

        for user in (self.coach, self.athlete1):
            self.authenticate(user)
            response = self.client.get(reverse('program-assignment-list'))
            self.assertEqual([a['id'] for a in response.data['results']], [assignment_id], user)
            self.assertEqual(self.client.get(detail).status_code, status.HTTP_200_OK, user)

        for user in (self.athlete2, self.other_coach):
            self.authenticate(user)
            response = self.client.get(reverse('program-assignment-list'))
            self.assertEqual(response.data['results'], [], user)
            self.assertEqual(self.client.get(detail).status_code, status.HTTP_404_NOT_FOUND, user)

    def test_athlete_reads_team_assignment_detail(self):
        """
        An active athlete of the team can read the detail of a team assignment.
        """
        team = self.make_team()
        TeamMembership.objects.create(
            team=team,
            user=self.athlete1,
            role=TeamMembership.Role.ATHLETE,
            status=TeamMembership.Status.ACTIVE,
        )
        self.authenticate(self.coach)
        assignment_id = self.assign_to_team(team).data['id']

        self.authenticate(self.athlete1)
        response = self.client.get(
            reverse('program-assignment-detail', kwargs={'pk': assignment_id})
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    # --- Archiving ---

    def make_team_with_athletes(self):
        team = self.make_team()
        for user in (self.athlete1, self.athlete2):
            TeamMembership.objects.create(
                team=team,
                user=user,
                role=TeamMembership.Role.ATHLETE,
                status=TeamMembership.Status.ACTIVE,
            )
        return team

    def test_archive_assignment(self):
        """
        An archived assignment stays readable and keeps its copies, archiving twice is an
        error.
        """
        team = self.make_team_with_athletes()
        self.authenticate(self.coach)
        assignment_id = self.assign_to_team(team).data['id']
        self.assertIsNone(ProgramAssignment.objects.get(pk=assignment_id).archived_at)
        archive = reverse('program-assignment-archive', kwargs={'pk': assignment_id})
        detail = reverse('program-assignment-detail', kwargs={'pk': assignment_id})

        response = self.client.post(archive)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsNotNone(response.data['archived_at'])
        archived_at = ProgramAssignment.objects.get(pk=assignment_id).archived_at
        self.assertIsNotNone(archived_at)

        response = self.client.post(archive)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(ProgramAssignment.objects.get(pk=assignment_id).archived_at, archived_at)

        copies = AssignedRoutine.objects.filter(assignment_id=assignment_id)
        self.assertEqual(copies.count(), 2)
        for copy in copies:
            self.assertEqual(copy.routine.days.count(), self.template.days.count())

        for user in (self.coach, self.athlete1):
            self.authenticate(user)
            response = self.client.get(detail)
            self.assertEqual(response.status_code, status.HTTP_200_OK, user)
            self.assertIsNotNone(response.data['archived_at'])

    def test_only_coach_archives(self):
        """
        Athletes get 403 and foreign users 404 when archiving, nothing changes.
        """
        team = self.make_team_with_athletes()
        self.authenticate(self.coach)
        assignment_id = self.assign_to_team(team).data['id']
        archive = reverse('program-assignment-archive', kwargs={'pk': assignment_id})

        self.authenticate(self.athlete1)
        self.assertEqual(self.client.post(archive).status_code, status.HTTP_403_FORBIDDEN)
        self.authenticate(self.other_coach)
        self.assertEqual(self.client.post(archive).status_code, status.HTTP_404_NOT_FOUND)

        self.assertIsNone(ProgramAssignment.objects.get(pk=assignment_id).archived_at)

    def test_archived_assignment_does_not_block_a_new_one(self):
        """
        After archiving, the same template can be assigned again for the same period.
        """
        team = self.make_team_with_athletes()
        self.authenticate(self.coach)
        assignment_id = self.assign_to_team(team).data['id']
        self.assertEqual(self.assign_to_team(team).status_code, status.HTTP_400_BAD_REQUEST)

        self.client.post(reverse('program-assignment-archive', kwargs={'pk': assignment_id}))
        self.assertEqual(self.assign_to_team(team).status_code, status.HTTP_201_CREATED)
        self.assertEqual(AssignedRoutine.objects.filter(athlete=self.athlete1).count(), 2)

    # --- Progress ---

    def make_log(self, user, routine, date):
        return WorkoutLog.objects.create(
            user=user,
            routine=routine,
            exercise_id=1,
            weight=10,
            repetitions=10,
            date=date,
        )

    def test_progress(self):
        """
        The progress lists every athlete of the assignment with the copy and the activity
        logged against that copy only.
        """
        team = self.make_team_with_athletes()
        self.authenticate(self.coach)
        assignment_id = self.assign_to_team(team).data['id']
        progress = reverse('program-assignment-progress', kwargs={'pk': assignment_id})
        copy1 = AssignedRoutine.objects.get(athlete=self.athlete1).routine
        copy2 = AssignedRoutine.objects.get(athlete=self.athlete2).routine

        first = datetime.datetime(2026, 11, 11, 18, 0, tzinfo=datetime.UTC)
        last = datetime.datetime(2026, 11, 13, 18, 0, tzinfo=datetime.UTC)
        self.make_log(self.athlete1, copy1, first)
        self.make_log(self.athlete1, copy1, last)
        self.make_log(self.athlete1, copy1, last)

        # A log against another routine of the athlete does not count
        own_routine = Routine.objects.create(
            user=self.athlete2,
            name='Own routine',
            start=datetime.date(2026, 11, 1),
            end=datetime.date(2026, 11, 30),
        )
        self.make_log(self.athlete2, own_routine, last)

        response = self.client.get(progress)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        rows = {row['athlete']: row for row in response.data}
        self.assertEqual(set(rows), {self.athlete1.pk, self.athlete2.pk})

        row = rows[self.athlete1.pk]
        self.assertEqual(row['username'], self.athlete1.username)
        self.assertEqual(row['routine'], copy1.pk)
        self.assertEqual(row['logs'], 3)
        self.assertEqual(row['sessions'], 2)
        self.assertEqual(parse_datetime(row['last_activity']), last)

        row = rows[self.athlete2.pk]
        self.assertEqual(row['routine'], copy2.pk)
        self.assertEqual(row['logs'], 0)
        self.assertEqual(row['sessions'], 0)
        self.assertIsNone(row['last_activity'])

    def test_progress_after_athlete_deleted_copy(self):
        """
        An athlete who deleted the copy stays in the progress, without a routine. The same
        template can then be assigned again.
        """
        team = self.make_team_with_athletes()
        self.authenticate(self.coach)
        assignment_id = self.assign_to_team(team).data['id']
        AssignedRoutine.objects.get(athlete=self.athlete1).routine.delete()

        response = self.client.get(
            reverse('program-assignment-progress', kwargs={'pk': assignment_id})
        )
        rows = {row['athlete']: row for row in response.data}
        self.assertEqual(set(rows), {self.athlete1.pk, self.athlete2.pk})
        self.assertIsNone(rows[self.athlete1.pk]['routine'])
        self.assertEqual(rows[self.athlete1.pk]['logs'], 0)
        self.assertIsNotNone(rows[self.athlete2.pk]['routine'])

        response = self.client.post(
            reverse('program-assignment-list'),
            {
                'template': self.template.pk,
                'athlete': self.athlete1.pk,
                'start_date': '2026-11-10',
                'end_date': '2026-12-10',
            },
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_only_coach_reads_progress(self):
        """
        Athletes get 403 and foreign users 404 for the progress of an assignment.
        """
        team = self.make_team_with_athletes()
        self.authenticate(self.coach)
        assignment_id = self.assign_to_team(team).data['id']
        progress = reverse('program-assignment-progress', kwargs={'pk': assignment_id})

        self.authenticate(self.athlete1)
        self.assertEqual(self.client.get(progress).status_code, status.HTTP_403_FORBIDDEN)
        self.authenticate(self.other_coach)
        self.assertEqual(self.client.get(progress).status_code, status.HTTP_404_NOT_FOUND)
