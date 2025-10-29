#!/usr/bin/python3
# Copyright (C) 2019 Jelmer Vernooij <jelmer@debian.org>
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

"""Functions for working with watch files."""

import logging
import sys
from io import StringIO
from typing import (
    BinaryIO,
    Callable,
    Iterable,
    Iterator,
    List,
    Optional,
    TextIO,
    Tuple,
    Union,
    cast,
)
from urllib.parse import urljoin

import pcre2
from debian.changelog import Version  # type: ignore[attr-defined]

from . import __version__
from .reformatting import Editor

DEFAULT_USER_AGENT = "debmutate/{}".format(".".join([str(x) for x in __version__]))

DEFAULT_VERSION: int = 4

SUBSTITUTIONS = {
    # This is substituted with the source package name found in the first line
    # of the debian/changelog file.
    # '@PACKAGE@': None,
    # This is substituted by the legal upstream version regex (capturing).
    "@ANY_VERSION@": r"[-_]?(\d[\-+\.:\~\da-zA-Z]*)",
    # This is substituted by the typical archive file extension regex
    # (non-capturing).
    "@ARCHIVE_EXT@": r"(?i)\.(?:tar\.xz|tar\.bz2|tar\.gz|zip|tgz|tbz|txz)",
    # This is substituted by the typical signature file extension regex
    # (non-capturing).
    "@SIGNATURE_EXT@": r"(?i)\.(?:tar\.xz|tar\.bz2|tar\.gz|zip|tgz|tbz|txz)"
    r"\.(?:asc|pgp|gpg|sig|sign)",
    # This is substituted by the typical Debian extension regexp (capturing).
    "@DEB_EXT@": r"[\+~](debian|dfsg|ds|deb)(\.)?(\d+)?$",
}


class InvalidUVersionMangle(ValueError):
    """uversionmangle is invalid."""


class WatchFile:
    def __init__(
        self,
        entries: Optional[List["Watch"]] = None,
        options: Optional[List[str]] = None,
        version: int = DEFAULT_VERSION,
    ) -> None:
        self.version = version
        if entries is None:
            entries = []
        self.entries = entries
        if options is None:
            options = []
        self.options = options

    def get_option(self, name: str) -> Optional[str]:
        for option in self.options:
            try:
                key, value = option.split("=", 1)
            except ValueError:
                key = option
                value = None
            if key == name:
                return value
        raise KeyError(name)

    def set_option(self, name: str, newvalue: Optional[str] = None) -> None:
        if newvalue is None:
            nv = name
        else:
            nv = f"{name}={newvalue}"
        for i, option in enumerate(self.options):
            try:
                key, value = option.split("=", 1)
            except ValueError:
                key = option
                value = None
            if key == value:
                self.options[i] = nv
                return
        self.options.append(nv)

    def del_option(self, name: str) -> None:
        for i, option in enumerate(self.options):
            try:
                key, value = option.split("=", 1)
            except ValueError:
                key = option
            if key == name:
                del self.options[i]
                return
        raise KeyError(name)

    def __iter__(self) -> Iterator["Watch"]:
        return iter(self.entries)

    def __bool__(self) -> bool:
        return bool(self.entries)

    def __eq__(self, other: object) -> bool:
        return (
            isinstance(other, type(self))
            and self.entries == other.entries
            and self.options == other.options
            and self.version == other.version
        )

    def dump(self, f: TextIO) -> None:
        def serialize_options(opts: List[str]) -> str:
            s = ",".join(opts)
            if " " in s or "\t" in s:
                return 'opts="' + s + '"'
            return "opts=" + s

        f.write(f"version={self.version}\n")
        if self.options:
            f.write(serialize_options(self.options) + "\n")
        for entry in self.entries:
            if entry.options:
                f.write(serialize_options(entry.options) + " ")
            f.write(entry.url)
            if entry.matching_pattern:
                f.write(" " + entry.matching_pattern)
            if entry.version:
                f.write(" " + entry.version)
            if entry.script:
                f.write(" " + entry.script)
            f.write("\n")


