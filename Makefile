init:
	pip install -r requirements.txt

test:
	python -m tests.scenario_medium

docs:
	$(MAKE) -C docs html

.PHONY: init test docs
