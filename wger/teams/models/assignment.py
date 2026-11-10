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
from wger.manager.models import Routine
from wger.teams.models.team import Team


class ProgramAssignment(models.Model):
    """
    An assignment of a routine template to either a team or a single athlete.
    Exactly one of team or athlete is set.
    """

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(team__isnull=False, athlete__isnull=True)
                    | models.Q(team__isnull=True, athlete__isnull=False)
                ),
                name='assignment_exactly_one_target',
            ),
        ]

    template = models.ForeignKey(
        Routine,
        verbose_name='Template',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        default=None,
    )

    team = models.ForeignKey(
        Team,
        verbose_name='Team',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        default=None,
    )

    athlete = models.ForeignKey(
        User,
        verbose_name='Athlete',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        default=None,
        related_name='program_assignments',
    )

    start_date = models.DateField(
        verbose_name='Start date',
    )

    end_date = models.DateField(
        verbose_name='End date',
    )

    assigned_by = models.ForeignKey(
        User,
        verbose_name='Assigned by',
        on_delete=models.SET_NULL,
        null=True,
        related_name='assigned_programs',
    )

    created = models.DateTimeField(
        verbose_name='Creation date',
        auto_now_add=True,
    )

    archived_at = models.DateTimeField(
        verbose_name='Archived at',
        null=True,
        blank=True,
        default=None,
    )
    """Set when the coach withdraws the assignment, the copies stay with the athletes"""

    def __str__(self):
        target = self.team if self.team else self.athlete
        return f'{self.template} -> {target}'

    def get_owner_object(self):
        """
        Returns the assignment itself; ownership is checked through memberships.
        """
        return self
