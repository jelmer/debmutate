#!/usr/bin/python3
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

"""Utility functions for dealing with rules files."""

import os
import re
from typing import Callable, Iterator, List, Optional, Union

from .reformatting import Editor


def wildcard_to_re(wildcard: str) -> re.Pattern[str]:
    wc = []
    for c in wildcard:
        if c == "%":
            wc.append(".*")
        else:
            wc.append(re.escape(c))
    return re.compile("".join(wc))


def matches_wildcard(text: str, wildcard: str) -> bool:
    wc = wildcard_to_re(wildcard)
    return bool(wc.fullmatch(text))


class Rule:
    """A make rule."""

    target: Optional[bytes]
    prereq_targets: List[bytes]
    precomment: List[bytes]

    def __init__(
        self,
        target: Optional[bytes] = None,
        commands: Optional[List[bytes]] = None,
        prereq_targets: Optional[List[bytes]] = None,
        precomment: Optional[List[bytes]] = None,
    ):
        self.precomment = precomment or []
        self.target = target
        self.components = prereq_targets or []
        if self.components:
            self._component_str = b" " + b" ".join(self.components)
        else:
            self._component_str = b""
        if target:
            self.lines = [b"%s:%s" % (target, self._component_str)] + [
                b"\t" + cmd for cmd in (commands or [])
            ]
        else:
            self.lines = []

    @classmethod
    def _from_first_line(
        cls, firstline: bytes, precomment: Optional[List[bytes]] = None
    ) -> "Rule":
        self = cls(precomment=precomment)
        self.lines = [firstline]
        # TODO(jelmer): What if there are multiple targets?
        self.target, self._component_str = firstline.split(b":", 1)
        self.components = self._component_str.split()
        return self

    def __repr__(self) -> str:
        return f"<{type(self).__name__}({self.target!r})>"

    @property
    def targets(self) -> List[bytes]:
        if self.target is None:
            raise AssertionError("no target set")
        return self.target.split(b" ")

    def has_target(self, target: bytes, exact: bool = True) -> bool:
        if exact:
            return target in self.targets
        else:
            return any(
                [matches_wildcard(target.decode(), t.decode()) for t in self.targets]
            )

    def rename_target(self, oldname: bytes, newname: bytes) -> bool:
        # TODO(jelmer): Handle multiple targets
        if self.target == oldname:
            self.target = newname
            firstline = b":".join([self.target, self._component_str])
            self.lines = [firstline] + self.lines[1:]
            return True
        return False

    def commands(self) -> List[bytes]:
        return [line[1:] for line in self.lines if line.startswith(b"\t")]

    def append_line(self, line: bytes) -> None:
        self.lines.append(line)

    def append_command(self, command: bytes) -> None:
        self.lines.append(b"\t" + command)

    def append_component(self, component: bytes) -> None:
        self.components.append(component)
        self._component_str = b" " + b" ".join(self.components)
        self.lines[0] = b"%s:%s" % (self.target, self._component_str)

    def remove_component(self, component: bytes) -> None:
        self.components.remove(component)
        self._component_str = b" " + b" ".join(self.components)
        self.lines[0] = b"%s:%s" % (self.target, self._component_str)

    def dump_lines(self) -> Iterator[bytes]:
        for line in self.precomment:
            yield line + b"\n"
        for line in self.lines:
            yield line + b"\n"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, type(self)):
            return False
        return list(self.dump_lines()) == list(other.dump_lines())

    def __bool__(self) -> bool:
        return bool(self.lines)

    def clear(self) -> None:
        self.precomment = []
        self.lines = []

    def _finish(self) -> List[Union[bytes, "Rule"]]:
        rest: List[Union[bytes, Rule]] = [self]
        while self.lines and (not self.lines[-1] or self.lines[-1].startswith(b"#")):
            rest.insert(1, self.lines.pop(-1))
        return rest


def _is_conditional(line: bytes) -> bool:
    line = line.lstrip(b" ")
    return (
        line.startswith(b"ifeq")
        or line.startswith(b"ifneq")
        or line.startswith(b"else")
        or line.startswith(b"endif")
        or line.startswith(b"include")
        or line.startswith(b"-include")
    )


def _is_rule(line: bytes) -> bool:
    before, sep, after = line.partition(b":")
    if sep != b":":
        return False
    if b"=" in before:
        return False
    if after.startswith(b"="):
        return False
    return True


