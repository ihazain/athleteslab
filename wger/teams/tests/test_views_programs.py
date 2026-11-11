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

# wger
from wger.core.tests.base_testcase import WgerTestCase
from wger.manager.models import (
    Routine,
    WorkoutLog,
)
from wger.teams.models import (
    AssignedRoutine,
    ProgramAssignment,
    Team,
    TeamGroup,
    TeamMembership,
)
from wger.teams.services import (
    archive_assignment,
    assign_program,
)


ACTIVE = TeamMembership.Status.ACTIVE
INVITED = TeamMembership.Status.INVITED
COACH = TeamMembership.Role.COACH
ATHLETE = TeamMembership.Role.ATHLETE


class CoachProgramBaseTestCase(WgerTestCase):
    """
    A team with a coach, two active athletes and an invited one, and a second team.
    """

    def setUp(self):
        super().setUp()
        self.coach = self.make_user('coach')
        self.athlete1 = self.make_user('athlete1')
        self.athlete2 = self.make_user('athlete2')
        self.invited = self.make_user('invited')
        self.other_coach = self.make_user('othercoach')
        self.foreign_athlete = self.make_user('foreignathlete')

        self.team = Team.objects.create(name='Lions', created_by=self.coach)
        self.memberships = {
            user.username: TeamMembership.objects.create(
                team=self.team, user=user, role=role, status=status
            )
            for user, role, status in (
                (self.coach, COACH, ACTIVE),
                (self.athlete1, ATHLETE, ACTIVE),
                (self.athlete2, ATHLETE, ACTIVE),
                (self.invited, ATHLETE, INVITED),
            )
        }
        self.other_team = Team.objects.create(name='Sharks', created_by=self.other_coach)
        TeamMembership.objects.create(
            team=self.other_team, user=self.other_coach, role=COACH, status=ACTIVE
        )
        self.foreign_membership = TeamMembership.objects.create(
            team=self.other_team, user=self.foreign_athlete, role=ATHLETE, status=ACTIVE
        )

        self.template = self.make_template(self.coach, 'Strength block')
        self.public_template = self.make_template(self.other_coach, 'Public plan', is_public=True)
        self.private_template = self.make_template(self.other_coach, 'Secret plan')

        self.detail = reverse('teams:team-detail', kwargs={'pk': self.team.pk})
        self.client.force_login(self.coach)

    @staticmethod
    def make_user(username: str) -> User:
        return User.objects.create_user(username=username, email=f'{username}@example.com')

    @staticmethod
    def make_template(user, name: str, is_public: bool = False) -> Routine:
        return Routine.objects.create(
            user=user,
            name=name,
            is_template=True,
            is_public=is_public,
            start=datetime.date(2026, 11, 1),
            end=datetime.date(2026, 11, 30),
        )

    def error_messages(self, response) -> list:
        return [str(m) for m in response.context['messages'] if m.level_tag == 'error']


