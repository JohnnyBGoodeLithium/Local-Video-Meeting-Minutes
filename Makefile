PY := .venv/bin/python

.PHONY: run doctor check package-check smoke assistant-live retrieval-live rag-index lock lock-check install-runtime install-ci product-site-build release-bundle release-verify

run:
	$(PY) web/server.py

doctor:
	$(PY) bin/doctor.py --profile all

check: package-check
	$(PY) web/tests/release_workflow_test.py
	git diff --check

package-check: export MEETING_RESOURCE_GUARD=0
package-check:
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
	$(PY) web/tests/release_metadata_test.py
	$(PY) web/tests/release_bundle_test.py
	$(PY) web/tests/product_intro_test.py
	$(PY) web/tests/product_pages_test.py
	$(PY) web/tests/documentation_structure_test.py
	$(PY) web/tests/summarize_request_test.py
	$(PY) web/tests/voice_draft_test.py
	$(PY) web/tests/job_scheduler_test.py
	$(PY) web/tests/job_log_safety_test.py
	$(PY) web/tests/job_progress_test.py
	$(PY) web/tests/job_recovery_test.py
	$(PY) web/tests/resource_policy_test.py
	$(PY) web/tests/job_preemption_test.py
	$(PY) web/tests/media_materialize_test.py
	$(PY) web/tests/media_url_test.py
	$(PY) web/tests/retranscribe_local_test.py
	$(PY) web/tests/teams_transcript_test.py
	$(PY) web/tests/slide_pages_test.py
	$(PY) web/tests/media_shots_test.py
	$(PY) web/tests/media_minutes_test.py
	$(PY) web/tests/media_navigation_test.py
	$(PY) web/tests/vl_cache_test.py
	$(PY) web/tests/vl_describe_pages_test.py
	$(PY) web/tests/meeting_generation_test.py
	$(PY) web/tests/meeting_structure_test.py
	$(PY) web/tests/meeting_photos_test.py
	$(PY) web/tests/photo_analysis_test.py
	$(PY) web/tests/knowledge_sink_test.py
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
	$(PY) web/tests/keyword_service_test.py
	$(PY) web/tests/keyword_index_test.py
	$(PY) web/tests/kb_document_test.py
	$(PY) web/tests/ai_context_test.py
	$(PY) web/tests/content_type_test.py
	$(PY) web/tests/companion_pairing_test.py
	$(PY) web/tests/companion_session_test.py
	$(PY) web/tests/companion_security_test.py
	$(PY) web/tests/companion_permissions_test.py
	$(PY) web/tests/companion_library_test.py
	$(PY) web/tests/companion_job_status_test.py
	$(PY) web/tests/companion_evidence_test.py
	$(PY) web/tests/companion_import_url_test.py
	$(PY) web/tests/companion_upload_test.py
	$(PY) web/tests/companion_speaker_confirmation_test.py
	$(PY) web/tests/viewer_boot_test.py
	@if command -v node >/dev/null 2>&1; then node --check web/static/app.js && node --check web/static/admin.js && node --check web/static/product-copy.js && node --check web/static/product-demo.js && node --check web/static/product.js && node --check web/static/companion.js && node web/tests/frontend_modules_test.mjs && node web/tests/job_progress_frontend_test.mjs && node web/tests/photo_import_frontend_test.mjs && node web/tests/speaker_correction_frontend_test.mjs && node web/tests/assistant_intent_test.mjs && node web/tests/product_demo_frontend_test.mjs && node web/tests/companion_frontend_test.mjs; else echo "Node unavailable: skipped JS syntax check"; fi

smoke: export MEETING_RESOURCE_GUARD=0
smoke:
	$(PY) web/tests/run_smoke.py

assistant-live:
	$(PY) web/tests/live_assistant_test.py

retrieval-live:
	$(PY) web/tests/live_retrieval_test.py

rag-index:
	$(PY) bin/build_rag_indexes.py

lock:
	$(PY) scripts/compile_locks.py

lock-check:
	$(PY) scripts/compile_locks.py --check

install-runtime:
	$(PY) -m pip install -r requirements/runtime.lock
	$(PY) -m pip install -e . --no-deps

install-ci:
	$(PY) -m pip install -r requirements/ci.lock
	$(PY) -m pip install -e . --no-deps

product-site-build:
	$(PY) scripts/build_product_pages.py

release-bundle:
	$(PY) scripts/build_release_bundle.py

release-verify: release-bundle
	$(PY) scripts/verify_release_bundle.py --full