class Makefile:
    contents: List[Union[bytes, Rule]]

    def __init__(self, contents: Optional[bytes] = None):
        self.contents = list(contents or [])  # type: ignore

    @classmethod
    def from_path(cls, path: str) -> "Makefile":
        with open(path, "rb") as f:
            original_contents = f.read()
        return cls.from_bytes(original_contents)

    def iter_all_rules(self) -> Iterator[Rule]:
        for entry in self.contents:
            if isinstance(entry, Rule):
                yield entry

    def iter_rules(self, target: bytes, exact: bool = True) -> Iterator[Rule]:
        for rule in self.iter_all_rules():
            if rule.has_target(target, exact):
                yield rule

    def get_variable(self, desired_key: bytes) -> bytes:
        for line in self.contents:
            if not isinstance(line, bytes):
                continue
            m = re.fullmatch(rb"(export\s)?([A-Za-z0-9_]+)\s*[:?]?=\s*(.*)", line)
            if not m:
                continue
            if m.group(2).strip() == desired_key:
                return m.group(3).strip()
        raise KeyError(desired_key)

    @classmethod
    def from_bytes(cls, contents: bytes) -> "Makefile":
        mf = cls()
        keep = b""
        rule = None
        joinedlines = []
        for line in contents.splitlines():
            line = keep + line
            keep = b""
            if line.endswith(b"\\"):
                keep = line + b"\n"
                continue
            joinedlines.append(line)

        if keep:
            # file ends with continuation line..
            joinedlines.append(keep)

        for line in joinedlines:
            if line.startswith(b"\t") and rule:
                rule.append_line(line)
            elif _is_conditional(line) or line.lstrip(b" ").startswith(b"#"):
                if rule:
                    rule.append_line(line)
                else:
                    mf.contents.append(line)
            elif _is_rule(line):
                if rule:
                    mf.contents.extend(rule._finish())
                precomment: List[bytes] = []
                while (
                    len(mf.contents) > 1
                    and isinstance(mf.contents[-1], bytes)
                    and mf.contents[-1].startswith(b"#")
                ):
                    precomment.insert(0, mf.contents.pop(-1))  # type: ignore
                rule = Rule._from_first_line(line, precomment=precomment)
            elif not line.strip():
                if rule:
                    rule.append_line(line)
                else:
                    mf.contents.append(line)
            else:
                if rule:
                    mf.contents.extend(rule._finish())
                rule = None
                mf.contents.append(line)

        if rule:
            mf.contents.extend(rule._finish())

        return mf

    def dump_lines(self) -> List[bytes]:
        lines: List[bytes] = []
        contents = self.contents[:]
        while contents and contents[-1] == b"":
            del contents[-1]
        for entry in contents:
            if isinstance(entry, Rule):
                if entry.lines == []:
                    if lines[-1] == b"\n":
                        lines.pop(-1)
                else:
                    lines.extend(entry.dump_lines())
            else:
                lines.append(entry + b"\n")
        return lines

    def dump(self) -> bytes:
        return b"".join(self.dump_lines())

    def add_rule(
        self,
        target: Union[bytes, List[bytes]],
        components: Optional[List[bytes]] = None,
        precomment: Optional[List[bytes]] = None,
    ) -> Rule:
        if self.contents:
            if isinstance(self.contents[-1], Rule):
                self.contents.append(b"")
        if isinstance(target, list):
            target = b" ".join(target)
        line = b"%s:" % target
        if components:
            line += b" " + b" ".join(components)
        rule = Rule._from_first_line(line, precomment=precomment)
        self.contents.append(rule)
        return rule

    def mark_phony(self, rule: bytes) -> None:
        for r in self.iter_rules(b".PHONY"):
            if rule in r.components:
                return
        try:
            phony_rule = list(self.iter_rules(b".PHONY"))[-1]
        except IndexError:
            self.add_rule(b".PHONY", [rule])
        else:
            phony_rule.append_component(rule)

    def add_phony(self, rule: bytes) -> None:
        try:
            phony_rule = list(self.iter_rules(b".PHONY"))[-1]
        except IndexError:
            return

        phony_rule.append_component(rule)

    def drop_phony(self, rule: bytes) -> None:
        for r in self.iter_rules(b".PHONY"):
            if rule in r.components:
                r.remove_component(rule)
            if not r.components:
                r.clear()


