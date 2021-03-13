#!/usr/bin/python3
# Copyright (C) 2019 Jelmer Vernooij <jelmer@debian.org>
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

"""Functions for working with watch files."""

from io import StringIO
import logging
import re
import sys
from typing import (
    Iterable, List, Union, Callable, Optional, TextIO, Iterator, Tuple)
from urllib.parse import urljoin

from debian.changelog import Version

from .reformatting import (
    Editor,
    )

from . import __version__

DEFAULT_USER_AGENT = 'debmutate/%s' % '.'.join([str(x) for x in __version__])

DEFAULT_VERSION: int = 4

# TODO(jelmer): Add support for substitution variables:

SUBSTITUTIONS = {
    # This is substituted with the source package name found in the first line
    # of the debian/changelog file.
    '@PACKAGE': None,
    # This is substituted by the legal upstream version regex (capturing).
    '@ANY_VERSION@': r'[-_]?(\d[\-+\.:\~\da-zA-Z]*)',
    # This is substituted by the typical archive file extension regex
    # (non-capturing).
    '@ARCHIVE_EXT@': r'(?i)\.(?:tar\.xz|tar\.bz2|tar\.gz|zip|tgz|tbz|txz)',
    # This is substituted by the typical signature file extension regex
    # (non-capturing).
    '@SIGNATURE_EXT@':
        r'(?i)\.(?:tar\.xz|tar\.bz2|tar\.gz|zip|tgz|tbz|txz)'
        r'\.(?:asc|pgp|gpg|sig|sign)',
    # This is substituted by the typical Debian extension regexp (capturing).
    '@DEB_EXT@': r'[\+~](debian|dfsg|ds|deb)(\.)?(\d+)?$',
}


class InvalidUVersionMangle(ValueError):
    """uversionmangle is invalid"""


class WatchFile(object):

    def __init__(self, entries: Optional[List['Watch']] = None,
                 options: Optional[List[str]] = None,
                 version: int = DEFAULT_VERSION) -> None:
        self.version = version
        if entries is None:
            entries = []
        self.entries = entries
        if options is None:
            options = []
        self.options = options

    def get_option(self, name):
        for option in self.options:
            try:
                key, value = option.split('=', 1)
            except ValueError:
                key = option
                value = None
            if key == name:
                return value
        raise KeyError(name)

    def set_option(self, name, newvalue=None):
        if newvalue is None:
            nv = name
        else:
            nv = '%s=%s' % (name, newvalue)
        for i, option in enumerate(self.options):
            try:
                key, value = option.split('=', 1)
            except ValueError:
                key = option
                value = None
            if key == value:
                self.options[i] = nv
                return
        self.options.append(nv)

    def del_option(self, name):
        for i, option in enumerate(self.options):
            try:
                key, value = option.split('=', 1)
            except ValueError:
                key = option
            if key == name:
                del self.options[i]
                return
        raise KeyError(name)

    def __iter__(self) -> Iterator['Watch']:
        return iter(self.entries)

    def __bool__(self) -> bool:
        return bool(self.entries)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, type(self)) and \
                self.entries == other.entries and \
                self.options == other.options and \
                self.version == other.version

    def dump(self, f: TextIO) -> None:
        def serialize_options(opts: List[str]) -> str:
            s = ','.join(opts)
            if ' ' in s or '\t' in s:
                return 'opts="' + s + '"'
            return 'opts=' + s
        f.write('version=%d\n' % self.version)
        if self.options:
            f.write(serialize_options(self.options) + '\n')
        for entry in self.entries:
            if entry.options:
                f.write(serialize_options(entry.options) + ' ')
            f.write(entry.url)
            if entry.matching_pattern:
                f.write(' ' + entry.matching_pattern)
            if entry.version:
                f.write(' ' + entry.version)
            if entry.script:
                f.write(' ' + entry.script)
            f.write('\n')


def parse_sed_expr(vm):
    if vm.startswith('s'):
        return ('s', parse_subst_expr(vm))
    if vm.startswith('tr'):
        return ('tr', parse_transl_expr(vm))
    raise InvalidUVersionMangle(vm, 'not a substitution or translation regex')


def parse_subst_expr(vm: str) -> Tuple[str, str, Optional[str]]:
    if vm[0] != 's':
        raise InvalidUVersionMangle(vm, 'not a substitution regex')
    parts = re.split(r'(?<!\\)' + vm[1], vm)
    if len(parts) < 3:
        raise InvalidUVersionMangle(vm)
    pattern = parts[1]
    replacement = parts[2]
    flags: Optional[str]
    try:
        flags = parts[3]
    except IndexError:
        flags = None
    return (pattern, replacement, flags)


