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
from django import forms
from django.db.models import Q
from django.utils import timezone
from django.utils.translation import (
    gettext as _,
    gettext_lazy,
    ngettext,
)

# wger
from wger.manager.models import Routine
from wger.teams.models import (
    Team,
    TeamGroup,
    TeamMembership,
)
from wger.teams.services import active_athletes


def athlete_count_label(count: int) -> str:
    return ngettext('%(count)d athlete', '%(count)d athletes', count) % {'count': count}


class MemberChoiceField(forms.ModelMultipleChoiceField):
    def label_from_instance(self, obj: TeamMembership) -> str:
        if obj.status == TeamMembership.Status.INVITED:
            return _('%(user)s (invited)') % {'user': obj.user.username}
        return obj.user.username


class GroupForm(forms.Form):
    """
    Name and members of a group. Only athletes of the team can be members.
    """

    name = forms.CharField(
        label=gettext_lazy('Name'),
        max_length=TeamGroup._meta.get_field('name').max_length,
    )
    members = MemberChoiceField(
        label=gettext_lazy('Members'),
        queryset=TeamMembership.objects.none(),
        required=False,
        widget=forms.CheckboxSelectMultiple,
    )

    def __init__(self, *args, team: Team, group: TeamGroup | None = None, **kwargs):
        if group is not None:
            kwargs.setdefault('prefix', f'group-{group.pk}')
            kwargs.setdefault(
                'initial',
                {'name': group.name, 'members': [member.pk for member in group.members.all()]},
            )
        super().__init__(*args, **kwargs)
        self.fields['members'].queryset = (
            team.memberships.filter(role=TeamMembership.Role.ATHLETE)
            .select_related('user')
            .order_by('user__username')
        )


class TemplateChoiceField(forms.ModelChoiceField):
    def __init__(self, *args, user, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)

    def label_from_instance(self, obj: Routine) -> str:
        if obj.user_id == self.user.pk:
            return obj.name
        return _('%(name)s (public plan)') % {'name': obj.name}


class AssignProgramForm(forms.Form):
    """
    Template, target and period of a program assignment within one team.

    The target is one choice: the whole team, one of its groups or one of its
    active athletes. The labels tell how many athletes receive a copy.
    """

    TEAM = 'team'

    def __init__(self, *args, team: Team, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.team = team

        self.fields['template'] = TemplateChoiceField(
            label=_('Plan'),
            user=user,
            queryset=Routine.objects.filter(is_template=True)
            .filter(Q(user=user) | Q(is_public=True))
            .order_by('name', 'pk'),
            empty_label=None,
        )

        athletes = active_athletes(team.memberships).select_related('user')
        athletes = list(athletes.order_by('user__username'))
        self.groups = {
            f'group-{group.pk}': group for group in team.groups.prefetch_related('members')
        }
        self.athletes = {f'athlete-{m.user_id}': m.user for m in athletes}

        choices = [
            (
                self.TEAM,
                _('Whole team (%(athletes)s)') % {'athletes': athlete_count_label(len(athletes))},
            )
        ]
        if self.groups:
            active = {m.pk for m in athletes}
            choices.append(
                (
                    _('Groups'),
                    [
                        (
                            key,
                            '%s (%s)'
                            % (
                                group.name,
                                athlete_count_label(
                                    sum(member.pk in active for member in group.members.all())
                                ),
                            ),
                        )
                        for key, group in self.groups.items()
                    ],
                )
            )
        if self.athletes:
            choices.append(
                (_('Single athlete'), [(key, u.username) for key, u in self.athletes.items()])
            )
        self.fields['target'] = forms.ChoiceField(label=_('Assign to'), choices=choices)

        today = timezone.now().astimezone(user.userprofile.zone_info).date()
        date_widget = {'widget': forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d')}
        self.fields['start_date'] = forms.DateField(
            label=_('Start date'), initial=today, **date_widget
        )
        self.fields['end_date'] = forms.DateField(
            label=_('End date'), initial=today + datetime.timedelta(days=27), **date_widget
        )

    def clean(self):
        cleaned = super().clean()
        start, end = cleaned.get('start_date'), cleaned.get('end_date')
        if start and end and start > end:
            self.add_error('end_date', _('The end date must not be before the start date.'))
        return cleaned

    def target_kwargs(self) -> dict:
        """
        The target as keyword argument for assign_program.
        """
        target = self.cleaned_data['target']
        if target == self.TEAM:
            return {'team': self.team}
        if target in self.groups:
            return {'group': self.groups[target]}
        return {'athlete': self.athletes[target]}
