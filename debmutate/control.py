#!/usr/bin/python3
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

"""Utility functions for dealing with control files."""

__all__ = [
    "dh_gnome_clean",
    "pg_buildext_updatecontrol",
    "guess_template_type",
    "ControlEditor",
    "update_control",
    "parse_relations",
    "format_relations",
    "get_relation",
    "iter_relations",
    "ensure_minimum_version",
    "ensure_exact_version",
    "ensure_some_version",
    "filter_dependencies",
    "drop_dependency",
    "delete_from_list",
    "is_dep_implied",
    "is_relation_implied",
    "parse_standards_version",
    "PkgRelationFieldEditor",
]

import collections
import contextlib
import operator
import os
import re
import subprocess
import time
import warnings
from itertools import takewhile
from types import TracebackType
from typing import (
    Any,
    Callable,
    ContextManager,
    Dict,
    Iterable,
    Iterator,
    List,
    Literal,
    Optional,
    Protocol,
    Tuple,
    Type,
    Union,
)

from debian.changelog import Version  # type: ignore[attr-defined]

from ._deb822 import PkgRelation
from .deb822 import (
    ChangeConflict,
    Deb822Editor,
    Deb822File,
    Deb822Paragraph,
    parse_deb822_file,
)
from .reformatting import GeneratedFile

# Type alias for changes dictionary
ChangesDict = Dict[Tuple[str, str], List[Tuple[str, Optional[str], Optional[str]]]]


class TreeLike(Protocol):
    """Protocol for tree-like objects that have an abspath method."""

    def abspath(self, path: str) -> str:
        """Return absolute path for the given relative path."""
        ...


# TODO(jelmer): dedupe with scripts/wrap-and-sort in devscripts
CONTROL_LIST_FIELDS = (
    "Breaks",
    "Build-Conflicts",
    "Build-Conflicts-Arch",
    "Build-Conflicts-Indep",
    "Build-Depends",
    "Build-Depends-Arch",
    "Build-Depends-Indep",
    "Built-Using",
    "Conflicts",
    "Depends",
    "Enhances",
    "Pre-Depends",
    "Provides",
    "Recommends",
    "Replaces",
    "Suggests",
    "Xb-Npp-MimeType",
)


class MissingSourceParagraph(Exception):
    """The first paragraph is not a Source paragraph."""


class TemplateExpansionFailed(Exception):
    def __init__(self, command: str, stderr: str) -> None:
        self.command = command
        self.stderr = stderr
        super().__init__(f"Template expansion ({command!r}) failed: {stderr}")


class TemplateExpandCommandMissing(Exception):
    def __init__(self, command: str) -> None:
        self.command = command
        super().__init__(f"Command for expanding template file missing: {command}")


def parse_relation(t: str) -> List[PkgRelation]:
    with warnings.catch_warnings():
        suppress_substvar_warnings()
        return PkgRelation.parse(t)


# From scripts/wrap-and-sort in devscripts
# Copyright (C) 2010-2018, Benjamin Drung <bdrung@debian.org>
#               2010, Stefano Rivera <stefanor@ubuntu.com>


def _sort_packages_key(package: str) -> Tuple[int, str]:
    # Sort dependencies starting with a "real" package name before ones
    # starting with a substvar
    return 0 if re.match("[a-z0-9]", package) else 1, package


def _wrap_field(
    control: Deb822Paragraph,
    entry: str,
    sort: bool,
    formatter: Optional[Callable[..., Any]],
) -> None:
    from debian._deb822_repro import LIST_COMMA_SEPARATED_INTERPRETATION

    view = control.as_interpreted_dict_view(LIST_COMMA_SEPARATED_INTERPRETATION)
    with view[entry] as field_content:
        seen = set()
        for package_ref in field_content.iter_value_references():
            value = package_ref.value
            new_value = " | ".join(x.strip() for x in value.split("|"))
            if not sort or new_value not in seen:
                package_ref.value = new_value
                seen.add(new_value)
            else:
                package_ref.remove()
        if sort:
            field_content.sort(key=_sort_packages_key)
            if formatter:
                field_content.value_formatter(formatter)
            field_content.reformat_when_finished()


# End import from devscripts


def dh_gnome_clean(path: str = ".") -> None:
    """Run the dh_gnome_clean command.

    This needs to do some post-hoc cleaning, since dh_gnome_clean
    writes various debhelper log files that should not be checked in.

    Args:
      path: Path to run dh_gnome_clean in
    """
    for n in os.listdir(os.path.join(path, "debian")):
        if n.endswith(".debhelper.log"):
            raise AssertionError("pre-existing .debhelper.log files")
    if not os.path.exists(os.path.join(path, "debian/changelog")):
        raise AssertionError(f"no changelog file in {path}")
    try:
        subprocess.check_call(["dh_gnome_clean"], cwd=path)
    except FileNotFoundError as e:
        raise TemplateExpandCommandMissing("dh_gnome_clean") from e
    for n in os.listdir(os.path.join(path, "debian")):
        if n.endswith(".debhelper.log"):
            os.unlink(os.path.join(path, "debian", n))