class MakefileEditor(Editor[Makefile, bytes]):
    def __init__(self, path: str) -> None:
        super().__init__(path, mode="b")

    def _parse(self, content: bytes) -> Makefile:
        return Makefile.from_bytes(content)

    def _format(self, parsed: Makefile) -> bytes:
        return parsed.dump()

    @property
    def makefile(self) -> Makefile:
        assert self._parsed is not None, "Makefile not parsed yet"
        return self._parsed


class RulesEditor(MakefileEditor):
    def __init__(self, path: str = "debian/rules") -> None:
        super().__init__(path)

    def legacy_update(
        self,
        command_line_cb: Optional[
            Union[
                Callable[[bytes, Optional[bytes]], Union[bytes, List[bytes]]],
                List[Callable[[bytes, Optional[bytes]], Union[bytes, List[bytes]]]],
            ]
        ] = None,
        global_line_cb: Optional[
            Callable[[bytes], Optional[Union[bytes, List[bytes]]]]
        ] = None,
        rule_cb: Optional[Callable[[Rule], None]] = None,
        makefile_cb: Optional[Callable[[Makefile], None]] = None,
        drop_related_comments: bool = False,
    ) -> bool:
        """Update a debian/rules file.

        Args:
          command_line_cb: Callback to call on every rule command line
          global_line_cb: Callback to call on every global line
          rule_cb: Callback to call on every rule
        Returns:
          boolean indicating whether any changes were made
        """
        newcontents: List[Union[bytes, Rule]] = []
        for entry in self.makefile.contents:
            if isinstance(entry, Rule):
                rule = entry
                newlines = []
                for line in list(rule.lines[1:]):
                    if line.startswith(b"\t"):
                        current_bytes = line[1:]
                        if callable(command_line_cb):
                            ret = command_line_cb(current_bytes, rule.target)
                        elif isinstance(command_line_cb, list):
                            ret = current_bytes
                            for fn in command_line_cb:
                                if isinstance(ret, bytes):
                                    ret = fn(ret, rule.target)
                                elif isinstance(ret, list):
                                    # ret is a list, process each item
                                    new_ret = []
                                    for item in ret:
                                        item_result = fn(item, rule.target)
                                        if isinstance(item_result, bytes):
                                            new_ret.append(item_result)
                                        elif isinstance(item_result, list):
                                            new_ret.extend(item_result)
                                    ret = new_ret
                        else:
                            ret = current_bytes
                        if isinstance(ret, bytes):
                            newlines.append(b"\t" + ret)
                        elif isinstance(ret, list):
                            for otherl in ret:
                                newlines.append(b"\t" + otherl)
                        else:
                            raise TypeError(ret)
                    else:
                        newlines.append(line)

                rule.lines = [rule.lines[0]] + newlines

                if rule_cb:
                    rule_cb(rule)
                if rule:
                    newcontents.append(rule)
                else:
                    if newcontents and newcontents[-1] == b"":
                        newcontents.pop(-1)
            else:
                if global_line_cb:
                    entry_line = global_line_cb(entry)
                else:
                    entry_line = entry
                if entry_line is None:
                    if drop_related_comments:
                        while (
                            newcontents
                            and newcontents[-1].startswith(b"#")  # type: ignore
                            and not newcontents[-1].startswith(b"#!")  # type: ignore
                        ):
                            del newcontents[-1]
                    if newcontents and not newcontents[-1]:
                        del newcontents[-1]
                    # TODO(jelmer): If there is no preceding whitespace, drop
                    # next line if it's empty?
                elif isinstance(entry_line, list):
                    newcontents.extend(entry_line)
                elif isinstance(entry_line, bytes):
                    newcontents.append(entry_line)
                else:
                    raise TypeError(entry_line)

        self.makefile.contents = newcontents
        if makefile_cb:
            makefile_cb(self.makefile)
        if self.has_changed():
            discard_pointless_overrides(self.makefile)
            return True
        else:
            return False


def discard_pointless_overrides(
    makefile: Makefile, ignore_comments: bool = False
) -> None:
    for rule in makefile.iter_all_rules():
        discard_pointless_override(makefile, rule, ignore_comments=ignore_comments)


