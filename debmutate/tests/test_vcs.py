#!/usr/bin/python3
# Copyright (C) 2018-2020 Jelmer Vernooij
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

"""Tests for the vcs module."""

from unittest import TestCase

from debmutate.vcs import (
    split_vcs_url,
    unsplit_vcs_url,
    mangle_version_for_git,
    gbp_expand_tag_name,
    )


class SplitVcsUrlTests(TestCase):

    def test_none(self):
        self.assertEqual(
            ('https://github.com/jelmer/example', None, None),
            split_vcs_url('https://github.com/jelmer/example'))
        self.assertEqual(
            ('https://github.com/jelmer/example', None, 'path/to/packaging'),
            split_vcs_url(
                'https://github.com/jelmer/example [path/to/packaging]'))

    def test_branch(self):
        self.assertEqual(
            ('https://github.com/jelmer/example',
                'master', 'path/to/packaging'),
            split_vcs_url(
                'https://github.com/jelmer/example [path/to/packaging] '
                '-b master'))
        self.assertEqual(
            ('https://github.com/jelmer/example',
                'master', 'path/to/packaging'),
            split_vcs_url(
                'https://github.com/jelmer/example -b master '
                '[path/to/packaging]'))
        self.assertEqual(
            ('https://github.com/jelmer/example', 'master', None),
            split_vcs_url(
                'https://github.com/jelmer/example -b master'))


class UnsplitVcsUrlTests(TestCase):

    def test_none(self):
        self.assertEqual(
            'https://github.com/jelmer/example',
            unsplit_vcs_url('https://github.com/jelmer/example', None, None))
        self.assertEqual(
            'https://github.com/jelmer/example [path/to/packaging]',
            unsplit_vcs_url(
                'https://github.com/jelmer/example', None,
                'path/to/packaging'))

    def test_branch(self):
        self.assertEqual(
            'https://github.com/jelmer/example -b master '
            '[path/to/packaging]',
            unsplit_vcs_url(
                'https://github.com/jelmer/example', 'master',
                'path/to/packaging'))
        self.assertEqual(
            'https://github.com/jelmer/example -b master',
            unsplit_vcs_url(
                'https://github.com/jelmer/example', 'master', None))


class MangleVersionForGitTests(TestCase):

    def test_replace_tilde(self):
        self.assertEqual('1.0_1', mangle_version_for_git('1.0~1'))

    def test_normal(self):
        self.assertEqual('1.0', mangle_version_for_git('1.0'))


class ExpandGbpTagFormatTests(TestCase):

    def test_gbp_tag_format(self):
        self.assertEqual(
            'blah-1.0', gbp_expand_tag_name('blah-%(version)s', '1.0'))
        self.assertEqual(
            'blah-0.1-1',
            gbp_expand_tag_name('blah-%(version%~%-)s', '0.1~1'))
