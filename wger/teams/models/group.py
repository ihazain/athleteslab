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
from django.db import models

# wger
from wger.teams.models.membership import TeamMembership
from wger.teams.models.team import Team


class TeamGroup(models.Model):
    """
    A sub-group of a team (e.g. the goalkeepers) that routines can be assigned to.
    """

    class Meta:
        ordering = ['name']
        constraints = [
            models.UniqueConstraint(
                fields=['team', 'name'],
                name='group_unique_team_name',
            ),
        ]

    team = models.ForeignKey(
        Team,
        verbose_name='Team',
        on_delete=models.CASCADE,
        related_name='groups',
    )

    name = models.CharField(
        max_length=100,
        verbose_name='Name',
    )

    members = models.ManyToManyField(
        TeamMembership,
        verbose_name='Members',
        related_name='groups',
        blank=True,
    )
    """Memberships of the same team, so leaving the team also leaves the group"""

    def __str__(self):
        return f'{self.team.name}: {self.name}'

    def get_owner_object(self):
        """
        Returns the team this group belongs to.
        """
        return self.team