def discard_pointless_override(
    makefile: Makefile, rule: Rule, ignore_comments: bool = False
) -> None:
    if rule.target is None or not rule.target.startswith(b"override_"):
        return
    command = rule.target[len(b"override_") :]
    if ignore_comments:
        effective_lines = [
            line for line in rule.lines[1:] if line.split(b"#", 1)[0].strip()
        ]
    else:
        effective_lines = [line for line in rule.lines[1:] if line.strip()]
    if effective_lines != [b"\t" + command]:
        return
    if rule.components:
        return
    rule.clear()
    if rule.target is not None:
        makefile.drop_phony(rule.target)


def update_rules(
    command_line_cb: Optional[
        Union[
            Callable[[bytes, Optional[bytes]], Union[bytes, List[bytes]]],
            List[Callable[[bytes, Optional[bytes]], Union[bytes, List[bytes]]]],
        ]
    ] = None,
    global_line_cb: Optional[
        Callable[[bytes], Optional[Union[bytes, List[bytes]]]]
    ] = None,
    rule_cb: Optional[Callable[[Rule], None]] = None,
    makefile_cb: Optional[Callable[[Makefile], None]] = None,
    path: str = "debian/rules",
    drop_related_comments: bool = False,
) -> bool:
    """Update a debian/rules file.

    Args:
      command_line_cb: Callback to call on every rule command line
      global_line_cb: Callback to call on every global line
      rule_cb: Callback to call on every rule
      path: Path to the debian/rules file to edit
    Returns:
      boolean indicating whether any changes were made
    """
    if not os.path.exists(path):
        return False
    updater = RulesEditor(path)
    with updater:
        changed = updater.legacy_update(
            command_line_cb=command_line_cb,
            global_line_cb=global_line_cb,
            rule_cb=rule_cb,
            makefile_cb=makefile_cb,
            drop_related_comments=drop_related_comments,
        )
    return changed


def dh_invoke_add_with(line: bytes, with_argument: bytes) -> bytes:
    """Add a particular value to a with argument."""
    if with_argument in line:
        return line
    if b" --with" not in line:
        return line + b" --with=" + with_argument
    return re.sub(
        b"([ \t])--with([ =])([^ \t]+)", b"\\1--with\\2\\3," + with_argument, line
    )


def dh_invoke_get_with(line: bytes) -> List[str]:
    ret: List[str] = []
    for m in re.finditer(b"[ \t]--with[ =]([^ \t]+)", line):
        ret.extend(m.group(1).decode("utf-8").split(","))
    return ret


def dh_invoke_drop_with(line: bytes, with_argument: bytes) -> bytes:
    """Drop a particular value from a with argument."""
    if with_argument not in line:
        return line
    # It's the only with argument
    line = re.sub(b"[ \t]--with[ =]" + with_argument + b"( .+|)$", b"\\1", line)
    # It's at the beginning of the line
    line = re.sub(b"([ \t])--with([ =])" + with_argument + b",", b"\\1--with\\2", line)
    # It's somewhere in the middle or the end
    line = re.sub(
        b"([ \t])--with([ =])(.+)," + with_argument + b"([ ,])",
        b"\\1--with\\2\\3\\4",
        line,
    )
    # It's at the end
    line = re.sub(
        b"([ \t])--with([ =])(.+)," + with_argument + b"$", b"\\1--with\\2\\3", line
    )
    return line


def dh_invoke_drop_argument(line: bytes, argument: bytes) -> bytes:
    """Drop a particular argument from a dh invocation."""
    if argument not in line:
        return line
    line = re.sub(b"[ \t]+" + argument + b"$", b"", line)
    line = re.sub(b"([ \t])" + argument + b"[ \t]", b"\\1", line)
    return line


def dh_invoke_replace_argument(line: bytes, old: bytes, new: bytes) -> bytes:
    if old not in line:
        return line
    line = re.sub(b"([ \t])" + old + b"$", b"\\1" + new, line)
    line = re.sub(b"([ \t])" + old + b"([ \t])", b"\\1" + new + b"\\2", line)
    return line


def check_cdbs(path: str = "debian/rules") -> bool:
    if not os.path.exists(path):
        return False
    with open(path, "rb") as f:
        for line in f:
            if line.lstrip(b"-").startswith(b"include /usr/share/cdbs/"):
                return True
    return False
