check:: testsuite style typing check-fmt

.PHONY: style testsuite unsupported

check-fmt::
	ruff format --check .

style::
	ruff check .

typing::
	mypy debmutate tests

testsuite::
	python3 -m unittest tests.test_suite
