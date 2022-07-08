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

from collections.abc import MutableMapping
from itertools import chain
import os
import re
from typing import Optional, Tuple

from debian.changelog import Changelog

from tomlkit import loads, dumps

from .reformatting import Editor


DEFAULT_MAINTAINER = (
    "Debian Rust Maintainers <pkg-rust-maintainers@alioth-lists.debian.net>")
DEFAULT_SECTION = 'rust'
CURRENT_STANDARDS_VERSION = '4.5.1'


class AutomaticFieldUnknown(KeyError):
    """Field is generated automatically, and value can not be determined."""


def semver_pair(version):
    import semver
    parsed = semver.VersionInfo.parse(version)
    return '%d.%d' % (parsed.major, parsed.minor)


class TomlEditor(Editor):

    def _parse(self, content):
        return loads(content)

    def _format(self, parsed):
        if not parsed:
            return None
        return dumps(parsed)

    def __contains__(self, key):
        return key in self._parsed

    def __getitem__(self, key):
        return self._parsed[key]

    def __delitem__(self, key):
        del self._parsed[key]

    def __setitem__(self, key, value):
        self._parsed[key] = value

    def get(self, key, default=None):
        return self._parsed.get(key, default)


class DebcargoEditor(TomlEditor):

    def __init__(
            self, path: str = 'debian/debcargo.toml',
            allow_reformatting: Optional[bool] = None,
            allow_missing: bool = False):
        super(DebcargoEditor, self).__init__(
            path=path, allow_reformatting=allow_reformatting)
        self.allow_missing = allow_missing

    def __repr__(self):
        return "%s(%r, allow_reformatting=%r, allow_missing=%r)" % (
            type(self).__name__, self.path, self.allow_reformatting,
            self.allow_missing)

    def _nonexistant(self):
        if self.allow_missing:
            return {}
        raise


class ShimParagraph(MutableMapping):

    def items(self):
        for key in iter(self):
            try:
                yield key, self[key]
            except AutomaticFieldUnknown:
                pass


class DebcargoSourceShimEditor(ShimParagraph):

    def __init__(self, debcargo, crate_name=None, crate_version=None,
                 cargo=None):
        self._debcargo = debcargo
        if crate_name is None:
            crate_name = cargo["package"]["name"]
        if crate_version is None:
            crate_version = cargo["package"]["version"]
        self.crate_version = crate_version
        self.crate_name = crate_name
        self.cargo = cargo

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
                raise KeyError(name)
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
                raise KeyError(name)
            else:
                if isinstance(value, list):
                    return ', '.join(value)
                return value
        elif name == 'Source':
            if self._debcargo.get("semver_suffix", False):
                return 'rust-%s-%s' % (
                    self.crate_name.replace('_', '-'),
                    semver_pair(self.crate_version))
            return 'rust-%s' % self.crate_name.replace('_', '-')
        elif name == 'Priority':
            return 'optional'
        elif name == 'Rules-Requires-Root':
            return 'no'
        else:
            raise KeyError(name)

    def _default_vcs_git(self):
        return ('https://salsa.debian.org/rust-team/debcargo-conf.git '
                '[src/%s]' % self.crate_name)

    def _default_vcs_browser(self):
        return ('https://salsa.debian.org/rust-team/debcargo-conf/tree/'
                'master/src/%s' % self.crate_name)

    def _build_depends(self):
        # TODO(jelmer): read Cargo.toml
        raise AutomaticFieldUnknown('Build-Depends')

    def _default_homepage(self):
        if self.cargo:
            return self.cargo["package"]["homepage"]
        else:
            raise AutomaticFieldUnknown("homepage")

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
                if 'source' not in self._debcargo:
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

    def __iter__(self):
        for name in chain(self.KEY_MAP, self.SOURCE_KEY_MAP,
                          ['Source', 'Priority', 'Rules-Requires-Root']):
            try:
                self[name]
            except KeyError:
                pass
            except AutomaticFieldUnknown:
                yield name
            else:
                yield name

    def __len__(self):
        return len(self.KEY_MAP) + len(self.SOURCE_KEY_MAP) + 2

    SOURCE_KEY_MAP = {
        'Standards-Version': ('policy', CURRENT_STANDARDS_VERSION),
        'Homepage': ('homepage', _default_homepage),
        'Vcs-Git': ('vcs_git', _default_vcs_git),
        'Vcs-Browser': (
            'vcs_browser', _default_vcs_browser),
        'Section': ('section', DEFAULT_SECTION),
        'Build-Depends': ('build_depends', _build_depends),
        }
    KEY_MAP = {
        'Maintainer': ('maintainer', DEFAULT_MAINTAINER),
        'Uploaders': ('uploaders', None),
        }


