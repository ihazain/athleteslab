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
from django.db import models

# wger
from wger.teams.models.team import Team


class TeamMembership(models.Model):
    """
    Membership of a user in a team, with a role (coach or athlete).
    """

    class Role(models.TextChoices):
        COACH = 'coach', 'Coach'
        ATHLETE = 'athlete', 'Athlete'

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['team', 'user'],
                name='membership_unique_team_user',
            ),
        ]

    team = models.ForeignKey(
        Team,
        verbose_name='Team',
        on_delete=models.CASCADE,
        related_name='memberships',
    )

    user = models.ForeignKey(
        User,
        verbose_name='User',
        on_delete=models.CASCADE,
    )

    role = models.CharField(
        max_length=10,
        choices=Role.choices,
        verbose_name='Role',
    )

    def __str__(self):
        return f'{self.user.username} - {self.team.name} ({self.role})'

    def get_owner_object(self):
        """
        Returns the team this membership belongs to.
        """
        return self.team
