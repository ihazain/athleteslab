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
from django import template


register = template.Library()

BRAND_NAME = 'Athlete Lab Pro'
"""Product name of this fork, shown in the navigation and in the page titles"""


@register.simple_tag
def brand_name() -> str:
    return BRAND_NAME


@register.filter
def brand_title(page_title: str) -> str:
    """
    The browser title: the page title followed by the product name.
    """
    page_title = ' '.join(page_title.split())
    return f'{page_title} | {BRAND_NAME}' if page_title else BRAND_NAME
