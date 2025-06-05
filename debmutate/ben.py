#!/usr/bin/python3

# Copyright (C) 2021 Jelmer Vernooij
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

"""Ben file parsing."""

import re
from typing import Any, Dict, List, Pattern, TextIO, Tuple, Union

SUPPORTED_KEYS = ["title", "notes", "is_affected", "is_good", "is_bad", "export"]

BenItem = Union[
    bool,
    int,
    str,
    List[Union[bool, int, str]],
    List[Tuple[str, Pattern[str]]],
    Any,  # this should actually be recursive, but older versions of Python don't support that
]


def _parse_benitem(
    v: str,
) -> BenItem:
    if v == "false":
        return False
    elif v == "true":
        return True
    elif v.startswith("[") and v.endswith("]"):
        return [_parse_benitem(i) for i in v.split(";")]
    elif v.startswith('"') and v.endswith('"'):
        return v[1:-1]
    elif v.isdigit():
        return int(v)
    elif "~" in v:
        regex = []
        for o in v.split(" | "):
            try:
                field, expr = o.split("~", 1)
            except ValueError:
                raise ValueError(f"expected ~: {o!r}")
            parsed = _parse_benitem(expr.strip())
            if not isinstance(parsed, str):
                raise ValueError(f"expected string after ~: {expr!r}")
            expr_pattern = re.compile(parsed)
            regex.append((field.strip(), expr_pattern))
        return regex
    else:
        return v


def parse_ben(
    f: TextIO,
) -> Dict[
    str,
    Union[bool, int, str, List[Union[bool, int, str]], List[Tuple[str, Pattern[str]]]],
]:
    ret = {}
    assignment = {}
    lastk = None
    v = ""
    for line in f:
        if lastk is None:
            if not line.strip():
                continue
            if line.startswith("#"):
                continue
            line = line.rstrip()
            (k, v) = line.split("=", 1)
            k = k.strip()
            v = v.lstrip()
            lastk = k
        else:
            v += line
        if v.rstrip().endswith(";"):
            assignment[lastk] = v[:-1]
            lastk = None
    if lastk is not None:
        raise ValueError(f"unterminated key: {lastk!r}")
    for k, v in assignment.items():
        ret[k] = _parse_benitem(v)
    return ret
