PY := .venv/bin/python

.PHONY: run doctor check smoke assistant-live

run:
	$(PY) web/server.py

doctor:
	$(PY) bin/doctor.py --profile all

check:
	$(PY) -c 'import ast,pathlib; files=list(pathlib.Path("bin").glob("*.py"))+list(pathlib.Path("web").glob("*.py"))+list(pathlib.Path("web/tests").glob("*.py")); [ast.parse(p.read_text(encoding="utf-8"), filename=str(p)) for p in files]; print(f"Python syntax: {len(files)} files OK")'
	@if command -v node >/dev/null 2>&1; then node --check web/static/app.js && node --check web/static/admin.js; else echo "Node unavailable: skipped JS syntax check"; fi
	git diff --check

smoke:
	$(PY) web/tests/run_smoke.py

assistant-live:
	$(PY) web/tests/live_assistant_test.py
