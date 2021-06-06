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

from datetime import datetime
import re
from typing import Optional, Tuple, Union
from debian.changelog import Version

__all__ = [
    'git_snapshot_data_from_version',
    'mangle_version_for_git',
    'upstream_version_add_revision',
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
    m = re.match(r".*\+next\.([0-9]{4})([0-9]{2})([0-9]{2}).*", version)
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

    Args:
      upstream_version: Upstream version string
      distribution_name: Distribution the package is for
      epoch: Optional epoch
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

    Args:
      upstream_version: a string containing the upstream version number.
    Returns:
      a string containing a revision specifier for the revision of the
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


def upstream_version_add_revision(
        version_string: str, sep: str = '+',
        gitid: Optional[bytes] = None,
        gitdate: Optional[datetime] = None,
        bzr_revno: Optional[str] = None,
        svn_revno: Optional[int] = None):
    """Update the revision in a upstream version string.

    Args:
      branch: Branch in which the revision can be found
      version_string: Original version string
      sep: Separator to use when adding snapshot
      gitid: git sha (as bytes)
      gitdate: timestamp for git
      bzr_revno: Bazaar dotted revno
      svn_revno: Subversion revision number
    """
    for known_suffix in ['+dfsg', '+ds']:
        if version_string.endswith(known_suffix):
            version_string = version_string[:-len(known_suffix)]
    if bzr_revno is not None:
        m = re.match(r"^(.*)([\+~])bzr(\d+)$", version_string)
        if m:
            return "%s%sbzr%s" % (m.group(1), m.group(2), bzr_revno)

    if gitid:
        decoded_gitid: Optional[str] = gitid[:7].decode('ascii')
    else:
        decoded_gitid = None
    if gitdate:
        gitdate_formatted: Optional[str] = gitdate.strftime('%Y%m%d')
    else:
        gitdate_formatted = None

    m = re.match(r"^(.*)([\+~-])git(\d{8})\.([a-f0-9]{7})$", version_string)
    if m and decoded_gitid:
        return "%s%sgit%s.%s" % (
            m.group(1), m.group(2), gitdate_formatted, decoded_gitid)

    m = re.match(r"^(.*)([\+~-])git(\d{8})\.(\d+)\.([a-f0-9]{7})$",
                 version_string)
    if m and decoded_gitid:
        if gitdate_formatted == m.group(3):
            snapshot = int(m.group(4)) + 1
        else:
            snapshot = 0
        return "%s%sgit%s.%d.%s" % (
            m.group(1), m.group(2), gitdate_formatted, snapshot, decoded_gitid)

    m = re.match(r"^(.*)([\+~-])git(\d{8})$", version_string)
    if m and decoded_gitid:
        return "%s%sgit%s" % (m.group(1), m.group(2), gitdate_formatted)

    m = re.match(r"^(.*)([\+~])svn(\d+)$", version_string)
    # FIXME: Raise error if +svn/~svn is present and svn_revno is not set?
    if m and svn_revno:
        return "%s%ssvn%d" % (m.group(1), m.group(2), svn_revno)

    if svn_revno:
        return "%s%ssvn%d" % (version_string, sep, svn_revno)
    elif decoded_gitid:
        return "%s%sgit%s.1.%s" % (
            version_string, sep, gitdate_formatted, decoded_gitid)
    elif bzr_revno is not None:
        return "%s%sbzr%s" % (version_string, sep, bzr_revno)
    else:
        raise ValueError


def debianize_upstream_version(version, package=None):
    """Make an upstream version string suitable for Debian.

    Args:
      version: original upstream version string
      package: package name, if known
    Returns:
      mangled version string for use in Debian versions
    """
    if version.count('_') == 1 and version.count('.') > 0:
        # This is a style commonly used for perl packages.
        # Most debian packages seem to just drop the underscore.
        # See
        # http://blogs.perl.org/users/grinnz/2018/04/a-guide-to-versions-in-perl.html
        version = version.replace('_', '')
    if '_' in version and '.' not in version:
        version = version.replace('_', '.')
    version = version.replace('-rc', '~rc')
    version = version.replace('-beta', '~beta')
    version = version.replace('-alpha', '~alpha')
    return version


def matches_release(upstream_version: str, release_version: str) -> bool:
    """Check whether an upstream version string matches a upstream release.

    This will e.g. strip git and dfsg suffixes before comparing.

    Args:
      upstream_version: Upstream version string
      release_version: Release to check for
    """
    release_version = release_version.lower()
    upstream_version = upstream_version.lower()
    m = re.match("(.*)([~+-])(ds|dfsg|git|bzr|svn|hg).*", upstream_version)
    if m and m.group(1) == release_version:
        return True
    m = re.match("(.*)([~+-]).*", upstream_version)
    if m and m.group(1) == release_version:
        return True
    return False
