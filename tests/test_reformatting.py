#!/usr/bin/python
# Copyright (C) 2019 Jelmer Vernooij
# This file is a part of debmutate.
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

"""Tests for lintian brush reformatting tools."""

from debmutate.reformatting import (
    FormattingUnpreservable,
    GeneratedFile,
    check_generated_file,
    check_preserve_formatting,
    edit_formatted_file,
)

from . import TestCase, TestCaseInTempDir


class CheckPreserveFormattingTests(TestCase):
    def test_formatting_same(self):
        check_preserve_formatting("FOO  ", "FOO  ", "debian/blah")

    def test_formatting_different(self):
        self.assertRaises(
            FormattingUnpreservable,
            check_preserve_formatting,
            "FOO ",
            "FOO  ",
            "debian/blah",
        )

    def test_diff(self):
        e = FormattingUnpreservable("debian/blah", "FOO X\n", "FOO  X\n")
        self.assertEqual(
            "".join(e.diff()),
            """\
--- original
+++ rewritten
@@ -1 +1 @@
-FOO X
+FOO  X
""",
        )

    def test_reformatting_allowed(self):
        check_preserve_formatting(
            "FOO  ", "FOO ", "debian/blah", allow_reformatting=True
        )


class GeneratedFileTests(TestCaseInTempDir):
    def test_generated_control_file(self):
        self.build_tree_contents(
            [
                ("debian/",),
                (
                    "debian/control.in",
                    """\
Source: blah
""",
                ),
            ]
        )
        self.assertRaises(GeneratedFile, check_generated_file, "debian/control")

    def test_missing(self):
        check_generated_file("debian/control")

    def test_do_not_edit(self):
        self.build_tree_contents(
            [
                ("debian/",),
                (
                    "debian/control",
                    """\
# DO NOT EDIT
# This file was generated by blah

Source: blah
Testsuite: autopkgtest

""",
                ),
            ]
        )
        self.assertRaises(GeneratedFile, check_generated_file, "debian/control")

    def test_do_not_edit_after_header(self):
        # check_generated_file() only checks the first 20 lines.
        self.build_tree_contents(
            [
                ("debian/",),
                (
                    "debian/control",
                    ("\n" * 50)
                    + """\
# DO NOT EDIT
# This file was generated by blah

Source: blah
Testsuite: autopkgtest

""",
                ),
            ]
        )
        check_generated_file("debian/control")


class EditFormattedFileTests(TestCaseInTempDir):
    def test_unchanged(self):
        self.build_tree_contents([("a", "some content\n")])
        self.assertFalse(
            edit_formatted_file(
                "a", "some content\n", "some content reformatted\n", "some content\n"
            )
        )
        self.assertFalse(
            edit_formatted_file(
                "a", "some content\n", "some content\n", "some content\n"
            )
        )
        self.assertFalse(
            edit_formatted_file(
                "a",
                "some content\n",
                "some content reformatted\n",
                "some content reformatted\n",
            )
        )

    def test_changed(self):
        self.build_tree_contents([("a", "some content\n")])
        self.assertTrue(
            edit_formatted_file(
                "a", "some content\n", "some content\n", "new content\n"
            )
        )
        self.assertFileEqual("new content\n", "a")

    def test_unformattable(self):
        self.assertRaises(
            FormattingUnpreservable,
            edit_formatted_file,
            "a",
            "some content\n",
            "reformatted content\n",
            "new content\n",
        )
