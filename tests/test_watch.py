#!/usr/bin/python
# Copyright (C) 2019 Jelmer Vernooij
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

"""Tests for debmutate.watch."""

import os
import shutil
import tempfile
from io import BytesIO, StringIO
from unittest import TestCase

from debmutate.watch import (
    InvalidUVersionMangle,
    MissingVersion,
    Watch,
    WatchEditor,
    WatchFile,
    html_search,
    parse_watch_file,
    plain_search,
    search,
)


class ParseWatchFileTests(TestCase):
    def test_parse_empty(self):
        self.assertIs(None, parse_watch_file(StringIO("")))

    def test_parse_no_version(self):
        self.assertRaises(MissingVersion, parse_watch_file, StringIO("foo\n"))
        self.assertRaises(MissingVersion, parse_watch_file, StringIO("foo=bar\n"))

    def test_parse_utf8(self):
        wf = parse_watch_file(
            StringIO(
                """\
version=3
https://samba.org/~jelmer/ blah-(\\d+).tar.gz
# ©
"""
            )
        )
        assert wf is not None
        self.assertEqual(3, wf.version)
        self.assertEqual(
            [Watch("https://samba.org/~jelmer/", "blah-(\\d+).tar.gz")], wf.entries
        )

    def test_parse_with_spacing_around_version(self):
        wf = parse_watch_file(
            StringIO(
                """\
version = 3
https://samba.org/~jelmer/ blah-(\\d+).tar.gz
"""
            )
        )
        assert wf is not None
        self.assertEqual(3, wf.version)
        self.assertEqual(
            [Watch("https://samba.org/~jelmer/", "blah-(\\d+).tar.gz")], wf.entries
        )

    def test_parse_with_script(self):
        wf = parse_watch_file(
            StringIO(
                """\
version=4
https://samba.org/~jelmer/ blah-(\\d+).tar.gz debian sh blah.sh
"""
            )
        )
        assert wf is not None
        self.assertEqual(4, wf.version)
        self.assertEqual(
            [
                Watch(
                    "https://samba.org/~jelmer/",
                    "blah-(\\d+).tar.gz",
                    "debian",
                    "sh blah.sh",
                )
            ],
            wf.entries,
        )

    def test_parse_single(self):
        wf = parse_watch_file(
            StringIO(
                """\
version=4
https://samba.org/~jelmer/blah-(\\d+).tar.gz
"""
            )
        )
        assert wf is not None
        self.assertEqual(4, wf.version)
        self.assertEqual(
            [Watch("https://samba.org/~jelmer", "blah-(\\d+).tar.gz")], wf.entries
        )

    def test_parse_simple(self):
        wf = parse_watch_file(
            StringIO(
                """\
version=4
https://samba.org/~jelmer/ blah-(\\d+).tar.gz
"""
            )
        )
        assert wf is not None
        self.assertEqual(4, wf.version)
        self.assertEqual(
            [Watch("https://samba.org/~jelmer/", "blah-(\\d+).tar.gz")], wf.entries
        )

    def test_parse_with_opts(self):
        wf = parse_watch_file(
            StringIO(
                """\
version=4
opts=pgpmode=mangle https://samba.org/~jelmer/ blah-(\\d+).tar.gz
"""
            )
        )
        assert wf is not None
        self.assertEqual(4, wf.version)
        self.assertEqual([], wf.options)
        self.assertEqual(
            [
                Watch(
                    "https://samba.org/~jelmer/",
                    "blah-(\\d+).tar.gz",
                    opts=["pgpmode=mangle"],
                )
            ],
            wf.entries,
        )

    def test_parse_global_opts(self):
        wf = parse_watch_file(
            StringIO(
                """\
version=4
opts=pgpmode=mangle
https://samba.org/~jelmer/ blah-(\\d+).tar.gz
"""
            )
        )
        assert wf is not None
        self.assertEqual(4, wf.version)
        self.assertEqual(["pgpmode=mangle"], wf.options)
        self.assertEqual(
            [Watch("https://samba.org/~jelmer/", "blah-(\\d+).tar.gz")], wf.entries
        )
        self.assertEqual(wf.get_option("pgpmode"), "mangle")
        self.assertRaises(KeyError, wf.get_option, "mode")

    def test_parse_opt_quotes(self):
        wf = parse_watch_file(
            StringIO(
                """\
version=4
opts="pgpmode=mangle" https://samba.org/~jelmer blah-(\\d+).tar.gz
"""
            )
        )
        assert wf is not None
        self.assertEqual(4, wf.version)
        self.assertEqual(
            wf.entries,
            [
                Watch(
                    "https://samba.org/~jelmer",
                    "blah-(\\d+).tar.gz",
                    opts=["pgpmode=mangle"],
                )
            ],
        )

    def test_parse_continued_leading_spaces_4(self):
        wf = parse_watch_file(
            StringIO(
                """\
version=4
opts=pgpmode=mangle,\\
    foo=bar https://samba.org/~jelmer blah-(\\d+).tar.gz
"""
            )
        )
        assert wf is not None
        self.assertEqual(4, wf.version)
        self.assertEqual(
            wf.entries,
            [
                Watch(
                    "https://samba.org/~jelmer",
                    "blah-(\\d+).tar.gz",
                    opts=["pgpmode=mangle", "foo=bar"],
                )
            ],
        )
        self.assertEqual(wf.entries[0].get_option("pgpmode"), "mangle")
        self.assertRaises(KeyError, wf.entries[0].get_option, "mode")

    def test_parse_continued_leading_spaces_3(self):
        wf = parse_watch_file(
            StringIO(
                """\
version=3
opts=pgpmode=mangle,\\
    foo=bar blah-(\\d+).tar.gz
"""
            )
        )
        assert wf is not None
        self.assertEqual(3, wf.version)
        self.assertEqual(
            wf.entries,
            [Watch("foo=bar", "blah-(\\d+).tar.gz", opts=["pgpmode=mangle", ""])],
        )

    def test_pattern_included(self):
        wf = parse_watch_file(
            StringIO(
                """\
version=4
https://pypi.debian.net/case/case-(.+).tar.gz debian
"""
            )
        )
        assert wf is not None
        self.assertEqual(4, wf.version)
        self.assertEqual(
            [Watch("https://pypi.debian.net/case", "case-(.+).tar.gz", "debian")],
            wf.entries,
        )

    def test_parse_weird_quotes(self):
        wf = parse_watch_file(
            StringIO(
                """\
# please also check https://pypi.debian.net/case/watch
version=3
opts=repacksuffix=+dfsg",pgpsigurlmangle=s/$/.asc/ \\
https://pypi.debian.net/case/case-(.+)\\.(?:zip|(?:tar\\.(?:gz|bz2|xz))) \\
debian sh debian/repack.stub
"""
            )
        )
        assert wf is not None
        self.assertEqual(3, wf.version)
        self.assertEqual(
            [
                Watch(
                    "https://pypi.debian.net/case",
                    "case-(.+)\\.(?:zip|(?:tar\\.(?:gz|bz2|xz)))",
                    "debian",
                    "sh debian/repack.stub",
                    opts=['repacksuffix=+dfsg"', "pgpsigurlmangle=s/$/.asc/"],
                )
            ],
            wf.entries,
        )

    def test_parse_package_variable(self):
        wf = parse_watch_file(
            StringIO(
                """\
version = 3
https://samba.org/~jelmer/@PACKAGE@ blah-(\\d+).tar.gz
"""
            )
        )
        assert wf is not None
        self.assertEqual(3, wf.version)
        self.assertEqual(
            [Watch("https://samba.org/~jelmer/@PACKAGE@", "blah-(\\d+).tar.gz")],
            wf.entries,
        )
        self.assertEqual(
            "https://samba.org/~jelmer/blah", wf.entries[0].format_url("blah")
        )

    def test_parse_subst_expr(self):
        wf = parse_watch_file(
            StringIO(
                """\
version = 3
opts=uversionmangle=s/(\\d)[_\\.\\-\\+]?((RC|rc|pre|alpha)\\d*)$/$1~$2/ \\
   https://samba.org/~jelmer/ blah-(\\d+).tar.gz
"""
            )
        )
        assert wf is not None
        self.assertEqual(3, wf.version)
        self.assertEqual("1.0", wf.entries[0].uversionmangle("1.0"))
        self.assertEqual("1.0~alpha1", wf.entries[0].uversionmangle("1.0alpha1"))

    def test_parse_tr_expr(self):
        wf = parse_watch_file(
            StringIO(
                """\
version = 3
opts=uversionmangle=tr/+/~/ \\
   https://samba.org/~jelmer/ blah-(\\d+).tar.gz
"""
            )
        )
        assert wf is not None
        self.assertEqual(3, wf.version)
        try:
            import tr  # noqa: F401
        except ModuleNotFoundError:
            self.skipTest("tr module not available")
        self.assertEqual("1.0", wf.entries[0].uversionmangle("1.0"))
        self.assertEqual("1.0~alpha1", wf.entries[0].uversionmangle("1.0+alpha1"))

    def test_parse_y_expr(self):
        wf = parse_watch_file(
            StringIO(
                """\
version = 3
opts=uversionmangle=y/+/~/ \\
   https://samba.org/~jelmer/ blah-(\\d+).tar.gz
"""
            )
        )
        assert wf is not None
        self.assertEqual(3, wf.version)
        try:
            import tr  # noqa: F401
        except ModuleNotFoundError:
            self.skipTest("tr module not available")
        self.assertEqual("1.0", wf.entries[0].uversionmangle("1.0"))
        self.assertEqual("1.0~alpha1", wf.entries[0].uversionmangle("1.0+alpha1"))

    def test_parse_subst_expr_escape(self):
        wf = parse_watch_file(
            StringIO(
                """\
version = 3
opts=uversionmangle=s/(\\d)[_\\.\\-\\+]?((RC|rc|pre|alpha|\\/)\\d*)$/$1~$2/ \\
   https://samba.org/~jelmer/ blah-(\\d+).tar.gz
"""
            )
        )
        assert wf is not None
        self.assertEqual(3, wf.version)
        self.assertEqual("1.0", wf.entries[0].uversionmangle("1.0"))
        self.assertEqual("1.0~alpha1", wf.entries[0].uversionmangle("1.0alpha1"))

    def test_parse_subst_expr_percent(self):
        wf = parse_watch_file(
            StringIO(
                """\
version = 3
opts=uversionmangle=s%(\\d)[_\\.\\-\\+]?((RC|rc|pre|alpha)\\d*)$%$1~$2% \\
   https://samba.org/~jelmer/ blah-(\\d+).tar.gz
"""
            )
        )
        assert wf is not None
        self.assertEqual(3, wf.version)
        self.assertEqual("1.0", wf.entries[0].uversionmangle("1.0"))
        self.assertEqual("1.0~alpha1", wf.entries[0].uversionmangle("1.0alpha1"))

    def test_parse_subst_expr_invalid(self):
        wf = parse_watch_file(
            StringIO(
                """\
version = 3
opts=uversionmangle=s/(\\d)[_\\.\\-\\+]?((RC|rc|pre|alpha)\\d*)$$1~$2 \\
   https://samba.org/~jelmer/ blah-(\\d+).tar.gz
"""
            )
        )
        assert wf is not None
        self.assertRaises(
            InvalidUVersionMangle, wf.entries[0].uversionmangle, "1.0alpha1"
        )


