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
from django.urls import reverse

# wger
from wger.manager.models import (
    Day,
    Routine,
    WorkoutSession,
)
from wger.teams.calendar import team_agenda
from wger.teams.models import (
    AssignedRoutine,
    TeamGroup,
    TeamMembership,
)
from wger.teams.services import (
    archive_assignment,
    assign_program,
)
from wger.teams.tests.test_views_programs import CoachProgramBaseTestCase


UTC = datetime.UTC
TODAY = datetime.date(2026, 11, 11)  # a Wednesday
START = datetime.date(2026, 11, 9)
END = datetime.date(2026, 11, 22)


class AgendaBaseTestCase(CoachProgramBaseTestCase):
    """
    The team got a program of two weeks, training and rest day in turn.
    """

    def setUp(self):
        super().setUp()
        Day.objects.create(routine=self.template, order=1, name='Upper body')
        Day.objects.create(routine=self.template, order=2, name='Rest', is_rest=True)
        self.assignment = assign_program(
            template=self.template,
            assigned_by=self.coach,
            start_date=START,
            end_date=END,
            team=self.team,
        )
        for module in ('wger.teams.calendar', 'wger.teams.views.coach'):
            patcher = mock.patch(f'{module}.user_today', return_value=TODAY)
            patcher.start()
            self.addCleanup(patcher.stop)

    def copy(self, athlete, assignment=None) -> Routine:
        return AssignedRoutine.objects.get(
            assignment=assignment or self.assignment, athlete=athlete
        ).routine

    def add_session(self, routine: Routine, *moment) -> WorkoutSession:
        return WorkoutSession.objects.create(
            user=routine.user,
            routine=routine,
            datetime_start=datetime.datetime(*moment, tzinfo=UTC),
        )

    def assign_sprints(self, **target):
        """
        A second program with training on every day, made by the coach.
        """
        template = self.make_template(self.coach, 'Speed block')
        Day.objects.create(routine=template, order=1, name='Sprints')
        return assign_program(
            template=template,
            assigned_by=self.coach,
            start_date=START,
            end_date=END,
            **target,
        )

    def agenda(self, start=START, end=datetime.date(2026, 11, 15)) -> dict:
        return {day.date.isoformat()[-2:]: day for day in team_agenda(self.team, start, end, TODAY)}


