check:: testsuite style typing

.PHONY: style testsuite unsupported

style::
	flake8

typing::
	mypy --check-untyped-defs debmutate tests

testsuite::
	python3 -m unittest tests.test_suite
