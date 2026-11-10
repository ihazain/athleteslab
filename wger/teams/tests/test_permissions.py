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
from django.db import transaction
from django.urls import reverse

# Third Party
from rest_framework.test import APIClient

# wger
from wger.core.tests.base_testcase import WgerTestCase
from wger.manager.models import Routine
from wger.teams.models import (
    AssignedRoutine,
    ProgramAssignment,
    Team,
    TeamGroup,
    TeamMembership,
)
from wger.teams.services import assign_program


ROLES = (
    'anonymous',
    'outsider',
    'foreign_coach',
    'invited',
    'invited_coach',
    'athlete',
    'athlete2',
    'coach',
)


def expect(default: int, **overrides: int) -> dict:
    """
    Expected status code per role: the default, except for the roles given.
    """
    unknown = set(overrides) - set(ROLES)
    assert not unknown, unknown
    return {role: overrides.get(role, default) for role in ROLES}


class TeamsPermissionTestCase(WgerTestCase):
    """
    Role x endpoint x method matrix of the teams API and foreign id (IDOR) cases.

    The team has an active coach, two active athletes (``athlete`` is in the
    group, ``athlete2`` is not), an invited athlete (also in the group) and an
    invited coach. ``foreign_coach`` has an own team, ``outsider`` has none.

    The foreign team has two athletes with an own assignment each, who must stay
    invisible to ``coach``: one is only invited to the team, the other one is a
    coach of the team.
    """

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.users = {
            role: User.objects.create_user(username=role, email=f'{role}@example.com')
            for role in ROLES
            if role != 'anonymous'
        }
        self.new_user = User.objects.create_user(username='new', email='new@example.com')

        self.team = Team.objects.create(name='Team', created_by=self.users['coach'])
        active = TeamMembership.Status.ACTIVE
        invited = TeamMembership.Status.INVITED
        coach = TeamMembership.Role.COACH
        athlete = TeamMembership.Role.ATHLETE
        self.memberships = {
            role: TeamMembership.objects.create(
                team=self.team, user=self.users[role], role=team_role, status=status
            )
            for role, team_role, status in (
                ('coach', coach, active),
                ('athlete', athlete, active),
                ('athlete2', athlete, active),
                ('invited', athlete, invited),
                ('invited_coach', coach, invited),
            )
        }
        self.group = TeamGroup.objects.create(team=self.team, name='Group')
        self.group.members.set([self.memberships['athlete'], self.memberships['invited']])

        # A public template, so that only the membership decides who may assign
        self.template = self.make_template(self.users['coach'], is_public=True)
        self.assignments = {
            'team': self.assign(0, team=self.team),
            'group': self.assign(1, group=self.group),
            'athlete': self.assign(2, athlete=self.users['athlete']),
        }

        # The foreign team
        foreign_coach = self.users['foreign_coach']
        self.foreign_athlete = User.objects.create_user(username='fa', email='fa@example.com')
        self.foreign_team = Team.objects.create(name='Foreign', created_by=foreign_coach)
        TeamMembership.objects.create(
            team=self.foreign_team, user=foreign_coach, role=coach, status=active
        )
        self.foreign_membership = TeamMembership.objects.create(
            team=self.foreign_team, user=self.foreign_athlete, role=athlete, status=active
        )
        self.foreign_group = TeamGroup.objects.create(team=self.foreign_team, name='Foreign')
        self.foreign_group.members.set([self.foreign_membership])
        self.foreign_template = self.make_template(foreign_coach, is_public=False)

        self.cocoach = User.objects.create_user(username='cocoach', email='cc@example.com')
        TeamMembership.objects.create(
            team=self.foreign_team, user=self.cocoach, role=athlete, status=active
        )
        TeamMembership.objects.create(team=self.team, user=self.cocoach, role=coach, status=active)
        TeamMembership.objects.create(
            team=self.team, user=self.foreign_athlete, role=athlete, status=invited
        )
        for index, user in enumerate((self.foreign_athlete, self.cocoach)):
            assign_program(
                template=self.foreign_template,
                assigned_by=foreign_coach,
                athlete=user,
                **self.period(index),
            )

    @staticmethod
    def make_template(user, is_public):
        return Routine.objects.create(
            user=user,
            name='Template',
            is_template=True,
            is_public=is_public,
            start=datetime.date(2026, 11, 1),
            end=datetime.date(2026, 11, 30),
        )

    @staticmethod
    def period(index: int) -> dict:
        """
        Non-overlapping periods, so the overlap check never decides a case.
        """
        start = datetime.date(2026, 1, 1) + datetime.timedelta(days=40 * index)
        return {'start_date': start, 'end_date': start + datetime.timedelta(days=30)}

    def assign(self, index, **target):
        return assign_program(
            template=self.template,
            assigned_by=self.users['coach'],
            **self.period(index),
            **target,
        )

    def assignment_payload(self, **target):
        return {'template': self.template.pk, **self.period(5), **target}

    def request_as(self, role, method, url, payload=None):
        """
        Runs one request as the given role and rolls back whatever it changed.
        """
        self.client.force_authenticate(user=self.users.get(role))
        with transaction.atomic():
            response = getattr(self.client, method)(url, payload, format='json')
            transaction.set_rollback(True)
        return response

    def check_matrix(self, cases):
        for label, method, url, payload, expected in cases:
            for role in ROLES:
                with self.subTest(case=label, role=role):
                    response = self.request_as(role, method, url, payload)
                    self.assertEqual(response.status_code, expected[role])

    def check_list_counts(self, name, expected):
        for role in ROLES:
            with self.subTest(endpoint=name, role=role):
                response = self.request_as(role, 'get', reverse(name))
                if expected[role] is None:
                    self.assertEqual(response.status_code, 403)
                else:
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(response.data['count'], expected[role])

    def test_team_endpoint(self):
        """
        Members read the team, only the active coach changes or deletes it.
        """
        detail = reverse('team-detail', kwargs={'pk': self.team.pk})
        self.check_matrix(
            [
                (
                    'read',
                    'get',
                    detail,
                    None,
                    expect(200, anonymous=403, outsider=404, foreign_coach=404),
                ),
                (
                    'patch',
                    'patch',
                    detail,
                    {'name': 'Changed'},
                    expect(403, outsider=404, foreign_coach=404, coach=200),
                ),
                (
                    'put',
                    'put',
                    detail,
                    {'name': 'Changed'},
                    expect(403, outsider=404, foreign_coach=404, coach=200),
                ),
                (
                    'delete',
                    'delete',
                    detail,
                    None,
                    expect(403, outsider=404, foreign_coach=404, coach=204),
                ),
                # Everybody can found an own team
                (
                    'create',
                    'post',
                    reverse('team-list'),
                    {'name': 'New'},
                    expect(201, anonymous=403),
                ),
            ]
        )
        self.check_list_counts('team-list', expect(1, anonymous=None, outsider=0))

    def test_membership_endpoint(self):
        """
        The coach manages memberships, users only read their own one and only the invited
        user answers an invitation.
        """
        detail = reverse('team-membership-detail', kwargs={'pk': self.memberships['athlete2'].pk})
        invitation = {'pk': self.memberships['invited'].pk}
        new = {'team': self.team.pk, 'user': self.new_user.pk, 'role': 'athlete'}
        self.check_matrix(
            [
                ('read', 'get', detail, None, expect(404, anonymous=403, athlete2=200, coach=200)),
                (
                    'patch',
                    'patch',
                    detail,
                    {'role': 'coach'},
                    expect(404, anonymous=403, athlete2=403, coach=200),
                ),
                (
                    'delete',
                    'delete',
                    detail,
                    None,
                    expect(404, anonymous=403, athlete2=403, coach=204),
                ),
                ('create', 'post', reverse('team-membership-list'), new, expect(403, coach=201)),
                (
                    'accept',
                    'post',
                    reverse('team-membership-accept', kwargs=invitation),
                    None,
                    expect(404, anonymous=403, coach=403, invited=200),
                ),
                (
                    'decline',
                    'post',
                    reverse('team-membership-decline', kwargs=invitation),
                    None,
                    expect(404, anonymous=403, coach=403, invited=204),
                ),
            ]
        )
        self.check_list_counts(
            'team-membership-list',
            expect(1, anonymous=None, outsider=0, foreign_coach=3, coach=7),
        )

    def test_group_endpoint(self):
        """
        The coach manages groups, the members of a group read it.
        """
        detail = reverse('team-group-detail', kwargs={'pk': self.group.pk})
        new = {'team': self.team.pk, 'name': 'New'}
        self.check_matrix(
            [
                ('read', 'get', detail, None, expect(404, anonymous=403, athlete=200, coach=200)),
                (
                    'patch',
                    'patch',
                    detail,
                    {'name': 'Changed'},
                    expect(404, anonymous=403, athlete=403, coach=200),
                ),
                (
                    'delete',
                    'delete',
                    detail,
                    None,
                    expect(404, anonymous=403, athlete=403, coach=204),
                ),
                ('create', 'post', reverse('team-group-list'), new, expect(403, coach=201)),
            ]
        )
        self.check_list_counts(
            'team-group-list',
            expect(0, anonymous=None, foreign_coach=1, athlete=1, coach=1),
        )

    def test_assignment_endpoint(self):
        """
        The coach assigns, archives and reads the progress. Athletes read the assignments
        they received a copy of and nothing else.
        """

        def url(name, key):
            return reverse(f'program-assignment-{name}', kwargs={'pk': self.assignments[key].pk})

        hidden = {'anonymous': 403, 'coach': 200, 'athlete': 200}
        create = reverse('program-assignment-list')
        self.check_matrix(
            [
                (
                    'read team',
                    'get',
                    url('detail', 'team'),
                    None,
                    expect(404, athlete2=200, **hidden),
                ),
                ('read group', 'get', url('detail', 'group'), None, expect(404, **hidden)),
                ('read athlete', 'get', url('detail', 'athlete'), None, expect(404, **hidden)),
                (
                    'archive',
                    'post',
                    url('archive', 'team'),
                    None,
                    expect(404, anonymous=403, athlete=403, athlete2=403, coach=200),
                ),
                (
                    'progress',
                    'get',
                    url('progress', 'team'),
                    None,
                    expect(404, anonymous=403, athlete=403, athlete2=403, coach=200),
                ),
                (
                    'archive athlete',
                    'post',
                    url('archive', 'athlete'),
                    None,
                    expect(404, anonymous=403, athlete=403, coach=200),
                ),
                (
                    'progress athlete',
                    'get',
                    url('progress', 'athlete'),
                    None,
                    expect(404, anonymous=403, athlete=403, coach=200),
                ),
                (
                    'assign to team',
                    'post',
                    create,
                    self.assignment_payload(team=self.team.pk),
                    expect(403, coach=201),
                ),
                (
                    'assign to group',
                    'post',
                    create,
                    self.assignment_payload(group=self.group.pk),
                    expect(403, coach=201),
                ),
                (
                    'assign to athlete',
                    'post',
                    create,
                    self.assignment_payload(athlete=self.users['athlete2'].pk),
                    expect(403, coach=201),
                ),
            ]
        )
        self.check_list_counts(
            'program-assignment-list',
            expect(0, anonymous=None, foreign_coach=2, athlete=3, athlete2=1, coach=3),
        )

    def test_assignment_cannot_be_changed_or_deleted(self):
        """
        No role can change or delete an assignment, the copies stay.
        """
        detail = reverse('program-assignment-detail', kwargs={'pk': self.assignments['team'].pk})
        for method in ('put', 'patch', 'delete'):
            for role in ROLES:
                with self.subTest(method=method, role=role):
                    response = self.client_request(role, method, detail)
                    self.assertIn(response.status_code, (403, 405))

        self.assertEqual(
            ProgramAssignment.objects.filter(assigned_by=self.users['coach']).count(), 3
        )
        self.assertEqual(
            AssignedRoutine.objects.filter(
                routine__isnull=False, assignment__assigned_by=self.users['coach']
            ).count(),
            4,
        )

    def client_request(self, role, method, url, payload=None):
        """
        Like request_as, but without rollback.
        """
        self.client.force_authenticate(user=self.users.get(role))
        return getattr(self.client, method)(url, payload, format='json')

    def test_foreign_ids(self):
        """
        A coach cannot reach into another team by putting its ids into a payload.
        """
        athlete_membership = self.memberships['athlete']
        cases = (
            (
                'membership in foreign team',
                'team-membership-list',
                {'team': self.foreign_team.pk, 'user': self.new_user.pk, 'role': 'coach'},
                403,
            ),
            (
                'group in foreign team',
                'team-group-list',
                {'team': self.foreign_team.pk, 'name': 'New'},
                403,
            ),
            (
                'foreign membership in own group',
                'team-group-list',
                {'team': self.team.pk, 'name': 'New', 'members': [self.foreign_membership.pk]},
                400,
            ),
            (
                'assign to foreign team',
                'program-assignment-list',
                self.assignment_payload(team=self.foreign_team.pk),
                403,
            ),
            (
                'assign to foreign group',
                'program-assignment-list',
                self.assignment_payload(group=self.foreign_group.pk),
                403,
            ),
            (
                'assign to foreign athlete',
                'program-assignment-list',
                self.assignment_payload(athlete=self.foreign_athlete.pk),
                403,
            ),
            (
                'assign to invited athlete',
                'program-assignment-list',
                self.assignment_payload(athlete=self.users['invited'].pk),
                403,
            ),
            (
                'assign to coach of the team',
                'program-assignment-list',
                self.assignment_payload(athlete=self.cocoach.pk),
                403,
            ),
            (
                'assign to user without team',
                'program-assignment-list',
                self.assignment_payload(athlete=self.users['outsider'].pk),
                403,
            ),
            (
                'assign foreign private template',
                'program-assignment-list',
                {
                    **self.assignment_payload(team=self.team.pk),
                    'template': self.foreign_template.pk,
                },
                403,
            ),
            (
                'unknown team',
                'program-assignment-list',
                self.assignment_payload(team=0),
                400,
            ),
            (
                'malformed athlete',
                'program-assignment-list',
                self.assignment_payload(athlete='abc'),
                400,
            ),
        )

        counts = self.object_counts()
        for label, name, payload, expected in cases:
            with self.subTest(case=label):
                response = self.client_request('coach', 'post', reverse(name), payload)
                self.assertEqual(response.status_code, expected)
        self.assertEqual(self.object_counts(), counts)

        # Moving a membership or a group into another team
        for name, pk in (
            ('team-membership-detail', athlete_membership.pk),
            ('team-group-detail', self.group.pk),
        ):
            with self.subTest(case=f'move {name}'):
                response = self.client_request(
                    'coach',
                    'patch',
                    reverse(name, kwargs={'pk': pk}),
                    {'team': self.foreign_team.pk},
                )
                self.assertEqual(response.status_code, 400)
        athlete_membership.refresh_from_db()
        self.group.refresh_from_db()
        self.assertEqual(athlete_membership.team, self.team)
        self.assertEqual(self.group.team, self.team)

    @staticmethod
    def object_counts() -> tuple:
        return (
            TeamMembership.objects.count(),
            TeamGroup.objects.count(),
            ProgramAssignment.objects.count(),
            AssignedRoutine.objects.count(),
            Routine.objects.count(),
        )
