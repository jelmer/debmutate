#!/usr/bin/python3
# Copyright (C) 2020 Jelmer Vernooij
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

"""Utility functions for editing patches under debian/patches/.
"""

from collections import namedtuple
import os
from typing import Iterator, List, Optional

from .reformatting import Editor


DEFAULT_DEBIAN_PATCHES_DIR = 'debian/patches'


QuiltSeriesEntry = namedtuple(
    'QuiltSeriesEntry', ['name', 'quoted', 'options'])


def parse_quilt_series_line(line: bytes):
    if line.startswith(b'#'):
        quoted = True
        line = line.split(b'#')[1].strip()
    else:
        quoted = False
    args = line.decode().split()
    if not args:
        return None
    patch = args[0]
    if not patch:
        return None
    options = args[1:]
    return QuiltSeriesEntry(patch, quoted, options)


def read_quilt_series(f: Iterator[bytes]) -> Iterator[QuiltSeriesEntry]:
    for line in f:
        ret = parse_quilt_series_line(line)
        if ret is not None:
            yield ret


def find_common_patch_suffix(names: List[str], default: str = '.patch') -> str:
    """Find the common prefix to use for patches.

    Args:
      names: List of filenames in debian/patches/
      default: Default suffix if no default can be found
    Returns:
      a suffix
    """
    suffix_count = {}
    for name in names:
        if name in ('series', '00list'):
            continue
        if name.startswith('README'):
            continue
        suffix = os.path.splitext(name)[1]
        if suffix not in suffix_count:
            suffix_count[suffix] = 0
        suffix_count[suffix] += 1
    if not suffix_count:
        return default
    return max(suffix_count.items(), key=lambda v: v[1])[0]


def write_quilt_series(entries):
    for entry in entries:
        args = []
        if entry.name is not None:
            args.append(entry.name.encode('utf-8'))
        if entry.options:
            args.extend([option.encode('utf-8') for option in entry.options])
        line = b' '.join(args)
        if entry.quoted:
            line = b'# ' + line
        line += b'\n'
        yield line


class QuiltSeriesEditor(Editor):
    """Edit a debian/patches/series file."""

    def __init__(
            self, path: str = 'debian/patches/series',
            allow_reformatting: Optional[bool] = None):
        super(QuiltSeriesEditor, self).__init__(
            path, mode='b', allow_reformatting=allow_reformatting)

    def _parse(self, content):
        return list(read_quilt_series(content.splitlines(True)))

    def _nonexistant(self):
        return None

    def _format(self, parsed):
        if parsed is None:
            return None
        # TODO(jelmer): Support formatting comments and options
        return b''.join(write_quilt_series(parsed))

    def append(self, name, options=[]):
        if self._parsed is None:
            self._parsed = []
        self._parsed.append(QuiltSeriesEntry(name, False, options))

    def patches(self):
        if self._parsed is None:
            return
        for entry in self._parsed:
            if not entry.quoted:
                yield entry.name

    def remove(self, name):
        for i, entry in enumerate(self._parsed):
            if entry.name == name:
                del self._parsed[i]
                return
        raise KeyError(name)
