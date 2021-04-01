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


# Ideally we wouldn't have a list like this, but unfortunately we do.
COMMON_VENDORS = ['debian', 'ubuntu', 'kali']


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


def initial_debian_revision(distribution_name):
    if distribution_name == "ubuntu":
        return "0ubuntu1"
    else:
        return "1"


def new_upstream_package_version(
        upstream_version, debian_revision, epoch=None):
    ret = Version("%s-%s" % (upstream_version, debian_revision))
    ret.epoch = epoch
    return ret


def new_package_version(upstream_version, distribution_name, epoch=None):
    """Determine the package version for a new upstream.

    :param upstream_version: Upstream version string
    :param distribution_name: Distribution the package is for
    :param epoch: Optional epoch
    """
    debian_revision = initial_debian_revision(distribution_name)
    return new_upstream_package_version(
        upstream_version, debian_revision, epoch=epoch)


def get_snapshot_revision(upstream_version):
    """Return the upstream revision specifier if specified in the upstream
    version.

    When packaging an upstream snapshot some people use +vcsnn or ~vcsnn to
    indicate what revision number of the upstream VCS was taken for the
    snapshot. This given an upstream version number this function will return
    an identifier of the upstream revision if it appears to be a snapshot. The
    identifier is a string containing a bzr revision spec, so it can be
    transformed in to a revision.

    :param upstream_version: a string containing the upstream version number.
    :return: a string containing a revision specifier for the revision of the
        upstream branch that the snapshot was taken from, or None if it
        doesn't appear to be a snapshot.
    """
    match = re.search("(?:~|\\+)bzr([0-9]+)$", upstream_version)
    if match is not None:
        return ("bzr", match.groups()[0])
    match = re.search("(?:~|\\+)svn([0-9]+)$", upstream_version)
    if match is not None:
        return ("svn", match.groups()[0])
    match = re.match(r"^(.*)([\+~])git(\d{8})\.([a-f0-9]{7})$",
                     upstream_version)
    if match:
        return ("git", match.group(4))
    match = re.match(r"^(.*)([\+~])git(\d{8})$", upstream_version)
    if match:
        return ("date", match.group(3))
    return None
