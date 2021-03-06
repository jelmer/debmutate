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
    'dh_gnome_clean',
    'pg_buildext_updatecontrol',
    'guess_template_type',
    'ControlEditor',
    'update_control',
    'parse_relations',
    'format_relations',
    'get_relation',
    'iter_relations',
    'ensure_minimum_version',
    'ensure_exact_version',
    'ensure_some_version',
    'filter_dependencies',
    'drop_dependency',
    'delete_from_list',
    'is_dep_implied',
    'is_relation_implied',
    'parse_standards_version',
    ]

import collections
import contextlib
from itertools import takewhile
import os
from typing import Optional, Callable, Tuple, Union, List, Iterable, Dict

from debian.changelog import Version
from debian.deb822 import Deb822
import subprocess
import warnings

from ._deb822 import PkgRelation
from .deb822 import Deb822Editor, ChangeConflict
from .reformatting import GeneratedFile


def parse_relation(t: str):
    with warnings.catch_warnings():
        suppress_substvar_warnings()
        return PkgRelation.parse(t)


def dh_gnome_clean(path: str = '.') -> None:
    """Run the dh_gnome_clean command.

    This needs to do some post-hoc cleaning, since dh_gnome_clean
    writes various debhelper log files that should not be checked in.

    Args:
      path: Path to run dh_gnome_clean in
    """
    for n in os.listdir(os.path.join(path, 'debian')):
        if n.endswith('.debhelper.log'):
            raise AssertionError('pre-existing .debhelper.log files')
    if not os.path.exists(os.path.join(path, 'debian/changelog')):
        raise AssertionError('no changelog file in %s' % path)
    subprocess.check_call(["dh_gnome_clean"], cwd=path)
    for n in os.listdir(os.path.join(path, 'debian')):
        if n.endswith('.debhelper.log'):
            os.unlink(os.path.join(path, 'debian', n))


def pg_buildext_updatecontrol(path: str = '.') -> None:
    """Run the 'pg_buildext updatecontrol' command.

    Args:
      path: path to run pg_buildext updatecontrol in
    """
    subprocess.check_call(["pg_buildext", "updatecontrol"], cwd=path)


def guess_template_type(template_path: str) -> Optional[str]:
    """Guess the type for a control template.

    Args:
      template_path: Template path
    Returns:
      Name of template type; None if unknown
    """
    # TODO(jelmer): This should use a proper make file parser of some sort..
    try:
        with open('debian/rules', 'rb') as f:
            for line in f:
                if line.startswith(b'debian/control:'):
                    return 'rules'
                if line.startswith(b'debian/%: debian/%.in'):
                    return 'rules'
    except FileNotFoundError:
        pass
    try:
        with open(template_path, 'rb') as f:
            template = f.read()
            if b'@GNOME_TEAM@' in template:
                return 'gnome'
            elif b'@cdbs@' in template:
                return 'cdbs'
            elif b'PGVERSION' in template:
                return 'postgresql'
            elif b'@lintian-brush-test@' in template:
                return 'lintian-brush-test'
            else:
                deb822 = Deb822(template)
                build_depends = deb822.get('Build-Depends', '')
                if any(iter_relations(build_depends, 'gnome-pkg-tools')):
                    return 'gnome'
                if any(iter_relations(build_depends, 'cdbs')):
                    return 'cdbs'
    except IsADirectoryError:
        return 'directory'
    if os.path.exists('debian/debcargo.toml'):
        return 'debcargo'
    return None


def _cdbs_resolve_conflict(
        para_key: str,
        field: str,
        actual_old_value: Optional[str],
        template_old_value: Optional[str],
        actual_new_value: Optional[str]
        ) -> Optional[str]:
    if (para_key[0] == 'Source' and field == 'Build-Depends' and
            template_old_value is not None and
            actual_old_value is not None and
            actual_new_value is not None):
        if actual_old_value in actual_new_value:
            # We're simply adding to the existing list
            return actual_new_value.replace(
                actual_old_value, template_old_value)
        else:
            existing = [v[1] for v in parse_relations(actual_old_value)]
            ret = template_old_value
            for _, v, _ in parse_relations(actual_new_value):
                if any(is_relation_implied(v, r) for r in existing):
                    continue
                ret = ensure_relation(ret, v)
            return ret
    raise ChangeConflict(
        para_key, field, actual_old_value, template_old_value,
        actual_new_value)


