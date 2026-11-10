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


class Team(models.Model):
    """
    A group of athletes and coaches that routines can be assigned to.
    """

    class Meta:
        ordering = ['name']

    name = models.CharField(
        max_length=100,
        verbose_name='Name',
    )

    created_by = models.ForeignKey(
        User,
        verbose_name='Created by',
        on_delete=models.SET_NULL,
        null=True,
    )

    created = models.DateTimeField(
        verbose_name='Creation date',
        auto_now_add=True,
    )

    def __str__(self):
        return self.name

    def get_owner_object(self):
        """
        Teams have no direct owner; ownership is handled through memberships.
        """
        return None