def pg_buildext_updatecontrol(path: str = ".") -> None:
    """Run the 'pg_buildext updatecontrol' command.

    Args:
      path: path to run pg_buildext updatecontrol in
    """
    try:
        subprocess.check_call(["pg_buildext", "updatecontrol"], cwd=path)
    except FileNotFoundError as e:
        raise TemplateExpandCommandMissing("pg_buildext") from e


def guess_template_type(
    template_path: str, debian_path: Optional[str] = None
) -> Optional[str]:
    """Guess the type for a control template.

    Args:
      template_path: Template path
      debian_path: Path to debian directory
    Returns:
      Name of template type; None if unknown
    """
    # TODO(jelmer): This should use a proper make file parser of some sort..
    if debian_path is not None:
        try:
            with open(os.path.join(debian_path, "rules"), "rb") as f:
                for line in f:
                    if line.startswith(b"debian/control:"):
                        return "rules"
                    if line.startswith(b"debian/%: debian/%.in"):
                        return "rules"
                    if line.startswith(b"include /usr/share/blends-dev/rules"):
                        return "rules"
        except FileNotFoundError:
            pass
    try:
        with open(template_path, "rb") as f:
            template = f.read()
            if b"@GNOME_TEAM@" in template:
                return "gnome"
            elif b"@cdbs@" in template:
                return "cdbs"
            elif b"PGVERSION" in template:
                return "postgresql"
            else:
                try:
                    deb822 = next(
                        iter(
                            parse_deb822_file(
                                template.splitlines(),
                                accept_files_with_error_tokens=True,
                            )
                        )
                    )
                except StopIteration:
                    build_depends = ""
                else:
                    build_depends = deb822.get("Build-Depends", "")
                if any(iter_relations(build_depends, "gnome-pkg-tools")):
                    return "gnome"
                if any(iter_relations(build_depends, "cdbs")):
                    return "cdbs"
    except IsADirectoryError:
        return "directory"
    if debian_path is not None and os.path.exists(
        os.path.join(debian_path, "debcargo.toml")
    ):
        return "debcargo"
    return None


def _cdbs_resolve_conflict(
    para_key: Tuple[str, str],
    field: str,
    actual_old_value: Optional[str],
    template_old_value: Optional[str],
    actual_new_value: Optional[str],
) -> Optional[str]:
    if (
        para_key[0] == "Source"
        and field == "Build-Depends"
        and template_old_value is not None
        and actual_old_value is not None
        and actual_new_value is not None
    ):
        if actual_old_value in actual_new_value:
            # We're simply adding to the existing list
            return actual_new_value.replace(actual_old_value, template_old_value)
        else:
            existing = [v[1] for v in parse_relations(actual_old_value)]
            ret = template_old_value
            for _, v, _ in parse_relations(actual_new_value):
                if any(is_relation_implied(v, r) for r in existing):
                    continue
                ret = ensure_relation(ret, v)
            return ret
    raise ChangeConflict(
        para_key, field, actual_old_value, template_old_value, actual_new_value
    )


def _expand_control_template(template_path: str, path: str, template_type: str) -> None:
    package_root = os.path.dirname(os.path.dirname(path)) or "."
    if template_type == "rules":
        try:
            path_mtime = os.stat(path).st_mtime
        except FileNotFoundError:
            path_mtime = None
        while os.stat(template_path).st_mtime == path_mtime:
            # Wait until mtime has changed, so that make knows to regenerate.
            os.utime(template_path, (time.time(), time.time()))
        try:
            subprocess.check_call(
                ["./debian/rules", "debian/control"],
                stderr=subprocess.PIPE,
                cwd=package_root,
            )
        except subprocess.CalledProcessError as e:
            raise TemplateExpansionFailed("./debian/rules", e.stderr.decode())
    elif template_type == "gnome":
        dh_gnome_clean(package_root)
    elif template_type == "postgresql":
        pg_buildext_updatecontrol(package_root)
    elif template_type == "directory":
        raise GeneratedFile(path, template_path)
    else:
        raise AssertionError


