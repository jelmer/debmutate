#!/usr/bin/python3
# Copyright (C) 2022 Jelmer Vernooij
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA

"""Utility functions for dealing with changelog files."""

__all__ = [
    'get_vendor_name',
]


import os
from debian.deb822 import Deb822


def _load_vendor_file(vendor: str = 'default') -> Deb822:
    with open('/etc/dpkg/origins/%s' % vendor, 'r') as f:
        return Deb822(f)


def get_vendor_name() -> str:
    if 'DEB_VENDOR' in os.environ:
        return os.environ['DEB_VENDOR']

    vendor = _load_vendor_file('default')
    return vendor['Vendor']
