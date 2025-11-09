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
    "ensure_minimum_debhelper_version",
    "read_debhelper_compat_file",
    "get_debhelper_compat_level",
]

import os
from dataclasses import dataclass
from typing import Dict, Iterator, List, Optional, Union, cast

from debian.changelog import Version  # type: ignore[attr-defined]
from debian.deb822 import Deb822

from .control import (
    ControlEditor,
    ensure_minimum_version,
    get_relation,
    parse_relations,
)
from .reformatting import Editor


def ensure_minimum_debhelper_version(
    source: Union[Deb822, Dict[str, str]], minimum_version: Union[str, Version]
) -> bool:
    """Ensure that the package is at least using version x of debhelper.

    This is a dedicated helper, since debhelper can now also be pulled in
    with a debhelper-compat dependency.

    Args:
      source: Source dictionary
      version: The minimum version
    """
    # TODO(jelmer): Also check Build-Depends-Indep and Build-Depends-Arch?
    for field in ["Build-Depends-Arch", "Build-Depends-Indep"]:
        value = source.get(field, "")
        try:
            offset, debhelper_compat = get_relation(value, "debhelper-compat")
        except KeyError:
            pass
        else:
            raise Exception(f"debhelper-compat in {field}")
        try:
            offset, debhelper_compat = get_relation(value, "debhelper")
        except KeyError:
            pass
        else:
            raise Exception(f"debhelper compat in {field}")

    build_depends = source.get("Build-Depends", "")
    minimum_version = Version(minimum_version)
    try:
        offset, debhelper_compat = get_relation(build_depends, "debhelper-compat")
    except KeyError:
        pass
    else:
        if len(debhelper_compat) > 1:
            raise Exception("Complex rule for debhelper-compat, aborting")
        if debhelper_compat[0].version is None:
            raise Exception("debhelper-compat without version, aborting")
        if debhelper_compat[0].version[0] != "=":
            raise Exception("Complex rule for debhelper-compat, aborting")
        if Version(debhelper_compat[0].version[1]) >= minimum_version:
            return False
    new_build_depends = ensure_minimum_version(
        build_depends, "debhelper", minimum_version
    )
    if new_build_depends != source.get("Build-Depends", ""):
        source["Build-Depends"] = new_build_depends
        return True
    return False


def read_debhelper_compat_file(path: str) -> int:
    """Read a debian/compat file.

    Args:
      path: Path to read from
    """
    with open(path, encoding="utf-8") as f:
        line = f.readline().split("#", 1)[0]
        return int(line.strip())


def get_debhelper_compat_level_from_control(
    control: Union[Deb822, Dict[str, str]],
) -> Optional[int]:
    """Get the debhelper compat level from a Deb822 control file.

    Args:
        control: A Deb822 object representing the control file
    Returns:
        The debhelper compat level, or None if not found
    """
    x_dh_compat = control.get("X-DH-Compat", "")
    if x_dh_compat:
        try:
            return int(x_dh_compat)
        except ValueError:
            raise ValueError(f"Invalid X-DH-Compat value: {x_dh_compat}")

    try:
        offset, [relation] = get_relation(
            control.get("Build-Depends", ""), "debhelper-compat"
        )
    except (IndexError, KeyError):
        return None
    else:
        if relation.version is None:
            return None
        return int(str(relation.version[1]))


def get_debhelper_compat_level(path: str = ".") -> Optional[int]:
    try:
        return read_debhelper_compat_file(os.path.join(path, "debian/compat"))
    except FileNotFoundError:
        pass

    try:
        with open(os.path.join(path, "debian/control"), encoding="utf-8") as f:
            control = Deb822(f)
    except FileNotFoundError:
        return None

    return get_debhelper_compat_level_from_control(control)


@dataclass
class MaintscriptSupports:
    command: str

    def args(self) -> List[str]:
        return ["supports", self.command]


