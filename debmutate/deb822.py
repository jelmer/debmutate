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

"""Utility functions for dealing with deb822 files."""

__all__ = [
    'dump_paragraphs',
    'reformat_deb822',
    'ChangeConflict',
    'Deb822Editor',
    'parse_deb822_file',
    'Deb822Paragraph',
]

from io import BytesIO
from typing import List, Optional

from debian._deb822_repro.parsing import (
    parse_deb822_file,
    Deb822ParagraphElement as Deb822Paragraph,
    Deb822FileElement as Deb822File,
)

from .reformatting import (
    Editor,
)


# Urgh; this is bad form as a library, but the alternative is
# silently discarding comments.
Deb822Paragraph._discard_comments_on_read = False  # type: ignore


def dump_paragraphs(paragraphs: Deb822File) -> bytes:
    """Dump a set of deb822 paragraphs to a file.

    Args:
      paragraphs: iterable over paragraphs
    Returns:
      formatted text (as bytes)
    """
    outf = BytesIO()
    if hasattr(paragraphs, 'dump'):
        # deb822_repro
        paragraphs.dump(outf)
    else:
        first = True
        for paragraph in paragraphs:
            if paragraph:
                if not first:
                    outf.write(b'\n')
                paragraph.dump(fd=outf)
                first = False
    return outf.getvalue()


def reformat_deb822(contents: bytes) -> bytes:
    """Check whether it's possible to preserve a control file.

    Args:
      contents: Original contents
    Returns:
      New contents
    """
    return dump_paragraphs(parse_deb822_file(BytesIO(contents)))


class ChangeConflict(Exception):
    """Indicates that a proposed change didn't match what was found.
    """

    def __init__(self, para_key, field, expected_old_value, actual_old_value,
                 new_value):
        self.paragraph_key = para_key
        self.field = field
        self.expected_old_value = expected_old_value
        self.actual_old_value = actual_old_value
        self.new_value = new_value

    def __repr__(self):
        return ("%s(para_key=%r, field=%r, expected_old_value=%r, "
                "actual_old_value=%r, new_value=%r)" % (
                    type(self).__name__,
                    self.paragraph_key, self.field, self.expected_old_value,
                    self.actual_old_value, self.new_value))


class Deb822Editor(Editor):
    """Update the contents of a Deb822-style file.

    """

    def __init__(self, path: str, allow_generated: bool = False,
                 allow_reformatting: Optional[bool] = None,
                 allow_missing: bool = False,
                 accept_files_with_error_tokens: bool = False) -> None:
        super(Deb822Editor, self).__init__(
            path, allow_generated=allow_generated,
            allow_reformatting=allow_reformatting,
            mode='b')
        self.allow_missing = allow_missing
        self.accept_files_with_error_tokens = accept_files_with_error_tokens

    def apply_changes(self, changes, resolve_conflict=None):
        """Apply a set of changes to this deb822 instance.

        Args:
          changes: dict mapping paragraph types to
              list of (field_name, old_value, new_value)
            resolve_conflict: callback that receives
                (para_key, field, actual_old_value, template_old_value,
                 actual_new_value) and returns a new template value
        """
        def _default_resolve_conflict(
                para_key, field, actual_old_value,
                template_old_value, actual_new_value):
            raise ChangeConflict(
                para_key, field, actual_old_value, template_old_value,
                actual_new_value)

        if resolve_conflict is None:
            resolve_conflict = _default_resolve_conflict

        changes = dict(changes.items())
        for paragraph in self.paragraphs:
            for item_ in list(paragraph.items()):
                item = (str(item_[0]), str(item_[1]))
                for key, old_value, new_value in changes.pop(item, []):
                    if paragraph.get(key) != old_value:
                        new_value = resolve_conflict(
                            item, key, old_value, paragraph.get(key),
                            new_value)
                    if new_value is None:
                        del paragraph[key]
                    else:
                        paragraph[key] = new_value
        # Add any new paragraphs that weren't processed earlier
        for key, p in changes.items():
            paragraph = Deb822Paragraph.new_empty_paragraph()
            for (field, old_value, new_value) in p:
                if old_value is not None:
                    new_value = resolve_conflict(
                        key, field, old_value, None, new_value)
                if new_value is None:
                    continue
                paragraph[field] = new_value
            self.paragraphs.append(paragraph)

    def _parse(self, content):
        return parse_deb822_file(
            content.splitlines(True),
            accept_files_with_error_tokens=self.accept_files_with_error_tokens)

    @property
    def paragraphs(self) -> List[Deb822Paragraph]:
        return self._parsed

    def _format(self, paragraphs):
        return dump_paragraphs(paragraphs)

    def _nonexistant(self):
        if self.allow_missing:
            return parse_deb822_file([])
        raise

    def sort_paragraphs(self, sort_key, skip=0):
        sortable = list(self.paragraphs)[skip:]
        for i, p in reversed(list(enumerate(self.paragraphs))):
            if i < skip:
                continue
            self.paragraphs.remove(p)
        for p in sorted(sortable, key=sort_key):
            self.paragraphs.append(p)
