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
from django.urls import reverse

# wger
from wger.core.tests.base_testcase import WgerTestCase
from wger.manager.models import (
    Day,
    Routine,
    WorkoutSession,
)
from wger.teams.calendar import (
    calendar_days,
    parse_date,
    parse_year,
    week_start,
)


UTC = datetime.UTC
TODAY = datetime.date(2026, 11, 11)  # a Wednesday


class CalendarBaseTestCase(WgerTestCase):
    """
    A user with one program of two weeks (training and rest day in turn), a template and
    another user with an own program.
    """

    def setUp(self):
        super().setUp()
        self.user = User.objects.create_user(username='athlete', email='athlete@example.com')
        self.other = User.objects.create_user(username='other', email='other@example.com')

        self.program = self.make_routine(self.user, 'Base', (2026, 11, 9), (2026, 11, 22))
        Day.objects.create(routine=self.program, order=1, name='Upper body')
        Day.objects.create(routine=self.program, order=2, name='Rest', is_rest=True)

        self.template = self.make_routine(
            self.user, 'Plan', (2026, 11, 1), (2026, 11, 30), is_template=True
        )
        Day.objects.create(routine=self.template, order=1, name='Template day')
        self.foreign = self.make_routine(self.other, 'Foreign', (2026, 11, 1), (2026, 11, 30))
        Day.objects.create(routine=self.foreign, order=1, name='Foreign day')

        patcher = mock.patch('wger.teams.calendar.user_today', return_value=TODAY)
        patcher.start()
        self.addCleanup(patcher.stop)
        for module in ('wger.teams.views.calendar.user_today',):
            patcher = mock.patch(module, return_value=TODAY)
            patcher.start()
            self.addCleanup(patcher.stop)

    @staticmethod
    def make_routine(user, name, start, end, is_template=False) -> Routine:
        return Routine.objects.create(
            user=user,
            name=name,
            start=datetime.date(*start),
            end=datetime.date(*end),
            is_template=is_template,
        )

    def add_session(self, user, *moment) -> WorkoutSession:
        return WorkoutSession.objects.create(
            user=user,
            datetime_start=datetime.datetime(*moment, tzinfo=UTC),
        )

    def days(self, start, end) -> dict:
        days = calendar_days(self.user, datetime.date(*start), datetime.date(*end))
        return {day.date.isoformat(): day for day in days}