class TeamAgendaTestCase(AgendaBaseTestCase):
    """
    Tests for the agenda of a team: the dates with training and who trained.
    """

    def test_training_dates_of_the_period(self):
        """
        Only dates with training inside the period show up, each with the routine of the
        assignment and the number of athletes who got it. Rest days are left out.
        """
        agenda = self.agenda()

        self.assertEqual(sorted(agenda), ['09', '11', '13', '15'])
        for day in agenda.values():
            self.assertEqual(
                [(unit.name, unit.assignment, unit.athletes) for unit in day.units],
                [('Upper body', self.assignment, 2)],
            )
            self.assertEqual(day.more, [])
        self.assertEqual(
            {date: (day.is_past, day.is_today) for date, day in agenda.items()},
            {
                '09': (True, False),
                '11': (False, True),
                '13': (False, False),
                '15': (False, False),
            },
        )

    def test_period_boundaries(self):
        """
        The first and the last day of the period count, the days around them do not.
        """
        agenda = self.agenda(datetime.date(2026, 11, 11), datetime.date(2026, 11, 13))

        self.assertEqual(sorted(agenda), ['11', '13'])

    def test_trained_counts_athletes_on_their_local_day(self):
        """
        An athlete counts once for a date, on the day the session started in the own
        time zone. Sessions for other routines do not count.
        """
        copy1 = self.copy(self.athlete1)
        self.add_session(copy1, 2026, 11, 9, 8, 0)
        self.add_session(copy1, 2026, 11, 9, 18, 0)

        # 23:30 UTC on the 10th is the 11th in Berlin
        profile = self.athlete2.userprofile
        profile.time_zone = 'Europe/Berlin'
        profile.save()
        self.add_session(self.copy(self.athlete2), 2026, 11, 10, 23, 30)

        own = Routine.objects.create(user=self.athlete2, name='Own', start=START, end=END)
        self.add_session(own, 2026, 11, 9, 18, 0)

        agenda = self.agenda()

        self.assertEqual(
            {date: day.first.trained for date, day in agenda.items()},
            {'09': 1, '11': 1, '13': 0, '15': 0},
        )

    def test_several_routines_on_one_date(self):
        """
        Assignments to a group and to a single athlete add their routines to the date, in
        the order they were made.
        """
        group = TeamGroup.objects.create(team=self.team, name='Goalkeepers')
        group.members.set([self.memberships['athlete1']])
        group_assignment = self.assign_sprints(group=group)

        day = self.agenda()['09']

        self.assertEqual(
            [(unit.name, unit.assignment, unit.athletes) for unit in day.units],
            [('Upper body', self.assignment, 2), ('Sprints', group_assignment, 1)],
        )
        self.assertEqual(day.first.name, 'Upper body')
        self.assertEqual([unit.name for unit in day.more], ['Sprints'])
        # Sprints are planned every day
        self.assertEqual([unit.name for unit in self.agenda()['10'].units], ['Sprints'])

    def test_withdrawn_and_foreign_assignments_are_left_out(self):
        """
        Withdrawn assignments, assignments of other teams and assignments whose copies
        were all deleted do not show up.
        """
        archive_assignment(self.assign_sprints(athlete=self.athlete1))
        Day.objects.create(routine=self.private_template, order=1, name='Foreign day')
        assign_program(
            template=self.private_template,
            assigned_by=self.other_coach,
            start_date=START,
            end_date=END,
            team=self.other_team,
        )
        names = {unit.name for day in self.agenda().values() for unit in day.units}
        self.assertEqual(names, {'Upper body'})

        for athlete in (self.athlete1, self.athlete2):
            self.copy(athlete).delete()
        self.assertEqual(self.agenda(), {})

    def test_team_page_shows_the_agenda(self):
        """
        The team page shows six weeks from the week before the selected one. A malformed
        date falls back to today.
        """
        for query in ('', '?date=2026-11-12', '?date=nonsense'):
            response = self.client.get(self.detail + query)

            self.assertEqual(response.status_code, 200)
            self.assertEqual(
                (response.context['agenda_start'], response.context['agenda_end']),
                (datetime.date(2026, 11, 2), datetime.date(2026, 12, 13)),
                query,
            )
            # Every second day of the program
            self.assertEqual(len(response.context['agenda']), 7)
            self.assertContains(response, 'Upper body')

        response = self.client.get(self.detail + '?date=2026-12-21')
        self.assertEqual(response.context['agenda'], [])
        self.assertContains(response, 'No training is planned for the team in these weeks.')

    def test_further_routines_are_collapsed(self):
        """
        The first routine of a date is visible, the others sit in a closed details element.
        """
        self.assign_sprints(athlete=self.athlete1)

        response = self.client.get(self.detail)

        self.assertContains(response, '1 more routine', count=7)
        self.assertContains(response, '<details class="alp-agenda-more">', count=7)