def _update_control_template(
    template_path: str, path: str, changes: ChangesDict, expand_template: bool = True
) -> bool:
    template_type = guess_template_type(
        template_path, debian_path=os.path.dirname(path)
    )
    if template_type is None:
        raise GeneratedFile(path, template_path)
    if template_type == "directory":
        # We can't handle these yet
        raise GeneratedFile(path, template_path)
    with Deb822Editor(template_path, accept_files_with_error_tokens=True) as updater:
        resolve_conflict: Optional[
            Callable[
                [Tuple[str, str], str, Optional[str], Optional[str], Optional[str]],
                Optional[str],
            ]
        ]
        if template_type == "cdbs":
            resolve_conflict = _cdbs_resolve_conflict
        else:
            resolve_conflict = None
        # Type assertion needed because mypy doesn't recognize Deb822Editor has apply_changes
        updater.apply_changes(changes, resolve_conflict=resolve_conflict)  # type: ignore[attr-defined]
    if not updater.changed:
        # A bit odd, since there were changes to the output file. Anyway.
        return False

    if expand_template:
        if template_type == "cdbs":
            with Deb822Editor(path, allow_generated=True) as updater:
                updater.apply_changes(changes)  # type: ignore[attr-defined]
        else:
            _expand_control_template(template_path, path, template_type)
    return True


@contextlib.contextmanager
def _preserve_field_order_preferences(
    paragraphs: List[Deb822Paragraph],
) -> Iterator[None]:
    description_is_not_last = set()
    for para in paragraphs:
        if "Package" not in para:
            continue
        if list(para) and list(para)[-1] != "Description":
            description_is_not_last.add(para["Package"])
    yield
    for para in paragraphs:
        if "Package" not in para:
            continue
        if para["Package"] not in description_is_not_last:
            # Make sure Description stays the last field
            try:
                para.order_last("Description")
            except KeyError:
                pass  # it's okay if the field doesn't exist


def update_control(
    path: str = "debian/control",
    source_package_cb: Optional[Callable[[Deb822Paragraph], None]] = None,
    binary_package_cb: Optional[Callable[[Deb822Paragraph], None]] = None,
) -> bool:
    def paragraph_cb(paragraph: Deb822Paragraph) -> None:
        if paragraph.get("Source"):
            if source_package_cb is not None:
                source_package_cb(paragraph)
        else:
            if binary_package_cb is not None:
                binary_package_cb(paragraph)

    with ControlEditor(path) as updater:
        for paragraph in updater.paragraphs:
            paragraph_cb(paragraph)
    return updater.changed


def _find_template_path(path: str) -> Optional[str]:
    for template_path in [path + ".in", path + ".m4"]:
        if os.path.exists(template_path):
            return template_path
    else:
        return None


