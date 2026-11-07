.PHONY: start test eval

start:
	./scripts/start.sh

test:
	PYTHONPATH=backend .venv/bin/pytest backend/tests -q
	npm test --prefix frontend

eval:
	PYTHONPATH=backend .venv/bin/python -m eval.run --output eval/results/latest.json
