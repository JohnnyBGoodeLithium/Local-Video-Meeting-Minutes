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
	$(PY) web/tests/minutes_restructure_test.py
	$(PY) web/tests/assistant_transport_test.py
	$(PY) web/tests/minutes_overview_test.py
	$(PY) web/tests/minutes_overview_direct_test.py
	$(PY) web/tests/minutes_degenerate_test.py
	$(PY) web/tests/design_tokens_test.py
	$(PY) web/tests/product_version_test.py
	$(PY) web/tests/summarize_request_test.py
	$(PY) web/tests/voice_draft_test.py
	$(PY) web/tests/job_scheduler_test.py
	$(PY) web/tests/job_log_safety_test.py
	$(PY) web/tests/job_recovery_test.py
	$(PY) web/tests/job_preemption_test.py
	$(PY) web/tests/media_materialize_test.py
	$(PY) web/tests/retranscribe_local_test.py
	$(PY) web/tests/teams_transcript_test.py
	$(PY) web/tests/slide_pages_test.py
	$(PY) web/tests/vl_cache_test.py
	$(PY) web/tests/vl_describe_pages_test.py
	$(PY) web/tests/meeting_generation_test.py
	$(PY) web/tests/meeting_structure_test.py
	$(PY) web/tests/meeting_topic_map_test.py
	$(PY) web/tests/hardware_test.py
	$(PY) web/tests/asr_provider_test.py
	$(PY) web/tests/transcribe_output_test.py
	$(PY) web/tests/terminology_test.py
	$(PY) web/tests/transcript_review_test.py
	$(PY) web/tests/diarization_test.py
	$(PY) web/tests/voice_split_test.py
	$(PY) web/tests/speaker_history_test.py
	$(PY) web/tests/voice_fragment_merge_test.py
	$(PY) web/tests/speaker_navigation_test.py
	$(PY) web/tests/translation_service_test.py
	$(PY) web/tests/viewer_boot_test.py
	@if command -v node >/dev/null 2>&1; then node --check web/static/app.js && node --check web/static/admin.js && node web/tests/assistant_intent_test.mjs; else echo "Node unavailable: skipped JS syntax check"; fi
	git diff --check

smoke:
	$(PY) web/tests/run_smoke.py

assistant-live:
	$(PY) web/tests/live_assistant_test.py

retrieval-live:
	$(PY) web/tests/live_retrieval_test.py

rag-index:
	$(PY) bin/build_rag_indexes.py
