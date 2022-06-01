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

"""Tests for debmutate.debcargo."""

from ..debcargo import (
    debcargo_version_to_semver,
    semver_pair,
    DebcargoControlShimEditor,
    DebcargoEditor,
    DEFAULT_MAINTAINER,
    )

from contextlib import ExitStack
import os
import shutil
import tempfile
from unittest import TestCase


class DebcargoVersionToSemverTests(TestCase):

    def test_prerelease(self):
        self.assertEqual(
            '1.0.0-rc1', debcargo_version_to_semver('1.0.0~rc1'))


class SemverPairTests(TestCase):

    def test_pair(self):
        self.assertEqual('1.2', semver_pair('1.2.3-rc1'))
        self.assertEqual('1.2', semver_pair('1.2.3'))
        self.assertEqual('1.2', semver_pair('1.2.4+ds'))


class DebcargoControlShimEditorTests(TestCase):

    def setUp(self):
        super(DebcargoControlShimEditorTests, self).setUp()
        self.td = tempfile.mkdtemp()
        os.mkdir(os.path.join(self.td, 'debian'))
        self.addCleanup(os.chdir, os.getcwd())
        os.chdir(self.td)
        self.addCleanup(shutil.rmtree, self.td)
        self.debcargo = DebcargoEditor(allow_missing=True)
        self.es = ExitStack()
        self.es.enter_context(self.debcargo)
        self.editor = DebcargoControlShimEditor(
            self.debcargo, 'crate', '1.2.3',
            features=['feature1', 'feature2'])
        self.es.enter_context(self.editor)

    def test_properties(self):
        self.assertEqual(['feature1', 'feature2'], self.editor.features)
        self.assertEqual('crate', self.editor.crate_name)
        self.assertEqual('1.2.3', self.editor.crate_version)

    def test_source(self):
        self.assertEqual('rust-crate', self.editor.source['Source'])

    def test_source_semver_suffix(self):
        self.debcargo['semver_suffix'] = True
        self.assertEqual('rust-crate-1.2', self.editor.source['Source'])

    def test_source_priority(self):
        self.assertEqual('optional', self.editor.source['Priority'])

    def test_source_vcs_git(self):
        self.assertEqual(
            'https://salsa.debian.org/rust-team/debcargo-conf.git [src/crate]',
            self.editor.source['Vcs-Git'])

    def test_source_vcs_git_specified(self):
        self.debcargo['source'] = {
            'vcs_git': 'https://github.com/jelmer/crate'}
        self.assertEqual(
            'https://github.com/jelmer/crate', self.editor.source['Vcs-Git'])

    def test_source_vcs_browser(self):
        self.assertEqual(
            'https://salsa.debian.org/rust-team/'
            'debcargo-conf/tree/master/src/crate',
            self.editor.source['Vcs-Browser'])

    def test_source_vcs_browser_specified(self):
        self.debcargo['source'] = {
            'vcs_browser': 'https://github.com/jelmer/crate'}
        self.assertEqual(
            'https://github.com/jelmer/crate',
            self.editor.source['Vcs-Browser'])

    def test_homepage(self):
        self.assertRaises(KeyError, self.editor.source.__getitem__, 'Homepage')

    def test_homepage_specified(self):
        self.debcargo['source'] = {
            'homepage': 'https://github.com/jelmer/crate'}
        self.assertEqual(
            'https://github.com/jelmer/crate', self.editor.source['Homepage'])

    def test_section(self):
        self.assertEqual('rust', self.editor.source['Section'])

    def test_section_specified(self):
        self.debcargo['source'] = {'section': 'web'}
        self.assertEqual('web', self.editor.source['Section'])

    def test_standards_version(self):
        self.assertIsInstance(self.editor.source['Standards-Version'], str)

    def test_standards_version_specified(self):
        self.debcargo['source'] = {'policy': '1.2.3'}
        self.assertEqual('1.2.3', self.editor.source['Standards-Version'])

    def test_maintainer(self):
        self.assertEqual(DEFAULT_MAINTAINER, self.editor.source['Maintainer'])

    def test_maintainer_specified(self):
        self.debcargo['maintainer'] = 'Jelmer Vernooij <jelmer@example.com>'
        self.assertEqual(
            'Jelmer Vernooij <jelmer@example.com>',
            self.editor.source['Maintainer'])

    def test_uploaders(self):
        self.assertRaises(
            KeyError, self.editor.source.__getitem__, 'Uploaders')

    def test_uploaders_specified(self):
        self.debcargo['uploaders'] = 'Jelmer Vernooij <jelmer@example.com>'
        self.assertEqual(
            'Jelmer Vernooij <jelmer@example.com>',
            self.editor.source['Uploaders'])

    def test_rules_requires_root(self):
        self.assertEqual('no', self.editor.source['Rules-Requires-Root'])
