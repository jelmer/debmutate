#!/usr/bin/python
# Copyright (C) 2018 Jelmer Vernooij
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

"""Tests for debmutate.copyright."""

import os
import shutil
import tempfile
from unittest import TestCase

from debian.copyright import FilesParagraph, License, LicenseParagraph
from debmutate.copyright import CopyrightEditor, NotMachineReadableError


class UpdateCopyrightTests(TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.test_dir)
        self.addCleanup(os.chdir, os.getcwd())
        os.chdir(self.test_dir)
        os.mkdir("debian")

    def test_preservable_weird_spacing(self):
        with open("debian/copyright", "w") as f:
            f.write(
                """\
Format: https://www.debian.org/doc/packaging-manuals/copyright-format/1.0/
Upstream-Name: lintian-brush
Upstream-Contact: Jelmer <jelmer@samba.org>
# A comment


Files: *
License: GPL
Copyright: 2012...
"""
            )

        with CopyrightEditor() as updater:
            updater.copyright.header.upstream_name = "llintian-brush"  # type: ignore

    def test_old_style(self):
        with open("debian/copyright", "w") as f:
            f.write(
                """\
This package was debianized in 1995 by Joe Example <joe@example.com>

It was downloaded from ftp://ftp.example.com/pub/blah.
"""
            )

        def dummy():
            with CopyrightEditor():
                pass

        self.assertRaises(NotMachineReadableError, dummy)

    def test_utf8(self):
        with open("debian/copyright", "w") as f:
            f.write(
                """\
Format: https://www.debian.org/doc/packaging-manuals/copyright-format/1.0/
Upstream-Name: lintian-brush
Upstream-Contact: Jelmer Vernooĳ <jelmer@jelmer.uk>

Files: *
License: GPL
Copyright: 2012...
"""
            )

        with CopyrightEditor() as updater:
            self.assertEqual(
                ("Jelmer Vernooĳ <jelmer@jelmer.uk>",),
                updater.copyright.header.upstream_contact,
            )

    def test_modify(self):
        with open("debian/copyright", "w") as f:
            f.write(
                """\
Format: https://www.debian.org/doc/packaging-manuals/copyright-format/1.0/
Upstream-Name: lintian-brush
Upstream-Contact: Jelmer <jelmer@samba.org>

Files: *
License: GPL
Copyright: 2012...
"""
            )

        with CopyrightEditor() as updater:
            p = FilesParagraph.create(["foo.c"], "2012 Joe Example", License("Apache"))
            updater.copyright.add_files_paragraph(p)
        self.assertTrue(updater.changed)
        with open("debian/copyright") as f:
            self.assertEqual(
                """\
Format: https://www.debian.org/doc/packaging-manuals/copyright-format/1.0/
Upstream-Name: lintian-brush
Upstream-Contact: Jelmer <jelmer@samba.org>

Files: *
License: GPL
Copyright: 2012...

Files: foo.c
Copyright: 2012 Joe Example
License: Apache
""",
                f.read(),
            )

    def test_add_paragraph(self):
        with open("debian/copyright", "w") as f:
            f.write(
                """\
Format: https://www.debian.org/doc/packaging-manuals/copyright-format/1.0/
Upstream-Name: lintian-brush
Upstream-Contact: Jelmer <jelmer@samba.org>
"""
            )

        with CopyrightEditor() as updater:
            updater.copyright.add_license_paragraph(
                LicenseParagraph.create(License("Blah", "Blah\nblah blah\nblah\n\n"))
            )
        self.assertTrue(updater.changed)
        with open("debian/copyright") as f:
            self.assertEqual(
                """\
Format: https://www.debian.org/doc/packaging-manuals/copyright-format/1.0/
Upstream-Name: lintian-brush
Upstream-Contact: Jelmer <jelmer@samba.org>

License: Blah
 Blah
 blah blah
 blah
 .
""",
                f.read(),
            )

    def test_preserve_whitespace(self):
        with open("debian/copyright", "w") as f:
            f.write(
                """\
Format: https://www.debian.org/doc/packaging-manuals/copyright-format/1.0/
Upstream-Name: lintian-brush
Upstream-Contact: Jelmer <jelmer@samba.org>

License: Blah
 blah
 .
"""
            )

        with CopyrightEditor() as updater:
            license_para = list(updater.copyright.all_license_paragraphs())[0]
            self.assertEqual("License: Blah\n blah\n .\n", license_para.dump())
            self.assertEqual("blah\n", license_para.license.text)  # type: ignore

    def test_remove_paragraph(self):
        with open("debian/copyright", "w") as f:
            f.write(
                """\
Format: https://www.debian.org/doc/packaging-manuals/copyright-format/1.0/
Upstream-Name: lintian-brush
Upstream-Contact: Jelmer <jelmer@samba.org>

License: Blah
 blah
 .
"""
            )

        with CopyrightEditor() as updater:
            license_para = list(updater.copyright.all_license_paragraphs())[0]
            updater.remove(license_para)
        with open("debian/copyright") as f:
            self.assertEqual(
                """\
Format: https://www.debian.org/doc/packaging-manuals/copyright-format/1.0/
Upstream-Name: lintian-brush
Upstream-Contact: Jelmer <jelmer@samba.org>
""",
                f.read(),
            )

    def test_append_paragraph(self):
        with open("debian/copyright", "w") as f:
            f.write(
                """\
Format: https://www.debian.org/doc/packaging-manuals/copyright-format/1.0/
Upstream-Name: lintian-brush
Upstream-Contact: Jelmer <jelmer@samba.org>

"""
            )

        with CopyrightEditor() as updater:
            p = FilesParagraph.create(["foo.c"], "2012 Joe Example", License("Apache"))
            updater.append(p)
            p = FilesParagraph.create(["bar.c"], "2013 Joe Example", License("Apache"))
            updater.append(p)
        with open("debian/copyright") as f:
            self.assertEqual(
                """\
Format: https://www.debian.org/doc/packaging-manuals/copyright-format/1.0/
Upstream-Name: lintian-brush
Upstream-Contact: Jelmer <jelmer@samba.org>

Files: foo.c
Copyright: 2012 Joe Example
License: Apache

Files: bar.c
Copyright: 2013 Joe Example
License: Apache
""",
                f.read(),
            )

    def test_insert_paragraph(self):
        with open("debian/copyright", "w") as f:
            f.write(
                """\
Format: https://www.debian.org/doc/packaging-manuals/copyright-format/1.0/
Upstream-Name: lintian-brush
Upstream-Contact: Jelmer <jelmer@samba.org>

Files: bar.c
Copyright: 2013 Joe Example
License: Apache
"""
            )

        with CopyrightEditor() as updater:
            p = FilesParagraph.create(["foo.c"], "2012 Joe Example", License("Apache"))
            updater.insert(0, p)
        with open("debian/copyright") as f:
            self.assertEqual(
                """\
Format: https://www.debian.org/doc/packaging-manuals/copyright-format/1.0/
Upstream-Name: lintian-brush
Upstream-Contact: Jelmer <jelmer@samba.org>

Files: foo.c
Copyright: 2012 Joe Example
License: Apache

Files: bar.c
Copyright: 2013 Joe Example
License: Apache
""",
                f.read(),
            )
