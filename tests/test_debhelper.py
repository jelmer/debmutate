#!/usr/bin/python
# Copyright (C) 2019-2020 Jelmer Vernooij
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

"""Tests for debmutate.debhelper."""

from typing import Dict

from debian.changelog import Version
from debmutate.debhelper import (
    MaintscriptEditor,
    MaintscriptMoveConffile,
    ensure_minimum_debhelper_version,
    get_debhelper_compat_level_from_control,
)

from . import TestCase, TestCaseInTempDir


class EnsureMinimumDebhelperVersionTests(TestCase):
    def test_already(self):
        d = {
            "Build-Depends": "debhelper (>= 10)",
        }
        self.assertFalse(ensure_minimum_debhelper_version(d, "10"))
        self.assertEqual(d, {"Build-Depends": "debhelper (>= 10)"})
        self.assertFalse(ensure_minimum_debhelper_version(d, "9"))
        self.assertEqual(d, {"Build-Depends": "debhelper (>= 10)"})

    def test_already_compat(self):
        d = {
            "Build-Depends": "debhelper-compat (= 10)",
        }
        self.assertFalse(ensure_minimum_debhelper_version(d, "10"))
        self.assertEqual(d, {"Build-Depends": "debhelper-compat (= 10)"})
        self.assertFalse(ensure_minimum_debhelper_version(d, "9"))
        self.assertEqual(d, {"Build-Depends": "debhelper-compat (= 10)"})

    def test_bump(self):
        d = {
            "Build-Depends": "debhelper (>= 10)",
        }
        self.assertTrue(ensure_minimum_debhelper_version(d, "11"))
        self.assertEqual(d, {"Build-Depends": "debhelper (>= 11)"})

    def test_bump_compat(self):
        d = {
            "Build-Depends": "debhelper-compat (= 10)",
        }
        self.assertTrue(ensure_minimum_debhelper_version(d, "11"))
        self.assertEqual(
            d, {"Build-Depends": "debhelper-compat (= 10), debhelper (>= 11)"}
        )
        self.assertTrue(ensure_minimum_debhelper_version(d, "11.1"))
        self.assertEqual(
            d, {"Build-Depends": "debhelper-compat (= 10), debhelper (>= 11.1)"}
        )

    def test_not_set(self):
        d: Dict[str, str] = {}
        self.assertTrue(ensure_minimum_debhelper_version(d, "10"))
        self.assertEqual(d, {"Build-Depends": "debhelper (>= 10)"})

    def test_in_indep(self):
        d = {"Build-Depends-Indep": "debhelper (>= 9)"}
        self.assertRaises(Exception, ensure_minimum_debhelper_version, d, "10")


class MaintscriptEditorTests(TestCaseInTempDir):
    def test_simple_edit(self):
        self.build_tree_contents(
            [
                ("debian/",),
                (
                    "debian/maintscript",
                    """\
mv_conffile /etc/iptotal/apache.conf /etc/apache2/conf-available/iptotal.conf \
0.3.3-13.1~
""",
                ),
            ]
        )
        with MaintscriptEditor() as e:
            self.assertEqual(
                [
                    MaintscriptMoveConffile(
                        "/etc/iptotal/apache.conf",
                        "/etc/apache2/conf-available/iptotal.conf",
                        Version("0.3.3-13.1~"),
                    )
                ],
                e.entries,
            )

    def test_simple_missing(self):
        with MaintscriptEditor() as e:
            self.assertEqual([], e.entries)

    def test_simple_comment(self):
        self.build_tree_contents(
            [
                ("debian/",),
                (
                    "debian/maintscript",
                    """\
# I am a comment
mv_conffile /etc/iptotal/apache.conf /etc/apache2/conf-available/iptotal.conf \
0.3.3-13.1~
""",
                ),
            ]
        )
        with MaintscriptEditor() as e:
            del e[0]
            self.assertRaises(IndexError, e.__delitem__, 0)
        with open("debian/maintscript") as f:
            self.assertEqual("# I am a comment\n", f.read())


class TestDebhelperCompatFromControl(TestCase):
    def test_x_dh_compat(self):
        d = {
            "X-DH-Compat": "10",
        }
        self.assertEqual(get_debhelper_compat_level_from_control(d), 10)

    def test_build_depends(self):
        d = {
            "Build-Depends": "debhelper-compat (= 10)",
        }
        self.assertEqual(get_debhelper_compat_level_from_control(d), 10)