class CalendarDaysTestCase(CalendarBaseTestCase):
    """
    Tests for calendar_days and the small helpers of the calendar.
    """

    def test_planned_training_comes_from_own_programs_only(self):
        """
        Training days of the own program are planned inside its period, rest days are not.
        Templates and programs of other users do not show up.
        """
        days = self.days((2026, 11, 7), (2026, 11, 24))

        self.assertEqual(len(days), 18)
        planned = {date: [p.name for p in day.planned] for date, day in days.items() if day.planned}
        # Every second day from the start to the end of the program
        expected = [f'2026-11-{number:02d}' for number in range(9, 23, 2)]
        self.assertEqual(sorted(planned), expected)
        self.assertEqual({name for names in planned.values() for name in names}, {'Upper body'})
        self.assertEqual({p.program for day in days.values() for p in day.planned}, {self.program})

    def test_day_states(self):
        """
        A day is trained with a session, missed if planned in the past without one, planned
        if planned today or later, free otherwise.
        """
        self.add_session(self.user, 2026, 11, 9, 18, 0)
        self.add_session(self.user, 2026, 11, 10, 18, 0)
        self.add_session(self.user, 2026, 11, 10, 20, 0)
        self.add_session(self.other, 2026, 11, 12, 18, 0)

        days = self.days((2026, 11, 8), (2026, 11, 14))

        self.assertEqual(
            {date[-2:]: (day.state, day.sessions) for date, day in days.items()},
            {
                '08': ('free', 0),
                '09': ('trained', 1),
                # A rest day with two sessions
                '10': ('trained', 2),
                '11': ('planned', 0),
                '12': ('free', 0),
                '13': ('planned', 0),
                '14': ('free', 0),
            },
        )
        self.assertEqual([d for d, day in days.items() if day.is_today], ['2026-11-11'])

        # Yesterday's missed training
        WorkoutSession.objects.filter(user=self.user).delete()
        self.assertEqual(self.days((2026, 11, 9), (2026, 11, 9))['2026-11-09'].state, 'missed')

    def test_sessions_count_for_the_local_day_of_the_user(self):
        """
        A session late in the evening UTC belongs to the next day for a user east of UTC,
        also on the first and last day of the period and around a DST switch.
        """
        profile = self.user.userprofile
        profile.time_zone = 'Europe/Berlin'
        profile.save()

        # 23:30 UTC is 00:30 the next day in Berlin (winter)
        self.add_session(self.user, 2026, 11, 9, 23, 30)
        self.add_session(self.user, 2026, 11, 15, 23, 30)
        # 22:30 UTC is still the same day
        self.add_session(self.user, 2026, 11, 12, 22, 30)

        days = self.days((2026, 11, 10), (2026, 11, 15))
        self.assertEqual(
            {date[-2:]: day.sessions for date, day in days.items() if day.sessions},
            {'10': 1, '12': 1},
        )
        # The session on the evening of the 15th belongs to the 16th, the day after the period
        self.assertEqual(self.days((2026, 11, 16), (2026, 11, 16))['2026-11-16'].sessions, 1)

        # DST ends on 2026-10-25 in Berlin: 22:30 UTC on the 24th is 00:30 on the 25th (CEST),
        # 22:30 UTC on the 25th is 23:30 on the 25th (CET)
        self.add_session(self.user, 2026, 10, 24, 22, 30)
        self.add_session(self.user, 2026, 10, 25, 22, 30)
        days = self.days((2026, 10, 24), (2026, 10, 26))
        self.assertEqual(
            {d[-2:]: day.sessions for d, day in days.items()}, {'24': 0, '25': 2, '26': 0}
        )

    def test_sessions_of_a_user_far_from_the_server_time_zone(self):
        """
        For a user half a day ahead of the server, a session on the server's previous day
        counts for the first day of the period, and one on the last day for the day after.
        """
        profile = self.user.userprofile
        profile.time_zone = 'Pacific/Auckland'
        profile.save()

        # 11:30 UTC is 00:30 the next day in Auckland (UTC+13 in November)
        self.add_session(self.user, 2026, 11, 9, 11, 30)
        self.add_session(self.user, 2026, 11, 10, 11, 30)

        days = self.days((2026, 11, 10), (2026, 11, 10))
        self.assertEqual(days['2026-11-10'].sessions, 1)

    def test_helpers(self):
        """
        Malformed dates and years fall back to the default, weeks start on Monday.
        """
        default = datetime.date(2026, 1, 1)
        self.assertEqual(parse_date('2026-03-04', default), datetime.date(2026, 3, 4))
        for value in (None, '', 'abc', '2026-13-40', '04.03.2026'):
            self.assertEqual(parse_date(value, default), default, value)

        self.assertEqual(parse_year('2025', 2026), 2025)
        for value in (None, '', 'abc', '1', '99999', '20.5'):
            self.assertEqual(parse_year(value, 2026), 2026, value)

        self.assertEqual(week_start(datetime.date(2026, 11, 11)), datetime.date(2026, 11, 9))
        self.assertEqual(week_start(datetime.date(2026, 11, 9)), datetime.date(2026, 11, 9))
        self.assertEqual(week_start(datetime.date(2026, 11, 15)), datetime.date(2026, 11, 9))


