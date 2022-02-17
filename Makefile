init:
	pip install -r requirements.txt

test:
	python -m tests.scenario_medium

coverage:
	coverage run --branch -m tests.scenario_medium && coverage html

upgrade:
	pip install --upgrade pip && pip install --upgrade pip-tools && rm requirements.txt && pip-compile requirements.in

docs:
	$(MAKE) -C docs html

.PHONY: init test docs
