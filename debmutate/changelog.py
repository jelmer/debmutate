#!/usr/bin/python3
# Copyright (C) 2019-2020 Jelmer Vernooij
#
# find_extra_authors and find_thanks originally imported from
# breezy-debian and (C) 2006 James Westby
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

"""Utility functions for dealing with changelog files."""

__all__ = [
    'ChangelogParseError',
    'ChangelogCreateError',
    'ChangelogEditor',
    'changes_sections',
    'changes_by_author',
    'changelog_add_entry',
    'changeblock_add_line',
    'changeblock_ensure_first_line',
    'all_sha_prefixed',
    'any_long_lines',
    'find_extra_authors',
    'find_thanks',
    'rewrap_change',
    'strip_changelog_message',
    'new_changelog_entries',
    'is_unreleased_inaugural',
    'upstream_merge_changelog_line',
    ]

from datetime import datetime
from email.utils import format_datetime, parseaddr
import re
import textwrap
from typing import List, Iterator, Tuple, Optional

from debian.changelog import (
    ChangeBlock,
    Changelog,
    ChangelogCreateError,
    ChangelogParseError,
    format_date,
    get_maintainer,
    Version,
    )
from .reformatting import Editor

WIDTH = 80
INITIAL_INDENT = '  * '


class ChangelogEditor(Editor):
    """Update a changelog file.

    This will only write out the changelog file if it has been changed.
    """

    def __init__(
            self, path: str = 'debian/changelog',
            allow_reformatting: Optional[bool] = False,
            allow_missing: bool = False):
        super(ChangelogEditor, self).__init__(
            path, allow_reformatting=allow_reformatting)
        self.allow_missing = allow_missing

    @classmethod
    def create(cls, path: str = 'debian/changelog'):
        return cls(path, allow_reformatting=True, allow_missing=True)

    def _parse(self, content):
        cl = Changelog()
        cl.parse_changelog(
            content, max_blocks=None, allow_empty_author=True, strict=False)
        return cl

    def _format(self, parsed):
        return parsed._format(allow_missing_author=True)

    @property
    def changelog(self):
        return self._parsed

    def __getitem__(self, i):
        return self.changelog[i]

    def _nonexistant(self):
        if self.allow_missing:
            return Changelog()
        raise

    def new_block(self, *args, **kwargs):
        return self.changelog.new_block(*args, **kwargs)

    def auto_version(self, version, **kwargs):
        return changelog_auto_version(
            self.changelog, version=version, **kwargs)

    def add_entry(
            self,
            summary: List[str],
            maintainer: Optional[Tuple[str, str]] = None,
            timestamp: Optional[datetime] = None,
            urgency: str = 'low') -> None:
        return changelog_add_entry(
            self.changelog, summary=summary, maintainer=maintainer,
            timestamp=timestamp, urgency=urgency)


def changelog_auto_version(
        cl: Changelog, version: Version,
        maintainer: Optional[Tuple[str, str]] = None,
        timestamp: Optional[datetime] = None,
        package: Optional[str] = None,
        urgency: str = 'low'):
    """Update current changelog entry to version or create a new one.
    """
    if maintainer is None:
        maintainer_name, maintainer_email = get_maintainer()
    else:
        maintainer_name, maintainer_email = maintainer
    if maintainer_name is None or maintainer_email is None:
        raise ValueError(
            'unable to determine maintainer details and none specified')
    if package is None:
        package = cl[0].package
    if timestamp is None:
        timestamp = datetime.now()
    if len(cl) > 0 and distribution_is_unreleased(cl[0].distributions):
        cl[0].version = version
        cl[0].date = format_datetime(timestamp)
        cl[0].package = package
        # TODO(jelmer): Also set maintainer again?
    else:
        cl.new_block(
            version=version, package=package,
            distributions='UNRELEASED', urgency=urgency,
            author="%s <%s>" % (maintainer_name, maintainer_email),
            date=format_datetime(timestamp))


def changes_sections(
        changes: List[str]
        ) -> Iterator[
            Tuple[Optional[str], List[int], List[List[Tuple[int, str]]]]
        ]:
    """Return the different sections from a set of changelog entries.

    Args:
      changes: list of changes from a changelog entry
    Returns:
      iterator over tuples with:
        (author, list of line numbers, list of list of (lineno, line) tuples
    """
    section: Tuple[
        Optional[str], List[int],
        List[List[Tuple[int, str]]]] = (None, [], [])
    change: List[Tuple[int, str]] = []
    for i, line in enumerate(changes):
        if not line and i == 0:
            # Skip the first line
            continue
        if not line:
            section[1].append(i)
            continue
        m = re.fullmatch(r'  \[ (.*) \]', line)
        if m:
            if change:
                section[2].append(change)
                change = []
            if section[1]:
                yield section
            section = (m.group(1), [i], [])
            continue
        if not line.startswith(INITIAL_INDENT):
            change.append((i, line))
            section[1].append(i)
        else:
            if change:
                section[2].append(change)
            change = [(i, line)]
            section[1].append(i)
    if change:
        section[2].append(change)
    if section[1]:
        yield section


