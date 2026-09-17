.PHONY: run test install venv clean

venv:
	python3 -m venv .venv
	. .venv/bin/activate && pip install -U pip && pip install -e ".[dev]"

install:
	pip install -e ".[dev]"

run:
	python -m app.main

test:
	pytest -q

clean:
	rm -rf .venv dist build *.egg-info .pytest_cache **/__pycache__
