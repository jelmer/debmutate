Contributing
============

Philosophy
----------

Debmutate is a package that provides a set of convenience infrastructure for
manipulating Debian packages.

Plain parsers/formatters should generally be upstreamed into python-debian.

Coding Style
------------

lintian-brush uses PEP8 as its coding style.

Code style can be checked by running ``flake8``:

```shell
flake8
```

Tests
-----

To run the testsuite, use:

```shell
python3 setup.py test
```

or simply:

```shell
make check
```

The tests are also run by the package build and autopkgtest.