def parse_sed_expr(vm: str) -> Tuple[str, Tuple[str, str, Optional[str]]]:
    if vm.startswith("s"):
        return ("s", parse_subst_expr(vm))
    if vm.startswith("tr"):
        return ("tr", parse_transl_expr(vm))
    if vm.startswith("y"):
        return ("y", parse_transl_expr(vm))
    raise InvalidUVersionMangle(vm, "not a substitution or translation regex")


def parse_subst_expr(vm: str) -> Tuple[str, str, Optional[str]]:
    if vm[0] != "s":
        raise InvalidUVersionMangle(vm, "not a substitution regex")
    parts = pcre2.split(r"(?<!\\)" + vm[1], vm)
    if len(parts) < 3:
        raise InvalidUVersionMangle(vm)
    pattern = parts[1]
    replacement = parts[2]
    flags: Optional[str]
    try:
        flags = parts[3]
    except IndexError:
        flags = None
    return (pattern, replacement, flags)


def parse_transl_expr(vm: str) -> Tuple[str, str, Optional[str]]:
    if vm.startswith("tr"):
        s = vm[2:]
    elif vm.startswith("y"):
        s = vm[1:]
    else:
        raise InvalidUVersionMangle(vm, "not a translation regex")
    parts = pcre2.split(r"(?<!\\)" + s[0], vm)
    if len(parts) < 3:
        raise InvalidUVersionMangle(vm)
    pattern = parts[1]
    replacement = parts[2]
    flags: Optional[str]
    try:
        flags = parts[3]
    except IndexError:
        flags = None
    return (pattern, replacement, flags)


def apply_sed_expr(vm: str, orig: str) -> str:
    (kind, (pattern, replacement, flags)) = parse_sed_expr(vm)
    if kind == "s":
        # TODO(jelmer): Handle flags
        return cast(str, pcre2.substitute(pattern, replacement, orig))
    elif kind == "tr":
        from tr import tr

        return cast(str, tr(pattern, replacement, orig, flags or ""))
    elif kind == "y":
        from tr import tr

        return cast(str, tr(pattern, replacement, orig, flags or ""))
    else:
        raise ValueError(kind)


def apply_url_mangle(expr: str, orig: str) -> str:
    return apply_sed_expr(expr, orig)


class Release:
    """A discovered release."""

    def __init__(self, version: str, url: str, pgpsigurl: Optional[str] = None) -> None:
        self.version = version
        self.url = url
        self.pgpsigurl = pgpsigurl

    def __lt__(self, other: "Release") -> bool:
        if type(self) is not type(other):
            raise TypeError(other)
        return Version(self.version) < Version(other.version)

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self.version!r}, {self.url!r}, pgpsigurl={self.pgpsigurl!r})"


def html_search(
    body: bytes, matching_pattern: str, base_url: str
) -> Iterator[Tuple[str, str]]:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(body, "html.parser")
    if "/" not in matching_pattern:
        matching_pattern = urljoin(base_url.rstrip("/") + "/", matching_pattern)
    for a in soup.find_all("a"):
        href = a.attrs.get("href")
        if not href or not isinstance(href, str):
            continue
        href = urljoin(base_url.rstrip("/") + "/", href)
        try:
            m = pcre2.match(matching_pattern, href)
            logging.debug("Matched pattern %r to %r", matching_pattern, href)
            yield (m.substring(1), urljoin(base_url, m.substring(0)))
        except pcre2.exceptions.MatchError:
            logging.debug("Did not match pattern %r to %r", matching_pattern, href)


def plain_search(
    body: bytes, matching_pattern: str, base_url: str
) -> Iterator[Tuple[str, str]]:
    for m in pcre2.scan(matching_pattern.encode(), body):
        yield (m.substring(1).decode(), urljoin(base_url, m.substring(0).decode()))


searchers = {
    "plain": plain_search,
    "html": html_search,
}