class ControlEditor:
    """Edit a control file."""

    changed: bool
    changed_files: List[str]
    _field_order_preserver: ContextManager[Any]

    def __init__(
        self,
        path: str = "debian/control",
        allow_reformatting: Optional[bool] = None,
        allow_missing: bool = False,
    ):
        self.path = path
        self._primary = Deb822Editor(
            path, allow_reformatting=allow_reformatting, allow_missing=allow_missing
        )
        self._template_only = False

    @classmethod
    def create(cls, path: str = "debian/control") -> "ControlEditor":
        return cls(path, allow_reformatting=True, allow_missing=True)

    @classmethod
    def from_tree(
        cls, tree: "TreeLike", subpath: Optional[str] = None
    ) -> "ControlEditor":
        relpath = "debian/control"
        if subpath not in (None, ".", ""):
            relpath = os.path.join(subpath or "", relpath)
        return cls(tree.abspath(relpath))

    @property
    def paragraphs(self) -> List[Deb822Paragraph]:
        """List of all the paragraphs."""
        return self._primary.paragraphs

    @property
    def source(self) -> Deb822Paragraph:
        """Source package."""
        for entry in self.paragraphs:
            if not entry.get("Source"):
                raise MissingSourceParagraph()
            return entry
        else:
            p = Deb822Paragraph.new_empty_paragraph()
            self.paragraphs.insert(0, p)
            return p

    @property
    def binaries(self) -> Iterable[Deb822Paragraph]:
        """List of binary packages."""
        for entry in self.paragraphs:
            if entry.get("Package"):
                yield entry

    def changes(self) -> ChangesDict:
        """Return a dictionary describing the changes since the base.

        Returns:
          dictionary mapping tuples of (kind, name) to
            list of (field_name, old_value, new_value)
        """
        orig = self._primary._parse(self._primary._orig_content)
        changes: ChangesDict = {}

        def by_key(
            ps: Union[Deb822File, list[Deb822Paragraph]],
        ) -> Dict[Tuple[str, str], Deb822Paragraph]:
            ret = {}
            for p in ps:
                if not p:
                    continue
                if "Source" in p:
                    ret[("Source", p["Source"])] = p
                else:
                    ret[("Package", p["Package"])] = p
            return ret

        orig_by_key = by_key(orig)
        new_by_key = by_key(self.paragraphs)
        for key in set(orig_by_key).union(set(new_by_key)):
            old: Deb822Paragraph = orig_by_key.get(key, {})  # type: ignore[arg-type]
            new: Deb822Paragraph = new_by_key.get(key, {})  # type: ignore[arg-type]
            if old == new:
                continue
            fields = list(old)
            fields.extend([field for field in new if field not in fields])
            for field in fields:
                if old.get(field) != new.get(field):
                    changes.setdefault(key, []).append(
                        (str(field), old.get(field), new.get(field))
                    )
        return changes

    def __enter__(self) -> "ControlEditor":
        try:
            self._primary.__enter__()
        except FileNotFoundError:
            template_path = _find_template_path(self.path)
            if template_path:
                self._template_only = True
                template_type = guess_template_type(
                    template_path, debian_path=os.path.dirname(self.path)
                )
                if template_type is None:
                    raise GeneratedFile(self.path, template_path)
                _expand_control_template(template_path, self.path, template_type)
                self._primary.__enter__()
            else:
                raise
        self._field_order_preserver = _preserve_field_order_preferences(
            self._primary.paragraphs
        )
        self._field_order_preserver.__enter__()
        return self

    def __exit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc_val: Optional[BaseException],
        exc_tb: Optional[TracebackType],
    ) -> Literal[False]:
        self._field_order_preserver.__exit__(exc_type, exc_val, exc_tb)
        try:
            if self._template_only:
                os.unlink(self.path)
                self.changed_files = [self.path]
                raise FileNotFoundError
            self._primary.__exit__(exc_type, exc_val, exc_tb)
        except GeneratedFile as e:
            if not e.template_path:
                raise
            self.changed = _update_control_template(
                e.template_path, self.path, self.changes()
            )
            if self.changed:
                self.changed_files = [e.template_path, self.path]
            else:
                self.changed_files = []
        except FileNotFoundError:
            template_path = _find_template_path(self.path)
            if template_path:
                self.changed = _update_control_template(
                    template_path,
                    self.path,
                    self.changes(),
                    expand_template=not self._template_only,
                )
                if self.changed:
                    self.changed_files = [template_path, self.path]
                else:
                    self.changed_files = []
            else:
                raise
        else:
            self.changed = self._primary.changed
            if self.changed:
                self.changed_files = [self.path]
            else:
                self.changed_files = []
        return False

    def sort_binary_packages(self, keep_first: bool = False) -> None:
        sort_key = operator.itemgetter("Package")
        self._primary.sort_paragraphs(skip=1 + int(keep_first), sort_key=sort_key)

    def wrap_and_sort(
        self,
        short_indent: bool = False,
        trailing_comma: bool = False,
        wrap_always: bool = False,
        max_line_length: int = 79,
    ) -> None:
        """Wrap and sort this control file."""
        try:
            from devscripts.control import wrap_and_sort_formatter
        except ImportError:
            raise NotImplementedError("version of devscripts too old")
        formatter = wrap_and_sort_formatter(
            1 if short_indent else "FIELD_NAME_LENGTH",
            trailing_separator=trailing_comma,
            immediate_empty_line=short_indent,
            max_line_length_one_liner=0 if wrap_always else max_line_length,
        )
        for paragraph in self.paragraphs:
            for field in CONTROL_LIST_FIELDS:
                if field in paragraph:
                    _wrap_field(paragraph, field, True, formatter)
            if "Uploaders" in paragraph:
                _wrap_field(paragraph, "Uploaders", False, formatter)
            if "Architecture" in paragraph:
                archs = list(paragraph["Architecture"].split())
                # Sort, with wildcard entries (such as linux-any) first:
                archs = sorted(archs, key=lambda x: ("any" not in x, x))
                paragraph["Architecture"] = " ".join(archs)

    def add_binary(self, contents: Union[Dict[str, str], Deb822Paragraph]) -> None:
        if isinstance(contents, dict):
            para = Deb822Paragraph.from_dict(contents)
        else:
            para = contents
        return self._primary.paragraphs.append(para)

    def remove(self, para: Deb822Paragraph) -> None:
        self._primary.paragraphs.remove(para)