class MemberDetailTestCase(AgendaBaseTestCase):
    """
    Tests for the profile of a team member as the coach sees it.
    """

    def setUp(self):
        super().setUp()
        # athlete1 is also in another team, with a program from there and an own one
        TeamMembership.objects.create(
            team=self.other_team,
            user=self.athlete1,
            role=TeamMembership.Role.ATHLETE,
            status=TeamMembership.Status.ACTIVE,
        )
        Day.objects.create(routine=self.private_template, order=1, name='Foreign day')
        self.foreign_assignment = assign_program(
            template=self.private_template,
            assigned_by=self.other_coach,
            start_date=START,
            end_date=END,
            team=self.other_team,
        )
        self.own = Routine.objects.create(user=self.athlete1, name='Own', start=START, end=END)
        Day.objects.create(routine=self.own, order=1, name='Own day')

    def url(self, username: str = 'athlete1', team=None) -> str:
        return reverse(
            'teams:member-detail',
            kwargs={
                'pk': (team or self.team).pk,
                'membership_pk': self.memberships[username].pk,
            },
        )

    def test_profile_shows_team_programs_only(self):
        """
        The coach sees the programs assigned in the own teams and to the athlete
        personally, with the sessions done. Programs from other teams and own programs
        of the athlete stay hidden, also in the week.
        """
        personal = self.assign_sprints(athlete=self.athlete1)
        self.add_session(self.copy(self.athlete1), 2026, 11, 9, 18, 0)
        self.add_session(self.own, 2026, 11, 10, 18, 0)
        self.add_session(self.copy(self.athlete1, self.foreign_assignment), 2026, 11, 10, 18, 0)

        response = self.client.get(self.url())

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [row['assignment'] for row in response.context['programs']],
            [personal, self.assignment],
        )
        self.assertEqual(
            (response.context['start'], response.context['end']), (START, END - 7 * DAY)
        )
        days = {day.date.isoformat()[-2:]: day for day in response.context['days']}
        self.assertEqual(
            {date: sorted(p.name for p in day.planned) for date, day in days.items()},
            {
                '09': ['Sprints', 'Upper body'],
                '10': ['Sprints'],
                '11': ['Sprints', 'Upper body'],
                '12': ['Sprints'],
                '13': ['Sprints', 'Upper body'],
                '14': ['Sprints'],
                '15': ['Sprints', 'Upper body'],
            },
        )
        self.assertEqual(
            {date: day.sessions for date, day in days.items() if day.sessions}, {'09': 1}
        )
        for hidden in ('Own day', 'Foreign day', 'Secret plan'):
            self.assertNotContains(response, hidden)

    def test_personal_programs_of_a_coach_stay_hidden(self):
        """
        Programs assigned personally only show for members who are athletes of the team.
        """
        self.assign_sprints(athlete=self.athlete1)
        membership = self.memberships['athlete1']
        membership.role = TeamMembership.Role.COACH
        membership.save()

        response = self.client.get(self.url())

        self.assertEqual(
            [row['assignment'] for row in response.context['programs']], [self.assignment]
        )

    def test_week_can_be_selected(self):
        """
        The date parameter selects the week, a malformed one falls back to today.
        """
        response = self.client.get(self.url() + '?date=2026-11-19')
        self.assertEqual(response.context['start'], datetime.date(2026, 11, 16))

        response = self.client.get(self.url() + '?date=nonsense')
        self.assertEqual(response.context['start'], START)

    def test_only_coaches_of_the_team_see_the_profile(self):
        """
        Athletes, coaches of other teams and anonymous users get no profile, and neither
        does the coach for invited users or with the membership of another team.
        """
        self.assertEqual(self.client.get(self.url('invited')).status_code, 404)
        foreign = reverse(
            'teams:member-detail',
            kwargs={'pk': self.team.pk, 'membership_pk': self.foreign_membership.pk},
        )
        self.assertEqual(self.client.get(foreign).status_code, 404)

        for user in (self.athlete1, self.athlete2, self.other_coach):
            self.client.force_login(user)
            self.assertEqual(self.client.get(self.url()).status_code, 404, user)

        self.client.logout()
        self.assertEqual(self.client.get(self.url()).status_code, 302)

    def test_dashboard_lists_the_athletes(self):
        """
        The teams page of the coach links to the profile of every active athlete.
        """
        response = self.client.get(reverse('teams:overview'))

        for username in ('athlete1', 'athlete2'):
            self.assertContains(response, self.url(username))
        self.assertNotContains(response, self.url('invited'))
        self.assertNotContains(response, self.url('coach'))


DAY = datetime.timedelta(days=1)
