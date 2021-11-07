Debmutate is a set of Python modules for manipulating the control files of
Debian packages, with the ability to preserve the existing formatting of
the control files.

It's built on top of the excellent
[python-debian](https://salsa.debian.org/python-debian-team/python-debian)
library, and was originally extracted from
[lintian-brush](https://salsa.debian.org/jelmer/lintian-brush).

To modify one of the control files, use one of the context managers to edit the file.

For example, for debian/control::

    from debmutate.control import ControlEditor

    with ControlEditor(path='debian/control') as control:
        print(control.source['Maintainer'])
        control.source['Maintainer'] = "Jelmer Vernooĳ <jelmer@debian.org>"

Or for debian/changelog::

    from debmutate.changelog import ChangelogEditor

   with ChangelogEditor(path='debian/changelog') as editor:
       editor.add_entry(['Some entry'])

Once you leave the context manager, the changes will be written to disk if
there were any. If the editor is unable to preserve the formatting of the
control file, it will raise a FormattingUnpreservable error.

If the control file that was edited was generated from another control file
(e.g. debian/control.in), debmutate will attempt to update that file instead
and then regenerate debian/control. If it is unable to do so, it will raise
a GeneratedFile exception.

The file will be left as-is if an exception is raised, or if the .cancel()
method is called.

debmutate currently provides editors for the following control files:

 * debian/changelog
 * debian/copyright
 * debian/control
 * debian/patches/series
 * debian/tests/control
 * debian/watch
 * debian/maintscripts, debian/\*.maintscripts
 * debian/source/lintian-overrides, debian/\*.lintian-overrides
 * debian/debcargo.toml