def _update_control_template(template_path: str, path: str, changes):
    package_root = os.path.dirname(os.path.dirname(path)) or '.'
    template_type = guess_template_type(template_path)
    if template_type is None:
        raise GeneratedFile(path, template_path)
    with Deb822Editor(template_path) as updater:
        resolve_conflict: Optional[Callable[[
            str, str, Optional[str], Optional[str], Optional[str]],
            Optional[str]]]
        if template_type == 'cdbs':
            resolve_conflict = _cdbs_resolve_conflict
        else:
            resolve_conflict = None
        updater.apply_changes(changes, resolve_conflict=resolve_conflict)
    if not updater.changed:
        # A bit odd, since there were changes to the output file. Anyway.
        return False
    if template_type == 'rules':
        subprocess.check_call(
            ['./debian/rules', 'debian/control'],
            cwd=package_root)
    elif template_type == 'cdbs':
        with Deb822Editor(path, allow_generated=True) as updater:
            updater.apply_changes(changes)
    elif template_type == 'gnome':
        dh_gnome_clean(package_root)
    elif template_type == 'postgresql':
        pg_buildext_updatecontrol(package_root)
    elif template_type == 'lintian-brush-test':
        with open(template_path, 'rb') as inf, open(path, 'wb') as outf:
            outf.write(
                inf.read().replace(b'@lintian-brush-test@', b'testvalue'))
    elif template_type == 'directory':
        raise GeneratedFile(path, template_path)
    else:
        raise AssertionError
    return True


@contextlib.contextmanager
def _preserve_field_order_preferences(paragraphs):
    description_is_not_last = set()
    for para in paragraphs:
        if 'Package' not in para:
            continue
        if list(para) and list(para)[-1] != 'Description':
            description_is_not_last.add(para['Package'])
    yield
    for para in paragraphs:
        if 'Package' not in para:
            continue
        if para['Package'] not in description_is_not_last:
            # Make sure Description stays the last field
            para._Deb822Dict__keys.add('Description')
            para._Deb822Dict__keys.remove('Description')


def update_control(path='debian/control', source_package_cb=None,
                   binary_package_cb=None):
    def paragraph_cb(paragraph):
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