def parse_relations(text: str) -> List[Tuple[str, List[PkgRelation], str]]:
    """Parse a package relations string.

    (e.g. a Depends, Provides, Build-Depends, etc field)

    This attempts to preserve some indentation.

    Args:
      text: Text to parse
    Returns: list of tuples with (whitespace, relation, whitespace)
    """
    ret: List[Tuple[str, List[PkgRelation], str]] = []
    for top_level in text.split(","):
        if top_level == "":
            if "," not in text:
                return []
        if top_level.isspace():
            ret.append((top_level, [], ""))
            continue
        head_whitespace = ""
        for i in range(len(top_level)):
            if not top_level[i].isspace():
                if i > 0:
                    head_whitespace = top_level[:i]
                top_level = top_level[i:]
                break
        tail_whitespace = ""
        for i in range(len(top_level)):
            if not top_level[-(i + 1)].isspace():
                if i > 0:
                    tail_whitespace = top_level[-i:]
                    top_level = top_level[:-i]
                break
        ret.append((head_whitespace, parse_relation(top_level), tail_whitespace))
    return ret


def format_relations(relations: List[Tuple[str, List[PkgRelation], str]]) -> str:
    """Format a package relations string.

    This attempts to create formatting.
    """
    ret = []
    for head_whitespace, relation, tail_whitespace in relations:
        ret.append(
            head_whitespace + " | ".join(o.str() for o in relation) + tail_whitespace
        )
    # The first line can be whitespace only, the subsequent ones can not
    lines = []
    for i, line in enumerate(",".join(ret).split("\n")):
        if i == 0:
            lines.append(line)
        else:
            if line.strip():
                lines.append(line)
    return "\n".join(lines)


def get_relation(relationstr: str, package: str) -> Tuple[int, List[PkgRelation]]:
    """Retrieve the relation for a particular package.

    Args:
      relationstr: package relation string
      package: package name
    Returns:
      Tuple with offset and relation object
    """
    for offset, relation in iter_relations(relationstr, package):
        names = [r.name for r in relation]
        if len(names) > 1 and package in names:
            raise ValueError(f"Complex rule for {package} , aborting")
        if names != [package]:
            continue
        return offset, relation
    raise KeyError(package)


def iter_relations(
    relationstr: str, package: str
) -> Iterable[Tuple[int, List[PkgRelation]]]:
    """Iterate over the relations relevant for a particular package.

    Args:
      relationstr: package relation string
      package: package name
    Yields:
      Tuples with offset and relation objects
    """
    relations = parse_relations(relationstr)
    return _iter_relations(relations, package)


def _iter_relations(
    relations: List[Tuple[str, List[PkgRelation], str]], package: str
) -> Iterator[Tuple[int, List[PkgRelation]]]:
    for i, (_head_whitespace, relation, _tail_whitespace) in enumerate(relations):
        if isinstance(relation, str):  # formatting
            continue
        names = [r.name for r in relation]
        if package not in names:
            continue
        yield i, relation


def ensure_minimum_version(
    relationstr: str, package: str, minimum_version: Union[str, Version]
) -> str:
    """Update a relation string to ensure a particular version is required.

    Args:
      relationstr: package relation string
      package: package name
      minimum_version: Minimum version
    Returns:
      updated relation string
    """

    def is_obsolete(relation: List[PkgRelation]) -> bool:
        for r in relation:
            if r.name != package:
                continue
            if r.version is None:
                continue
            if r.version[0] == ">>" and Version(r.version[1]) < minimum_version:
                return True
            if r.version[0] == ">=" and Version(r.version[1]) <= minimum_version:
                return True
        return False

    minimum_version = Version(minimum_version)
    found = False
    changed = False
    relations = parse_relations(relationstr)
    obsolete_relations = []
    for i, (_head_whitespace, relation, _tail_whitespace) in enumerate(relations):
        if isinstance(relation, str):  # formatting
            continue
        names = [r.name for r in relation]
        if len(names) > 1 and package in names and is_obsolete(relation):
            obsolete_relations.append(i)
        if names != [package]:
            continue
        found = True
        if (
            relation[0].version is None
            or Version(relation[0].version[1]) < minimum_version
        ):
            relation[0].version = (">=", str(minimum_version))
            changed = True
    if not found:
        changed = True
        _add_relation(
            relations, [PkgRelation(name=package, version=(">=", str(minimum_version)))]
        )
    for i in reversed(obsolete_relations):
        del relations[i]
    if changed:
        return format_relations(relations)
    # Just return the original; we don't preserve all formatting yet.
    return relationstr


