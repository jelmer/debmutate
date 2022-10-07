check:: testsuite style typing

.PHONY: style testsuite unsupported

style::
	flake8

typing::
	mypy debmutate

testsuite::
	python3 -m unittest debmutate.tests.test_suite
