check:: style testsuite

.PHONY: style testsuite unsupported

style::
	flake8

typing::
	mypy lintian_brush fixers

testsuite::
	python3 setup.py test