def search(
    searchmode: str,
    resp: BinaryIO,
    *,
    matching_pattern: str,
    package: Union[str, Callable[[], str]],
    url: str,
) -> Iterator[Tuple[str, str]]:
    """Search for versions in a response.

    Args:
      full_url: URL of the version
      version: Version string
    """
    yield from searchers[searchmode](
        resp.read(), _subst(matching_pattern, package), url
    )


def _subst(text: str, package: Union[str, Callable[[], str]]) -> str:
    substs = dict(SUBSTITUTIONS)
    if "@PACKAGE@" in text:
        if callable(package):
            package = package()
        substs["@PACKAGE@"] = package
    for k, v in substs.items():
        text = text.replace(k, v)
    return text


class Watch:
    def __init__(
        self,
        url: str,
        matching_pattern: Optional[str] = None,
        version: Optional[str] = None,
        script: Optional[str] = None,
        opts: Optional[List[str]] = None,
    ) -> None:
        self.url = url
        self.matching_pattern = matching_pattern
        self.version = version
        self.script = script
        if opts is None:
            opts = []
        self.options = opts

    def uversionmangle(self, version: str) -> str:
        try:
            vm = self.get_option("uversionmangle")
        except KeyError:
            return version
        if vm is None:
            return version
        try:
            return apply_sed_expr(vm, version)
        except pcre2.exceptions.LibraryError as e:
            raise WatchSyntaxError(f"invalid uversionmangle {vm!r}: {e}") from e

    def get_option(self, name: str) -> Optional[str]:
        for option in self.options:
            try:
                key, value = option.split("=", 1)
            except ValueError:
                key = option
                value = None
            if key == name:
                return value
        raise KeyError(name)

    def has_option(self, name: str) -> bool:
        try:
            self.get_option(name)
        except KeyError:
            return False
        return True

    def set_option(self, name: str, newvalue: Optional[str] = None) -> None:
        if newvalue is None:
            nv = name
        else:
            nv = f"{name}={newvalue}"
        for i, option in enumerate(self.options):
            try:
                key, value = option.split("=", 1)
            except ValueError:
                key = option
                value = None
            if key == value:
                self.options[i] = nv
                return
        self.options.append(nv)

    def del_option(self, name: str) -> None:
        for i, option in enumerate(self.options):
            try:
                key, _value = option.split("=", 1)
            except ValueError:
                key = option
            if key == name:
                del self.options[i]
                return
        raise KeyError(name)

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}({self.url!r}, matching_pattern={self.matching_pattern!r}, "
            f"version={self.version!r}, script={self.script!r}, opts={self.options!r})"
        )

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Watch):
            return False
        return (
            other.url == self.url
            and other.matching_pattern == self.matching_pattern
            and other.version == self.version
            and other.script == self.script
            and other.options == self.options
        )

    def format_url(self, package: Union[str, Callable[[], str]]) -> str:
        return _subst(self.url, package)

    def discover(self, package: Union[str, Callable[[], str]]) -> Iterator[Release]:
        from urllib.request import Request, urlopen

        url = self.format_url(package)
        try:
            user_agent = self.get_option("user-agent")
        except KeyError:
            user_agent = DEFAULT_USER_AGENT
        try:
            searchmode = self.get_option("searchmode")
        except KeyError:
            searchmode = "html"
        if searchmode is None:
            searchmode = "html"
        logging.debug("Fetching url %s; searchmode=%s", url, searchmode)
        headers = {}
        if user_agent:
            headers["User-Agent"] = user_agent
        req = Request(url, headers=headers)
        resp = urlopen(req)
        if self.matching_pattern is None:
            raise ValueError("matching_pattern is required")

        for version, full_url in search(
            searchmode,
            resp,
            matching_pattern=self.matching_pattern,
            package=package,
            url=url,
        ):
            # TODO(jelmer): Apply uversionmangle
            try:
                pgpsigurlmangle = self.get_option("pgpsigurlmangle")
            except KeyError:
                pgpsigurl = None
            else:
                if pgpsigurlmangle is None:
                    pgpsigurl = None
                else:
                    pgpsigurl = apply_url_mangle(pgpsigurlmangle, full_url)
            yield Release(version, full_url, pgpsigurl=pgpsigurl)


