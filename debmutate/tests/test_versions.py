#!/usr/bin/python
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

"""Tests for debmutate.versions."""

from debmutate.versions import (
    git_snapshot_data_from_version,
    mangle_version_for_git,
    )

from unittest import TestCase


class MangleVersionForGitTests(TestCase):

    def test_simple(self):
        self.assertEqual(mangle_version_for_git('1.1'), '1.1')
        self.assertEqual(mangle_version_for_git('1.1a'), '1.1a')

    def test_mangled(self):
        self.assertEqual(mangle_version_for_git('1.1~a'), '1.1_a')
        self.assertEqual(mangle_version_for_git('1:1.1'), '1%1.1')
        self.assertEqual(mangle_version_for_git('1.1.'), '1.1.#')
        self.assertEqual(mangle_version_for_git('1.1..a'), '1.1.#.a')
        self.assertEqual(mangle_version_for_git('1.1.lock'), '1.1.#lock')


class GitSnapshotDataFromVersionTests(TestCase):

    def test_not_git(self):
        self.assertEqual((None, None), git_snapshot_data_from_version('1.1'))

    def test_git(self):
        self.assertEqual(
            (None, '2020-01-01'),
            git_snapshot_data_from_version('1.1+git20200101'))
