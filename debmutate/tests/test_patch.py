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

"""Tests for debmutate.patch."""

from io import BytesIO

from . import TestCase

from ..patch import (
    find_common_patch_suffix,
    read_quilt_series,
    )


class ReadSeriesFileTests(TestCase):

    def test_comment(self):
        f = BytesIO(b"""\
# This file intentionally left blank.
""")
        self.assertEqual(
            [('This', True, ['file', 'intentionally', 'left', 'blank.'])],
            list(read_quilt_series(f)))

    def test_empty(self):
        f = BytesIO(b"\n")
        self.assertEqual([], list(read_quilt_series(f)))

    def test_empty_line(self):
        f = BytesIO(b"""\
patch1

patch2
""")
        self.assertEqual(
            [
                ("patch1", False, []),
                ("patch2", False, []),
            ], list(read_quilt_series(f)))

    def test_options(self):
        f = BytesIO(b"""\
name -p0
name2
""")
        self.assertEqual(
            [
                ("name", False, ["-p0"]),
                ("name2", False, []),
            ],
            list(read_quilt_series(f)))


class FindCommonPatchSuffixTests(TestCase):

    def test_simple(self):
        self.assertEqual(
            '.blah',
            find_common_patch_suffix(['foo.blah', 'series']))
        self.assertEqual(
            '.patch', find_common_patch_suffix(['foo.patch', 'series']))
        self.assertEqual(
            '.patch', find_common_patch_suffix(['series']))
        self.assertEqual(
            '.blah', find_common_patch_suffix(['series'], '.blah'))
        self.assertEqual(
            '', find_common_patch_suffix(['series', 'foo', 'bar']))
        self.assertEqual(
            '.patch',
            find_common_patch_suffix(['series', 'foo.patch', 'bar.patch']))
