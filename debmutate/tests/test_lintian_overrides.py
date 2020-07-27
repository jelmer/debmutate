#!/usr/bin/python
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

"""Tests for lintian_brush.lintian_overrides."""

from . import (
    TestCase,
    TestCaseInTempDir,
    )

from io import StringIO

from ..lintian_overrides import (
    LintianOverride,
    LintianOverridesEditor,
    iter_overrides,
    parse_override,
    serialize_override,
    )


class UpdateOverridesEditorTests(TestCaseInTempDir):

    def test_no_changes(self):
        CONTENT = """\
# An architecture wildcard would look like:
foo [any-i386] binary: another-tag optional-extra
"""
        self.build_tree_contents([('overrides', CONTENT)])

        with LintianOverridesEditor(path='overrides'):
            pass
        self.assertFileEqual(CONTENT, 'overrides')

    def test_change_set_archlist(self):
        self.build_tree_contents([('overrides', """\
# An architecture wildcard would look like:
foo binary: another-tag optional-extra
""")])

        with LintianOverridesEditor(path='overrides') as editor:
            editor.overrides[0].archlist = ['any-i386']

        self.assertFileEqual("""\
# An architecture wildcard would look like:
foo [any-i386] binary: another-tag optional-extra
""", 'overrides')


class ParseOverrideTests(TestCase):

    def test_tag_only(self):
        self.assertEqual(
            LintianOverride(tag='sometag'),
            parse_override('sometag\n'))

    def test_origin(self):
        self.assertEqual(
            LintianOverride(tag='sometag', package='mypkg'),
            parse_override('mypkg: sometag\n'))

    def test_archlist(self):
        self.assertEqual(
            LintianOverride(tag='sometag', archlist=['i386', 'amd64']),
            parse_override('[i386 amd64]: sometag\n'))

    def test_iter_overrides(self):
        self.assertEqual([
            LintianOverride(tag='sometag', archlist=['i386', 'amd64']),
            LintianOverride(tag='anothertag', info='optional-extra')],
            list(iter_overrides(StringIO("""
[i386 amd64]: sometag
anothertag optional-extra
"""))))


class SerializeOverrideTests(TestCase):

    def test_tag_only(self):
        self.assertEqual(
            serialize_override(LintianOverride(tag='sometag')),
            'sometag\n')

    def test_origin(self):
        self.assertEqual(
            serialize_override(
                LintianOverride(tag='sometag', package='mypkg')),
            'mypkg: sometag\n')

    def test_archlist(self):
        self.assertEqual(
            serialize_override(
                LintianOverride(tag='sometag', archlist=['i386'])),
            '[i386]: sometag\n')
