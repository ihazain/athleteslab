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
        TeamMembership.objects.create(team=team, user=self.coach, role=TeamMembership.Role.COACH)

        self.authenticate(self.other_coach)
        response = self.client.get(reverse('team-detail', kwargs={'pk': team.pk}))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_coach_sees_own_team(self):
        """
        A coach can retrieve their own team.
        """
        team = Team.objects.create(name='My Team', created_by=self.coach)
        TeamMembership.objects.create(team=team, user=self.coach, role=TeamMembership.Role.COACH)

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
        TeamMembership.objects.create(team=team, user=self.coach, role=TeamMembership.Role.COACH)

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
        TeamMembership.objects.create(team=team, user=self.coach, role=TeamMembership.Role.COACH)

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
        TeamMembership.objects.create(team=team, user=self.coach, role=TeamMembership.Role.COACH)

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
            team=team, user=self.coach, role=TeamMembership.Role.COACH
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
        TeamMembership.objects.create(team=team, user=self.coach, role=TeamMembership.Role.COACH)
        TeamMembership.objects.create(
            team=team, user=self.athlete1, role=TeamMembership.Role.ATHLETE
        )
        TeamMembership.objects.create(
            team=team, user=self.athlete2, role=TeamMembership.Role.ATHLETE
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
        TeamMembership.objects.create(team=team, user=self.coach, role=TeamMembership.Role.COACH)
        TeamMembership.objects.create(
            team=team, user=self.athlete1, role=TeamMembership.Role.ATHLETE
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
        TeamMembership.objects.create(team=team, user=self.coach, role=TeamMembership.Role.COACH)
        TeamMembership.objects.create(
            team=team, user=self.athlete1, role=TeamMembership.Role.ATHLETE
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
        TeamMembership.objects.create(team=team, user=self.coach, role=TeamMembership.Role.COACH)

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
        TeamMembership.objects.create(team=team, user=self.coach, role=TeamMembership.Role.COACH)

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
        TeamMembership.objects.create(team=team, user=self.coach, role=TeamMembership.Role.COACH)
        TeamMembership.objects.create(
            team=team, user=self.athlete1, role=TeamMembership.Role.ATHLETE
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
        TeamMembership.objects.create(team=team, user=self.coach, role=TeamMembership.Role.COACH)
        TeamMembership.objects.create(
            team=team, user=self.athlete1, role=TeamMembership.Role.ATHLETE
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
            team=team, user=self.coach, role=TeamMembership.Role.COACH
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
        TeamMembership.objects.create(team=team, user=self.coach, role=TeamMembership.Role.COACH)
        membership = TeamMembership.objects.create(
            team=team, user=self.athlete1, role=TeamMembership.Role.ATHLETE
        )
        other_team = Team.objects.create(name='Other Team', created_by=self.coach)
        TeamMembership.objects.create(
            team=other_team, user=self.coach, role=TeamMembership.Role.COACH
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
        TeamMembership.objects.create(team=team, user=self.coach, role=TeamMembership.Role.COACH)
        membership = TeamMembership.objects.create(
            team=team, user=self.athlete1, role=TeamMembership.Role.ATHLETE
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
        TeamMembership.objects.create(team=team, user=self.coach, role=TeamMembership.Role.COACH)
        TeamMembership.objects.create(
            team=team, user=self.athlete1, role=TeamMembership.Role.ATHLETE
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
        TeamMembership.objects.create(team=team, user=self.coach, role=TeamMembership.Role.COACH)
        membership = TeamMembership.objects.create(
            team=team, user=self.athlete1, role=TeamMembership.Role.ATHLETE
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
        TeamMembership.objects.create(team=team, user=self.coach, role=TeamMembership.Role.COACH)
        TeamMembership.objects.create(
            team=team, user=self.athlete1, role=TeamMembership.Role.ATHLETE
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
        TeamMembership.objects.create(team=team, user=self.coach, role=TeamMembership.Role.COACH)
        TeamMembership.objects.create(
            team=team, user=self.athlete1, role=TeamMembership.Role.ATHLETE
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
        TeamMembership.objects.create(team=team, user=self.coach, role=TeamMembership.Role.COACH)

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
        TeamMembership.objects.create(team=team, user=self.coach, role=TeamMembership.Role.COACH)
        TeamMembership.objects.create(
            team=team, user=self.athlete1, role=TeamMembership.Role.ATHLETE
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
            team=other_team, user=self.other_coach, role=TeamMembership.Role.COACH
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
        TeamMembership.objects.create(team=team, user=self.coach, role=TeamMembership.Role.COACH)
        TeamMembership.objects.create(
            team=team, user=self.athlete1, role=TeamMembership.Role.ATHLETE
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
