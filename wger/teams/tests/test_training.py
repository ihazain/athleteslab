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
from wger.core.models import (
    RepetitionUnit,
    WeightUnit,
)
from wger.core.tests.base_testcase import WgerTestCase
from wger.manager.models import (
    Day,
    Routine,
    Slot,
    SlotEntry,
)
from wger.teams.models import (
    Team,
    TeamMembership,
)
from wger.teams.services import assign_program


TODAY = datetime.date(2026, 11, 11)


class TrainingPagesTestCase(WgerTestCase):
    """
    Tests for the Training page: programs, plans and routines of the user.
    """

    def setUp(self):
        super().setUp()
        self.user = User.objects.create_user(username='athlete', email='athlete@example.com')
        self.other = User.objects.create_user(username='other', email='other@example.com')

        self.finished = self.make_routine(self.user, 'Old block', (2026, 9, 1), (2026, 9, 28))
        self.current = self.make_routine(self.user, 'Base block', (2026, 11, 2), (2026, 11, 29))
        self.upcoming = self.make_routine(self.user, 'Next block', (2026, 12, 1), (2027, 1, 11))
        self.plan = self.make_routine(
            self.user, 'Full body plan', (2026, 1, 1), (2026, 1, 28), is_template=True
        )
        self.foreign = self.make_routine(self.other, 'Foreign block', (2026, 11, 2), (2026, 11, 29))
        self.foreign_plan = self.make_routine(
            self.other, 'Foreign plan', (2026, 1, 1), (2026, 1, 28), is_template=True
        )

        self.upper = self.add_day(self.current, 1, 'Upper body', exercises=2)
        self.add_day(self.current, 2, 'Rest', is_rest=True)
        self.plan_day = self.add_day(self.plan, 1, 'Plan day A', exercises=1)
        self.add_day(self.plan, 2, 'Plan day B')
        self.add_day(self.foreign, 1, 'Foreign day')

        patcher = mock.patch('wger.teams.views.training.user_today', return_value=TODAY)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.client.force_login(self.user)

    @staticmethod
    def make_routine(user, name, start, end, is_template=False) -> Routine:
        return Routine.objects.create(
            user=user,
            name=name,
            start=datetime.date(*start),
            end=datetime.date(*end),
            is_template=is_template,
        )

    @staticmethod
    def add_day(routine, order, name, is_rest=False, exercises=0) -> Day:
        day = Day.objects.create(routine=routine, order=order, name=name, is_rest=is_rest)
        for number in range(exercises):
            slot = Slot.objects.create(day=day, order=number + 1)
            SlotEntry.objects.create(
                slot=slot,
                exercise_id=1,
                repetition_unit=RepetitionUnit.objects.first(),
                weight_unit=WeightUnit.objects.first(),
                order=1,
            )
        return day

    def test_login_required(self):
        """
        Anonymous users are sent to the login on all three tabs.
        """
        self.client.logout()
        for name in ('training:programs', 'training:plans', 'training:routines'):
            response = self.client.get(reverse(name))
            self.assertEqual(response.status_code, 302, name)
            self.assertIn('login', response.url)

    def test_programs(self):
        """
        Programs are the own dated routines: the running one first, then upcoming, then
        finished, with weeks and number of routines. No plans, nothing of other users.
        """
        later = self.make_routine(self.user, 'Later block', (2027, 2, 1), (2027, 2, 14))
        older = self.make_routine(self.user, 'Older block', (2026, 5, 4), (2026, 5, 31))

        response = self.client.get(reverse('training:programs'))

        self.assertEqual(response.status_code, 200)
        entries = response.context['entries']
        # The next upcoming program before later ones, the latest finished one first
        self.assertEqual(
            [(e['program'], e['status'], e['weeks']) for e in entries],
            [
                (self.current, 'current', 4),
                (self.upcoming, 'upcoming', 6),
                (later, 'upcoming', 2),
                (self.finished, 'finished', 4),
                (older, 'finished', 4),
            ],
        )
        # The rest day is not a routine
        self.assertEqual(entries[0]['program'].training_days, 1)
        self.assertIsNone(entries[0]['assignment'])
        self.assertContains(response, self.current.get_absolute_url())
        self.assertNotContains(response, 'Full body plan')
        self.assertNotContains(response, 'Foreign')

    def test_program_boundary_days(self):
        """
        A program is running on its first and last day, upcoming the day before and finished
        the day after.
        """
        cases = (
            ((2026, 11, 11), (2026, 11, 20), 'current'),
            ((2026, 11, 1), (2026, 11, 11), 'current'),
            ((2026, 11, 12), (2026, 11, 20), 'upcoming'),
            ((2026, 11, 1), (2026, 11, 10), 'finished'),
        )
        for start, end, expected in cases:
            routine = self.make_routine(self.user, 'Boundary', start, end)
            response = self.client.get(reverse('training:programs'))
            status = {e['program']: e['status'] for e in response.context['entries']}[routine]
            self.assertEqual(status, expected, (start, end))
            routine.delete()

    def test_assigned_program_shows_team_and_coach(self):
        """
        A program that came from a coach names the team and the coach.
        """
        coach = User.objects.create_user(username='coach', email='coach@example.com')
        team = Team.objects.create(name='Lions', created_by=coach)
        for user, role in ((coach, 'coach'), (self.user, 'athlete')):
            TeamMembership.objects.create(team=team, user=user, role=role, status='active')
        template = self.make_routine(coach, 'Coach plan', (2026, 1, 1), (2026, 1, 28), True)
        assignment = assign_program(
            template=template,
            assigned_by=coach,
            start_date=datetime.date(2026, 11, 9),
            end_date=datetime.date(2026, 12, 6),
            team=team,
        )

        response = self.client.get(reverse('training:programs'))

        entry = next(e for e in response.context['entries'] if e['program'].name == 'Coach plan')
        self.assertEqual(entry['assignment'], assignment)
        self.assertEqual(entry['program'].user, self.user)
        self.assertContains(response, 'Assigned in Lions')

    def test_plans(self):
        """
        Plans are the own templates with their number of routines, nothing else.
        """
        response = self.client.get(reverse('training:plans'))

        self.assertEqual(response.status_code, 200)
        plans = list(response.context['plans'])
        self.assertEqual(plans, [self.plan])
        self.assertEqual(plans[0].training_days, 2)
        self.assertContains(response, reverse('manager:template:view', args=[self.plan.pk]))
        self.assertNotContains(response, 'Base block')
        self.assertNotContains(response, 'Foreign')

    def test_routines(self):
        """
        Routines are the single training days of own plans and programs with their number of
        exercises, without rest days and without days of other users.
        """
        response = self.client.get(reverse('training:routines'))

        self.assertEqual(response.status_code, 200)
        days = list(response.context['days'])
        # Days of programs first, then the ones of plans
        self.assertEqual([d.name for d in days], ['Upper body', 'Plan day A', 'Plan day B'])
        self.assertEqual([d.exercises for d in days], [2, 1, 0])
        self.assertNotContains(response, 'Foreign day')
        self.assertNotContains(response, '>Rest<')

    # --- New program ---

    def program_payload(self, **overrides) -> dict:
        data = {
            'name': 'Built program',
            'start_date': '2026-11-16',
            'end_date': '2026-12-13',
        }
        data.update(overrides)
        return data

    def test_new_program_form_offers_own_and_public_sources(self):
        """
        The form offers own plans and public plans, and the own routines without rest days.
        The Programs tab links to it.
        """
        Routine.objects.filter(pk=self.foreign_plan.pk).update(is_public=True)
        private = self.make_routine(self.other, 'Private plan', (2026, 1, 1), (2026, 1, 28), True)

        response = self.client.get(reverse('training:program-new'))

        self.assertEqual(response.status_code, 200)
        form = response.context['form']
        offered = {
            plan for plan in form.fields['plan'].queryset if plan.user in (self.user, self.other)
        }
        self.assertEqual(offered, {self.plan, self.foreign_plan})
        self.assertNotIn(private, form.fields['plan'].queryset)
        self.assertEqual(
            [day.name for day in form.fields['routines'].queryset],
            ['Upper body', 'Plan day A', 'Plan day B'],
        )
        self.assertContains(response, 'Upper body (from Base block)')
        self.assertContains(
            self.client.get(reverse('training:programs')), reverse('training:program-new')
        )

    def test_new_program_from_plan_and_routine(self):
        """
        Posting a plan and a routine creates the program with copies of both and opens it
        in the editor.
        """
        response = self.client.post(
            reverse('training:program-new'),
            self.program_payload(plan=self.plan.pk, routines=[self.upper.pk]),
        )

        program = Routine.objects.get(name='Built program')
        self.assertRedirects(
            response,
            reverse('manager:routine:edit', kwargs={'pk': program.pk}),
            fetch_redirect_response=False,
        )
        self.assertEqual(program.user, self.user)
        self.assertFalse(program.is_template)
        self.assertEqual(
            (program.start, program.end), (datetime.date(2026, 11, 16), datetime.date(2026, 12, 13))
        )
        self.assertEqual(
            [day.name for day in program.days.order_by('order')],
            ['Plan day A', 'Plan day B', 'Upper body'],
        )
        # The sources are untouched
        self.assertEqual(self.plan.days.count(), 2)
        self.assertEqual(self.current.days.count(), 2)

    def test_new_program_invalid_input_creates_nothing(self):
        """
        No source, a routine or private plan of another user, a rest day, wrong dates and a
        too long period show the form again with an error and create nothing.
        """
        count = Routine.objects.count()
        foreign_day = Day.objects.get(name='Foreign day')
        rest_day = Day.objects.get(name='Rest')
        cases = (
            {},
            {'routines': [foreign_day.pk]},
            {'routines': [self.upper.pk, foreign_day.pk]},
            {'routines': [rest_day.pk]},
            {'plan': self.foreign_plan.pk},
            {'plan': self.current.pk},
            {'plan': self.plan.pk, 'name': ''},
            {'plan': self.plan.pk, 'name': 'x' * 26},
            {'plan': self.plan.pk, 'end_date': '2026-11-15'},
            {'plan': self.plan.pk, 'end_date': '2027-03-17'},
            {'plan': self.plan.pk, 'start_date': 'soon'},
        )
        for overrides in cases:
            response = self.client.post(
                reverse('training:program-new'), self.program_payload(**overrides)
            )
            self.assertEqual(response.status_code, 200, overrides)
            self.assertTrue(response.context['form'].errors, overrides)

        self.assertEqual(Routine.objects.count(), count)

    def test_new_program_needs_login(self):
        """
        Anonymous users are sent to the login and create nothing.
        """
        self.client.logout()
        count = Routine.objects.count()
        for response in (
            self.client.get(reverse('training:program-new')),
            self.client.post(
                reverse('training:program-new'), self.program_payload(plan=self.plan.pk)
            ),
        ):
            self.assertEqual(response.status_code, 302)
            self.assertIn('login', response.url)
        self.assertEqual(Routine.objects.count(), count)

    # --- New plan and new routine ---

    def test_new_plan(self):
        """
        Posting routines creates a plan (a private template) with copies of them and opens
        it. Without a source the form shows an error. The Plans tab links to the form.
        """
        url = reverse('training:plan-new')
        self.assertContains(self.client.get(reverse('training:plans')), url)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('start_date', response.context['form'].fields)

        count = Routine.objects.count()
        response = self.client.post(url, {'name': 'Nothing'})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['form'].errors)
        self.assertEqual(Routine.objects.count(), count)

        response = self.client.post(
            url, {'name': 'Built plan', 'routines': [self.upper.pk, self.plan_day.pk]}
        )
        plan = Routine.objects.get(name='Built plan')
        self.assertRedirects(
            response,
            reverse('manager:template:view', kwargs={'pk': plan.pk}),
            fetch_redirect_response=False,
        )
        self.assertTrue(plan.is_template)
        self.assertFalse(plan.is_public)
        self.assertEqual(plan.user, self.user)
        self.assertEqual(
            [day.name for day in plan.days.order_by('order')], ['Upper body', 'Plan day A']
        )
        self.assertIn(plan, self.client.get(reverse('training:plans')).context['plans'])

    def test_new_routine_form_offers_own_programs_and_routines(self):
        """
        The form offers a new program or the own programs as target, no plans and nothing
        of other users, and the own routines as source. The Routines tab links to it.
        """
        url = reverse('training:routine-new')
        self.assertContains(self.client.get(reverse('training:routines')), url)

        form = self.client.get(url).context['form']

        self.assertEqual(
            [key for key, label in form.fields['program'].choices],
            ['new', str(self.upcoming.pk), str(self.current.pk), str(self.finished.pk)],
        )
        self.assertEqual(
            [day.name for day in form.fields['source'].queryset],
            ['Upper body', 'Plan day A', 'Plan day B'],
        )

    def test_new_routine(self):
        """
        A routine is created empty in a new program, or as a copy inside an own program,
        and the program opens in the editor.
        """
        url = reverse('training:routine-new')

        response = self.client.post(url, {'name': 'Sprint session', 'program': 'new'})
        day = Day.objects.get(name='Sprint session')
        self.assertRedirects(
            response,
            reverse('manager:routine:edit', kwargs={'pk': day.routine_id}),
            fetch_redirect_response=False,
        )
        self.assertEqual((day.routine.user, day.routine.name), (self.user, 'Sprint session'))
        self.assertFalse(day.routine.is_template)

        response = self.client.post(
            url, {'name': 'Upper copy', 'program': self.upcoming.pk, 'source': self.upper.pk}
        )
        day = Day.objects.get(name='Upper copy')
        self.assertEqual(day.routine, self.upcoming)
        self.assertEqual(day.slots.count(), 2)
        self.assertEqual(self.upper.slots.count(), 2)
        self.assertRedirects(
            response,
            reverse('manager:routine:edit', kwargs={'pk': self.upcoming.pk}),
            fetch_redirect_response=False,
        )

    def test_new_routine_invalid_input_creates_nothing(self):
        """
        A plan or a program of another user as target, a routine of another user as source,
        a missing or too long name show the form again and create nothing.
        """
        foreign_day = Day.objects.get(name='Foreign day')
        counts = (Day.objects.count(), Routine.objects.count())
        cases = (
            {'name': 'x', 'program': self.plan.pk},
            {'name': 'x', 'program': self.foreign.pk},
            {'name': 'x', 'program': 'abc'},
            {'name': 'x'},
            {'name': 'x', 'program': 'new', 'source': foreign_day.pk},
            {'name': '', 'program': 'new'},
            {'name': 'x' * 21, 'program': 'new'},
        )
        for data in cases:
            response = self.client.post(reverse('training:routine-new'), data)
            self.assertEqual(response.status_code, 200, data)
            self.assertTrue(response.context['form'].errors, data)

        self.assertEqual((Day.objects.count(), Routine.objects.count()), counts)

    def test_new_plan_and_routine_need_login(self):
        """
        Anonymous users are sent to the login and create nothing.
        """
        self.client.logout()
        counts = (Day.objects.count(), Routine.objects.count())
        for name, data in (
            ('training:plan-new', {'name': 'x', 'routines': [self.upper.pk]}),
            ('training:routine-new', {'name': 'x', 'program': 'new'}),
        ):
            for response in (self.client.get(reverse(name)), self.client.post(reverse(name), data)):
                self.assertEqual(response.status_code, 302, name)
                self.assertIn('login', response.url)
        self.assertEqual((Day.objects.count(), Routine.objects.count()), counts)
