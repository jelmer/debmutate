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

from itertools import chain
import os
from typing import Optional

from tomlkit import loads, dumps

from .reformatting import Editor


DEFAULT_MAINTAINER = (
    "Debian Rust Maintainers <pkg-rust-maintainers@alioth-lists.debian.net>")
DEFAULT_SECTION = 'rust'


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


class DebcargoSourceShimEditor(object):

    def __init__(self, debcargo, crate_name):
        self._debcargo = debcargo
        self.crate_name = crate_name

    def __getitem__(self, name):
        if name in self.SOURCE_KEY_MAP:
            (toml_name, default) = self.SOURCE_KEY_MAP[name]
            try:
                value = self._debcargo['source'][toml_name]
            except KeyError:
                if callable(default):
                    default = default(self)
                if default is not None:
                    return default
                raise
            else:
                if isinstance(value, list):
                    return ', '.join(value)
                return value
        elif name in self.KEY_MAP:
            (toml_name, default) = self.KEY_MAP[name]
            try:
                value = self._debcargo[toml_name]
            except KeyError:
                if callable(default):
                    default = default(self)
                if default is not None:
                    return default
                raise
            else:
                if isinstance(value, list):
                    return ', '.join(value)
                return value
        elif name == 'Source':
            return 'rust-%s' % self.crate_name
        elif name == 'Priority':
            return 'optional'
        else:
            raise KeyError(name)

    def _default_vcs_git(self):
        return 'https://salsa.debian.org/rust-team/debcargo-conf.git [src/%s]' % self.crate_name

    def _default_vcs_browser(self):
        return 'https://salsa.debian.org/rust-team/debcargo-conf/tree/master/src/%s' % self.crate_name

    def __setitem__(self, name, value):
        if name in self.SOURCE_KEY_MAP:
            toml_name, default = self.SOURCE_KEY_MAP[name]
            if callable(default):
                default = default(self)
            if value == default:
                try:
                    del self._debcargo['source'][toml_name]
                except KeyError:
                    pass
            else:
                if not 'source' in self._debcargo:
                    self._debcargo['source'] = {}
                self._debcargo['source'][toml_name] = value
        elif name in self.KEY_MAP:
            toml_name, default = self.KEY_MAP[name]
            if callable(default):
                default = default(self)
            if value == default:
                del self._debcargo[toml_name]
            else:
                self._debcargo[toml_name] = value
        else:
            raise KeyError(name)

    def __delitem__(self, name):
        if name in self.SOURCE_KEY_MAP:
            toml_name, default = self.SOURCE_KEY_MAP[name]
            if default is None:
                try:
                    del self._debcargo['source'][toml_name]
                except KeyError:
                    pass
            else:
                raise KeyError(name)
        elif name in self.KEY_MAP:
            toml_name, default = self.KEY_MAP[name]
            if default is None:
                del self._debcargo[toml_name]
            else:
                raise KeyError(name)
        else:
            raise KeyError(name)

    def get(self, name, default=None):
        try:
            return self[name]
        except KeyError:
            return default

    def __iter__(self):
        for name in chain(self.KEY_MAP, self.SOURCE_KEY_MAP, ['Source', 'Priority']):
            try:
                self[name]
            except KeyError:
                pass
            else:
                yield name

    def items(self):
        for name in self:
            try:
                yield (name, self[name])
            except KeyError:
                pass

    SOURCE_KEY_MAP = {
        'Standards-Version': ('policy', None),
        'Homepage': ('homepage', None),
        'Vcs-Git': ('vcs_git', _default_vcs_git),
        'Vcs-Browser': (
            'vcs_browser', _default_vcs_browser),
        'Section': ('section', None),
        'Build-Depends': ('build_depends', None),
        }
    KEY_MAP = {
        'Maintainer': ('maintainer', DEFAULT_MAINTAINER),
        'Uploaders': ('uploaders', None),
        }


class DebcargoBinaryShimEditor(object):

    BINARY_KEY_MAP = {
        'Section': ('section', DEFAULT_SECTION),
        'Depends': ('depends', None),
        'Recommends': ('recommends', None),
        'Suggests': ('suggests', None),
        'Provides': ('provides', None),
        }

    def __init__(self, debcargo, key, package_name):
        self._debcargo = debcargo
        self._key = key
        self.package_name = package_name

    def __getitem__(self, name):
        if name in self.BINARY_KEY_MAP:
            (toml_name, default) = self.BINARY_KEY_MAP[name]
            try:
                return self._debcargo['packages.' + self._key][toml_name]
            except KeyError:
                if callable(default):
                    default = default(self)
                if default is None:
                    raise
                return default
        elif name == 'Package':
            return self.package_name
        else:
            raise KeyError(name)

    def __setitem__(self, name, value):
        if name in self.BINARY_KEY_MAP:
            self._debcargo['packages.' + self._key][self.BINARY_KEY_MAP[name]] = value
        else:
            raise KeyError(name)

    def get(self, name, default=None):
        try:
            return self[name]
        except KeyError:
            return default

    def __iter__(self):
        for name in chain(self.BINARY_KEY_MAP, ['Package']):
            try:
                self[name]
            except KeyError:
                pass
            else:
                yield name

    def items(self):
        for name in self:
            try:
                yield (name, self[name])
            except KeyError:
                pass


class DebcargoControlShimEditor(object):
    """Shim for debian/control that edits debian/debcargo.toml."""

    def __init__(self, debcargo_editor):
        self.debcargo_editor = debcargo_editor
        self.source = DebcargoSourceShimEditor(
            self.debcargo_editor, self.crate)

    @property
    def crate(self):
        # TODO(jelmer): Check changelog instead?
        return os.path.basename(os.path.abspath(
            os.path.join(os.path.dirname(self.debcargo_editor.path), '..')))

    def __enter__(self):
        self.debcargo_editor.__enter__()
        return self

    def __exit__(self, exc_typ, exc_val, exc_tb):
        self.debcargo_editor.__exit__(exc_typ, exc_val, exc_tb)
        return False

    @property
    def binaries(self):
        ret = [DebcargoBinaryShimEditor(
            self.debcargo_editor, 'lib', 'librust-%s-dev' % self.crate)]
        try:
            need_bin_package = self.debcargo_editor['bin']
        except KeyError:
            try:
                need_bin_package = not self.debcargo_editor['semver_suffix']
            except KeyError:
                need_bin_package = False
        if need_bin_package:
            try:
                bin_name = self.debcargo_editor['bin_name']
            except KeyError:
                bin_name = self.crate
            ret.append(DebcargoBinaryShimEditor(
                self.debcargo_editor, 'bin', bin_name))
        # TODO(jelmer): Add lib+feature packages
        return ret

    @property
    def paragraphs(self):
        return [self.source] + self.binaries