class DebcargoBinaryShimEditor(ShimParagraph):

    def _provides(self):
        import semver
        parsed = semver.VersionInfo.parse(self.crate_version)
        semver_suffix = self._debcargo.get('semver_suffix', False)
        ret = []
        suffixes = []
        if not semver_suffix:
            suffixes.append('')
        suffixes.append('-%d' % (parsed.major, ))
        suffixes.append('-%d.%d' % (parsed.major, parsed.minor))
        suffixes.append(
            '-%d.%d.%d' % (parsed.major, parsed.minor, parsed.patch))
        for ver_suffix in suffixes:
            for feature in chain([None], self.features or []):
                ret.append(debcargo_binary_name(
                    self.crate_name,
                    suffix=ver_suffix + (('+' + feature) if feature else '')))
        if self.package_name in ret:
            ret.remove(self.package_name)
        if not ret:
            return None
        return '\n ' + ',\n '.join(
            ['%s (= ${binary:Version})' % p for p in ret])

    def _description(self):
        return (
            self._debcargo['description'] + ' - Rust source code\n'
            ' This package contains the source for the Rust mio crate, '
            'packaged by debcargo\n'
            'for use with cargo and dh-cargo.')

    BINARY_KEY_MAP = {
        'Section': ('section', None),
        'Depends': ('depends', None),
        'Recommends': ('recommends', None),
        'Suggests': ('suggests', None),
        'Provides': ('provides', _provides),
        'Description': ('description', _description),
        }

    def __init__(self, crate_name, crate_version, debcargo, key, package_name,
                 features):
        self.crate_name = crate_name
        self.crate_version = crate_version
        self._debcargo = debcargo
        self._key = key
        self.package_name = package_name
        self.features = features

    @property
    def _section(self):
        return 'packages.' + self._key

    def __getitem__(self, name):
        if name in self.BINARY_KEY_MAP:
            (toml_name, default) = self.BINARY_KEY_MAP[name]
            try:
                return self._debcargo[self._section][toml_name]
            except KeyError:
                if callable(default):
                    default = default(self)
                if default is None:
                    raise KeyError(name)
                return default
        elif name == 'Package':
            return self.package_name
        elif name == 'Architecture':
            return 'any'
        elif name == 'Multi-Arch':
            return 'same'
        else:
            raise KeyError(name)

    def __setitem__(self, name, value):
        if name in self.BINARY_KEY_MAP:
            (toml_name, default) = self.BINARY_KEY_MAP[name]
            if self._section not in self._debcargo:
                self._debcargo[self._section] = {}
            self._debcargo[self._section][toml_name] = value
        else:
            raise KeyError(name)

    def __delitem__(self, name):
        if name in self.BINARY_KEY_MAP:
            (toml_name, default) = self.BINARY_KEY_MAP[name]
            if default is None:
                try:
                    del self._debcargo[self._section][toml_name]
                except KeyError:
                    pass
            else:
                raise KeyError(name)
        else:
            raise KeyError(name)

    def __iter__(self):
        for name in chain(
                self.BINARY_KEY_MAP,
                ['Package', 'Provides', 'Multi-Arch', 'Architecture']):
            try:
                self[name]
            except AutomaticFieldUnknown:
                yield name
            except KeyError:
                pass
            else:
                yield name

    def __len__(self):
        return len(self.BINARY_KEY_MAP) + 1


def debcargo_version_to_semver(version):
    m = re.fullmatch('(.*)~([a-z]+)(.*)', version)
    if m:
        return '%s-%s%s' % (m.group(1), m.group(2), m.group(3))
    return version