class WatchEditorTests(TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.test_dir)
        self.addCleanup(os.chdir, os.getcwd())
        os.chdir(self.test_dir)

    def test_file_with_just_comments(self):
        with open("watch", "w") as f:
            f.write("# tests\n")
        with WatchEditor("watch") as updater:
            self.assertEqual(WatchFile([]), updater.watch_file)
        with open("watch") as f:
            self.assertEqual("# tests\n", f.read())

    def test_version_change(self):
        with open("watch", "w") as f:
            f.write(
                """\
version=3
https://pypi.debian.net/case case-(.+)\\.tar.gz
"""
            )
        with WatchEditor("watch") as updater:
            updater.watch_file.version = 4
        with open("watch") as f:
            self.assertEqual(
                """\
version=4
https://pypi.debian.net/case case-(.+)\\.tar.gz
""",
                f.read(),
            )


class HtmlSearchTests(TestCase):
    def test_html_search(self):
        body = b"""\
<html>
<head>
<title>Upstream release page</title>
</head>
<body>
<h1>Some title</h1>
<p>Some text</p>
<a href="https://example.com/foo-1.0.tar.gz">foo-1.0.tar.gz</a>
</body>
</html>
"""
        self.assertEqual(
            [("1.0", "https://example.com/foo-1.0.tar.gz")],
            list(
                html_search(
                    body, "/foo-(\\d+\\.\\d+)\\.tar\\.gz", "https://example.com/"
                )
            ),
        )

        # Try with a pattern that is not found
        self.assertEqual(
            [],
            list(
                html_search(
                    body, "/bar-(\\d+\\.\\d+)\\.tar\\.gz", "https://example.com/"
                )
            ),
        )

        # Try with a full URL pattern
        self.assertEqual(
            [("1.0", "https://example.com/foo-1.0.tar.gz")],
            list(
                html_search(
                    body,
                    "https://example.com/foo-(\\d+\\.\\d+)\\.tar\\.gz",
                    "https://bar.com/",
                )
            ),
        )


