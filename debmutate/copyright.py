#!/usr/bin/python3
# Copyright (C) 2018 Jelmer Vernooij
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

"""Utility functions for dealing with copyright files."""

__all__ = [
    'NotMachineReadableError',
    'MachineReadableFormatError',
    'CopyrightEditor',
    'upstream_fields_in_copyright',
]

from typing import Dict, Optional

from debian.copyright import (
    Copyright,
    MachineReadableFormatError,
    NotMachineReadableError,
)
from debian.deb822 import RestrictedField

from .reformatting import Editor


class CopyrightEditor(Editor):
    """Update a machine-readable copyright file.
    """

    def __init__(
            self, path: str = 'debian/copyright',
            allow_reformatting: Optional[bool] = None) -> None:
        super(CopyrightEditor, self).__init__(
            path, allow_reformatting=allow_reformatting)

    def _parse(self, content):
        try:
            return Copyright(content, strict=False)
        except ValueError as e:
            raise NotMachineReadableError(str(e))

    def _format(self, parsed):
        return parsed.dump()

    @property
    def copyright(self) -> Copyright:
        """The actual copyright file."""
        return self._parsed

    @property
    def _deb822(self):
        return self._parsed._Copyright__file

    def remove(self, paragraph):
        self._parsed._Copyright__paragraphs.remove(paragraph)
        self._deb822.remove(paragraph._underlying_paragraph)

    def append(self, paragraph):
        self._parsed._Copyright__paragraphs.append(paragraph)
        self._deb822.append(paragraph._underlying_paragraph)

    def insert(self, idx, paragraph):
        self._parsed._Copyright__paragraphs.insert(idx, paragraph)
        self._deb822.insert(idx + 1, paragraph._underlying_paragraph)

    def pop(self, idx):
        p = self._parsed._Copyright__paragraphs[idx]
        self.remove(p)
        return p


def upstream_fields_in_copyright(
        path: str = 'debian/copyright') -> Dict[str, RestrictedField]:
    """Extract upstream fields from a copyright file.

    Args:
      path: Copyright file to open
    Returns:
      Dictionary with Contact/Name keys
    """
    ret = {}
    try:
        with open(path, 'r') as f:
            c = Copyright(f, strict=False)
    except (ValueError, FileNotFoundError, NotMachineReadableError,
            MachineReadableFormatError):
        return {}
    else:
        if c.header.upstream_contact:
            ret['Contact'] = c.header.upstream_contact
        if c.header.upstream_name:
            ret['Name'] = c.header.upstream_name
    return ret
