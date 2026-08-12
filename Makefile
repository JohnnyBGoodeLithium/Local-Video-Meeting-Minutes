PY := .venv/bin/python

.PHONY: run doctor check smoke assistant-live retrieval-live rag-index

run:
	$(PY) web/server.py

doctor:
	$(PY) bin/doctor.py --profile all

check:
	$(PY) -c 'import ast,pathlib; files=list(pathlib.Path("bin").rglob("*.py"))+list(pathlib.Path("web").rglob("*.py")); [ast.parse(p.read_text(encoding="utf-8"), filename=str(p)) for p in files]; print(f"Python syntax: {len(files)} files OK")'
	$(PY) web/tests/orgchart_extract_test.py
	$(PY) web/tests/minutes_markdown_test.py
	$(PY) web/tests/minutes_policy_test.py
	$(PY) web/tests/minutes_overview_test.py
	$(PY) web/tests/summarize_request_test.py
	$(PY) web/tests/voice_draft_test.py
	$(PY) web/tests/job_scheduler_test.py
	$(PY) web/tests/media_materialize_test.py
	$(PY) web/tests/slide_pages_test.py
	$(PY) web/tests/vl_cache_test.py
	$(PY) web/tests/meeting_generation_test.py
	$(PY) web/tests/meeting_structure_test.py
	$(PY) web/tests/meeting_topic_map_test.py
	$(PY) web/tests/translation_service_test.py
	@if command -v node >/dev/null 2>&1; then node --check web/static/app.js && node --check web/static/admin.js; else echo "Node unavailable: skipped JS syntax check"; fi
	git diff --check

smoke:
	$(PY) web/tests/run_smoke.py

assistant-live:
	$(PY) web/tests/live_assistant_test.py

retrieval-live:
	$(PY) web/tests/live_retrieval_test.py

rag-index:
	$(PY) bin/build_rag_indexes.py