class PlainSearchTests(TestCase):
    def test_plain_search(self):
        body = b"""\
Some text
foo-1.0.tar.gz
Some more text
"""
        self.assertEqual(
            [("1.0", "https://example.com/foo-1.0.tar.gz")],
            list(
                plain_search(
                    body, "foo-(\\d+\\.\\d+)\\.tar\\.gz", "https://example.com/"
                )
            ),
        )

        # Try with a pattern that is not found
        self.assertEqual(
            [],
            list(
                plain_search(
                    body, "bar-(\\d+\\.\\d+)\\.tar\\.gz", "https://example.com/"
                )
            ),
        )

        body = b"""\
Some text
https://example.com/foo-1.0.tar.gz
Some more text
"""

        # Try with a full URL pattern
        self.assertEqual(
            [("1.0", "https://example.com/foo-1.0.tar.gz")],
            list(
                plain_search(
                    body,
                    "https://example.com/foo-(\\d+\\.\\d+)\\.tar\\.gz",
                    "https://bar.com/",
                )
            ),
        )


class SearchTests(TestCase):
    def test_search(self):
        body = b"""\
<html>
<head>
<title>Upstream release page</title>
</head>
<body>
<h1>Some title</h1>
<p>Some text</p>
<a href="https://example.com/foo-1.0.tar.gz">foo-1.0.tar.gz</a>
</body>
</html>
"""
        self.assertEqual(
            [("1.0", "https://example.com/foo-1.0.tar.gz")],
            list(
                search(
                    "html",
                    BytesIO(body),
                    matching_pattern="/foo-(\\d+\\.\\d+)\\.tar\\.gz",
                    url="https://example.com/",
                    package="foo",
                )
            ),
        )
