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

"""Utility functions for dealing with Debian Vcs URLs of various types."""

__all__ = [
    'split_vcs_url',
    'unsplit_vcs_url',
    'get_vcs_info',
    'mangle_version_for_git',
    'source_package_vcs',
    'gbp_expand_tag_name',
    ]

import re
from typing import Optional, Tuple


def split_vcs_url(url: str) -> Tuple[str, Optional[str], Optional[str]]:
    """Split a Debian VCS URL.

    Args:
      url: Url to split
    Returns:
      tuple with (url, optional branch, optional path)
    """
    subpath: Optional[str]
    branch: Optional[str]
    m = re.search(r' \[([^] ]+)\]', url)
    if m:
        url = url[:m.start()] + url[m.end():]
        subpath = m.group(1)
    else:
        subpath = None
    try:
        (repo_url, branch) = url.split(' -b ', 1)
    except ValueError:
        branch = None
        repo_url = url
    return (repo_url, branch, subpath)


def unsplit_vcs_url(repo_url: str,
                    branch: Optional[str] = None,
                    subpath: Optional[str] = None) -> str:
    """Unsplit a Debian VCS URL.

    Args:
      repo_url: Repository URL
      branch: Branch name
      subpath: Subpath in the tree
    Returns: full URL
    """
    url = repo_url
    if branch:
        url = '%s -b %s' % (url, branch)
    if subpath:
        url = '%s [%s]' % (url, subpath)
    return url


def get_vcs_info(control) -> Tuple[
        Optional[str], Optional[str], Optional[str]]:
    if "Vcs-Git" in control:
        repo_url, branch, subpath = split_vcs_url(control["Vcs-Git"])
        return ("Git", repo_url, subpath)

    if "Vcs-Bzr" in control:
        return ("Bzr", control["Vcs-Bzr"], None)

    if "Vcs-Svn" in control:
        return ("Svn", control["Vcs-Svn"], None)

    if "Vcs-Hg" in control:
        repo_url, branch, subpath = split_vcs_url(control["Vcs-Hg"])
        return ("Hg", repo_url, subpath)

    return None, None, None


def mangle_version_for_git(version: str) -> str:
    """Mangle a version string for use in a Git tag.

    Args:
      version: version string to manipulate
    Returns: tag name
    """
    # See https://dep-team.pages.debian.net/deps/dep14/
    manipulated = (
        version.replace("~", "_").replace(':', '%').replace('..', '.#.'))
    if manipulated.endswith('.'):
        manipulated += '#'
    if manipulated.endswith('.lock'):
        manipulated = manipulated[:-4] + '#lock'
    return manipulated


def source_package_vcs(control) -> Tuple[str, str]:
    """Extract the Vcs URL from a source package.

    Args:
      control: A source control paragraph
    Returns:
      Tuple with Vcs type and Vcs URL
    Raises:
      KeyError: When no Vcs header was found
    """
    for prefix in ['Vcs-', 'XS-Vcs-', 'X-Vcs']:
        for field, value in control.items():
            if field.startswith(prefix):
                vcs_type = field[len(prefix):]
                if vcs_type == 'Browser':
                    continue
                return vcs_type, value
    raise KeyError


class GbpTagFormatError(Exception):
    """Unknown variable in gbp tag name."""

    def __init__(self, tag_name, variable):
        super(GbpTagFormatError, self).__init__(tag_name, variable)
        self.variable = variable
        self.tag_name = tag_name


def gbp_expand_tag_name(tag_format: str, version: str) -> str:
    # See gbp/pkg/pkgpolicy.py in gbp-buildpackage
    version_mangle_re = (
        r'%\(version'
        r'%(?P<M>[^%])'
        r'%(?P<R>([^%]|\\%))+'
        r'\)s')

    ret = tag_format
    m = re.search(version_mangle_re, tag_format)
    if m:
        ret = re.sub(version_mangle_re, "%(version)s", tag_format)
        version = version.replace(
            m.group('M'), m.group('R').replace(r'\%', '%'))

    vars = {
        'version': version,
        'hversion': version.replace('.', '-'),
        }
    try:
        return ret % vars
    except KeyError as e:
        raise GbpTagFormatError(tag_format, e.args[0])