class CoachGroupTestCase(CoachProgramBaseTestCase):
    """
    Tests for managing the groups of a team on the team page.
    """

    def add_url(self) -> str:
        return reverse('teams:group-add', kwargs={'pk': self.team.pk})

    def group_url(self, name: str, group: TeamGroup) -> str:
        return reverse(f'teams:{name}', kwargs={'pk': self.team.pk, 'group_pk': group.pk})

    def make_group(self, *usernames: str) -> TeamGroup:
        group = TeamGroup.objects.create(team=self.team, name='Goalkeepers')
        group.members.set([self.memberships[username] for username in usernames])
        return group

    def test_create_group(self):
        """
        The coach creates a group with athletes of the team, it shows up on the team page.
        """
        members = [self.memberships['athlete1'].pk, self.memberships['invited'].pk]
        response = self.client.post(self.add_url(), {'name': 'Goalkeepers', 'members': members})

        self.assertRedirects(response, self.detail)
        group = TeamGroup.objects.get(team=self.team)
        self.assertEqual(group.name, 'Goalkeepers')
        self.assertEqual({m.user for m in group.members.all()}, {self.athlete1, self.invited})

        response = self.client.get(self.detail)
        self.assertEqual([entry['group'] for entry in response.context['groups']], [group])
        self.assertContains(response, 'Goalkeepers')

    def test_group_errors(self):
        """
        A missing or duplicate name, a coach or a membership of another team as member create
        nothing and show an error.
        """
        self.make_group('athlete1')
        for data in (
            {'name': ''},
            {'name': 'Goalkeepers'},
            {'name': 'Coaches', 'members': [self.memberships['coach'].pk]},
            {'name': 'Foreign', 'members': [self.foreign_membership.pk]},
        ):
            response = self.client.post(self.add_url(), data, follow=True)
            self.assertEqual(len(self.error_messages(response)), 1, data)

        self.assertEqual(TeamGroup.objects.count(), 1)

    def test_edit_group(self):
        """
        The coach renames a group and replaces its members, not with a foreign membership
        and not to the name of another group.
        """
        group = self.make_group('athlete1')
        TeamGroup.objects.create(team=self.team, name='Strikers')
        url = self.group_url('group-edit', group)
        prefix = f'group-{group.pk}'

        response = self.client.post(
            url,
            {f'{prefix}-name': 'Keepers', f'{prefix}-members': [self.memberships['athlete2'].pk]},
        )
        self.assertRedirects(response, self.detail)
        group.refresh_from_db()
        self.assertEqual(group.name, 'Keepers')
        self.assertEqual([m.user for m in group.members.all()], [self.athlete2])

        # Keeping the name while changing the members is not a duplicate
        both = [self.memberships['athlete1'].pk, self.memberships['athlete2'].pk]
        response = self.client.post(
            url, {f'{prefix}-name': 'Keepers', f'{prefix}-members': both}, follow=True
        )
        self.assertEqual(self.error_messages(response), [])
        self.assertEqual(group.members.count(), 2)
        group.members.set([self.memberships['athlete2']])

        for data in (
            {f'{prefix}-name': 'Strikers'},
            {f'{prefix}-name': 'Keepers', f'{prefix}-members': [self.foreign_membership.pk]},
        ):
            response = self.client.post(url, data, follow=True)
            self.assertEqual(len(self.error_messages(response)), 1, data)

        group.refresh_from_db()
        self.assertEqual(group.name, 'Keepers')
        self.assertEqual([m.user for m in group.members.all()], [self.athlete2])

    def test_delete_group_keeps_assignment(self):
        """
        Deleting a group keeps the assignment made to it and the copy of the athlete.
        """
        group = self.make_group('athlete1')
        assignment = assign_program(
            template=self.template,
            assigned_by=self.coach,
            start_date=datetime.date(2026, 11, 2),
            end_date=datetime.date(2026, 11, 29),
            group=group,
        )

        response = self.client.post(self.group_url('group-delete', group))

        self.assertRedirects(response, self.detail)
        self.assertFalse(TeamGroup.objects.exists())
        assignment.refresh_from_db()
        self.assertEqual(assignment.team, self.team)
        self.assertEqual(assignment.assigned_routines.filter(routine__isnull=False).count(), 1)

    def test_groups_are_for_coaches_of_the_team_only(self):
        """
        Athletes and coaches of other teams get 404, a group of another team as well, GET is
        not allowed. Nothing changes.
        """
        group = self.make_group('athlete1')
        foreign_group = TeamGroup.objects.create(team=self.other_team, name='Foreign')
        urls = (
            self.add_url(),
            self.group_url('group-edit', group),
            self.group_url('group-delete', group),
        )
        for url in urls:
            self.assertEqual(self.client.get(url).status_code, 405, url)
        for name in ('group-edit', 'group-delete'):
            response = self.client.post(self.group_url(name, foreign_group), {'name': 'Mine'})
            self.assertEqual(response.status_code, 404, name)

        for user in (self.athlete1, self.other_coach):
            self.client.force_login(user)
            for url in urls:
                response = self.client.post(url, {'name': 'Hacked'})
                self.assertEqual(response.status_code, 404, (user, url))

        self.assertEqual(
            sorted(TeamGroup.objects.values_list('name', flat=True)), ['Foreign', 'Goalkeepers']
        )