class ControlEditor(object):
    """Edit a control file.
    """

    changed: bool

    def __init__(self, path: str = 'debian/control',
                 allow_reformatting: Optional[bool] = None):
        self.path = path
        self._primary = Deb822Editor(
            path, allow_reformatting=allow_reformatting)

    @classmethod
    def from_tree(cls, tree, subpath=None):
        relpath = 'debian/control'
        if subpath not in (None, '.', ''):
            relpath = os.path.join(subpath, relpath)
        return cls(tree.abspath(relpath))

    @property
    def paragraphs(self) -> List[Deb822]:
        """List of all the paragraphs."""
        return self._primary.paragraphs

    @property
    def source(self) -> Deb822:
        """Source package."""
        if not self._primary.paragraphs[0].get('Source'):
            raise ValueError('first paragraph is not Source')
        return self._primary.paragraphs[0]

    @property
    def binaries(self) -> List[Deb822]:
        """List of binary packages."""
        return self._primary.paragraphs[1:]

    def changes(self):
        """Return a dictionary describing the changes since the base.

        Returns:
          dictionary mapping tuples of (kind, name) to
            list of (field_name, old_value, new_value)
        """
        orig = self._primary._parse(self._primary._orig_content)
        changes = {}

        def by_key(ps):
            ret = {}
            for p in ps:
                if not p:
                    continue
                if 'Source' in p:
                    ret[('Source', p['Source'])] = p
                else:
                    ret[('Package', p['Package'])] = p
            return ret

        orig_by_key = by_key(orig)
        new_by_key = by_key(self.paragraphs)
        for key in set(orig_by_key).union(set(new_by_key)):
            old = orig_by_key.get(key, {})
            new = new_by_key.get(key, {})
            if old == new:
                continue
            fields = list(old)
            fields.extend([field for field in new if field not in fields])
            for field in fields:
                if old.get(field) != new.get(field):
                    changes.setdefault(key, []).append(
                        (field, old.get(field), new.get(field)))
        return changes

    def __enter__(self):
        self._primary.__enter__()
        self._field_order_preserver = _preserve_field_order_preferences(
            self._primary.paragraphs)
        self._field_order_preserver.__enter__()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self._field_order_preserver.__exit__(exc_type, exc_val, exc_tb)
        try:
            self._primary.__exit__(exc_type, exc_val, exc_tb)
        except GeneratedFile as e:
            if not e.template_path:
                raise
            self.changed = _update_control_template(
                e.template_path, self.path, self.changes())
        except FileNotFoundError:
            for template_path in [self.path + '.in', self.path + '.m4']:
                if os.path.exists(template_path):
                    self.changed = _update_control_template(
                        template_path, self.path, self.changes())
                    break
            else:
                raise
        else:
            self.changed = self._primary.changed
        return False


def parse_relations(text: str):
    """Parse a package relations string.

    (e.g. a Depends, Provides, Build-Depends, etc field)

    This attemps to preserve some indentation.

    Args:
      text: Text to parse
    Returns: list of tuples with (whitespace, relation, whitespace)
    """
    ret: List[Tuple[str, List[PkgRelation], str]] = []
    for top_level in text.split(','):
        if top_level == "":
            if ',' not in text:
                return []
        if top_level.isspace():
            ret.append((top_level, [], ''))
            continue
        head_whitespace = ''
        for i in range(len(top_level)):
            if not top_level[i].isspace():
                if i > 0:
                    head_whitespace = top_level[:i]
                top_level = top_level[i:]
                break
        tail_whitespace = ''
        for i in range(len(top_level)):
            if not top_level[-(i+1)].isspace():
                if i > 0:
                    tail_whitespace = top_level[-i:]
                    top_level = top_level[:-i]
                break
        ret.append((head_whitespace, parse_relation(top_level),
                    tail_whitespace))
    return ret


def format_relations(
        relations: List[Tuple[str, List[PkgRelation], str]]) -> str:
    """Format a package relations string.

    This attemps to create formatting.
    """
    ret = []
    for (head_whitespace, relation, tail_whitespace) in relations:
        ret.append(head_whitespace + ' | '.join(o.str() for o in relation) +
                   tail_whitespace)
    # The first line can be whitespace only, the subsequent ones can not
    lines = []
    for i, line in enumerate(','.join(ret).split('\n')):
        if i == 0:
            lines.append(line)
        else:
            if line.strip():
                lines.append(line)
    return '\n'.join(lines)


def get_relation(
        relationstr: str, package: str) -> Tuple[int, List[PkgRelation]]:
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
            raise ValueError("Complex rule for %s , aborting" % package)
        if names != [package]:
            continue
        return offset, relation
    raise KeyError(package)


def iter_relations(
        relationstr: str,
        package: str) -> Iterable[Tuple[int, List[PkgRelation]]]:
    """Iterate over the relations relevant for a particular package.

    Args:
      relationstr: package relation string
      package: package name
    Yields:
      Tuples with offset and relation objects
    """
    relations = parse_relations(relationstr)
    for i, (head_whitespace, relation, tail_whitespace) in enumerate(
            relations):
        if isinstance(relation, str):  # formatting
            continue
        names = [r.name for r in relation]
        if package not in names:
            continue
        yield i, relation