def changes_by_author(
        changes: List[str]
        ) -> Iterator[Tuple[Optional[str], List[int], List[str]]]:
    """Changes by author.

    Args:
      changes: Find changes by author from a list of lines
    Returns:
      Iterator over items by author (maintainer, offsets, changes)
    """
    for (author, linenos, contents) in changes_sections(changes):
        for change_entries in contents:
            change_linenos, change_lines = zip(*change_entries)
            yield (author, change_linenos, change_lines)  # type: ignore


class TextWrapper(textwrap.TextWrapper):

    whitespace = r'[%s]' % re.escape('\t\n\x0b\x0c\r ')
    wordsep_simple_re = re.compile(r'(%s+)' % whitespace)

    def __init__(self, initial_indent=INITIAL_INDENT):
        super(TextWrapper, self).__init__(
            width=WIDTH, initial_indent=initial_indent,
            subsequent_indent=' ' * len(initial_indent),
            break_long_words=False, break_on_hyphens=False)

    def _split(self, text):
        chunks = [c for c in self.wordsep_simple_re.split(text) if c]
        ret = []
        i = 0
        while i < len(chunks):
            if (any(chunks[i].endswith(x) for x in ['Closes:', 'LP:']) and
                    i+2 < len(chunks) and chunks[i+2].startswith('#')):
                ret.append('%s %s' % (chunks[i], chunks[i+2]))
                i += 3
            else:
                ret.append(chunks[i])
                i += 1
        return ret


_initial_re = re.compile(r'^[  ]+[\+\-\*] ')


def _can_join(line1, line2):
    if line1.endswith(':'):
        return False
    if line2 and line2[:1].isupper():
        if line1.endswith(']') or line1.endswith('}'):
            return False
        if not line1.endswith('.'):
            return False
    return True


def any_long_lines(lines: List[str], width: int = WIDTH) -> bool:
    """Check if any lines are longer than the specified width.
    """
    return any([len(line) > width for line in lines])


def rewrap_change(change: List[str]) -> List[str]:
    """Rewrap lines from a list of changes.

    Args:
      change: List of lines
    Returns:
      new list of lines
    """
    if not change:
        return change
    m = _initial_re.match(change[0])
    if not any_long_lines(change) or not m:
        return change
    wrapper = TextWrapper(m.group(0))
    prefix_len = len(m.group(0))
    lines = [line[prefix_len:] for line in change]
    todo = [lines[0]]
    ret = []
    for i in range(len(lines) - 1):
        if _can_join(lines[i], lines[i+1]) and any_long_lines(
                todo, WIDTH-prefix_len):
            todo.append(lines[i+1])
        else:
            ret.extend(wrapper.wrap('\n'.join(todo)))
            wrapper = TextWrapper(change[i+1][:len(m.group(0))])
            todo = [lines[i+1]]
    ret.extend(wrapper.wrap('\n'.join(todo)))
    return ret


def rewrap_changes(changes: Iterator[str]) -> Iterator[str]:
    change: List[str] = []
    indent = None
    for line in changes:
        m = _initial_re.match(line)
        if m:
            yield from rewrap_change(change)
            change = [line]
            indent = len(m.group(0))
        elif change and line.startswith(' ' * indent):  # type: ignore
            change.append(line)
        else:
            yield from rewrap_change(change)
            change = []
            yield line


def _inc_version(version: Version) -> Version:
    """Increment a Debian version string."""
    ret = Version(str(version))
    # TODO(jelmer): Add ubuntuX suffix on Ubuntu
    if ret.debian_revision:
        # Non-native package
        m = re.match('^(.*?)([0-9]+)$', ret.debian_revision)
        if m:
            ret.debian_revision = m.group(1) + str(int(m.group(2))+1)
        else:
            ret.debian_revision += "1"
        return ret
    elif ret.upstream_version:
        # Native package
        m = re.match('^(.*?)([0-9]+)$', ret.upstream_version)
        if m:
            ret.upstream_version = m.group(1) + str(int(m.group(2))+1)
        else:
            ret.upstream_version += "1"
        return ret
    else:
        # Uhm..
        raise ValueError(ret)