def parse_transl_expr(vm: str) -> Tuple[str, str, Optional[str]]:
    if not vm.startswith('tr'):
        raise InvalidUVersionMangle(vm, 'not a translation regex')
    parts = re.split(r'(?<!\\)' + vm[2], vm)
    if len(parts) < 3:
        raise InvalidUVersionMangle(vm)
    pattern = parts[1]
    replacement = parts[2]
    flags: Optional[str]
    try:
        flags = parts[3]
    except IndexError:
        flags = None
    return (pattern, replacement, flags)


def apply_sed_expr(vm: str, orig: str) -> str:
    (kind, (pattern, replacement, flags)) = parse_sed_expr(vm)
    if kind == 's':
        # TODO(jelmer): Handle flags
        return re.sub(pattern, replacement.replace('$', '\\'), orig)
    elif kind == 'tr':
        from tr import tr
        return tr(pattern, replacement, orig, flags or '')
    else:
        raise ValueError(kind)


def apply_url_mangle(expr: str, orig: str) -> str:
    return apply_sed_expr(expr, orig)


class Release(object):
    """A discovered release."""

    def __init__(self, version, url, pgpsigurl=None):
        self.version = version
        self.url = url
        self.pgpsigurl = pgpsigurl

    def __lt__(self, other):
        if type(self) != type(other):
            raise TypeError(other)
        return Version(self.version) < Version(other.version)

    def __repr__(self):
        return "%s(%r, %r, pgpsigurl=%r)" % (
            type(self).__name__, self.version, self.url,
            self.pgpsigurl)


def html_search(body, matching_pattern, base_url):
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(body, 'html.parser')
    matching_pattern = urljoin(base_url.rstrip('/') + '/', matching_pattern)
    for a in soup.find_all('a'):
        href = a.attrs.get('href')
        if not href:
            continue
        href = urljoin(base_url.rstrip('/') + '/', href)
        m = re.fullmatch(matching_pattern, href)
        if m:
            yield m


def plain_search(body, matching_pattern, base_url):
    return re.finditer(matching_pattern.encode(), body)


searchers = {
    'plain': plain_search,
    'html': html_search,
    }


class Watch(object):

    def __init__(self, url: str, matching_pattern: Optional[str] = None,
                 version: Optional[str] = None, script: Optional[str] = None,
                 opts: Optional[List[str]] = None) -> None:
        self.url = url
        self.matching_pattern = matching_pattern
        self.version = version
        self.script = script
        if opts is None:
            opts = []
        self.options = opts

    def uversionmangle(self, version):
        try:
            vm = self.get_option('uversionmangle')
        except KeyError:
            return version
        try:
            return apply_sed_expr(vm, version)
        except re.error as e:
            raise WatchSyntaxError(
                'invalid uversionmangle %r: %s' % (vm, e)) from e

    def get_option(self, name):
        for option in self.options:
            try:
                key, value = option.split('=', 1)
            except ValueError:
                key = option
                value = None
            if key == name:
                return value
        raise KeyError(name)

    def has_option(self, name):
        try:
            self.get_option(name)
        except KeyError:
            return False
        return True

    def set_option(self, name, newvalue=None):
        if newvalue is None:
            nv = name
        else:
            nv = '%s=%s' % (name, newvalue)
        for i, option in enumerate(self.options):
            try:
                key, value = option.split('=', 1)
            except ValueError:
                key = option
                value = None
            if key == value:
                self.options[i] = nv
                return
        self.options.append(nv)

    def del_option(self, name):
        for i, option in enumerate(self.options):
            try:
                key, value = option.split('=', 1)
            except ValueError:
                key = option
            if key == name:
                del self.options[i]
                return
        raise KeyError(name)

    def __repr__(self) -> str:
        return (
            "%s(%r, matching_pattern=%r, version=%r, script=%r, opts=%r)" % (
                self.__class__.__name__, self.url, self.matching_pattern,
                self.version, self.script, self.options))

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Watch):
            return False
        return (other.url == self.url and
                other.matching_pattern == self.matching_pattern and
                other.version == self.version and
                other.script == self.script and
                other.options == self.options)

    def format_url(self, package: Union[str, Callable[[], str]]) -> str:
        if '@PACKAGE@' not in self.url:
            return self.url
        if callable(package):
            package = package()
        return self.url.replace('@PACKAGE@', package)

    def discover(self, package):
        from urllib.request import urlopen, Request
        url = self.format_url(package)
        try:
            user_agent = self.get_option('user-agent')
        except KeyError:
            user_agent = DEFAULT_USER_AGENT
        try:
            searchmode = self.get_option('searchmode')
        except KeyError:
            searchmode = 'html'
        logging.debug('Fetching url %s; searchmode=%s', url, searchmode)
        req = Request(url, headers={'User-Agent': user_agent})
        resp = urlopen(req)
        for m in searchers[searchmode](
                resp.read(), self.matching_pattern, url):
            # TODO(jelmer): Apply uversionmangle
            full_url = urljoin(url, m.group(0))
            try:
                pgpsigurlmangle = self.get_option('pgpsigurlmangle')
            except KeyError:
                pgpsigurl = None
            else:
                pgpsigurl = apply_url_mangle(pgpsigurlmangle, full_url)
            yield Release(m.group(1), full_url, pgpsigurl=pgpsigurl)


