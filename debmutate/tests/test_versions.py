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
    new_package_version,
    )

from debian.changelog import Version
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


class TestPackageVersion(TestCase):

    def test_simple_debian(self):
        self.assertEquals(
            Version("1.2-1"),
            new_package_version("1.2", "debian"))

    def test_simple_ubuntu(self):
        self.assertEquals(
            Version("1.2-0ubuntu1"),
            new_package_version("1.2", "ubuntu"))

    def test_debian_with_dash(self):
        self.assertEquals(
            Version("1.2-0ubuntu1-1"),
            new_package_version("1.2-0ubuntu1", "debian"))

    def test_ubuntu_with_dash(self):
        self.assertEquals(
            Version("1.2-1-0ubuntu1"),
            new_package_version("1.2-1", "ubuntu"))

    def test_ubuntu_with_epoch(self):
        self.assertEquals(
            Version("3:1.2-1-0ubuntu1"),
            new_package_version("1.2-1", "ubuntu", "3"))
