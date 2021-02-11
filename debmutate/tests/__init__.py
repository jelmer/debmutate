#!/usr/bin/python
# Copyright (C) 2018 Jelmer Vernooij
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

__all__ = [
    'TestCase',
    'TestCaseInTempDir',
    ]

import os
import tempfile
import unittest


class TestCase(unittest.TestCase):

    def overrideEnv(self, key, value):
        oldvalue = os.environ.get(key)

        def restore():
            if oldvalue is None:
                del os.environ[key]
            else:
                os.environ[key] = value

        self.addCleanup(restore)
        os.environ[key] = value


class TestCaseInTempDir(TestCase):

    def setUp(self):
        td = tempfile.TemporaryDirectory(prefix='debmutate')
        self.test_dir = td.name
        self.addCleanup(td.cleanup)
        cwd = os.getcwd()
        self.addCleanup(os.chdir, cwd)
        os.chdir(self.test_dir)

    def build_tree_contents(self, entries):
        for entry in entries:
            if entry[0].endswith('/'):
                os.mkdir(entry[0])
            else:
                with open(entry[0], 'w') as f:
                    f.write(entry[1])

    def assertFileEqual(self, content, path):
        with open(path, 'r') as f:
            self.assertEqual(content, f.read())


def test_suite():
    names = [
        'changelog',
        'control',
        'deb822',
        'debcargo',
        'debhelper',
        'debmutate',
        'lintian_overrides',
        'patch',
        'reformatting',
        'vcs',
        'versions',
        'watch',
        '_rules',
        ]
    module_names = [__name__ + '.test_' + name for name in names]
    loader = unittest.TestLoader()
    return loader.loadTestsFromNames(module_names)
