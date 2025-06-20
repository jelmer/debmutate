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

"""Utility functions for dealing with lintian overrides files."""

import fnmatch
import re
from typing import Callable, Iterator, List, Optional, TextIO, Union

from .reformatting import Editor

# https://lintian.debian.org/manual/section-2.4.html
# File format (as documented in policy 2.4.1):
# [[<package>][ <archlist>][ <type>]: ]<lintian-tag>[ [*]<lintian-info>[*]]


VALID_TYPES = ["udeb", "source", "binary"]


def _create_matcher(value: Optional[str]) -> Callable[[str], bool]:
    if value:
        p = re.compile(fnmatch.translate(value))
        return lambda x: bool(p.match(x))
    else:
        return lambda x: True


class LintianOverride:
    def __init__(
        self,
        package: Optional[str] = None,
        archlist: Optional[List[str]] = None,
        type: Optional[str] = None,
        tag: Optional[str] = None,
        info: Optional[str] = None,
    ) -> None:
        self.package = package
        self.archlist = archlist
        if type is not None and type not in VALID_TYPES:
            raise ValueError(type)
        self.type = type
        self.tag = tag
        self._tag_match = _create_matcher(self.tag)
        self.info = info
        self._info_match = _create_matcher(self.info)

    def __repr__(self) -> str:
        return f"{type(self).__name__}(package={self.package!r}, archlist={self.archlist!r}, type={self.type!r}, tag={self.tag!r}, info={self.info!r})"

    def matches(
        self,
        package: Optional[str] = None,
        tag: Optional[str] = None,
        info: Optional[str] = None,
        arch: Optional[str] = None,
        type: Optional[str] = None,
    ) -> bool:
        if self.package is not None and package is not None and self.package != package:
            return False
        if self.type is not None and type is not None and self.type != type:
            return False
        if self.tag is not None and tag is not None and not self._tag_match(tag):
            return False
        if self.info is not None and info is not None and not self._info_match(info):
            return False
        # TODO(jelmer): wildcards in the arch list?
        if self.archlist and arch is not None and arch not in self.archlist:
            return False
        return True

    def __eq__(self, other: object) -> bool:
        return (
            isinstance(other, type(self))
            and self.package == other.package
            and self.archlist == other.archlist
            and self.type == other.type
            and self.tag == other.tag
            and self.info == other.info
        )


class LintianOverridesEditor(Editor[List[Union[str, LintianOverride]], str]):
    def _parse(self, content: str) -> List[Union[str, LintianOverride]]:
        """Parse the specified bytestring and returned parsed object."""
        ret: List[Union[str, LintianOverride]] = []
        for line in content.splitlines(True):
            if line.startswith("#") or not line.strip():
                ret.append(line)
            else:
                ret.append(parse_override(line))
        return ret

    @property
    def lines(self) -> List[Union[str, LintianOverride]]:
        return self._parsed or []

    @property
    def overrides(self) -> List[LintianOverride]:
        return [entry for entry in self.lines if isinstance(entry, LintianOverride)]

    def _nonexistent(self) -> List[Union[str, LintianOverride]]:
        return []

    def override_exists(
        self, tag: str, info: Optional[str] = None, package: Optional[str] = None
    ) -> bool:
        """Check if a particular override exists.

        Args:
          tag: Tag name
          info: Optional info
          package: Package (as type, name tuple)
        """
        for override in self.overrides:
            if override.matches(package=package, info=info, tag=tag):
                return True
        return False

    def _format(
        self, parsed: Optional[List[Union[str, LintianOverride]]]
    ) -> Optional[str]:
        """Serialize the parsed object."""
        if self._parsed is None:
            return None
        ret = []
        for entry in self._parsed:
            if isinstance(entry, str):
                ret.append(entry)
            else:
                ret.append(serialize_override(entry))
        return "".join(ret)


def parse_override(line: str) -> LintianOverride:
    """Parse an override line.

    Args:
      line: Line to parse
    Returns:
      An Override object
    Raises:
      ValueError: when encountering invalid syntax
    """
    info: Optional[str]
    line = line.strip()
    archlist = None
    package = None
    type = None
    if ": " in line:
        origin, issue = line.split(": ", 1)
        while origin:
            origin = origin.strip()
            if origin.startswith("["):
                archs, origin = origin[1:].split("]", 1)
                archlist = archs.strip().split()
            else:
                try:
                    field, origin = origin.split(" ", 1)
                except ValueError:
                    field = origin
                    origin = ""
                if field in VALID_TYPES:
                    type = field
                else:
                    package = field
    else:
        issue = line
    try:
        tag, info = issue.split(None, 1)
    except ValueError:
        tag = issue
        info = None
    return LintianOverride(
        package=package, archlist=archlist, type=type, tag=tag, info=info
    )


def serialize_override(override: LintianOverride) -> str:
    """Serialize an override.

    Args:
      override: An Override object
    Returns:
      serialized override, including newline
    """
    origin = []
    if override.package:
        origin.append(override.package)
    if override.archlist:
        origin.append("[" + " ".join(override.archlist) + "]")
    if override.type:
        origin.append(override.type)
    if origin:
        line = " ".join(origin) + ": " + (override.tag or "")
    else:
        line = override.tag or ""
    if override.info:
        line += " " + override.info
    return line + "\n"


def iter_overrides(f: TextIO) -> Iterator[LintianOverride]:
    """Iterate over overrides in a file."""
    for line in f.readlines():
        if line.startswith("#") or not line.strip():
            pass
        else:
            yield parse_override(line)
