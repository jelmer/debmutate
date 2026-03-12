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
    parse_watch_file_deb822,
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


class ParseWatchFileDeb822Tests(TestCase):
    def test_parse_empty(self):
        self.assertIs(None, parse_watch_file_deb822(StringIO("")))

    def test_parse_no_version(self):
        self.assertRaises(
            MissingVersion,
            parse_watch_file_deb822,
            StringIO("Source: https://example.com/\n"),
        )

    def test_parse_simple(self):
        wf = parse_watch_file_deb822(
            StringIO(
                """\
Version: 5

Source: https://samba.org/~jelmer/
Matching-Pattern: blah-(\\d+).tar.gz
"""
            )
        )
        assert wf is not None
        self.assertEqual(5, wf.version)
        self.assertEqual(
            [Watch("https://samba.org/~jelmer/", "blah-(\\d+).tar.gz")],
            wf.entries,
        )

    def test_parse_single_paragraph(self):
        wf = parse_watch_file_deb822(
            StringIO(
                """\
Version: 5
Source: https://samba.org/~jelmer/
Matching-Pattern: blah-(\\d+).tar.gz
"""
            )
        )
        assert wf is not None
        self.assertEqual(5, wf.version)
        self.assertEqual(1, len(wf.entries))
        self.assertEqual("https://samba.org/~jelmer/", wf.entries[0].url)
        self.assertEqual("blah-(\\d+).tar.gz", wf.entries[0].matching_pattern)

    def test_parse_with_options(self):
        wf = parse_watch_file_deb822(
            StringIO(
                """\
Version: 5

Source: https://samba.org/~jelmer/
Matching-Pattern: blah-(\\d+).tar.gz
Pgp-Mode: mangle
Pgp-Sig-Url-Mangle: s/$/.asc/
"""
            )
        )
        assert wf is not None
        self.assertEqual(5, wf.version)
        self.assertEqual(1, len(wf.entries))
        self.assertEqual("pgpmode=mangle", wf.entries[0].options[0])
        self.assertEqual("pgpsigurlmangle=s/$/.asc/", wf.entries[0].options[1])

    def test_parse_global_defaults(self):
        wf = parse_watch_file_deb822(
            StringIO(
                """\
Version: 5
Pgp-Mode: auto

Source: https://samba.org/~jelmer/
Matching-Pattern: blah-(\\d+).tar.gz
"""
            )
        )
        assert wf is not None
        self.assertEqual(5, wf.version)
        self.assertEqual(["pgpmode=auto"], wf.options)
        # Entry should inherit global default
        self.assertEqual("auto", wf.entries[0].get_option("pgpmode"))

    def test_parse_global_defaults_override(self):
        wf = parse_watch_file_deb822(
            StringIO(
                """\
Version: 5
Pgp-Mode: auto

Source: https://samba.org/~jelmer/
Matching-Pattern: blah-(\\d+).tar.gz
Pgp-Mode: mangle
"""
            )
        )
        assert wf is not None
        self.assertEqual(5, wf.version)
        # Entry-level override takes precedence
        self.assertEqual("mangle", wf.entries[0].get_option("pgpmode"))

    def test_parse_multiple_entries(self):
        wf = parse_watch_file_deb822(
            StringIO(
                """\
Version: 5

Source: https://example.com/main/
Matching-Pattern: main-(\\d+).tar.gz

Source: https://example.com/component/
Matching-Pattern: comp-(\\d+).tar.gz
Component: extra
"""
            )
        )
        assert wf is not None
        self.assertEqual(5, wf.version)
        self.assertEqual(2, len(wf.entries))
        self.assertEqual("https://example.com/main/", wf.entries[0].url)
        self.assertEqual("https://example.com/component/", wf.entries[1].url)
        self.assertEqual("extra", wf.entries[1].get_option("component"))

    def test_parse_with_comments(self):
        wf = parse_watch_file_deb822(
            StringIO(
                """\
# This is a comment
Version: 5

# Another comment
Source: https://samba.org/~jelmer/
Matching-Pattern: blah-(\\d+).tar.gz
"""
            )
        )
        assert wf is not None
        self.assertEqual(5, wf.version)
        self.assertEqual(1, len(wf.entries))

    def test_parse_update_script(self):
        wf = parse_watch_file_deb822(
            StringIO(
                """\
Version: 5

Source: https://samba.org/~jelmer/
Matching-Pattern: blah-(\\d+).tar.gz
Update-Script: debian/repack.sh
"""
            )
        )
        assert wf is not None
        self.assertEqual("debian/repack.sh", wf.entries[0].script)

    def test_parse_case_insensitive(self):
        wf = parse_watch_file_deb822(
            StringIO(
                """\
version: 5

source: https://samba.org/~jelmer/
matching-pattern: blah-(\\d+).tar.gz
"""
            )
        )
        assert wf is not None
        self.assertEqual(5, wf.version)
        self.assertEqual("https://samba.org/~jelmer/", wf.entries[0].url)

    def test_autodetect_deb822(self):
        """parse_watch_file auto-detects deb822 format."""
        wf = parse_watch_file(
            StringIO(
                """\
Version: 5

Source: https://samba.org/~jelmer/
Matching-Pattern: blah-(\\d+).tar.gz
"""
            )
        )
        assert wf is not None
        self.assertEqual(5, wf.version)
        self.assertEqual(1, len(wf.entries))
        self.assertEqual("https://samba.org/~jelmer/", wf.entries[0].url)

    def test_roundtrip(self):
        original = """\
Version: 5

Source: https://samba.org/~jelmer/
Matching-Pattern: blah-(\\d+).tar.gz
Pgp-Mode: mangle
"""
        wf = parse_watch_file_deb822(StringIO(original))
        assert wf is not None
        output = StringIO()
        wf.dump(output)
        wf2 = parse_watch_file_deb822(StringIO(output.getvalue()))
        assert wf2 is not None
        self.assertEqual(wf.version, wf2.version)
        self.assertEqual(len(wf.entries), len(wf2.entries))
        self.assertEqual(wf.entries[0].url, wf2.entries[0].url)
        self.assertEqual(
            wf.entries[0].matching_pattern, wf2.entries[0].matching_pattern
        )
        self.assertEqual(
            wf.entries[0].get_option("pgpmode"),
            wf2.entries[0].get_option("pgpmode"),
        )

    def test_dump_deb822(self):
        wf = WatchFile(
            entries=[
                Watch(
                    "https://example.com/",
                    matching_pattern="foo-(\\d+).tar.gz",
                    opts=["pgpmode=mangle"],
                ),
            ],
            version=5,
        )
        output = StringIO()
        wf.dump(output)
        self.assertEqual(
            output.getvalue(),
            """\
Version: 5

Source: https://example.com/
Matching-Pattern: foo-(\\d+).tar.gz
Pgp-Mode: mangle
""",
        )

    def test_dump_deb822_with_global_options(self):
        wf = WatchFile(
            entries=[
                Watch(
                    "https://example.com/",
                    matching_pattern="foo-(\\d+).tar.gz",
                ),
            ],
            options=["pgpmode=auto"],
            version=5,
        )
        output = StringIO()
        wf.dump(output)
        self.assertEqual(
            output.getvalue(),
            """\
Version: 5
Pgp-Mode: auto

Source: https://example.com/
Matching-Pattern: foo-(\\d+).tar.gz
""",
        )

    def test_parse_version_too_low(self):
        from debmutate.watch import WatchSyntaxError

        self.assertRaises(
            WatchSyntaxError,
            parse_watch_file_deb822,
            StringIO("Version: 4\n\nSource: https://example.com/\n"),
        )

    def test_parse_boolean_option(self):
        wf = parse_watch_file_deb822(
            StringIO(
                """\
Version: 5

Source: https://example.com/
Matching-Pattern: foo-(\\d+).tar.gz
Repack: yes
"""
            )
        )
        assert wf is not None
        self.assertTrue(wf.entries[0].has_option("repack"))

    def test_parse_untrackable(self):
        wf = parse_watch_file_deb822(
            StringIO(
                """\
Version: 5
Untrackable: upstream gone

Source: https://example.com/
"""
            )
        )
        assert wf is not None
        self.assertEqual(5, wf.version)

    def test_autodetect_legacy(self):
        """parse_watch_file still handles legacy format correctly."""
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
        self.assertEqual(1, len(wf.entries))

    def test_parse_git_mode(self):
        wf = parse_watch_file_deb822(
            StringIO(
                """\
Version: 5

Source: https://github.com/user/project.git
Matching-Pattern: refs/tags/v@ANY_VERSION@
Mode: git
Git-Mode: full
"""
            )
        )
        assert wf is not None
        self.assertEqual("git", wf.entries[0].get_option("mode"))
        self.assertEqual("full", wf.entries[0].get_option("gitmode"))

    def test_roundtrip_multiple_entries(self):
        original = """\
Version: 5

Source: https://example.com/main/
Matching-Pattern: main-(\\d+).tar.gz

Source: https://example.com/extra/
Matching-Pattern: extra-(\\d+).tar.gz
Component: extra
"""
        wf = parse_watch_file_deb822(StringIO(original))
        assert wf is not None
        output = StringIO()
        wf.dump(output)
        wf2 = parse_watch_file_deb822(StringIO(output.getvalue()))
        assert wf2 is not None
        self.assertEqual(2, len(wf2.entries))
        self.assertEqual("https://example.com/main/", wf2.entries[0].url)
        self.assertEqual("https://example.com/extra/", wf2.entries[1].url)
        self.assertEqual("extra", wf2.entries[1].get_option("component"))

    def test_roundtrip_global_options_inherited(self):
        original = """\
Version: 5
Pgp-Mode: auto

Source: https://example.com/
Matching-Pattern: foo-(\\d+).tar.gz
"""
        wf = parse_watch_file_deb822(StringIO(original))
        assert wf is not None
        output = StringIO()
        wf.dump(output)
        wf2 = parse_watch_file_deb822(StringIO(output.getvalue()))
        assert wf2 is not None
        self.assertEqual(["pgpmode=auto"], wf2.options)
        self.assertEqual("auto", wf2.entries[0].get_option("pgpmode"))

    def test_dump_multiple_entries(self):
        wf = WatchFile(
            entries=[
                Watch(
                    "https://example.com/main/",
                    matching_pattern="main-(\\d+).tar.gz",
                ),
                Watch(
                    "https://example.com/extra/",
                    matching_pattern="extra-(\\d+).tar.gz",
                    opts=["component=extra"],
                ),
            ],
            version=5,
        )
        output = StringIO()
        wf.dump(output)
        self.assertEqual(
            output.getvalue(),
            """\
Version: 5

Source: https://example.com/main/
Matching-Pattern: main-(\\d+).tar.gz

Source: https://example.com/extra/
Matching-Pattern: extra-(\\d+).tar.gz
Component: extra
""",
        )

    def test_parse_no_matching_pattern(self):
        wf = parse_watch_file_deb822(
            StringIO(
                """\
Version: 5

Source: https://example.com/
"""
            )
        )
        assert wf is not None
        self.assertEqual(1, len(wf.entries))
        self.assertIsNone(wf.entries[0].matching_pattern)

    def test_parse_skips_bad_paragraph(self):
        wf = parse_watch_file_deb822(
            StringIO(
                """\
Version: 5

Foo: bar

Source: https://example.com/
Matching-Pattern: foo-(\\d+).tar.gz
"""
            )
        )
        assert wf is not None
        self.assertEqual(1, len(wf.entries))
        self.assertEqual("https://example.com/", wf.entries[0].url)


class WatchEditorDeb822Tests(TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.test_dir)
        self.addCleanup(os.chdir, os.getcwd())
        os.chdir(self.test_dir)

    def test_edit_deb822(self):
        with open("watch", "w") as f:
            f.write(
                """\
Version: 5

Source: https://example.com/
Matching-Pattern: foo-(\\d+).tar.gz
"""
            )
        with WatchEditor("watch") as updater:
            self.assertEqual(5, updater.watch_file.version)
            self.assertEqual(1, len(updater.watch_file.entries))
            updater.watch_file.entries[0].set_option("pgpmode", "mangle")
        with open("watch") as f:
            content = f.read()
        self.assertIn("Pgp-Mode: mangle", content)

    def test_no_changes_preserves_file(self):
        original = """\
Version: 5

Source: https://example.com/
Matching-Pattern: foo-(\\d+).tar.gz
"""
        with open("watch", "w") as f:
            f.write(original)
        with WatchEditor("watch") as updater:
            self.assertEqual(5, updater.watch_file.version)
        with open("watch") as f:
            self.assertEqual(original, f.read())