def ensure_exact_version(
    relationstr: str,
    package: str,
    version: Union[str, Version],
    position: Optional[int] = None,
) -> str:
    """Update a relation string to depend on a specific version.

    Args:
      relationstr: package relation string
      package: package name
      version: Exact version to depend on
      position: Optional position in the list to insert any new entries
    Returns:
      updated relation string
    """
    version = Version(version)
    found = False
    changed = False
    relations = parse_relations(relationstr)
    for _head_whitespace, relation, _tail_whitespace in relations:
        if isinstance(relation, str):  # formatting
            continue
        names = [r.name for r in relation]
        if len(names) > 1 and names[0] == package:
            raise Exception(f"Complex rule for {package} , aborting")
        if names != [package]:
            continue
        found = True
        if relation[0].version is None or (
            relation[0].version[0],
            Version(relation[0].version[1]),
        ) != ("=", version):
            relation[0].version = ("=", str(version))
            changed = True
    if not found:
        changed = True
        _add_relation(
            relations,
            [PkgRelation(name=package, version=("=", str(version)))],
            position=position,
        )
    if changed:
        return format_relations(relations)
    # Just return the original; we don't preserve all formatting yet.
    return relationstr


def ensure_relation(
    relationstr: str,
    new_relationstr: Union[str, List[PkgRelation]],
    position: Optional[int] = None,
) -> str:
    """Ensure that a relation exists.

    This is done by either verifying that there is an existing
    relation that satisfies the specified relation, or
    by upgrading an existing relation.
    """
    if isinstance(new_relationstr, str):
        new_relation = parse_relation(new_relationstr)
    else:
        new_relation = new_relationstr
    relations = parse_relations(relationstr)
    added = False
    to_remove = []
    for i, (_head_whitespace, relation, _tail_whitespace) in enumerate(relations):
        if isinstance(relation, str):  # formatting
            continue
        if is_relation_implied(new_relation, relation):
            return relationstr
        if is_relation_implied(relation, new_relation):
            if added:
                to_remove.append(i)
            else:
                relations[i] = (relations[i][0], new_relation, relations[i][2])
                added = True
    if not added:
        _add_relation(relations, new_relation)

    for i in reversed(to_remove):
        del relations[i]

    return format_relations(relations)


def _add_relation(
    relations: List[Tuple[str, List[PkgRelation], str]],
    relation: List[PkgRelation],
    position: Optional[int] = None,
) -> None:
    """Add a relation to a list of relations.

    Args:
      relations: existing list of relations
      relation: New relation
      position: Optional position to insert the new relation
    Returns:
      Nothing
    """
    if len(relations) > 0 and not relations[-1][1]:
        pointless_tail: Optional[Tuple[str, List[PkgRelation], str]]
        pointless_tail = relations.pop(-1)
    else:
        pointless_tail = None
    if len(relations) == 0:
        head_whitespace = ""
        tail_whitespace = ""
    elif len(relations) == 1:
        head_whitespace = relations[0][0] or " "  # Best guess
        tail_whitespace = ""
    else:
        hws: Dict[str, int] = collections.defaultdict(lambda: 0)
        for r in relations[1:]:
            hws[r[0]] += 1
        if len(hws) == 1:
            head_whitespace = list(hws.keys())[0]
        else:
            head_whitespace = relations[-1][0]  # Best guess
        tws: Dict[str, int] = collections.defaultdict(lambda: 0)
        for r in relations[0:-1]:
            tws[r[2]] += 1
        if len(tws) == 1:
            tail_whitespace = list(tws.keys())[0]
        else:
            tail_whitespace = relations[0][2]  # Best guess

    if position is None:
        position = len(relations)

    if position < 0 or position > len(relations):
        raise IndexError(f"position out of bounds: {position!r}")

    if position == len(relations):
        if len(relations) == 0:
            last_tail_whitespace = ""
        else:
            last_tail_whitespace = relations[-1][2]
            relations[-1] = relations[-1][:2] + (tail_whitespace,)
        relations.append((head_whitespace, relation, last_tail_whitespace))
    elif position == 0:
        relations.insert(position, (relations[0][0], relation, tail_whitespace))
        relations[1] = (head_whitespace, relations[1][1], relations[1][2])
    else:
        relations.insert(position, (head_whitespace, relation, tail_whitespace))
    if pointless_tail:
        relations.append(pointless_tail)


def add_dependency(
    relationstr: str,
    relation: Union[str, List[PkgRelation]],
    position: Optional[int] = None,
) -> str:
    """Add a dependency to a depends line.

    Args:
      relationstr: existing relations line
      relation: New relation
      position: Optional position to insert relation at (defaults to last)

    Returns:
      Nothing
    """
    relations = parse_relations(relationstr)
    if isinstance(relation, str):
        relation = parse_relation(relation)
    _add_relation(relations, relation, position=position)
    return format_relations(relations)