class CoachAssignTestCase(CoachProgramBaseTestCase):
    """
    Tests for the page that assigns a program.
    """

    def setUp(self):
        super().setUp()
        self.url = reverse('teams:assign', kwargs={'pk': self.team.pk})
        self.group = TeamGroup.objects.create(team=self.team, name='Goalkeepers')
        self.group.members.set([self.memberships['athlete1'], self.memberships['invited']])

    def payload(self, **overrides) -> dict:
        data = {
            'template': self.template.pk,
            'target': 'team',
            'start_date': '2026-11-16',
            'end_date': '2026-12-13',
        }
        data.update(overrides)
        return data

    def copies(self) -> set:
        return {
            (a.athlete.username, a.routine.name)
            for a in AssignedRoutine.objects.select_related('athlete', 'routine')
        }

    def test_form_offers_own_and_public_templates_and_team_targets(self):
        """
        The page offers the own templates and public ones, and as targets the team, its
        groups and its active athletes with the number of athletes who receive a copy.
        """
        Routine.objects.filter(pk=self.template.pk).update(name='Strength block')
        own_routine = self.make_template(self.coach, 'Not a template')
        Routine.objects.filter(pk=own_routine.pk).update(is_template=False)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        form = response.context['form']
        self.assertEqual(
            {
                t.name
                for t in form.fields['template'].queryset
                if t.user in (self.coach, self.other_coach)
            },
            {'Strength block', 'Public plan'},
        )
        self.assertEqual(
            form.fields['target'].choices,
            [
                ('team', 'Whole team (2 athletes)'),
                ('Groups', [(f'group-{self.group.pk}', 'Goalkeepers (1 athlete)')]),
                (
                    'Single athlete',
                    [
                        (f'athlete-{self.athlete1.pk}', 'athlete1'),
                        (f'athlete-{self.athlete2.pk}', 'athlete2'),
                    ],
                ),
            ],
        )
        self.assertContains(response, 'Whole team (2 athletes)')
        self.assertNotContains(response, 'Secret plan')

    def test_assign_to_team_group_and_athlete(self):
        """
        Each target creates the copies for exactly its active athletes and opens the
        assignment page.
        """
        cases = (
            ('team', '2026-01-05', {'athlete1', 'athlete2'}),
            (f'group-{self.group.pk}', '2026-03-02', {'athlete1'}),
            (f'athlete-{self.athlete2.pk}', '2026-05-04', {'athlete2'}),
        )
        for target, start, expected in cases:
            end = datetime.date.fromisoformat(start) + datetime.timedelta(days=27)
            response = self.client.post(
                self.url, self.payload(target=target, start_date=start, end_date=end.isoformat())
            )

            assignment = ProgramAssignment.objects.latest('pk')
            self.assertRedirects(
                response, reverse('teams:assignment-detail', kwargs={'pk': assignment.pk})
            )
            self.assertEqual(assignment.assigned_by, self.coach)
            self.assertEqual(assignment.start_date.isoformat(), start)
            self.assertEqual(assignment.end_date, end)
            self.assertEqual(
                {a.athlete.username for a in assignment.assigned_routines.all()}, expected, target
            )

        self.assertEqual(ProgramAssignment.objects.count(), 3)
        self.assertFalse(Routine.objects.filter(user=self.invited).exists())

    def test_assign_public_template(self):
        """
        A public template of another user can be assigned.
        """
        response = self.client.post(self.url, self.payload(template=self.public_template.pk))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.copies(), {('athlete1', 'Public plan'), ('athlete2', 'Public plan')})

    def test_invalid_input_assigns_nothing(self):
        """
        Wrong dates, a private template of another user, targets outside the team and an
        overlapping assignment show the form again with an error and create nothing.
        """
        assign_program(
            template=self.template,
            assigned_by=self.coach,
            start_date=datetime.date(2026, 6, 1),
            end_date=datetime.date(2026, 6, 28),
            athlete=self.athlete1,
        )
        foreign_group = TeamGroup.objects.create(team=self.other_team, name='Foreign')
        cases = (
            {'start_date': '2026-12-13', 'end_date': '2026-11-16'},
            {'start_date': 'tomorrow'},
            {'template': self.private_template.pk},
            {'template': ''},
            {'target': f'athlete-{self.foreign_athlete.pk}'},
            {'target': f'athlete-{self.invited.pk}'},
            {'target': f'athlete-{self.coach.pk}'},
            {'target': f'group-{foreign_group.pk}'},
            {'target': ''},
            # Overlaps the assignment athlete1 already has
            {'start_date': '2026-06-28', 'end_date': '2026-07-26'},
        )
        for overrides in cases:
            response = self.client.post(self.url, self.payload(**overrides))
            self.assertEqual(response.status_code, 200, overrides)
            self.assertTrue(response.context['form'].errors, overrides)

        self.assertEqual(ProgramAssignment.objects.count(), 1)
        self.assertEqual(AssignedRoutine.objects.count(), 1)
        self.assertContains(response, 'athlete1')

    def test_assign_page_is_for_coaches_of_the_team_only(self):
        """
        Athletes and coaches of other teams get 404 for the page and for assigning.
        """
        other_template = self.public_template
        for user in (self.athlete1, self.invited, self.other_coach):
            self.client.force_login(user)
            self.assertEqual(self.client.get(self.url).status_code, 404, user)
            response = self.client.post(self.url, self.payload(template=other_template.pk))
            self.assertEqual(response.status_code, 404, user)

        self.client.logout()
        self.assertEqual(self.client.get(self.url).status_code, 302)
        self.assertEqual(ProgramAssignment.objects.count(), 0)


