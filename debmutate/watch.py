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
import re
import sys
from io import StringIO
from typing import (
    TYPE_CHECKING,
    BinaryIO,
    Callable,
    Dict,
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

if TYPE_CHECKING:
    from debian.deb822 import Deb822

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


# Canonical deb822 field names for serialization, keyed by normalized name.
_DEB822_CANONICAL_NAMES: Dict[str, str] = {
    "source": "Source",
    "matchingpattern": "Matching-Pattern",
    "updatescript": "Update-Script",
    "pgpmode": "Pgp-Mode",
    "pgpsigurlmangle": "Pgp-Sig-Url-Mangle",
    "uversionmangle": "Uversion-Mangle",
    "dversionmangle": "Dversion-Mangle",
    "dirversionmangle": "Dirversion-Mangle",
    "filenamemangle": "Filename-Mangle",
    "downloadurlmangle": "Download-Url-Mangle",
    "oversionmangle": "Oversion-Mangle",
    "pagemangle": "Page-Mangle",
    "versionmangle": "Version-Mangle",
    "mode": "Mode",
    "searchmode": "Search-Mode",
    "compression": "Compression",
    "repack": "Repack",
    "repacksuffix": "Repacksuffix",
    "component": "Component",
    "ctype": "Ctype",
    "versionconstraint": "Version-Constraint",
    "versionschema": "Version-Schema",
    "versionseparator": "Version-Separator",
    "decompress": "Decompress",
    "bare": "Bare",
    "versionless": "Versionless",
    "hrefdecode": "Href-Decode",
    "useragent": "User-Agent",
    "unzipopt": "Unzip-Opt",
    "gitpretty": "Git-Pretty",
    "gitdate": "Git-Date",
    "gitexport": "Git-Export",
    "gitmode": "Git-Mode",
    "gitmodules": "Git-Modules",
    "template": "Template",
    "dist": "Dist",
    "owner": "Owner",
    "project": "Project",
    "package": "Package",
    "releaseonly": "Release-Only",
    "versiontype": "Version-Type",
}


def _normalize_deb822_field_name(name: str) -> str:
    """Normalize a deb822 field name: lowercase and remove hyphens."""
    return name.lower().replace("-", "")


def _deb822_field_name(normalized: str) -> str:
    """Convert a normalized field name back to its canonical deb822 form."""
    return _DEB822_CANONICAL_NAMES.get(normalized, normalized.title())


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
        if self.version >= 5:
            self._dump_deb822(f)
        else:
            # Templates are a v5-only feature; expand them before
            # writing to a legacy format.
            for entry in self.entries:
                if entry.has_option("template"):
                    expand_template(entry)
            self._dump_legacy(f)

    def _dump_legacy(self, f: TextIO) -> None:
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

    def _dump_deb822(self, f: TextIO) -> None:
        # First paragraph: version + global options
        f.write(f"Version: {self.version}\n")
        for option in self.options:
            try:
                key, value = option.split("=", 1)
            except ValueError:
                key = option
                value = "yes"
            f.write(f"{_deb822_field_name(key)}: {value}\n")
        for entry in self.entries:
            f.write("\n")
            f.write(f"Source: {entry.url}\n")
            if entry.matching_pattern:
                f.write(f"Matching-Pattern: {entry.matching_pattern}\n")
            if entry.script:
                f.write(f"Update-Script: {entry.script}\n")
            for option in entry.options:
                try:
                    key, value = option.split("=", 1)
                except ValueError:
                    key = option
                    value = "yes"
                f.write(f"{_deb822_field_name(key)}: {value}\n")


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
        return cast(str, pcre2.sub(pattern, replacement, orig))
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
        m = pcre2.search(matching_pattern, href)
        if m:
            logging.debug("Matched pattern %r to %r", matching_pattern, href)
            yield (m.group(1), urljoin(base_url, m.group(0)))
        else:
            logging.debug("Did not match pattern %r to %r", matching_pattern, href)


def plain_search(
    body: bytes, matching_pattern: str, base_url: str
) -> Iterator[Tuple[str, str]]:
    for m in pcre2.finditer(matching_pattern.encode(), body):
        yield (m.group(1).decode(), urljoin(base_url, m.group(0).decode()))


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
        except pcre2.LibraryError as e:
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


class UnknownTemplate(ValueError):
    """Unknown watch file template."""


def _get_template_option(entry: Watch, name: str) -> Optional[str]:
    """Get and remove a template-specific option from a Watch entry."""
    try:
        value = entry.get_option(name)
    except KeyError:
        return None
    entry.del_option(name)
    return value


def _set_default_option(entry: Watch, name: str, value: str) -> None:
    """Set an option only if it is not already present."""
    if not entry.has_option(name):
        entry.set_option(name, value)


def _expand_template_github(entry: Watch) -> None:
    owner = _get_template_option(entry, "owner")
    project = _get_template_option(entry, "project")
    dist = _get_template_option(entry, "dist")
    release_only = _get_template_option(entry, "releaseonly")
    version_type = _get_template_option(entry, "versiontype") or "@ANY_VERSION@"

    if not dist and not (owner and project):
        raise WatchSyntaxError("GitHub template requires Dist or Owner/Project")
    if dist:
        dist = re.sub(r"^.*?github\.com", "https://api.github.com/repos", dist)
        dist = re.sub(r"\.git$", "", dist)
    else:
        dist = f"https://api.github.com/repos/{owner}/{project}"

    if not entry.url:
        ref_type = "release/" if release_only else "tags/"
        entry.url = f"{dist}/git/matching-refs/{ref_type}"
    if not entry.matching_pattern:
        entry.matching_pattern = (
            "https://api.github.com/repos/[^/]+/[^/]+/git/refs/tags/"
            r"(?>[^/]+(?<=(?:\D|alpha|beta|rc))\-)?" + version_type + '(?:(?=")|$)'
        )
    _set_default_option(
        entry,
        "downloadurlmangle",
        r"s%(api.github.com/repos/[^/]+/[^/]+)/git/refs/%$1/tarball/refs/%g",
    )
    try:
        component = entry.get_option("component")
    except KeyError:
        component = None
    if component:
        _set_default_option(
            entry,
            "filenamemangle",
            r"s%.*/(?:[^/]+(?<=(?:\D|alpha|beta|rc))\-)?@ANY_VERSION@"
            r"%@PACKAGE@-@COMPONENT@-$1.tar.gz%",
        )
    else:
        _set_default_option(
            entry,
            "filenamemangle",
            r"s%.*/(?:[^/]+(?<=(?:\D|alpha|beta|rc))\-)?@ANY_VERSION@"
            r"%@PACKAGE@-$1.tar.gz%",
        )
    _set_default_option(entry, "searchmode", "plain")
    _set_default_option(entry, "pgpmode", "none")


def _expand_template_gitlab(entry: Watch) -> None:
    dist = _get_template_option(entry, "dist")
    version_type = _get_template_option(entry, "versiontype") or "@ANY_VERSION@"

    if not dist:
        raise WatchSyntaxError("GitLab template requires Dist")
    dist = dist.rstrip("/")

    if not entry.url:
        entry.url = dist
    if not entry.matching_pattern:
        entry.matching_pattern = f".*?{version_type}"
    try:
        component = entry.get_option("component")
    except KeyError:
        component = None
    if component:
        _set_default_option(
            entry,
            "filenamemangle",
            f"s%.*?{version_type}$%@PACKAGE@-@COMPONENT@-$1.tar.gz%",
        )
    else:
        _set_default_option(
            entry,
            "filenamemangle",
            f"s%.*?{version_type}$%@PACKAGE@-$1.tar.gz%",
        )
    _set_default_option(entry, "uversionmangle", "auto")
    _set_default_option(entry, "pgpmode", "none")
    _set_default_option(entry, "mode", "gitlab")


def _expand_template_pypi(entry: Watch) -> None:
    dist = _get_template_option(entry, "dist")
    if not dist:
        raise WatchSyntaxError("Pypi template requires Dist")

    if not entry.url:
        entry.url = f"https://pypi.debian.net/{dist}/"
    if not entry.matching_pattern:
        entry.matching_pattern = f"{dist}-@ANY_VERSION@.tar.gz"
    _set_default_option(entry, "searchmode", "plain")
    _set_default_option(entry, "pgpmode", "none")
    if not entry.has_option("uversionmangle"):
        entry.set_option("uversionmangle", r"s/(rc|a|b|c)/~$1/")


def _expand_template_npmregistry(entry: Watch) -> None:
    dist = _get_template_option(entry, "dist")
    version_type = _get_template_option(entry, "versiontype") or "@ANY_VERSION@"

    if not dist:
        raise WatchSyntaxError("Npmregistry template requires Dist")
    name = dist.rsplit("/", 1)[-1]

    if not entry.url:
        entry.url = f"https://registry.npmjs.org/{dist}"
    if not entry.matching_pattern:
        entry.matching_pattern = (
            f"https://registry.npmjs.org/{dist}/-/{name}-{version_type}@ARCHIVE_EXT@"
        )
    _set_default_option(entry, "uversionmangle", "auto")
    _set_default_option(entry, "filenamemangle", "auto")
    _set_default_option(entry, "pgpmode", "none")
    _set_default_option(entry, "searchmode", "plain")


def _expand_template_metacpan(entry: Watch) -> None:
    dist = _get_template_option(entry, "dist")
    version_type = _get_template_option(entry, "versiontype") or "@ANY_VERSION@"

    if not dist:
        raise WatchSyntaxError("Metacpan template requires Dist")
    dist = dist.replace("::", "-")

    entry.set_option("mode", "metacpan")
    if not entry.url:
        entry.url = dist
    if not entry.matching_pattern:
        entry.matching_pattern = (
            f"https://cpan.metacpan.org/.*{dist}-{version_type}@ARCHIVE_EXT@"
        )
    _set_default_option(entry, "pgpmode", "none")


def _expand_template_cran(entry: Watch) -> None:
    package = _get_template_option(entry, "package")
    if not package:
        raise WatchSyntaxError("CRAN template requires Package")

    if not entry.url:
        entry.url = f"https://cran.r-project.org/package={package}"
    if not entry.matching_pattern:
        entry.matching_pattern = ".*_@ANY_VERSION@.tar.gz"
    _set_default_option(entry, "compression", "xz")
    _set_default_option(entry, "dversionmangle", r"s/\+dfsg[0-9]*//g")
    _set_default_option(
        entry,
        "downloadurlmangle",
        r"s%.*/src/contrib/%https://cran.r-project.org/src/contrib/%",
    )
    _set_default_option(entry, "repacksuffix", "+dfsg")


def _expand_template_bioconductor(entry: Watch) -> None:
    package = _get_template_option(entry, "package")
    if not package:
        raise WatchSyntaxError("Bioconductor template requires Package")

    if not entry.url:
        entry.url = f"https://bioconductor.org/packages/{package}"
    if not entry.matching_pattern:
        entry.matching_pattern = ".*_@ANY_VERSION@.tar.gz"
    _set_default_option(entry, "compression", "xz")
    _set_default_option(entry, "dversionmangle", r"s/\+dfsg[0-9]*//g")
    _set_default_option(
        entry,
        "downloadurlmangle",
        r"s%.*/src/contrib/%https://bioconductor.org/packages/release/bioc/src/contrib/%",
    )
    _set_default_option(entry, "repacksuffix", "+dfsg")


_TEMPLATES: Dict[str, Callable[[Watch], None]] = {
    "github": _expand_template_github,
    "gitlab": _expand_template_gitlab,
    "pypi": _expand_template_pypi,
    "npmregistry": _expand_template_npmregistry,
    "metacpan": _expand_template_metacpan,
    "cran": _expand_template_cran,
    "bioconductor": _expand_template_bioconductor,
}


def expand_template(entry: Watch) -> None:
    """Expand a template in a Watch entry.

    Resolves the ``template`` option (e.g. ``GitHub``, ``Pypi``) by
    filling in ``url``, ``matching_pattern``, and default options
    according to the template's rules.  Template-specific fields
    (``Dist``, ``Owner``, etc.) are consumed and removed.

    Raises UnknownTemplate if the template name is not recognised.
    Raises WatchSyntaxError if required template fields are missing.
    """
    template_name = _get_template_option(entry, "template")
    if template_name is None:
        return

    handler = _TEMPLATES.get(template_name.lower())
    if handler is None:
        raise UnknownTemplate(template_name)
    handler(entry)


class MissingVersion(Exception):
    """The version= line is missing."""


class WatchSyntaxError(Exception):
    """Syntax error in watch file."""


def _deb822_para_to_options(
    para: "Deb822",
    skip_keys: "frozenset[str]",
) -> List[str]:
    """Convert deb822 paragraph fields to a list of option strings.

    Fields in skip_keys are excluded. Field names are normalized
    (lowercased, hyphens removed) to match the legacy opts= format.
    """
    options: List[str] = []
    for key in para:
        normalized = _normalize_deb822_field_name(key)
        if normalized in skip_keys:
            continue
        value = para[key]
        if value == "":
            # Empty field value is falsy in uscan (Perl), skip it.
            continue
        options.append(f"{normalized}={value}")
    return options


# Fields that map to Watch/WatchFile attributes rather than options.
_DEB822_ENTRY_SKIP = frozenset(
    {"version", "source", "matchingpattern", "updatescript", "untrackable"}
)


def parse_watch_file_deb822(f: Iterable[str]) -> Optional[WatchFile]:
    """Parse a version 5 (deb822-style) watch file.

    Args:
      f: watch file lines to parse
    """
    from debian.deb822 import Deb822

    lines_list = list(f)
    # Ensure lines have newline terminators for Deb822 paragraph splitting
    text = "\n".join(line.rstrip("\n") for line in lines_list) + "\n"
    if not text.strip():
        return None

    paragraphs = list(Deb822.iter_paragraphs(text.splitlines(True)))
    if not paragraphs:
        return None

    header = paragraphs[0]
    if "Version" not in header:
        raise MissingVersion()
    version = int(header["Version"])
    if version < 5:
        raise WatchSyntaxError(
            f"deb822-style watch files require version >= 5, got {version}"
        )

    if header.get("Untrackable"):
        logging.warning("Untrackable project: %s", header["Untrackable"])

    entries: List[Watch] = []
    global_options: List[str] = []

    if len(paragraphs) == 1 and ("Source" in header or "Template" in header):
        # Single-paragraph format: header is also the only source
        url = header.get("Source", "")
        matching_pattern = header.get("Matching-Pattern")
        script = header.get("Update-Script")
        options = _deb822_para_to_options(header, _DEB822_ENTRY_SKIP)
        entries.append(
            Watch(
                url,
                matching_pattern=matching_pattern,
                script=script,
                opts=options,
            )
        )
    else:
        # Multi-paragraph: header provides defaults, subsequent paragraphs
        # are sources. Global options are non-structural header fields.
        global_options = _deb822_para_to_options(
            header, frozenset({"version", "untrackable"})
        )

        for para in paragraphs[1:]:
            if "Source" not in para and "Template" not in para:
                logging.warning("Paragraph without Source or Template, skipping")
                continue
            # Inherit defaults from header
            merged = Deb822(header)
            merged.update(para)

            url = merged.get("Source", "")
            matching_pattern = merged.get("Matching-Pattern")
            script = merged.get("Update-Script")
            options = _deb822_para_to_options(merged, _DEB822_ENTRY_SKIP)
            entries.append(
                Watch(
                    url,
                    matching_pattern=matching_pattern,
                    script=script,
                    opts=options,
                )
            )

    return WatchFile(entries=entries, options=global_options, version=version)


def parse_watch_file(f: Iterable[str]) -> Optional[WatchFile]:
    """Parse a watch file.

    Automatically detects whether the file uses the legacy line-based format
    (versions 1-4) or the deb822-style format (version 5+).

    Args:
      f: watch file to parse
    """
    lines_list = list(f)
    # Detect format by looking at the first non-blank, non-comment line.
    # deb822 format uses "Version: N", legacy uses "version=N".
    for raw_line in lines_list:
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if re.match(r"^version\s*:\s*\d+\s*$", stripped, re.IGNORECASE):
            return parse_watch_file_deb822(iter(lines_list))
        break

    return _parse_watch_file_legacy(iter(lines_list))


def _parse_watch_file_legacy(f: Iterable[str]) -> Optional[WatchFile]:
    """Parse a legacy (version 1-4) watch file.

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