def ensure_some_version(relationstr: str, package: str) -> str:
    """Add a package dependency to a depends line if it's not there.

    Args:
      relationstr: existing relations line
      package: Package to add dependency on
    Returns:
      new formatted relation string
    """
    if not isinstance(package, str):
        raise TypeError(package)
    relations = parse_relations(relationstr)
    for _head_whitespace, relation, _tail_whitespace in relations:
        if isinstance(relation, str):  # formatting
            continue
        names = [r.name for r in relation]
        if len(names) > 1 and names[0] == package:
            raise Exception(f"Complex rule for {package} , aborting")
        if names != [package]:
            continue
        return relationstr
    _add_relation(relations, parse_relation(package))
    return format_relations(relations)


def filter_dependencies(
    relations: List[Tuple[str, List[PkgRelation], str]],
    keep: Callable[[List[PkgRelation]], bool],
) -> List[Tuple[str, List[PkgRelation], str]]:
    """Filter out some dependencies.

    Args:
      relations: List of relations
      keep: callback that receives a relation and returns a boolean
    Returns:
      Updated list of relations
    """
    ret = []
    for i, entry in enumerate(relations):
        (head_whitespace, relation, tail_whitespace) = entry
        if isinstance(relation, str):  # formatting
            ret.append(entry)
            continue
        if keep(relation):
            ret.append(entry)
            continue
        elif i == 0 and len(relations) > 1:
            # If the first item is removed, then copy the spacing to the next
            # item
            relations[1] = (head_whitespace, relations[1][1], tail_whitespace)
    return ret


def drop_dependency(relationstr: str, package: str) -> str:
    """Drop a dependency from a depends line.

    Args:
      relationstr: package relation string
      package: package name
    Returns:
      updated relation string
    """
    relations = parse_relations(relationstr)

    def keep(relation: List[PkgRelation]) -> bool:
        names = [r.name for r in relation]
        return set(names) != {package}

    ret = filter_dependencies(relations, keep)
    if relations != ret:
        return format_relations(ret)
    # Just return the original; we don't preserve all formatting yet.
    return relationstr


def delete_from_list(liststr: str, item_to_delete: Union[str, List[str]]) -> str:
    if not item_to_delete:
        raise ValueError(item_to_delete)
    if isinstance(item_to_delete, str):
        items_to_delete = [item_to_delete.strip()]
    elif isinstance(item_to_delete, list):
        items_to_delete = [item.strip() for item in item_to_delete]
    else:
        raise TypeError(item_to_delete)
    items = liststr.split(",")
    for i, item in enumerate(items):
        if item.strip() in items_to_delete:
            deleted_item = items.pop(i)
            head_whitespace = "".join(takewhile(lambda x: x.isspace(), deleted_item))
            if i == 0 and len(items) >= 1:
                # If we're removing the first item, copy its whitespace to the
                # second
                items[i] = head_whitespace + items[i].lstrip()
            elif i == len(items):
                if i > 1:
                    items[i - 1] = items[i - 1].rstrip()
    return ",".join(items)


def is_dep_implied(dep: PkgRelation, outer: PkgRelation) -> bool:
    """Check if one dependency is implied by another.

    Is dep implied by outer?
    """
    if dep.name != outer.name:
        return False
    if not dep.version:
        return True
    if outer.version == dep.version:
        return True
    if not outer.version:
        return False
    if dep.version[0] == ">=":
        if outer.version[0] == ">>":
            return Version(outer.version[1]) > Version(dep.version[1])
        elif outer.version[0] in (">=", "="):
            return Version(outer.version[1]) >= Version(dep.version[1])
        elif outer.version[0] in ("<<", "<="):
            return False
        else:
            raise AssertionError(f"unsupported: {outer.version[0]}")
    elif dep.version[0] == "=":
        if outer.version[0] == "=":
            return Version(outer.version[1]) == Version(dep.version[1])
        else:
            return False
    elif dep.version[0] == "<<":
        if outer.version[0] == "<<":
            return Version(outer.version[1]) <= Version(dep.version[1])
        if outer.version[0] in ("<=", "="):
            return Version(outer.version[1]) < Version(dep.version[1])
        elif outer.version[0] in (">>", ">="):
            return False
        else:
            raise AssertionError(f"unsupported: {outer.version[0]}")
    elif dep.version[0] == "<=":
        if outer.version[0] in ("<=", "=", "<<"):
            return Version(outer.version[1]) <= Version(dep.version[1])
        elif outer.version[0] in (">>", ">="):
            return False
        else:
            raise AssertionError(f"unsupported: {outer.version[0]}")
    elif dep.version[0] == ">>":
        if outer.version[0] == ">>":
            return Version(outer.version[1]) >= Version(dep.version[1])
        elif outer.version[0] in ("=", ">="):
            return Version(outer.version[1]) > Version(dep.version[1])
        elif outer.version[0] in ("<<", "<="):
            return False
        else:
            raise AssertionError(f"unsupported: {outer.version[0]}")
    else:
        raise AssertionError(f"unable to handle checks for {dep.version[0]}")


