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

Code style can be checked by running ``ruff``:

```shell
ruff check debmutate tests
```

To format the code, run ruff format:

```shell
ruff format debmutate tests
```

Tests
-----

To run the testsuite, use:

```shell
python3 -m unittest debmutate.tests.test_suite
```

or simply:

```shell
make check
```

The tests are also run by the package build and autopkgtest.