def changelog_add_entry(
        cl: Changelog, summary: List[str],
        maintainer: Optional[Tuple[str, str]] = None,
        timestamp: Optional[datetime] = None,
        urgency: str = 'low') -> None:
    """Add an entry to a changelog.

    Args:
      cl: Changelog object to modify
      summary: List of lines
      maintainer: maintainer identity to use (defaults to get_maintainer())
      timestamp: Timestamp to set for new entries
      urgency: Urgency to use for new items
    Raises:
      ValueError: when the maintainer details can not be found and were not
        specified
    """
    if timestamp is None:
        timestamp = datetime.now()
    if maintainer is None:
        maintainer_name, maintainer_email = get_maintainer()
    else:
        maintainer_name, maintainer_email = maintainer
    if maintainer_name is None or maintainer_email is None:
        raise ValueError(
            'unable to determine maintainer details and none specified')
    if (distribution_is_unreleased(cl[0].distributions) or (
                cl[0].author is None and cl[0].date is None)):
        by_author = list(changes_by_author(cl[0].changes()))
        if cl[0]._changes == []:
            cl[0]._changes.append('')
        if all([author is None for (author, linenos, change) in by_author]):
            if cl[0].author is not None:
                entry_maintainer = parseaddr(cl[0].author)
                if entry_maintainer != (maintainer_name, maintainer_email):
                    cl[0]._changes.insert(1, '  [ %s ]' % entry_maintainer[0])
                    if cl[0]._changes[-1]:
                        cl[0]._changes.append('')
                    cl[0]._changes.append('  [ %s ]' % maintainer_name)
        else:
            if by_author[-1][0] != maintainer_name:
                if cl[0]._changes[-1]:
                    cl[0]._changes.append('')
                cl[0]._changes.append('  [ %s ]' % maintainer_name)
        if len(cl[0] ._changes) > 1 and not cl[0]._changes[-1].strip():
            del cl[0]._changes[-1]
    else:
        cl.new_block(
            package=cl[0].package,
            version=_inc_version(cl[0].version),
            urgency=urgency,
            author="%s <%s>" % (maintainer_name, maintainer_email),
            date=format_datetime(timestamp),
            distributions='UNRELEASED',
            changes=[''])
    changeblock_add_line(cl[0], summary)


def changeblock_add_line(block, lines):
    wrapper = TextWrapper(INITIAL_INDENT)
    block._changes.extend(wrapper.wrap(lines[0]))
    for line in lines[1:]:
        prefix = len(INITIAL_INDENT) * ' '
        m = re.match(r'^[  ]*[\+\-\*] ', line)
        if m:
            prefix += m.group(0)
            line = line[len(m.group(0)):]
        block._changes.extend(TextWrapper(prefix).wrap(line))
    block._changes.append('')


def strip_changelog_message(changes: List[str]) -> List[str]:
    """Strip a changelog message like debcommit does.

    Takes a list of changes from a changelog entry and applies a transformation
    so the message is well formatted for a commit message.

    :param changes: a list of lines from the changelog entry
    :return: another list of lines with blank lines stripped from the start
        and the spaces the start of the lines split if there is only one
        logical entry.
    """
    if not changes:
        return changes
    while changes and changes[-1] == '':
        changes.pop()
    while changes and changes[0] == '':
        changes.pop(0)

    whitespace_column_re = re.compile(r'  |\t')
    changes = [whitespace_column_re.sub('', line, 1) for line in changes]

    leader_re = re.compile(r'[ \t]*[*+-] ')
    count = len([line for line in changes if leader_re.match(line)])
    if count == 1:
        return [leader_re.sub('', line, 1).lstrip() for line in changes]
    else:
        return changes


def new_changelog_entries(
        old_text: List[bytes], new_text: List[bytes]) -> List[str]:
    import difflib
    sequencematcher = difflib.SequenceMatcher
    changes = []
    for group in sequencematcher(
            None, old_text, new_text).get_grouped_opcodes(0):
        j1, j2 = group[0][3], group[-1][4]
        for line in new_text[j1:j2]:
            if line.startswith(b"  "):
                # Debian Policy Manual states that debian/changelog must be
                # UTF-8
                changes.append(line.decode('utf-8'))
    return changes


def new_upstream_package_version(
        upstream_version: str, distribution_name: str,
        epoch: Optional[str] = None) -> Version:
    """Determine the package version for a new upstream.

    Args:
      upstream_version: Upstream version string
      distribution_name: Distribution the package is for
      epoch: Optional epoch
    Returns:
      The new version
    """
    if distribution_name == "ubuntu":
        ret = Version("%s-0ubuntu1" % upstream_version)
    else:
        ret = Version("%s-1" % upstream_version)
    ret.epoch = epoch
    return ret