def is_relation_implied(
    inner: Union[str, List[PkgRelation]], outer: Union[str, List[PkgRelation]]
) -> bool:
    """Check if one relation implies another.

    Args:
      inner: Inner relation
      outer: Outer relation
    Return: boolean
    """
    if isinstance(inner, str):
        inner_rel = parse_relation(inner)
    else:
        inner_rel = inner
    if isinstance(outer, str):
        outer_rel = parse_relation(outer)
    else:
        outer_rel = outer

    if inner_rel == outer_rel:
        return True

    # "bzr >= 1.3" implied by "bzr >= 1.3 | libc6"
    for inner_dep in inner_rel:
        if any(is_dep_implied(inner_dep, outer_dep) for outer_dep in outer_rel):
            return True
    return False


def parse_standards_version(v: str) -> Tuple[int, ...]:
    """Parse a standards version.

    Args:
      v: Version string
    Returns: Tuple with version
    """
    return tuple([int(k) for k in v.split(".")])


def suppress_substvar_warnings() -> None:
    import warnings

    warnings.filterwarnings(
        action="ignore",
        category=UserWarning,
        message=(
            r"cannot parse package relationship \"\$\{.*\}\", returning " r"it raw"
        ),
    )


class PkgRelationFieldEditor:
    """Convenience wrapper for editing pkg relation fields."""

    _parsed: Optional[List[Tuple[str, List[PkgRelation], str]]]

    def __init__(self, paragraph: Deb822Paragraph, name: str) -> None:
        self.paragraph = paragraph
        self.name = name
        self._parsed = None

    def __enter__(self) -> "PkgRelationFieldEditor":
        v = self.paragraph.get(self.name)
        if v is not None:
            self._parsed = parse_relations(v)
        else:
            self._parsed = None

        return self

    def drop_relation(self, package: str) -> bool:
        """Drop a relation.

        Args:
          package: package name
        """
        if self._parsed is None:
            return False

        def keep(relation: List[PkgRelation]) -> bool:
            names = [r.name for r in relation]
            return set(names) != {package}

        new_parsed = filter_dependencies(self._parsed, keep)
        ret = self._parsed != new_parsed
        self._parsed = new_parsed
        return ret

    def __bool__(self) -> bool:
        return self._parsed is not None

    def add_relation(
        self, relation: Union[str, List[PkgRelation]], position: Optional[int] = None
    ) -> None:
        """Add a relation.

        Args:
          relation: New relation
          position: Optional position to insert relation at (defaults to last)
        """
        if isinstance(relation, str):
            relation = parse_relation(relation)
        if not self._parsed:
            self._parsed = []
        return _add_relation(self._parsed, relation, position=position)

    def iter_relations(
        self, package: str
    ) -> Optional[Iterator[Tuple[int, List[PkgRelation]]]]:
        """Iterate over all relations with a particular package.

        Args:
          package: Package name
        Yields:
          Tuples with offset and relation objects
        """
        if self._parsed is None:
            return None
        return _iter_relations(self._parsed, package)

    def get_relation(self, package: str) -> Tuple[int, List[PkgRelation]]:
        """Retrieve the relation for a particular package.

        Args:
          relationstr: package relation string
          package: package name
        Raises:
          ValueError if there is more than one relation with the package
        Returns:
          Tuple with offset and relation object
        """
        iter_result = self.iter_relations(package)
        if iter_result is None:
            raise KeyError(package)
        for offset, relation in iter_result:
            names = [r.name for r in relation]
            if len(names) > 1 and package in names:
                raise ValueError(f"Complex rule for {package} , aborting")
            if names != [package]:
                continue
            return offset, relation
        raise KeyError(package)

    def has_relation(self, package: str) -> bool:
        """Check whether there is a relation with specified package.

        Args:
          package: name of the package
        Returns: boolean
        """
        try:
            self.get_relation(package)
        except KeyError:
            return False
        else:
            return True

    def __exit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc_val: Optional[BaseException],
        exc_tb: Optional[TracebackType],
    ) -> Literal[False]:
        if exc_type is None:
            if self._parsed is None:
                try:
                    del self.paragraph[self.name]
                except KeyError:
                    pass
            else:
                self.paragraph[self.name] = format_relations(self._parsed)
        return False


def format_description(summary: str, long_description: List[str]) -> str:
    """Format a description based on summary and long description lines."""
    return summary + "\n" + "".join([f" {line}\n" for line in long_description])