class CoachAssignmentPageTestCase(CoachProgramBaseTestCase):
    """
    Tests for the assignment page (who received, who trained, withdraw) and the list of
    assignments on the team page.
    """

    def setUp(self):
        super().setUp()
        self.assignment = self.assign(datetime.date(2026, 11, 2), team=self.team)
        self.url = reverse('teams:assignment-detail', kwargs={'pk': self.assignment.pk})
        self.archive_url = reverse('teams:assignment-archive', kwargs={'pk': self.assignment.pk})

    def assign(self, start: datetime.date, assigned_by=None, template=None, **target):
        return assign_program(
            template=template or self.template,
            assigned_by=assigned_by or self.coach,
            start_date=start,
            end_date=start + datetime.timedelta(days=27),
            **target,
        )

    def test_assignment_page_shows_progress(self):
        """
        The page lists every athlete of the assignment with sessions and last activity and
        counts who trained.
        """
        copy = AssignedRoutine.objects.get(assignment=self.assignment, athlete=self.athlete1)
        WorkoutLog.objects.create(
            user=self.athlete1,
            routine=copy.routine,
            exercise_id=1,
            weight=10,
            repetitions=10,
            date=timezone.now(),
        )
        AssignedRoutine.objects.get(athlete=self.athlete2).routine.delete()

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['assignment'], self.assignment)
        rows = {row['username']: row for row in response.context['progress']}
        self.assertEqual(set(rows), {'athlete1', 'athlete2'})
        self.assertEqual((rows['athlete1']['sessions'], rows['athlete1']['logs']), (1, 1))
        self.assertIsNone(rows['athlete2']['routine'])
        self.assertEqual(response.context['trained'], 1)
        self.assertContains(response, 'Deleted by the athlete')
        self.assertContains(response, 'Not started')
        self.assertContains(response, self.archive_url)

    def test_withdraw_assignment(self):
        """
        Withdrawing archives the assignment once, the copies stay and the page says so.
        """
        response = self.client.post(self.archive_url)
        self.assertRedirects(response, self.url)
        self.assignment.refresh_from_db()
        archived_at = self.assignment.archived_at
        self.assertIsNotNone(archived_at)

        response = self.client.post(self.archive_url, follow=True)
        self.assertEqual(len(self.error_messages(response)), 1)
        self.assignment.refresh_from_db()
        self.assertEqual(self.assignment.archived_at, archived_at)

        self.assertEqual(AssignedRoutine.objects.filter(routine__isnull=False).count(), 2)
        self.assertNotContains(response, self.archive_url)
        self.assertContains(response, 'was withdrawn on')

    def test_assignment_pages_are_for_coaches_only(self):
        """
        Athletes of the assignment and coaches of other teams get 404 for the page and for
        withdrawing, GET on withdraw is not allowed.
        """
        self.assertEqual(self.client.get(self.archive_url).status_code, 405)
        for user in (self.athlete1, self.invited, self.other_coach):
            self.client.force_login(user)
            self.assertEqual(self.client.get(self.url).status_code, 404, user)
            self.assertEqual(self.client.post(self.archive_url).status_code, 404, user)

        self.client.logout()
        self.assertEqual(self.client.get(self.url).status_code, 302)
        self.assignment.refresh_from_db()
        self.assertIsNone(self.assignment.archived_at)

    def test_individual_assignment_page(self):
        """
        The coach opens and withdraws an assignment made to a single athlete.
        """
        assignment = self.assign(datetime.date(2027, 1, 4), athlete=self.athlete1)
        url = reverse('teams:assignment-detail', kwargs={'pk': assignment.pk})

        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual([row['username'] for row in response.context['progress']], ['athlete1'])

        self.client.post(reverse('teams:assignment-archive', kwargs={'pk': assignment.pk}))
        assignment.refresh_from_db()
        self.assertIsNotNone(assignment.archived_at)

    def test_team_page_lists_assignments_of_the_team(self):
        """
        The team page lists the assignments of the team, its groups and its athletes with
        the number of recipients, newest first, and none of another team.
        """
        group = TeamGroup.objects.create(team=self.team, name='Goalkeepers')
        group.members.set([self.memberships['athlete1']])
        to_group = self.assign(datetime.date(2027, 1, 4), group=group)
        to_athlete = self.assign(datetime.date(2027, 3, 1), athlete=self.athlete2)
        foreign = self.assign(
            datetime.date(2027, 3, 1),
            assigned_by=self.other_coach,
            template=self.private_template,
            athlete=self.foreign_athlete,
        )

        response = self.client.get(self.detail)

        assignments = list(response.context['assignments'])
        self.assertEqual(assignments, [to_athlete, to_group, self.assignment])
        self.assertEqual([a.received for a in assignments], [1, 1, 2])
        self.assertNotIn(foreign, assignments)
        for assignment in assignments:
            self.assertContains(
                response, reverse('teams:assignment-detail', kwargs={'pk': assignment.pk})
            )
        self.assertContains(response, reverse('teams:assign', kwargs={'pk': self.team.pk}))