def all_sha_prefixed(cb: ChangeBlock) -> bool:
    """Check if all lines in a changelog entry are prefixed with a sha.

    This is generally done by gbp-dch(1).

    Args:
      cl: Changelog entry
    Returns: bool
    """
    sha_prefixed = 0
    for change in cb.changes():
        if not change.startswith('  * '):
            continue
        if re.match(r'  \* \[[0-9a-f]{7}\] ', change):
            sha_prefixed += 1
        else:
            return False
    return (sha_prefixed > 0)


def distribution_is_unreleased(distribution):
    return (
        distribution == 'UNRELEASED' or
        distribution.startswith('UNRELEASED-'))


def changeblock_ensure_first_line(block, line, maintainer=None):
    """Ensure that the first line matches the specified line.
    """
    if maintainer is None:
        maintainer_name, maintainer_email = get_maintainer()
    else:
        maintainer_name, maintainer_email = maintainer
    if maintainer_name is None or maintainer_email is None:
        raise ValueError(
            'unable to determine maintainer details and none specified')
    if block._changes[0]:
        raise ValueError('first block line not empty')
    line = '  * ' + line
    if block._changes[1] == line:
        return
    block._changes.insert(1, line)
    if block._changes[2].startswith('  ['):
        block._changes.insert(2, '')
    elif parseaddr(block.author)[0] != maintainer_name:
        block._changes.insert(2, '  [ %s ]' % parseaddr(block.author)[0])
        block._changes.insert(2, '')
        block.author = "%s <%s>" % (maintainer_name, maintainer_email)


def release(cl, distribution="unstable", timestamp=None, localtime=True):
    """Create a release for a changelog file.
    """
    if distribution_is_unreleased(cl[0].distributions):
        cl[0].distributions = distribution
        cl[0].date = format_date(timestamp=timestamp, localtime=localtime)


def find_last_distribution(changelog):
    """Find the last changelog that was used in a changelog.

    This will skip stanzas with the 'UNRELEASED' distribution.

    Args:
      changelog: Changelog to analyze
    """
    for block in changelog._blocks:
        distribution = block.distributions.split(" ")[0]
        if not distribution_is_unreleased(distribution):
            return distribution
    return None


def find_extra_authors(changes):
    """Find additional authors from a changelog entry.

    :return: List of fullnames of additional authors, without e-mail address.
    """
    authors = []
    for new_author, linenos, lines in changes_by_author(changes):
        if new_author is None:
            continue
        already_included = False
        for author in authors:
            if author.startswith(new_author):
                already_included = True
                break
        if not already_included:
            authors.append(new_author)
    return authors


def find_thanks(changes):
    """Find all people thanked in a changelog entry.

    :param changes: String with the contents of the changelog entry
    :return: List of people thanked, optionally including email address.
    """
    thanks_re = re.compile(
        r"[tT]hank(?:(?:s)|(?:you))(?:\s*to)?"
        "((?:\\s+(?:(?:\\w\\.)|(?:\\w+(?:-\\w+)*)))+"
        "(?:\\s+<[^@>]+@[^@>]+>)?)",
        re.UNICODE)
    thanks = []
    for new_author, linenos, lines in changes_by_author(changes):
        for match in thanks_re.finditer(''.join(lines)):
            if thanks is None:
                thanks = []
            thanks_str = match.group(1).strip()
            thanks_str = re.sub(r"\s+", " ", thanks_str)
            thanks.append(thanks_str)
    return thanks


def upstream_merge_changelog_line(upstream_version: str) -> str:
    """Describe that a new upstream revision was merged.

    This will either describe that a new upstream release or a new upstream
    snapshot was merged.

    Args:
      upstream_version: Upstream version string
    Returns:
       line string for use in changelog
    """
    vcs_suffixes = ["~bzr", "+bzr", "~svn", "+svn", "~git", "+git", "-git"]
    for vcs_suffix in vcs_suffixes:
        if vcs_suffix in str(upstream_version):
            entry_description = "New upstream snapshot."
            break
    else:
        entry_description = "New upstream release."
    return entry_description


def is_unreleased_inaugural(cl: Changelog) -> bool:
    """Check whether this is a traditional inaugural release.

    Args:
      cl: A changelog object to inspect
    """
    if cl is None:
        return False
    if len(cl) != 1:
        return False
    if not distribution_is_unreleased(cl[0].distributions):
        return False
    actual = [change for change in cl[0].changes() if change.strip()]
    if len(actual) != 1:
        return False
    if not actual[0].startswith('  * Initial release'):
        return False
    return True


def gbp_dch(path: str) -> None:
    """Run 'gbp dch'."""
    import os
    from gbp.scripts.dch import main
    old_cwd = os.getcwd()
    try:
        os.chdir(path)
        main(['gbp-dch', '--ignore-branch'])
    finally:
        os.chdir(old_cwd)