class DebcargoControlShimEditor(object):
    """Shim for debian/control that edits debian/debcargo.toml."""

    def __init__(self, debcargo_editor, crate_name, crate_version, cargo=None,
                 features=None):
        self.debcargo_editor = debcargo_editor
        self.cargo = cargo
        self.crate_name = crate_name
        self.crate_version = crate_version
        self.features = features

    def __repr__(self):
        return "%s(%r, %r, %r)" % (
            type(self).__name__, self.debcargo_editor,
            self.crate_name, self.crate_version)

    @property
    def source(self):
        return DebcargoSourceShimEditor(
            self.debcargo_editor, crate_name=self.crate_name,
            crate_version=self.crate_version, cargo=self.cargo)

    def wrap_and_sort(self, short_indent: bool = False,
                      trailing_comma: bool = False,
                      wrap_always: bool = False,
                      max_line_length: int = 79) -> None:
        pass

    def sort_binary_packages(self, keep_first: bool = False):
        pass

    @classmethod
    def from_debian_dir(cls, path, crate_name=None, crate_version=None,
                        features=None, cargo=None):
        editor = DebcargoEditor(
                os.path.join(path, 'debcargo.toml'), allow_missing=True)
        cargo_path = os.path.join(path, '..', 'Cargo.toml')
        if cargo is None:
            try:
                with open(cargo_path, 'r') as f:
                    cargo = loads(f.read())
                    crate_name = cargo["package"]["name"]
                    crate_version = cargo["package"]["version"]
                    features = list(cargo['features'])
            except FileNotFoundError:
                pass
        try:
            with open(os.path.join(path, 'changelog'), 'r') as f:
                cl = Changelog(f)
                package = cl.package
                if crate_name is None or crate_version is None:
                    crate_version = debcargo_version_to_semver(
                        cl.version.upstream_version)
                    with editor:
                        semver_suffix = editor.get("semver_suffix", False)
                    crate_name, crate_semver_version = (
                        parse_debcargo_source_name(package, semver_suffix))
        except FileNotFoundError:
            pass
        return cls(
            editor, crate_name=crate_name, crate_version=crate_version,
            cargo=cargo, features=features)

    def __enter__(self):
        self.debcargo_editor.__enter__()
        return self

    def __exit__(self, exc_typ, exc_val, exc_tb):
        self.debcargo_editor.__exit__(exc_typ, exc_val, exc_tb)
        return False

    @property
    def binaries(self):
        semver_suffix = self.debcargo_editor.get('semver_suffix', False)
        ret = [DebcargoBinaryShimEditor(
            self.crate_name, self.crate_version, self.debcargo_editor, 'lib',
            debcargo_binary_name(
                self.crate_name, '-' + semver_pair(self.crate_version)
                if semver_suffix else ''),
            self.features)]
        try:
            need_bin_package = self.debcargo_editor['bin']
        except KeyError:
            try:
                need_bin_package = not semver_suffix
            except KeyError:
                need_bin_package = False
        if need_bin_package:
            try:
                bin_name = self.debcargo_editor['bin_name']
            except KeyError:
                bin_name = self.crate_name
            ret.append(DebcargoBinaryShimEditor(
                self.crate_name, self.crate_version, self.debcargo_editor,
                'bin', bin_name, self.features))
        # TODO(jelmer): Add lib+feature packages
        return ret

    @property
    def paragraphs(self):
        return [self.source] + self.binaries


def parse_debcargo_source_name(
        source_name: str,
        semver_suffix: bool = False) -> Tuple[str, Optional[str]]:
    """Parse a debcargo source name and return crate.

    Args:
      source_name: Source package name
      semver_suffix: Whether semver_suffix is enabled
    Returns:
      tuple with crate name and optional semver
    """
    if not source_name.startswith('rust-'):
        raise ValueError(source_name)
    crate = source_name[len('rust-'):]
    crate_semver_version = None
    if semver_suffix and '-' in crate:
        crate, crate_semver_version = crate.rsplit('-', 1)
    return crate, crate_semver_version


def cargo_translate_dashes(crate):
    import subprocess
    output = subprocess.check_output(['cargo', 'search', crate])
    for line in output.splitlines(False):
        name = line.split(b' = ')[0].decode()
        return name
    return crate


def unmangle_debcargo_version(version):
    return version.replace('~', '-')


def debcargo_binary_name(crate_name, suffix=''):
    return 'librust-%s%s-dev' % (crate_name.replace('_', '-'), suffix)


if __name__ == '__main__':
    from debian.deb822 import Deb822
    with DebcargoControlShimEditor.from_debian_dir('debian') as editor:
        print(Deb822(editor.source))
        for binary in editor.binaries:
            print(Deb822(binary))