class MissingVersion(Exception):
    """The version= line is missing."""


class WatchSyntaxError(Exception):
    """Syntax error in watch file."""


def parse_watch_file(f: Iterable[str]) -> Optional[WatchFile]:
    """Parse a watch file.

    Args:
      f: watch file to parse
    """
    line: Optional[str]
    lines: List[List[str]] = []
    continued: List[str] = []
    for line in f:
        if line.startswith('#'):
            continue
        if not line.strip():
            continue
        if line.rstrip('\n').endswith('\\'):
            continued.append(line.rstrip('\n\\'))
        else:
            continued.append(line)
            lines.append(continued)
            continued = []
    if continued:
        # Hmm, broken line?
        logging.warning('watchfile ended with \\; skipping last line')
        lines.append(continued)
    if not lines:
        return None
    firstline = ''.join(lines.pop(0))
    try:
        key, value = firstline.split('=', 1)
    except ValueError:
        raise MissingVersion()
    if key.strip() != 'version':
        raise MissingVersion()
    version = int(value.strip())
    persistent_options: List[str] = []
    entries: List[Watch] = []
    chunked: List[str]
    for chunked in lines:
        if version > 3:
            chunked = [chunk.lstrip() for chunk in chunked]
        line = ''.join(chunked).strip()
        if not line:
            continue
        opts: Optional[List[str]]
        if line.startswith('opts='):
            if line[5] == '"':
                optend = line.index('"', 6)
                if optend == -1:
                    raise ValueError('Not matching " in %r' % line)
                opts_str = line[6:optend]
                line = line[optend+1:]
            else:
                try:
                    (opts_str, line) = line[5:].split(maxsplit=1)
                except ValueError:
                    opts_str = line[5:]
                    line = None
            opts = opts_str.split(',')
        else:
            opts = None
        if not line:
            if opts:
                persistent_options.extend(opts)
        else:
            try:
                url, line = line.split(maxsplit=1)
            except ValueError:
                url = line
                line = ''
            m = re.findall(r'/([^/]*\([^/]*\)[^/]*)$', url)
            if m:
                parts = [m[0]] + line.split(maxsplit=1)
                url = url[:-len(m[0])-1].strip()
            else:
                parts = line.split(maxsplit=2)
            entries.append(Watch(url, *parts, opts=opts))  # type: ignore
    return WatchFile(
        entries=entries, options=persistent_options, version=version)


class WatchEditor(Editor):

    _parsed: WatchFile

    def __init__(
            self, path: str = 'debian/watch',
            allow_reformatting: Optional[bool] = None) -> None:
        super(WatchEditor, self).__init__(
            path, allow_reformatting=allow_reformatting)

    @property
    def watch_file(self) -> WatchFile:
        return self._parsed

    def _nonexistant(self) -> None:
        return None

    def _parse(self, content: str) -> WatchFile:
        wf = parse_watch_file(content.splitlines())
        if wf is None:
            return WatchFile([])
        return wf

    def _format(self, parsed: WatchFile) -> str:
        if parsed is None:
            return None
        nf = StringIO()
        parsed.dump(nf)
        return nf.getvalue()


def uscan(wf, package):
    for entry in wf.entries:
        logging.info('entry: %s' % entry)
        for d in entry.discover(package):
            logging.info('  %s' % d)


def main(argv):
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--verbose', action='store_true')
    args = parser.parse_args()
    if args.verbose:
        logging.basicConfig(level=logging.DEBUG, format='%(message)s')
    else:
        logging.basicConfig(level=logging.INFO, format='%(message)s')
    with open('debian/watch', 'r') as f:
        wf = parse_watch_file(f)
    from debian.deb822 import Deb822
    with open('debian/control', 'r') as f:
        source = Deb822(f)
    uscan(wf, source['Source'])


if __name__ == '__main__':
    sys.exit(main(sys.argv))