class CalendarViewsTestCase(CalendarBaseTestCase):
    """
    Tests for the week, timeline and year pages.
    """

    def setUp(self):
        super().setUp()
        self.client.force_login(self.user)

    def test_login_required(self):
        """
        Anonymous users are sent to the login on all three pages.
        """
        self.client.logout()
        for name in ('calendar:week', 'calendar:timeline', 'calendar:year'):
            response = self.client.get(reverse(name))
            self.assertEqual(response.status_code, 302, name)
            self.assertIn('login', response.url)

    def test_week(self):
        """
        The week page shows Monday to Sunday of the requested week, the current week for a
        missing or malformed date, with own training only.
        """
        for query in ('', '?date=abc', '?date=2026-11-15'):
            response = self.client.get(reverse('calendar:week') + query)
            self.assertEqual(response.status_code, 200, query)
            dates = [day.date for day in response.context['days']]
            self.assertEqual(dates[0], datetime.date(2026, 11, 9), query)
            self.assertEqual(dates[-1], datetime.date(2026, 11, 15), query)
            self.assertEqual(len(dates), 7)

        self.assertContains(response, 'Upper body')
        self.assertNotContains(response, 'Foreign day')
        self.assertNotContains(response, 'Template day')
        self.assertContains(response, '?date=2026-11-02')
        self.assertContains(response, '?date=2026-11-16')

        response = self.client.get(reverse('calendar:week') + '?date=2027-01-01')
        self.assertEqual(response.context['days'][0].date, datetime.date(2026, 12, 28))

    def test_timeline(self):
        """
        The timeline shows own programs of the twelve weeks as bars, cut at the edges of
        the window, without templates and programs of others.
        """
        before = self.make_routine(self.user, 'Runs in', (2026, 9, 1), (2026, 10, 28))
        self.make_routine(self.user, 'Long ago', (2026, 1, 1), (2026, 2, 1))

        response = self.client.get(reverse('calendar:timeline'))

        self.assertEqual(response.status_code, 200)
        # Two weeks before the current week, twelve weeks in all
        self.assertEqual(response.context['start'], datetime.date(2026, 10, 26))
        self.assertEqual(response.context['end'], datetime.date(2027, 1, 17))
        self.assertEqual(response.context['today_column'], 17)
        rows = {row['program']: row for row in response.context['rows']}
        self.assertEqual(set(rows), {self.program, before})

        row = rows[self.program]
        self.assertEqual((row['column'], row['span'], row['weeks']), (15, 14, 2))
        self.assertTrue(row['is_current'])
        self.assertFalse(row['starts_before'] or row['ends_after'])

        row = rows[before]
        self.assertEqual((row['column'], row['span']), (1, 3))
        self.assertTrue(row['starts_before'])
        self.assertFalse(row['is_current'])

        self.assertNotContains(response, 'Foreign')
        self.assertNotContains(response, 'Long ago')
        self.assertEqual(
            self.client.get(reverse('calendar:timeline') + '?date=nope').status_code, 200
        )

    def test_year(self):
        """
        The year page has twelve months with every day once and counts trained and planned
        days, for the current year if the year is missing or malformed.
        """
        self.add_session(self.user, 2026, 11, 9, 18, 0)
        self.add_session(self.user, 2026, 3, 3, 18, 0)
        self.add_session(self.other, 2026, 5, 5, 18, 0)

        for query in ('', '?year=abc', '?year=99999'):
            response = self.client.get(reverse('calendar:year') + query)
            self.assertEqual(response.status_code, 200, query)
            self.assertEqual(response.context['year'], 2026, query)

        months = response.context['months']
        self.assertEqual(len(months), 12)
        days = [day for month in months for week in month['weeks'] for day in week if day]
        self.assertEqual(len(days), 365)
        self.assertEqual(len({day.date for day in days}), 365)
        self.assertEqual((response.context['trained'], response.context['planned']), (2, 7))
        self.assertEqual((months[10]['trained'], months[10]['planned']), (1, 7))
        self.assertEqual(months[4]['trained'], 0)

        self.assertContains(response, '<h4 class="mb-0">2026</h4>')
        self.assertContains(response, '?year=2027')

        response = self.client.get(reverse('calendar:year') + '?year=2024')
        self.assertEqual(response.context['year'], 2024)
        days = [d for m in response.context['months'] for w in m['weeks'] for d in w if d]
        self.assertEqual(len(days), 366)
