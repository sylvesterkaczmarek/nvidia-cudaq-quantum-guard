.PHONY: install install-cudaq test smoke doctor build clean

install:
	python -m pip install -e ".[dev]"

install-cudaq:
	python -m pip install -e ".[cudaq,dev]"

test:
	python -m pytest

smoke:
	cudaq-guard run ghz --policy policies/local-safe.toml --target qpp-cpu --qubits 3 --shots 256 --seed 7 --audit /tmp/cudaq-guard-audit.jsonl
	cudaq-guard audit verify /tmp/cudaq-guard-audit.jsonl

doctor:
	cudaq-guard doctor

build:
	python -m build

clean:
	rm -rf build dist *.egg-info .pytest_cache