def ensure_minimum_version(
        relationstr: str, package: str,
        minimum_version: Union[str, Version]) -> str:
    """Update a relation string to ensure a particular version is required.

    Args:
      relationstr: package relation string
      package: package name
      minimum_version: Minimum version
    Returns:
      updated relation string
    """
    def is_obsolete(relation):
        for r in relation:
            if r.name != package:
                continue
            if r.version[0] == '>>' and r.version[1] < minimum_version:
                return True
            if r.version[0] == '>=' and r.version[1] <= minimum_version:
                return True
        return False

    minimum_version = Version(minimum_version)
    found = False
    changed = False
    relations = parse_relations(relationstr)
    obsolete_relations = []
    for i, (head_whitespace, relation, tail_whitespace) in enumerate(
            relations):
        if isinstance(relation, str):  # formatting
            continue
        names = [r.name for r in relation]
        if len(names) > 1 and package in names and is_obsolete(relation):
            obsolete_relations.append(i)
        if names != [package]:
            continue
        found = True
        if (relation[0].version is None or
                Version(relation[0].version[1]) < minimum_version):
            relation[0].version = ('>=', minimum_version)
            changed = True
    if not found:
        changed = True
        _add_dependency(
            relations,
            [PkgRelation(name=package, version=('>=', minimum_version))])
    for i in reversed(obsolete_relations):
        del relations[i]
    if changed:
        return format_relations(relations)
    # Just return the original; we don't preserve all formatting yet.
    return relationstr


def ensure_exact_version(
        relationstr: str, package: str,
        version: Union[str, Version], position: Optional[int] = None) -> str:
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
    for (head_whitespace, relation, tail_whitespace) in relations:
        if isinstance(relation, str):  # formatting
            continue
        names = [r.name for r in relation]
        if len(names) > 1 and names[0] == package:
            raise Exception("Complex rule for %s , aborting" % package)
        if names != [package]:
            continue
        found = True
        if (relation[0].version is None or
                (relation[0].version[0],
                 Version(relation[0].version[1])) != ('=', version)):
            relation[0].version = ('=', version)
            changed = True
    if not found:
        changed = True
        _add_dependency(
            relations,
            [PkgRelation(name=package, version=('=', version))],
            position=position)
    if changed:
        return format_relations(relations)
    # Just return the original; we don't preserve all formatting yet.
    return relationstr


def ensure_relation(
        relationstr: str, new_relationstr: Union[str, List[PkgRelation]],
        position: Optional[int] = None) -> str:
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
    for i, (head_whitespace, relation, tail_whitespace) in enumerate(
            relations):
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
        _add_dependency(relations, new_relation)

    for i in reversed(to_remove):
        del relations[i]

    return format_relations(relations)


