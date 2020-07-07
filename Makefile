check:: style testsuite typing

.PHONY: style testsuite unsupported

style::
	flake8

typing::
	mypy debmutate

testsuite::
	python3 setup.py test
