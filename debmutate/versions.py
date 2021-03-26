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

"""Utility functions for dealing with Debian versions."""

import re
from typing import Optional, Tuple, Union
from debian.changelog import Version

__all__ = [
    'git_snapshot_data_from_version',
    'mangle_version_for_git',
    ]


def git_snapshot_data_from_version(
        version: Union[str, Version]) -> Tuple[Optional[str], Optional[str]]:
    """Extract git snapshot information from an upstream version string.

    Args:
      version: A version string
    """
    version = str(version)
    git_id = None
    date = None
    if "+git" in version or "~git" in version or "-git" in version:
        m = re.match(
            ".*[~+-]git([0-9]{4})([0-9]{2})([0-9]{2})\\.([0-9a-f]{7}).*",
            version)
        if not m:
            m = re.match(
                ".*[~+-]git([0-9]{4})([0-9]{2})([0-9]{2})\\."
                "[0-9+]\\.([0-9a-f]{7}).*",
                version)
        if m:
            git_id = m.group(4)
            date = "%s-%s-%s" % (m.group(1), m.group(2), m.group(3))
        else:
            m = re.match(".*[~+]git([0-9]{4})([0-9]{2})([0-9]{2}).*", version)
            if m:
                date = "%s-%s-%s" % (m.group(1), m.group(2), m.group(3))
    return (git_id, date)


def mangle_version_for_git(version: Union[Version, str]) -> str:
    version = str(version)
    # See https://dep-team.pages.debian.net/deps/dep14/
    manipulated = (
        version.replace("~", "_").replace(':', '%').replace('..', '.#.'))
    if manipulated.endswith('.'):
        manipulated += '#'
    if manipulated.endswith('.lock'):
        manipulated = manipulated[:-4] + '#lock'
    return manipulated


def new_package_version(upstream_version, distribution_name, epoch=None):
    """Determine the package version for a new upstream.

    :param upstream_version: Upstream version string
    :param distribution_name: Distribution the package is for
    :param epoch: Optional epoch
    """
    if distribution_name == "ubuntu":
        ret = Version("%s-0ubuntu1" % upstream_version)
    else:
        ret = Version("%s-1" % upstream_version)
    ret.epoch = epoch
    return ret