def _add_dependency(
        relations: List[Tuple[str, List[PkgRelation], str]],
        relation: List[PkgRelation],
        position: Optional[int] = None) -> None:
    """Add a dependency to a depends line.

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
        head_whitespace = ''
        tail_whitespace = ''
    elif len(relations) == 1:
        head_whitespace = (relations[0][0] or " ")  # Best guess
        tail_whitespace = ''
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
        raise IndexError('position out of bounds: %r' % position)

    if position == len(relations):
        if len(relations) == 0:
            last_tail_whitespace = ''
        else:
            last_tail_whitespace = relations[-1][2]
            relations[-1] = relations[-1][:2] + (tail_whitespace, )
        relations.append((head_whitespace, relation, last_tail_whitespace))
    elif position == 0:
        relations.insert(
            position, (relations[0][0], relation, tail_whitespace))
        relations[1] = (head_whitespace, relations[1][1], relations[1][2])
    else:
        relations.insert(
            position, (head_whitespace, relation, tail_whitespace))
    if pointless_tail:
        relations.append(pointless_tail)


def add_dependency(relationstr, relation, position=None):
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
    _add_dependency(relations, relation, position=position)
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
    for (head_whitespace, relation, tail_whitespace) in relations:
        if isinstance(relation, str):  # formatting
            continue
        names = [r.name for r in relation]
        if len(names) > 1 and names[0] == package:
            raise Exception("Complex rule for %s , aborting" % package)
        if names != [package]:
            continue
        return relationstr
    _add_dependency(relations, parse_relation(package))
    return format_relations(relations)


def filter_dependencies(
        relations: List[Tuple[str, List[PkgRelation], str]],
        keep: Callable[[List[PkgRelation]], bool]
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

    def keep(relation):
        names = [r.name for r in relation]
        return set(names) != set([package])
    ret = filter_dependencies(relations, keep)
    if relations != ret:
        return format_relations(ret)
    # Just return the original; we don't preserve all formatting yet.
    return relationstr


def delete_from_list(liststr: str, item_to_delete: str) -> str:
    if not item_to_delete:
        raise ValueError(item_to_delete)
    if isinstance(item_to_delete, str):
        items_to_delete = [item_to_delete.strip()]
    elif isinstance(item_to_delete, list):
        items_to_delete = [item.strip() for item in item_to_delete]
    else:
        raise TypeError(item_to_delete)
    items = liststr.split(',')
    for i, item in enumerate(items):
        if item.strip() in items_to_delete:
            deleted_item = items.pop(i)
            head_whitespace = ''.join(
                takewhile(lambda x: x.isspace(), deleted_item))
            if i == 0 and len(items) >= 1:
                # If we're removing the first item, copy its whitespace to the
                # second
                items[i] = head_whitespace + items[i].lstrip()
            elif i == len(items):
                if i > 1:
                    items[i-1] = items[i-1].rstrip()
    return ','.join(items)


def is_dep_implied(dep: PkgRelation, outer: PkgRelation) -> bool:
    """Check if one dependency is implied by another.
    """
    if dep.name != outer.name:
        return False
    if not dep.version:
        return True
    if outer.version == dep.version:
        return True
    if not outer.version:
        return False
    if dep.version[0] == '>=':
        if outer.version[0] == '>>':
            return Version(outer.version[1]) > Version(dep.version[1])
        elif outer.version[0] in ('>=', '='):
            return Version(outer.version[1]) >= Version(dep.version[1])
        elif outer.version[0] in ('<<', '<='):
            return False
        else:
            raise AssertionError('unsupported: %s' % outer.version[0])
    elif dep.version[0] == '=':
        if outer.version[0] == '=':
            return Version(outer.version[1]) == Version(dep.version[1])
        else:
            return False
    elif dep.version[0] == '<<':
        if outer.version[0] == '<<':
            return Version(outer.version[1]) <= Version(dep.version[1])
        if outer.version[0] in ('<=', '='):
            return Version(outer.version[1]) < Version(dep.version[1])
        elif outer.version[0] in ('>>', '>='):
            return False
        else:
            raise AssertionError('unsupported: %s' % outer.version[0])
    elif dep.version[0] == '<=':
        if outer.version[0] in ('<=', '=', '<<'):
            return Version(outer.version[1]) <= Version(dep.version[1])
        elif outer.version[0] in ('>>', '>='):
            return False
        else:
            raise AssertionError('unsupported: %s' % outer.version[0])
    else:
        raise AssertionError('unable to handle checks for %s' % dep.version[0])


def is_relation_implied(
        inner: Union[str, List[PkgRelation]],
        outer: Union[str, List[PkgRelation]]) -> bool:
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
        if all(is_dep_implied(inner_dep, outer_dep)
               for outer_dep in outer_rel):
            return True
    return False


def parse_standards_version(v: str) -> Tuple[int, ...]:
    """Parse a standards version.

    Args:
      v: Version string
    Returns: Tuple with version
    """
    return tuple([int(k) for k in v.split('.')])


def suppress_substvar_warnings():
    import warnings
    warnings.filterwarnings(
        action='ignore',
        category=UserWarning,
        message=(r'cannot parse package relationship \"\$\{.*\}\", returning '
                 r'it raw'))