class CoachDashboardTestCase(CoachProgramBaseTestCase):
    """
    Tests for the coach numbers on the teams page.
    """

    def test_dashboard_counts_own_teams_only(self):
        """
        The dashboard counts active athletes, open invitations, assignments running today
        and athletes who logged training for them in the last seven days, per coached team.
        """
        today = datetime.date.today()
        running = assign_program(
            template=self.template,
            assigned_by=self.coach,
            start_date=today - datetime.timedelta(days=3),
            end_date=today + datetime.timedelta(days=3),
            team=self.team,
        )
        # Not running: over, not started yet, withdrawn
        for offset, archive in ((-40, False), (40, False), (-3, True)):
            assignment = assign_program(
                template=self.make_template(self.coach, f'Other {offset} {archive}'),
                assigned_by=self.coach,
                start_date=today + datetime.timedelta(days=offset),
                end_date=today + datetime.timedelta(days=offset + 6),
                team=self.team,
            )
            if archive:
                archive_assignment(assignment)

        copy = AssignedRoutine.objects.get(assignment=running, athlete=self.athlete1).routine
        WorkoutLog.objects.create(
            user=self.athlete1,
            routine=copy,
            exercise_id=1,
            weight=10,
            repetitions=10,
            date=timezone.now() - datetime.timedelta(days=1),
        )
        # Too old, and a log on a routine that is not from this team
        old_copy = AssignedRoutine.objects.get(assignment=running, athlete=self.athlete2).routine
        WorkoutLog.objects.create(
            user=self.athlete2,
            routine=old_copy,
            exercise_id=1,
            weight=10,
            repetitions=10,
            date=timezone.now() - datetime.timedelta(days=8),
        )
        own = Routine.objects.create(
            user=self.athlete2, name='Own', start=today, end=today + datetime.timedelta(days=7)
        )
        WorkoutLog.objects.create(
            user=self.athlete2,
            routine=own,
            exercise_id=1,
            weight=10,
            repetitions=10,
            date=timezone.now(),
        )

        response = self.client.get(reverse('teams:overview'))

        dashboard = response.context['dashboard']
        self.assertEqual([entry['team'] for entry in dashboard['teams']], [self.team])
        entry = dashboard['teams'][0]
        self.assertEqual(
            (entry['athletes'], entry['invited'], entry['running'], entry['trained']),
            (2, 1, 1, 1),
        )
        self.assertEqual(
            (dashboard['athletes'], dashboard['invited'], dashboard['running']), (2, 1, 1)
        )
        self.assertContains(response, '1 of 2 trained in the last 7 days')
        self.assertNotContains(response, 'Sharks')

    def test_athletes_get_no_dashboard(self):
        """
        Athletes and invited users see no coach numbers.
        """
        for user in (self.athlete1, self.invited):
            self.client.force_login(user)
            response = self.client.get(reverse('teams:overview'))
            self.assertEqual(response.context['dashboard']['teams'], [], user)
            self.assertNotContains(response, 'Teams you coach')
