.PHONY: demo test web init compose-down

demo:
	PYTHONPATH=src python -m operations_copilot.cli

test:
	python -m pytest -q

init:
	PYTHONPATH=src python scripts/init_demo.py

web:
	PYTHONPATH=src python -m uvicorn operations_copilot.api:create_app --factory --host 127.0.0.1 --port 8000

compose-down:
	docker compose down