@dataclass
class MaintscriptRemoveConffile:
    conffile: str
    prior_version: Optional[Version] = None
    package: Optional[str] = None

    def args(self) -> List[str]:
        ret = ["rm_conffile", self.conffile]
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

    def args(self) -> List[str]:
        ret = ["mv_conffile", self.old_conffile, self.new_conffile]
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

    def args(self) -> List[str]:
        ret = ["symlink_to_dir", self.pathname, self.old_target]
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

    def args(self) -> List[str]:
        ret = ["dir_to_symlink", self.pathname, self.new_target]
        if self.prior_version:
            ret.append(str(self.prior_version))
            if self.package:
                ret.append(self.package)
        return ret


# Type alias for maintscript entries
MaintscriptEntry = Union[
    MaintscriptSupports,
    MaintscriptRemoveConffile,
    MaintscriptMoveConffile,
    MaintscriptSymlinkToDir,
    MaintscriptDirToSymlink,
]


def parse_maintscript_line(line: str) -> Union[str, MaintscriptEntry]:
    args = line.split()
    constructors = {
        "supports": MaintscriptSupports,
        "rm_conffile": MaintscriptRemoveConffile,
        "mv_conffile": MaintscriptMoveConffile,
        "symlink_to_dir": MaintscriptSymlinkToDir,
        "dir_to_symlink": MaintscriptDirToSymlink,
    }
    if args[0] in constructors:
        return cast(MaintscriptEntry, constructors[args[0]](*args[1:]))
    else:
        return line.strip()


def serialize_maintscript_line(args: List[str]) -> str:
    return " ".join(args)


class MaintscriptEditor(Editor[List[Union[str, MaintscriptEntry]], str]):
    def __init__(
        self,
        path: str = "debian/maintscript",
        allow_reformatting: Optional[bool] = None,
    ):
        super().__init__(path=path, allow_reformatting=allow_reformatting)

    def _nonexistent(self) -> List[Union[str, MaintscriptEntry]]:
        return []

    def _parse(self, content: str) -> List[Union[str, MaintscriptEntry]]:
        """Parse the specified bytestring and returned parsed object."""
        ret: List[Union[str, MaintscriptEntry]] = []
        for line in content.splitlines(True):
            if line.startswith("#") or not line.strip():
                ret.append(line.rstrip("\n"))
            else:
                ret.append(parse_maintscript_line(line))
        return ret

    @property
    def lines(self) -> List[Union[str, MaintscriptEntry]]:
        if self._parsed is None:
            return []
        return self._parsed

    @property
    def entries(self) -> List[MaintscriptEntry]:
        return [entry for entry in self.lines if not isinstance(entry, str)]

    def __delitem__(self, req: int) -> None:
        ei = 0
        # TODO(jelmer): Also remove preceding comments?
        for i, e in enumerate(self.lines):
            if not isinstance(e, str):
                if ei == req:
                    del self.lines[i]
                    return
                ei += 1
        raise IndexError(req)

    def __getitem__(self, req: int) -> MaintscriptEntry:
        return self.entries[req]

    def __len__(self) -> int:
        return len(self.entries)

    def append(self, entry: MaintscriptEntry) -> None:
        if self._parsed is None:
            self._parsed = [entry]
        else:
            self._parsed.extend([entry])

    def _format(
        self, parsed: Optional[List[Union[str, MaintscriptEntry]]]
    ) -> Optional[str]:
        """Serialize the parsed object."""
        if self._parsed is None:
            return None
        ret = []
        for entry in self._parsed:
            if isinstance(entry, str):
                ret.append(entry + "\n")
            else:
                ret.append(serialize_maintscript_line(entry.args()) + "\n")
        if ret:
            return "".join(ret)
        return None


def get_sequences(
    debian_path: str = "debian", control_editor: Optional[ControlEditor] = None
) -> Iterator[str]:
    if control_editor is None:
        control_editor = ControlEditor(os.path.join(debian_path, "control"))
    with control_editor:
        for _ws1, entry, _ws2 in parse_relations(
            control_editor.source.get("Build-Depends", "")
        ):
            for option in entry:
                if option.name.startswith("dh-sequence-"):
                    yield option.name[len("dh-sequence-") :]
