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

"""Handling of orig tarballs."""

import os
from typing import Optional

SUPPORTED_SUFFIXES = [".tar.gz", ".tar.bz2", ".tar.lzma", ".tar.xz"]


def component_from_orig_tarball(
    tarball_filename: str, package: str, version: str
) -> Optional[str]:
    tarball_filename = os.path.basename(tarball_filename)
    prefix = f"{package}_{version}.orig"
    if not tarball_filename.startswith(prefix):
        raise ValueError(
            f"invalid orig tarball file {tarball_filename} does not have expected prefix {prefix}"
        )
    base = tarball_filename[len(prefix) :]
    for ext in SUPPORTED_SUFFIXES:
        if tarball_filename.endswith(ext):
            base = base[: -len(ext)]
            break
    else:
        raise ValueError(f"orig tarball file {tarball_filename} has unknown extension")
    if base == "":
        return None
    elif base[0] == "-":
        # Extra component
        return base[1:]
    else:
        raise ValueError(
            f"Invalid extra characters in tarball filename {tarball_filename}"
        )
