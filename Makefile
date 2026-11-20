.PHONY: install backend frontend test demo

install:
	cd backend && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
	cd frontend && npm ci

backend:
	cd backend && ./run.sh

frontend:
	cd frontend && npm run dev

test:
	cd backend && .venv/bin/python -I run_tests.py

demo:
	cd backend && .venv/bin/python -I scripts/scenario_demo.py
