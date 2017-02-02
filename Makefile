PYTHON ?= python
COVERAGE ?= $(PYTHON)-coverage

SOURCE = txfixtures
OMIT = $(SOURCE)/osutils.py,$(SOURCE)/tachandler.py,$(SOURCE)/_twisted/backports/*.py

check:
	rm -f .coverage
	$(COVERAGE) run --omit=$(OMIT) --source=$(SOURCE) -m testtools.run discover
	$(COVERAGE) report -m --fail-under=100

check-doc:
	$(MAKE) -C doc doctest

html:
	$(MAKE) -C doc html

.PHONY: check check-doc html
