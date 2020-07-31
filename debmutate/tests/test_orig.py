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

"""Tests for debmutate.orig."""

from . import TestCase

from ..orig import (
    component_from_orig_tarball,
    )


class ComponentFromOrigTarballTests(TestCase):

    def test_base_tarball(self):
        self.assertIs(
            None,
            component_from_orig_tarball(
                "foo_0.1.orig.tar.gz", "foo", "0.1"))
        self.assertRaises(
            ValueError,
            component_from_orig_tarball, "foo_0.1.orig.tar.gz", "bar", "0.1")

    def test_invalid_extension(self):
        self.assertRaises(
            ValueError,
            component_from_orig_tarball, "foo_0.1.orig.unknown", "foo", "0.1")

    def test_component(self):
        self.assertEquals(
            "comp",
            component_from_orig_tarball(
                "foo_0.1.orig-comp.tar.gz", "foo", "0.1"))
        self.assertEquals(
            "comp-dash",
            component_from_orig_tarball(
                "foo_0.1.orig-comp-dash.tar.gz", "foo", "0.1"))

    def test_invalid_character(self):
        self.assertRaises(
            ValueError,
            component_from_orig_tarball, "foo_0.1.orig;.tar.gz", "foo", "0.1")
