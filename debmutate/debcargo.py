#!/usr/bin/python3
# Copyright (C) 2020 Jelmer Vernooij
# This file is a part of debmutate.
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

"""Utility functions for dealing with debcargo files."""

from typing import Optional

from toml.decoder import loads
from toml.encoder import dumps

from .reformatting import Editor


class TomlEditor(Editor):

    def _parse(self, content):
        return loads(content)

    def _format(self, parsed):
        return dumps(parsed)

    def __getitem__(self, key):
        return self._parsed[key]

    def __delitem__(self, key):
        del self._parsed[key]

    def __setitem__(self, key, value):
        self._parsed[key] = value


class DebcargoEditor(TomlEditor):

    def __init__(
            self, path: str = 'debian/debcargo.toml',
            allow_reformatting: Optional[bool] = None):
        super(DebcargoEditor, self).__init__(
            path=path, allow_reformatting=allow_reformatting)