class MissingVersion(Exception):
    """The version= line is missing."""


class WatchSyntaxError(Exception):
    """Syntax error in watch file."""


def parse_watch_file(f: Iterable[str]) -> Optional[WatchFile]:
    """Parse a watch file.

    Args:
      f: watch file to parse
    """
    line: Optional[str]
    lines: List[List[str]] = []
    continued: List[str] = []
    for line in f:
        if line.startswith("#"):
            continue
        if not line.strip():
            continue
        if line.rstrip("\n").endswith("\\"):
            continued.append(line.rstrip("\n\\"))
        else:
            continued.append(line)
            lines.append(continued)
            continued = []
    if continued:
        # Hmm, broken line?
        logging.warning("watchfile ended with \\; skipping last line")
        lines.append(continued)
    if not lines:
        return None
    firstline = "".join(lines.pop(0))
    try:
        key, value = firstline.split("=", 1)
    except ValueError:
        raise MissingVersion()
    if key.strip() != "version":
        raise MissingVersion()
    version = int(value.strip())
    persistent_options: List[str] = []
    entries: List[Watch] = []
    chunked: List[str]
    for chunked in lines:
        if version > 3:
            chunked = [chunk.lstrip() for chunk in chunked]
        line = "".join(chunked).strip()
        if not line:
            continue
        opts: Optional[List[str]]
        if line.startswith("opts="):
            if line[5] == '"':
                optend = line.index('"', 6)
                if optend == -1:
                    raise ValueError(f'Not matching " in {line!r}')
                opts_str = line[6:optend]
                line = line[optend + 1 :]
            else:
                try:
                    (opts_str, line) = line[5:].split(maxsplit=1)
                except ValueError:
                    opts_str = line[5:]
                    line = None
            opts = opts_str.split(",")
        else:
            opts = None
        if not line:
            if opts:
                persistent_options.extend(opts)
        else:
            try:
                url, line = line.split(maxsplit=1)
            except ValueError:
                url = line
                line = ""
            m = pcre2.findall(r"/([^/]*\([^/]*\)[^/]*)$", url)
            if m:
                parts = [m[0]] + line.split(maxsplit=1)
                url = url[: -len(m[0]) - 1].strip()
            else:
                parts = line.split(maxsplit=2)
            entries.append(Watch(url, *parts, opts=opts))  # type: ignore
    return WatchFile(entries=entries, options=persistent_options, version=version)


class WatchEditor(Editor[WatchFile, str]):
    _parsed: WatchFile

    def __init__(
        self,
        path: str = "debian/watch",
        *,
        allow_reformatting: Optional[bool] = None,
        allow_missing: bool = False,
    ) -> None:
        super().__init__(path, allow_reformatting=allow_reformatting)
        self.allow_missing = allow_missing

    @property
    def watch_file(self) -> WatchFile:
        return self._parsed

    def _nonexistent(self) -> WatchFile:
        if self.allow_missing:
            return WatchFile([])
        raise

    def _parse(self, content: str) -> WatchFile:
        wf = parse_watch_file(content.splitlines())
        if wf is None:
            return WatchFile([])
        return wf

    def _format(self, parsed: WatchFile) -> Optional[str]:
        if parsed is None:
            return None
        nf = StringIO()
        parsed.dump(nf)
        return nf.getvalue()


def uscan(wf: WatchFile, package: str) -> None:
    for entry in wf.entries:
        logging.info(f"entry: {entry}")
        for d in entry.discover(package):
            logging.info(f"  {d}")


def main(argv: List[str]) -> None:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()
    if args.verbose:
        logging.basicConfig(level=logging.DEBUG, format="%(message)s")
    else:
        logging.basicConfig(level=logging.INFO, format="%(message)s")
    with open("debian/watch") as f:
        wf = parse_watch_file(f)
    if wf is None:
        print("No watch file found")
        return
    from debian.deb822 import Deb822

    with open("debian/control") as f:
        source = Deb822(f)
    uscan(wf, source["Source"])


if __name__ == "__main__":
    main(sys.argv)
