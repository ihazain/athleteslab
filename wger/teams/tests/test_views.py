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

# wger
from wger.core.tests.base_testcase import WgerTestCase
from wger.manager.models import Routine
from wger.teams.models import (
    AssignedRoutine,
    Team,
    TeamMembership,
)
from wger.teams.services import (
    archive_assignment,
    assign_program,
)
from wger.teams.templatetags.brand import (
    BRAND_NAME,
    brand_title,
)


class AthleteOverviewTestCase(WgerTestCase):
    """
    Tests for the athlete page: invitations, teams and assigned programs of the user.
    """

    def setUp(self):
        super().setUp()
        self.coach = User.objects.create_user(username='coach', email='coach@example.com')
        self.athlete = User.objects.create_user(username='athlete', email='athlete@example.com')
        self.other = User.objects.create_user(username='other', email='other@example.com')

        self.team = self.make_team('Lions')
        self.inviting_team = self.make_team('Tigers')
        self.foreign_team = self.make_team('Sharks')
        self.membership = self.add(self.team, self.athlete, TeamMembership.Status.ACTIVE)
        self.invitation = self.add(self.inviting_team, self.athlete)
        self.other_invitation = self.add(self.foreign_team, self.other)

        self.template = Routine.objects.create(
            user=self.coach,
            name='Strength block',
            is_template=True,
            start=datetime.date(2026, 11, 1),
            end=datetime.date(2026, 11, 30),
        )
        self.url = reverse('teams:overview')

    def make_team(self, name: str) -> Team:
        team = Team.objects.create(name=name, created_by=self.coach)
        TeamMembership.objects.create(
            team=team,
            user=self.coach,
            role=TeamMembership.Role.COACH,
            status=TeamMembership.Status.ACTIVE,
        )
        return team

    @staticmethod
    def add(team, user, status=TeamMembership.Status.INVITED) -> TeamMembership:
        return TeamMembership.objects.create(
            team=team, user=user, role=TeamMembership.Role.ATHLETE, status=status
        )

    def assign(self, start: datetime.date, **target):
        return assign_program(
            template=self.template,
            assigned_by=self.coach,
            start_date=start,
            end_date=start + datetime.timedelta(days=27),
            **target,
        )

    def test_login_required(self):
        """
        Anonymous users are sent to the login, for the page and for both answers.
        """
        answer = {'pk': self.invitation.pk}
        for response in (
            self.client.get(self.url),
            self.client.post(reverse('teams:invitation-accept', kwargs=answer)),
            self.client.post(reverse('teams:invitation-decline', kwargs=answer)),
        ):
            self.assertEqual(response.status_code, 302)
            self.assertIn('login', response.url)

        self.invitation.refresh_from_db()
        self.assertEqual(self.invitation.status, TeamMembership.Status.INVITED)

    def test_overview_shows_only_own_data(self):
        """
        The page lists the invitations, teams and programs of the user and nothing of others.
        """
        own = self.assign(datetime.date(2026, 11, 2), team=self.team)
        TeamMembership.objects.filter(pk=self.other_invitation.pk).update(
            status=TeamMembership.Status.ACTIVE
        )
        foreign = self.assign(datetime.date(2027, 1, 4), team=self.foreign_team)

        self.client.force_login(self.athlete)
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(list(response.context['invitations']), [self.invitation])
        self.assertEqual(list(response.context['memberships']), [self.membership])
        programs = list(response.context['programs'])
        self.assertEqual([p.assignment for p in programs], [own])
        self.assertEqual(programs[0].athlete, self.athlete)
        self.assertNotIn(foreign, [p.assignment for p in programs])

        self.assertContains(response, 'Lions')
        self.assertContains(response, 'Tigers')
        self.assertContains(response, 'Strength block')
        self.assertContains(response, programs[0].routine.get_absolute_url())
        self.assertContains(response, reverse('teams:invitation-accept', args=[self.invitation.pk]))
        self.assertNotContains(response, 'Sharks')
        self.assertNotContains(
            response, reverse('teams:invitation-accept', args=[self.other_invitation.pk])
        )

    def test_overview_marks_archived_and_deleted_programs(self):
        """
        Archived programs and programs whose copy was deleted stay listed and are marked.
        """
        archived = self.assign(datetime.date(2026, 11, 2), team=self.team)
        archive_assignment(archived)
        deleted = self.assign(datetime.date(2026, 12, 7), athlete=self.athlete)
        AssignedRoutine.objects.get(assignment=deleted).routine.delete()

        self.client.force_login(self.athlete)
        response = self.client.get(self.url)

        programs = {p.assignment: p for p in response.context['programs']}
        self.assertEqual(set(programs), {archived, deleted})
        self.assertIsNone(programs[deleted].routine)
        self.assertContains(response, 'Withdrawn by the coach')
        self.assertContains(response, 'You deleted this routine')

    def test_empty_overview(self):
        """
        A user without invitations, teams and programs gets the page with empty lists.
        """
        user = User.objects.create_user(username='nobody', email='nobody@example.com')
        self.client.force_login(user)
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        for key in ('invitations', 'memberships', 'programs'):
            self.assertEqual(len(response.context[key]), 0, key)

    def test_accept_invitation(self):
        """
        Accepting activates the membership and returns to the page, only with POST.
        """
        url = reverse('teams:invitation-accept', kwargs={'pk': self.invitation.pk})
        self.client.force_login(self.athlete)

        self.assertEqual(self.client.get(url).status_code, 405)
        self.invitation.refresh_from_db()
        self.assertEqual(self.invitation.status, TeamMembership.Status.INVITED)

        response = self.client.post(url)
        self.assertRedirects(response, self.url)
        self.invitation.refresh_from_db()
        self.assertEqual(self.invitation.status, TeamMembership.Status.ACTIVE)

    def test_decline_invitation(self):
        """
        Declining removes the invitation and returns to the page, only with POST.
        """
        url = reverse('teams:invitation-decline', kwargs={'pk': self.invitation.pk})
        self.client.force_login(self.athlete)

        self.assertEqual(self.client.get(url).status_code, 405)
        self.assertTrue(TeamMembership.objects.filter(pk=self.invitation.pk).exists())

        response = self.client.post(url)
        self.assertRedirects(response, self.url)
        self.assertFalse(TeamMembership.objects.filter(pk=self.invitation.pk).exists())

    def test_cannot_answer_invitation_of_another_user(self):
        """
        The invitation of another user answers 404 and stays untouched, also for the coach.
        """
        answer = {'pk': self.other_invitation.pk}
        for user in (self.athlete, self.coach):
            self.client.force_login(user)
            for name in ('teams:invitation-accept', 'teams:invitation-decline'):
                response = self.client.post(reverse(name, kwargs=answer))
                self.assertEqual(response.status_code, 404, (user, name))

        self.other_invitation.refresh_from_db()
        self.assertEqual(self.other_invitation.status, TeamMembership.Status.INVITED)

    def test_active_membership_cannot_be_declined(self):
        """
        Answering a membership that is already active changes nothing and shows an error.
        """
        self.client.force_login(self.athlete)
        for name in ('teams:invitation-accept', 'teams:invitation-decline'):
            response = self.client.post(
                reverse(name, kwargs={'pk': self.membership.pk}), follow=True
            )
            self.assertRedirects(response, self.url)
            messages = [m for m in response.context['messages']]
            self.assertEqual([m.level_tag for m in messages], ['error'], name)

        self.membership.refresh_from_db()
        self.assertEqual(self.membership.status, TeamMembership.Status.ACTIVE)


