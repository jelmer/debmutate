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

from datetime import datetime

from debmutate.versions import (
    add_dfsg_suffix,
    git_snapshot_data_from_version,
    mangle_version_for_git,
    new_package_version,
    get_snapshot_revision,
    upstream_version_add_revision,
    debianize_upstream_version,
    matches_release,
    strip_dfsg_suffix,
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

    def test_next(self):
        self.assertEqual(
            (None, '2020-01-02'),
            git_snapshot_data_from_version('1.1+next.20200102'))


class TestPackageVersion(TestCase):

    def test_simple_debian(self):
        self.assertEqual(
            Version("1.2-1"),
            new_package_version("1.2", "debian"))

    def test_simple_ubuntu(self):
        self.assertEqual(
            Version("1.2-0ubuntu1"),
            new_package_version("1.2", "ubuntu"))

    def test_debian_with_dash(self):
        self.assertEqual(
            Version("1.2-0ubuntu1-1"),
            new_package_version("1.2-0ubuntu1", "debian"))

    def test_ubuntu_with_dash(self):
        self.assertEqual(
            Version("1.2-1-0ubuntu1"),
            new_package_version("1.2-1", "ubuntu"))

    def test_ubuntu_with_epoch(self):
        self.assertEqual(
            Version("3:1.2-1-0ubuntu1"),
            new_package_version("1.2-1", "ubuntu", "3"))


class GetRevisionSnapshotTests(TestCase):

    def test_with_snapshot(self):
        self.assertEqual(("bzr", "30"), get_snapshot_revision("0.4.4~bzr30"))

    def test_with_snapshot_plus(self):
        self.assertEqual(("bzr", "30"), get_snapshot_revision("0.4.4+bzr30"))

    def test_without_snapshot(self):
        self.assertEqual(None, get_snapshot_revision("0.4.4"))

    def test_non_numeric_snapshot(self):
        self.assertEqual(
            None,
            get_snapshot_revision("0.4.4~bzra"))

    def test_with_svn_snapshot(self):
        self.assertEqual(
            ("svn", "4242"), get_snapshot_revision("0.4.4~svn4242"))

    def test_with_svn_snapshot_plus(self):
        self.assertEqual(
            ("svn", "2424"), get_snapshot_revision("0.4.4+svn2424"))

    def test_git(self):
        self.assertEqual(
            ("date", "20190101"),
            get_snapshot_revision("0.4.4+git20190101"))
        self.assertEqual(
            ("git", "abc1def"),
            get_snapshot_revision("0.4.4+git20190101.abc1def"))


class TestUpstreamVersionAddRevision(TestCase):
    """Test that updating the version string works."""

    def setUp(self):
        super(TestUpstreamVersionAddRevision, self).setUp()
        self.revnos = {}
        self.svn_revnos = {b"somesvnrev": 45}
        self.git_shas = {
            b"somegitrev": b"e7f47cf254a6ddd4996fe41fa6115bd32eff5437"}
        self.revnos = {b"somerev": 42, b"somesvnrev": 12, b"somegitrev": 66}
        self.repository = self

    def revision_id_to_revno(self, revid):
        return self.revnos[revid]

    def revision_id_to_dotted_revno(self, revid):
        return (self.revnos[revid], )

    def test_update_plus_rev(self):
        self.assertEqual(
            "1.3+bzr42",
            upstream_version_add_revision("1.3+bzr23", bzr_revno="42"))

    def test_update_tilde_rev(self):
        self.assertEqual(
            "1.3~bzr42",
            upstream_version_add_revision("1.3~bzr23", bzr_revno="42"))

    def test_new_rev(self):
        self.assertEqual(
            "1.3+bzr42",
            upstream_version_add_revision("1.3", bzr_revno="42"))

    def test_svn_new_rev(self):
        self.assertEqual(
            "1.3+svn45",
            upstream_version_add_revision("1.3", svn_revno=45))

    def test_svn_plus_rev(self):
        self.assertEqual(
            "1.3+svn45",
            upstream_version_add_revision("1.3+svn3", svn_revno=45))

    def test_svn_tilde_rev(self):
        self.assertEqual(
            "1.3~svn45",
            upstream_version_add_revision("1.3~svn800", svn_revno=45))

    def test_git_tilde_rev(self):
        self.assertEqual(
            "1.3~git20180101.e7f47cf",
            upstream_version_add_revision(
                "1.3~git20171201.11b1d57",
                gitid=b'e7f47cfeaae7f47cfeaae7f47cfeaae7f47cfeaa',
                gitdate=datetime(2018, 1, 1)))

    def test_git_new_rev(self):
        self.assertEqual(
            "1.3+git20180101.1.e7f47cf",
            upstream_version_add_revision(
                "1.3",
                gitid=b'e7f47cfeaae7f47cfeaae7f47cfeaae7f47cfeaa',
                gitdate=datetime(2018, 1, 1)))
        self.assertEqual(
            "1.0~git20180101",
            upstream_version_add_revision(
                "1.0~git20160320",
                gitid=b'e7f47cfeaae7f47cfeaae7f47cfeaae7f47cfeaa',
                gitdate=datetime(2018, 1, 1)))
        self.assertEqual(
            "1.0-git20180101",
            upstream_version_add_revision(
                "1.0-git20160320",
                gitid=b'e7f47cfeaae7f47cfeaae7f47cfeaae7f47cfeaa',
                gitdate=datetime(2018, 1, 1)))
        self.assertEqual(
            "1.0~git20180101.1.e7f47cf",
            upstream_version_add_revision(
                "1.0~git20180101.0.11b1d57",
                gitid=b'e7f47cfeaae7f47cfeaae7f47cfeaae7f47cfeaa',
                gitdate=datetime(2018, 1, 1)))
        self.assertEqual(
            "1.0~git20180101.0.e7f47cf",
            upstream_version_add_revision(
                "1.0~git20170101.0.11b1d57",
                gitid=b'e7f47cfeaae7f47cfeaae7f47cfeaae7f47cfeaa',
                gitdate=datetime(2018, 1, 1)))
        self.assertEqual(
            "0.0~git20180101.0.e7f47cf",
            upstream_version_add_revision(
                "0.0~git20161231.0.3435554",
                gitid=b'e7f47cfeaae7f47cfeaae7f47cfeaae7f47cfeaa',
                gitdate=datetime(2018, 1, 1)))

    def test_dfsg(self):
        self.assertEqual(
            "1.3+git20180101.1.e7f47cf",
            upstream_version_add_revision(
                "1.3+dfsg",
                gitid=b'e7f47cfeaae7f47cfeaae7f47cfeaae7f47cfeaa',
                gitdate=datetime(2018, 1, 1)))
        self.assertEqual(
            "1.3+git20180101.1.e7f47cf",
            upstream_version_add_revision(
                "1.3+dfsg4",
                gitid=b'e7f47cfeaae7f47cfeaae7f47cfeaae7f47cfeaa',
                gitdate=datetime(2018, 1, 1)))


class DebianizeUpstreamVersionTests(TestCase):

    def test_unchanged(self):
        self.assertEqual('1.0', debianize_upstream_version('1.0'))

    def test_changed(self):
        self.assertEqual('1.0~beta1', debianize_upstream_version('1.0-beta1'))
        self.assertEqual('1.0~rc1', debianize_upstream_version('1.0-rc1'))
        self.assertEqual('1.0~a1', debianize_upstream_version('1.0a1'))


class MatchesReleaseTests(TestCase):

    def test_matches(self):
        self.assertTrue(matches_release('1.0', '1.0'))
        self.assertTrue(matches_release('1.0+ds1', '1.0'))
        self.assertTrue(
            matches_release('1.14.3+dfsg+~0.15.3', '0.15.3'))


class AddDfsgSuffixTests(TestCase):

    def test_new(self):
        self.assertEqual('1.0+ds', add_dfsg_suffix('1.0'))

    def test_existing(self):
        self.assertEqual('1.0+ds', add_dfsg_suffix('1.0', '0.9'))
        self.assertEqual('1.0+ds', add_dfsg_suffix('1.0', '0.9+ds'))
        self.assertEqual('1.0+ds1', add_dfsg_suffix('1.0', '0.9+ds1'))
        self.assertEqual('1.0+dfsg1', add_dfsg_suffix('1.0', '0.9+dfsg2'))
        self.assertEqual('1.0+dfsg', add_dfsg_suffix('1.0', '0.9+dfsg'))


class StripDfsgSuffixTests(TestCase):

    def test_nothing(self):
        self.assertEqual('1.0', strip_dfsg_suffix('1.0'))
        self.assertEqual('1.0+bzr2', strip_dfsg_suffix('1.0+bzr2'))

    def test_strip(self):
        self.assertEqual('1.0', strip_dfsg_suffix('1.0+ds1'))
        self.assertEqual('1.0', strip_dfsg_suffix('1.0+dfsg2'))
