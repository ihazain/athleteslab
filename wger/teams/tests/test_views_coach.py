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

# Django
from django.contrib.auth.models import User
from django.urls import reverse

# wger
from wger.core.tests.base_testcase import WgerTestCase
from wger.teams.models import (
    Team,
    TeamMembership,
)


ACTIVE = TeamMembership.Status.ACTIVE
INVITED = TeamMembership.Status.INVITED
COACH = TeamMembership.Role.COACH
ATHLETE = TeamMembership.Role.ATHLETE


class CoachTeamTestCase(WgerTestCase):
    """
    Tests for the coach pages: creating a team and managing its members.
    """

    def setUp(self):
        super().setUp()
        self.coach = User.objects.create_user(username='coach', email='coach@example.com')
        self.athlete = User.objects.create_user(username='athlete', email='athlete@example.com')
        self.invited = User.objects.create_user(username='invited', email='invited@example.com')
        self.new = User.objects.create_user(username='Newbie', email='New@Example.com')
        self.outsider = User.objects.create_user(username='outsider', email='out@example.com')

        self.team = Team.objects.create(name='Lions', created_by=self.coach)
        self.memberships = {
            user.username: TeamMembership.objects.create(
                team=self.team, user=user, role=role, status=status
            )
            for user, role, status in (
                (self.coach, COACH, ACTIVE),
                (self.athlete, ATHLETE, ACTIVE),
                (self.invited, ATHLETE, INVITED),
            )
        }
        self.detail = reverse('teams:team-detail', kwargs={'pk': self.team.pk})
        self.client.force_login(self.coach)

    def url(self, name: str, **kwargs) -> str:
        return reverse(f'teams:{name}', kwargs=kwargs or {'pk': self.team.pk})

    def member_url(self, name: str, username: str) -> str:
        return self.url(name, pk=self.team.pk, membership_pk=self.memberships[username].pk)

    def error_messages(self, response) -> list:
        return [str(m) for m in response.context['messages'] if m.level_tag == 'error']

    def test_create_team(self):
        """
        Creating a team makes the user its active coach and opens the team page.
        """
        response = self.client.post(reverse('teams:team-add'), {'name': 'Tigers'})

        team = Team.objects.get(name='Tigers')
        self.assertRedirects(response, self.url('team-detail', pk=team.pk))
        self.assertEqual(team.created_by, self.coach)
        membership = TeamMembership.objects.get(team=team)
        self.assertEqual(
            (membership.user, membership.role, membership.status), (self.coach, COACH, ACTIVE)
        )

    def test_create_team_without_name(self):
        """
        An empty name creates nothing and shows an error.
        """
        response = self.client.post(reverse('teams:team-add'), {'name': '  '}, follow=True)

        self.assertEqual(Team.objects.count(), 1)
        self.assertEqual(len(self.error_messages(response)), 1)

    def test_team_page_lists_members(self):
        """
        The coach sees all members of the team with role and status, and a link from the
        overview.
        """
        response = self.client.get(self.detail)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['team'], self.team)
        self.assertEqual(
            {m.user.username: (m.role, m.status) for m in response.context['memberships']},
            {'coach': (COACH, ACTIVE), 'athlete': (ATHLETE, ACTIVE), 'invited': (ATHLETE, INVITED)},
        )
        # Active members first, coaches before athletes
        self.assertEqual(
            [m.user.username for m in response.context['memberships']],
            ['coach', 'athlete', 'invited'],
        )
        for username in ('coach', 'athlete', 'invited'):
            self.assertContains(response, username)
        self.assertNotContains(response, 'outsider')

        self.assertContains(self.client.get(reverse('teams:overview')), self.detail)

    def test_team_pages_are_for_coaches_only(self):
        """
        Athletes, invited users and outsiders get 404 for the team page and every action,
        anonymous users are sent to the login. Nothing changes.
        """
        posts = (
            (self.url('team-edit'), {'name': 'Hacked'}),
            (self.url('team-delete'), {}),
            (self.url('member-invite'), {'identifier': 'outsider', 'role': COACH}),
            (self.member_url('member-role', 'athlete'), {'role': COACH}),
            (self.member_url('member-remove', 'coach'), {}),
        )
        invited_coach = User.objects.create_user(username='second', email='second@example.com')
        TeamMembership.objects.create(team=self.team, user=invited_coach, role=COACH)

        for user in (self.athlete, self.invited, invited_coach, self.outsider):
            self.client.force_login(user)
            self.assertEqual(self.client.get(self.detail).status_code, 404, user)
            for url, data in posts:
                self.assertEqual(self.client.post(url, data).status_code, 404, (user, url))
            self.assertNotContains(self.client.get(reverse('teams:overview')), self.detail)

        self.client.logout()
        for response in [self.client.get(self.detail)] + [
            self.client.post(url, data) for url, data in posts
        ]:
            self.assertEqual(response.status_code, 302)
            self.assertIn('login', response.url)

        self.team.refresh_from_db()
        self.assertEqual(self.team.name, 'Lions')
        self.assertEqual(
            {m.user.username: m.role for m in self.team.memberships.all()},
            {'coach': COACH, 'athlete': ATHLETE, 'invited': ATHLETE, 'second': COACH},
        )

    def test_actions_need_post(self):
        """
        The actions answer 405 for GET and change nothing.
        """
        for url in (
            reverse('teams:team-add'),
            self.url('team-edit'),
            self.url('team-delete'),
            self.url('member-invite'),
            self.member_url('member-role', 'athlete'),
            self.member_url('member-remove', 'athlete'),
        ):
            self.assertEqual(self.client.get(url).status_code, 405, url)
        self.assertEqual(self.team.memberships.count(), 3)

    def test_invite_by_username_or_email(self):
        """
        A user is invited by username or e-mail, ignoring case, and starts as invited.
        """
        other = User.objects.create_user(username='second', email='second@example.com')
        for identifier, user, role in (
            ('newbie', self.new, ATHLETE),
            (' SECOND@example.com ', other, COACH),
        ):
            response = self.client.post(
                self.url('member-invite'), {'identifier': identifier, 'role': role}
            )
            self.assertRedirects(response, self.detail)
            membership = TeamMembership.objects.get(team=self.team, user=user)
            self.assertEqual((membership.role, membership.status), (role, INVITED))

    def test_invite_errors(self):
        """
        Unknown users, existing members and invalid roles create nothing and show an error.
        """
        for data in (
            {'identifier': 'nobody', 'role': ATHLETE},
            {'identifier': 'athlete', 'role': ATHLETE},
            {'identifier': 'invited', 'role': COACH},
            {'identifier': 'newbie', 'role': 'owner'},
            {'identifier': '', 'role': ATHLETE},
        ):
            response = self.client.post(self.url('member-invite'), data, follow=True)
            self.assertRedirects(response, self.detail)
            self.assertEqual(len(self.error_messages(response)), 1, data)

        self.assertEqual(self.team.memberships.count(), 3)
        self.assertEqual(self.memberships['invited'].role, ATHLETE)

    def test_change_role(self):
        """
        The coach promotes an athlete, the last active coach cannot be demoted.
        """
        response = self.client.post(self.member_url('member-role', 'athlete'), {'role': COACH})
        self.assertRedirects(response, self.detail)
        self.memberships['athlete'].refresh_from_db()
        self.assertEqual(self.memberships['athlete'].role, COACH)

        self.client.post(self.member_url('member-role', 'athlete'), {'role': ATHLETE})
        self.memberships['athlete'].refresh_from_db()
        self.assertEqual(self.memberships['athlete'].role, ATHLETE)

        for username, role in (('coach', ATHLETE), ('athlete', 'owner'), ('athlete', '')):
            url = self.member_url('member-role', username)
            before = self.memberships[username].role
            response = self.client.post(url, {'role': role}, follow=True)
            self.assertEqual(len(self.error_messages(response)), 1, (username, role))
            self.memberships[username].refresh_from_db()
            self.assertEqual(self.memberships[username].role, before)

    def test_remove_member(self):
        """
        The coach removes athletes and open invitations, but not the last active coach.
        """
        for username in ('athlete', 'invited'):
            response = self.client.post(self.member_url('member-remove', username))
            self.assertRedirects(response, self.detail)
            self.assertFalse(
                TeamMembership.objects.filter(pk=self.memberships[username].pk).exists()
            )

        response = self.client.post(self.member_url('member-remove', 'coach'), follow=True)
        self.assertEqual(len(self.error_messages(response)), 1)
        self.assertTrue(TeamMembership.objects.filter(pk=self.memberships['coach'].pk).exists())

    def test_membership_of_another_team(self):
        """
        A membership that belongs to another team answers 404 and stays untouched.
        """
        other_team = Team.objects.create(name='Sharks', created_by=self.outsider)
        TeamMembership.objects.create(
            team=other_team, user=self.outsider, role=COACH, status=ACTIVE
        )
        foreign = TeamMembership.objects.create(
            team=other_team, user=self.new, role=ATHLETE, status=ACTIVE
        )
        kwargs = {'pk': self.team.pk, 'membership_pk': foreign.pk}

        response = self.client.post(self.url('member-role', **kwargs), {'role': COACH})
        self.assertEqual(response.status_code, 404)
        response = self.client.post(self.url('member-remove', **kwargs))
        self.assertEqual(response.status_code, 404)

        foreign.refresh_from_db()
        self.assertEqual(foreign.role, ATHLETE)

    def test_rename_and_delete_team(self):
        """
        The coach renames the team (not to an empty name) and deletes it.
        """
        response = self.client.post(self.url('team-edit'), {'name': 'Panthers'})
        self.assertRedirects(response, self.detail)
        self.team.refresh_from_db()
        self.assertEqual(self.team.name, 'Panthers')

        response = self.client.post(self.url('team-edit'), {'name': ''}, follow=True)
        self.assertEqual(len(self.error_messages(response)), 1)
        self.team.refresh_from_db()
        self.assertEqual(self.team.name, 'Panthers')

        response = self.client.post(self.url('team-delete'))
        self.assertRedirects(response, reverse('teams:overview'))
        self.assertFalse(Team.objects.filter(pk=self.team.pk).exists())