class BrandTestCase(WgerTestCase):
    """
    Tests for the product name and logo in the page frame.
    """

    def test_brand_title(self):
        """
        The browser title is the page title followed by the product name, or the name alone.
        """
        self.assertEqual(brand_title('  Teams\n '), f'Teams | {BRAND_NAME}')
        self.assertEqual(brand_title(' \n '), BRAND_NAME)

    def test_page_frame_shows_brand(self):
        """
        Pages show the product name and logo in the navigation, the logo as icon and the
        product name in the title, with the page title escaped once.
        """
        user = User.objects.create_user(username='coach', email='coach@example.com')
        team = Team.objects.create(name='A&B <U18>', created_by=user)
        TeamMembership.objects.create(
            team=team,
            user=user,
            role=TeamMembership.Role.COACH,
            status=TeamMembership.Status.ACTIVE,
        )
        self.client.force_login(user)

        response = self.client.get(reverse('teams:overview'))
        self.assertContains(response, f'<title>Teams | {BRAND_NAME}</title>')
        self.assertContains(response, 'teams/brand/icon-inverse.svg', count=1)
        self.assertContains(response, 'teams/brand/icon-app.svg', count=1)
        self.assertContains(response, f'<span class="alp-wordmark">{BRAND_NAME}</span>')
        self.assertContains(response, 'teams/brand/navbar.css')
        self.assertNotContains(response, 'wger logo')

        response = self.client.get(reverse('teams:team-detail', kwargs={'pk': team.pk}))
        self.assertContains(response, f'<title>A&amp;B &lt;U18&gt; | {BRAND_NAME}</title>')
