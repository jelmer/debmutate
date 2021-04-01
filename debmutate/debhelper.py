#!/usr/bin/python3
# Copyright (C) 2019 Jelmer Vernooij
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


"""Debhelper utility functions."""

__all__ = [
    'ensure_minimum_debhelper_version',
    'read_debhelper_compat_file',
    'get_debhelper_compat_level',
    ]

from dataclasses import dataclass
import os
from typing import Optional, Union

from debian.deb822 import Deb822

from debian.changelog import Version

from .control import (
    ensure_minimum_version,
    get_relation,
    parse_relations,
    ControlEditor,
    )
from .reformatting import Editor


def ensure_minimum_debhelper_version(
        source: Deb822, minimum_version: Union[str, Version]) -> bool:
    """Ensure that the pakcage is at least using version x of debhelper.

    This is a dedicated helper, since debhelper can now also be pulled in
    with a debhelper-compat dependency.

    Args:
      source: Source dictionary
      version: The minimum version
    """
    # TODO(jelmer): Also check Build-Depends-Indep and Build-Depends-Arch?
    for field in ['Build-Depends-Arch', 'Build-Depends-Indep']:
        value = source.get(field, '')
        try:
            offset, debhelper_compat = get_relation(
                value, "debhelper-compat")
        except KeyError:
            pass
        else:
            raise Exception('debhelper-compat in %s' % field)
        try:
            offset, debhelper_compat = get_relation(
                value, "debhelper")
        except KeyError:
            pass
        else:
            raise Exception('debhelper compat in %s' % field)

    build_depends = source.get('Build-Depends', '')
    minimum_version = Version(minimum_version)
    try:
        offset, debhelper_compat = get_relation(
            build_depends, "debhelper-compat")
    except KeyError:
        pass
    else:
        if len(debhelper_compat) > 1:
            raise Exception("Complex rule for debhelper-compat, aborting")
        if debhelper_compat[0].version[0] != '=':
            raise Exception("Complex rule for debhelper-compat, aborting")
        if Version(debhelper_compat[0].version[1]) >= minimum_version:
            return False
    new_build_depends = ensure_minimum_version(
            build_depends,
            "debhelper", minimum_version)
    if new_build_depends != source.get('Build-Depends'):
        source['Build-Depends'] = new_build_depends
        return True
    return False


def read_debhelper_compat_file(path: str) -> int:
    """Read a debian/compat file.

    Args:
      path: Path to read from
    """
    with open(path, 'r') as f:
        line = f.readline().split('#', 1)[0]
        return int(line.strip())


def get_debhelper_compat_level_from_control(control) -> Optional[int]:
    try:
        offset, [relation] = get_relation(
            control.get("Build-Depends", ""), "debhelper-compat")
    except (IndexError, KeyError):
        return None
    else:
        return int(str(relation.version[1]))


def get_debhelper_compat_level(path: str = '.') -> Optional[int]:
    try:
        return read_debhelper_compat_file(os.path.join(path, 'debian/compat'))
    except FileNotFoundError:
        pass

    try:
        with open(os.path.join(path, 'debian/control'), 'r') as f:
            control = Deb822(f)
    except FileNotFoundError:
        return None

    return get_debhelper_compat_level_from_control(control)


@dataclass
class MaintscriptSupports:
    command: str

    def args(self):
        return ['supports', self.command]


@dataclass
class MaintscriptRemoveConffile:
    conffile: str
    prior_version: Optional[Version] = None
    package: Optional[str] = None

    def args(self):
        ret = ['rm_conffile', self.conffile]
        if self.prior_version:
            ret.append(str(self.prior_version))
            if self.package:
                ret.append(self.package)
        return ret


@dataclass
class MaintscriptMoveConffile:
    old_conffile: str
    new_conffile: str
    prior_version: Optional[Version] = None
    package: Optional[str] = None

    def args(self):
        ret = ['mv_conffile', self.old_conffile, self.new_conffile]
        if self.prior_version:
            ret.append(str(self.prior_version))
            if self.package:
                ret.append(self.package)
        return ret


@dataclass
class MaintscriptSymlinkToDir:
    pathname: str
    old_target: str
    prior_version: Optional[Version] = None
    package: Optional[str] = None

    def args(self):
        ret = ['symlink_to_dir', self.pathname, self.old_target]
        if self.prior_version:
            ret.append(str(self.prior_version))
            if self.package:
                ret.append(self.package)
        return ret


@dataclass
class MaintscriptDirToSymlink:
    pathname: str
    new_target: str
    prior_version: Optional[Version] = None
    package: Optional[str] = None

    def args(self):
        ret = ['dir_to_symlink', self.pathname, self.new_target]
        if self.prior_version:
            ret.append(str(self.prior_version))
            if self.package:
                ret.append(self.package)
        return ret


def parse_maintscript_line(line):
    args = line.split()
    return {
        'supports': MaintscriptSupports,
        'rm_conffile': MaintscriptRemoveConffile,
        'mv_conffile': MaintscriptMoveConffile,
        'symlink_to_dir': MaintscriptSymlinkToDir,
        'dir_to_symlink': MaintscriptDirToSymlink,
        }.get(args[0], list)(*args[1:])


def serialize_maintscript_line(args):
    return ' '.join(args)


class MaintscriptEditor(Editor):

    def __init__(
            self, path: str = 'debian/maintscript',
            allow_reformatting: Optional[bool] = None):
        super(MaintscriptEditor, self).__init__(
            path=path, allow_reformatting=allow_reformatting)

    def _nonexistant(self):
        return None

    def _parse(self, content):
        """Parse the specified bytestring and returned parsed object."""
        ret = []
        for line in content.splitlines(True):
            if line.startswith('#') or not line.strip():
                ret.append(line.rstrip('\n'))
            else:
                ret.append(parse_maintscript_line(line))
        return ret

    @property
    def lines(self):
        if self._parsed is None:
            return []
        return self._parsed

    @property
    def entries(self):
        return [entry for entry in self.lines
                if not isinstance(entry, str)]

    def __delitem__(self, req):
        ei = 0
        # TODO(jelmer): Also remove preceding comments?
        for i, e in enumerate(self.lines):
            if not isinstance(e, str):
                if ei == req:
                    del self.lines[i]
                    return
                ei += 1
        raise IndexError(req)

    def __getitem__(self, req):
        return self.entries[req]

    def __len__(self):
        return len(self.entries)

    def append(self, entry):
        if self._parsed is None:
            self._parsed = [entry]
        else:
            self._parsed.extend([entry])

    def _format(self, parsed):
        """Serialize the parsed object."""
        if self._parsed is None:
            return None
        ret = []
        for entry in self._parsed:
            if isinstance(entry, str):
                ret.append(entry + '\n')
            else:
                ret.append(serialize_maintscript_line(entry.args()) + '\n')
        if ret:
            return ''.join(ret)
        return None


def get_sequences(debian_path='debian', control_editor=None):
    if control_editor is None:
        control_editor = ControlEditor(os.path.join(debian_path, 'control'))
    with control_editor:
        for ws1, entry, ws2 in parse_relations(
                control_editor.source.get('Build-Depends', '')):
            for option in entry:
                if option.name.startswith('dh-sequence-'):
                    yield option.name[len('dh-sequence-'):]
