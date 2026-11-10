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
from wger.teams.models.assignment import ProgramAssignment


class AssignedRoutine(models.Model):
    """
    The routine copy created for one athlete within one program assignment.
    """

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['assignment', 'athlete'],
                name='assigned_routine_unique_assignment_athlete',
            ),
        ]

    assignment = models.ForeignKey(
        ProgramAssignment,
        verbose_name='Assignment',
        on_delete=models.CASCADE,
        related_name='assigned_routines',
    )

    athlete = models.ForeignKey(
        User,
        verbose_name='Athlete',
        on_delete=models.CASCADE,
    )

    routine = models.OneToOneField(
        Routine,
        verbose_name='Routine copy',
        on_delete=models.CASCADE,
    )

    def __str__(self):
        return f'{self.athlete.username} - {self.routine}'

    def get_owner_object(self):
        """
        Returns the assignment this assigned routine belongs to.
        """
        return self.assignment
