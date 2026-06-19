.PHONY: install dev test lint fmt run serve autopilot clean

install:
	pip install -e .

dev:
	pip install -e ".[dev,saas,trading]"

test:
	pytest

lint:
	ruff check moneyagent tests

fmt:
	ruff format moneyagent tests

run:
	python -m moneyagent providers

serve:
	python -m moneyagent serve

autopilot:
	python -m moneyagent autopilot --jobs config/jobs.example.yaml --once

clean:
	rm -rf build dist *.egg-info .pytest_cache __pycache__
	find . -name "__pycache__" -type d -prune -exec rm -rf {} +
