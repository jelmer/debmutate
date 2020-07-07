#!/usr/bin/python3

from debmutate.control import ControlEditor

with ControlEditor(path='debian/control') as control:
    print(control.source['Maintainer'])
    control.source['Maintainer'] = "Jelmer Vernooĳ <jelmer@debian.org>"
