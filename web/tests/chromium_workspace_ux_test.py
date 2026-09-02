#!/usr/bin/env python3
"""Exercise the v0.15 processing, recovery, and meeting-material journeys in Chromium.

Only the synthetic smoke meeting is used. Writes are intercepted in the browser so the
shared fixture remains unchanged; Python/API tests cover persistence separately.
"""

from __future__ import annotations

import base64
import json
import os
import shutil
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path

from chromium_speaker_correction_test import CDP, wait_devtools_port


CHROME = (shutil.which("chromium") or shutil.which("chromium-browser")
          or shutil.which("google-chrome"))
ROOT = Path(__file__).resolve().parents[2]


def capture(cdp: CDP, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    result = cdp.call("Page.captureScreenshot", {"format": "png", "fromSurface": True})
    path.write_bytes(base64.b64decode(result["data"]))


def main() -> int:
    if not CHROME:
        print("workspace UX browser: chromium not found, skipped")
        return 0
    base = os.environ.get("MM_TEST_BASE", "http://127.0.0.1:8899")
    capture_dir = os.environ.get("MM_WORKSPACE_SCREENSHOT_DIR", "").strip()
    # Chromium children can finish touching the profile just after the parent exits.
    # The browser assertions must remain strict; only this runner-cleanup race is ignored.
    with tempfile.TemporaryDirectory(
        prefix="mm-chromium-workspace-", ignore_cleanup_errors=True,
    ) as tmp:
        profile = Path(tmp)
        process = subprocess.Popen([
            CHROME, "--headless=new", "--disable-gpu", "--no-sandbox",
            "--remote-debugging-port=0", "--remote-allow-origins=*",
            f"--user-data-dir={profile}", "--window-size=1600,1000", base,
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            active = profile / "DevToolsActivePort"
            port = wait_devtools_port(active)
            target = None
            deadline = time.time() + 10
            while time.time() < deadline:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list") as response:
                    pages = json.load(response)
                target = next((item for item in pages if item.get("type") == "page"), None)
                if target:
                    break
                time.sleep(0.05)
            if not target:
                raise RuntimeError("No Chromium page target")
            cdp = CDP(target["webSocketDebuggerUrl"])
            try:
                ready_deadline = time.time() + 12
                while time.time() < ready_deadline:
                    try:
                        if cdp.evaluate("document.readyState === 'complete' && !!document.querySelector('#turn-0')"):
                            break
                    except RuntimeError as exc:
                        if "Execution context was destroyed" not in str(exc):
                            raise
                    time.sleep(0.1)
                else:
                    diagnostic = cdp.evaluate(r"""
(async () => {
  const source = document.querySelector('script[type="module"]')?.src;
  try {
    if (source) await import(source);
    return `module loaded but workspace missing; source=${source || 'missing'}`;
  } catch (error) {
    return `module error: ${error?.stack || error}; source=${source || 'missing'}`;
  }
})()
""")
                    raise RuntimeError(f"workspace did not finish loading: {diagnostic}")

                cdp.evaluate(r"""
window.__workspaceUxE2E = 'running';
void (async () => {
  const waitFor = async (fn, label, timeout = 10000) => {
    const end = Date.now() + timeout;
    while (Date.now() < end) {
      const value = fn();
      if (value) return value;
      await new Promise(resolve => setTimeout(resolve, 50));
    }
    throw new Error(`timeout: ${label}`);
  };
  const jp = await import('/static/modules/job-progress.js');
  const view = await import('/static/modules/job-progress-view.js');
  const banner = document.querySelector('#processing-banner');
  const sheet = document.querySelector('#job-detail-sheet');
  const phases = [
    {id:'prepare',state:'done',elapsed_seconds:18},
    {id:'teams_alignment',state:'done',elapsed_seconds:130},
    {id:'voice_draft',state:'done',elapsed_seconds:156},
    {id:'visual_extraction',state:'done',elapsed_seconds:24},
    {id:'visual_understanding',state:'running',done:12,total:36,unit:'pages'},
    {id:'final_minutes',state:'pending'}, {id:'topic_map',state:'pending'},
  ];
  const progress = {
    schema:'job-progress/v2',source:'structured',route:'teams',state:'running',
    phase:'visual_understanding',phase_index:4,phase_count:7,done:12,total:36,unit:'pages',
    available_outputs:{transcript:'ready',speaker_navigation:'ready',voice_draft:'ready',
      visuals:'partial',final_minutes:'pending',topic_map:'pending',retrieval:'pending'},
    estimated_first_usable:null,
    estimated_remaining:{low_seconds:1080,high_seconds:1560,confidence:'medium'},
    phases,attempt:1,
  };
  const runningJob = {id:'synthetic-progress',kind:'upload',route:'teams',status:'running',
    meeting:'_smoke',progress};
  let runningModel = jp.jobPresentation(runningJob, 'Synthetic review', 'zh-CN');
  view.renderProcessingBanner(banner, runningModel, {language:'zh-CN',onAction:(action, model, trigger) => {
    if (action === 'details') view.renderJobSheet(sheet, model, {mode:'details'},
      {language:'zh-CN',onClose:()=>view.closeJobSheet(sheet)});
  }});
  const draftReady = banner.textContent.includes('语音草稿已就绪')
    && banner.textContent.includes('12 / 36') && banner.textContent.includes('18–26');
  banner.querySelector('[data-job-action="details"]').click();
  const detailReady = sheet.textContent.includes('生成语音草稿')
    && sheet.textContent.includes('理解画面与现场资料') && sheet.textContent.includes('12 / 36')
    && sheet.querySelector('[aria-current="step"]');
  window.__workspaceUxCapture = 'progress';
  await new Promise(resolve => setTimeout(resolve, 350));

  const media = document.querySelector('#player-holder audio, #player-holder video');
  if (media) { try { media.currentTime = 2; } catch (_) {} }
  const transcript = document.querySelector('#transcript');
  transcript.scrollTop = Math.min(24, transcript.scrollHeight);
  const timeBefore = media ? media.currentTime : 0;
  const scrollBefore = transcript.scrollTop;
  const failedProgress = structuredClone(progress);
  failedProgress.state = 'failed';
  failedProgress.phases[4].state = 'failed';
  failedProgress.failure = {
    code:'VISUAL_MODEL_START_FAILED',category:'service_unavailable',
    recoverability:'resume_from_checkpoint',failed_phase:'visual_understanding',
    completed_units:12,total_units:36,preserved_outputs:['transcript','speaker_navigation','voice_draft'],
    blocked_outputs:['visuals','final_minutes','topic_map'],diagnostic_id:'ERR-TEST15',
    technical:{exception_type:'ModelServiceUnavailable'},retry_options:[
      {id:'resume_standard',action:'resume',enabled:true},
      {id:'finish_without_visuals',action:'degraded_continue',enabled:true},
    ],
  };
  const failedJob = {id:'synthetic-failure',kind:'upload',route:'teams',status:'failed',
    meeting:'_smoke',progress:failedProgress,recovery:{state:'available',mode:'minutes'},
    attempt_history:[
      {attempt:1,status:'failed',phase:'visual_understanding',done:12,total:36},
      {attempt:2,status:'recovering',phase:'visual_understanding',done:18,total:36},
    ]};
  const failedModel = jp.jobPresentation(failedJob, 'Synthetic review', 'zh-CN');
  view.renderProcessingBanner(banner, failedModel, {language:'zh-CN',onAction:(action, model) => {
    if (action === 'recovery') view.renderJobSheet(sheet, model, {mode:'recovery'}, {
      language:'zh-CN',onClose:()=>view.closeJobSheet(sheet),
      onStartRecovery:()=>{ window.__recoveryStarted = true; },
      onStartDegraded:()=>{ window.__degradedOffered = true; },
    });
  }});
  const failureClear = banner.textContent.includes('理解画面与现场资料没有完成')
    && banner.textContent.includes('本地视觉服务未能启动')
    && banner.textContent.includes('语音草稿');
  banner.querySelector('[data-job-action="recovery"]').click();
  const previewClear = sheet.textContent.includes('从第 13 个画面继续')
    && sheet.textContent.includes('将复用') && sheet.textContent.includes('将重新执行')
    && sheet.textContent.includes('跳过剩余画面');
  sheet.querySelector('[data-job-action="start_recovery"]').click();
  const contextKept = (!media || Math.abs(media.currentTime - timeBefore) < .1)
    && transcript.scrollTop === scrollBefore;
  view.closeJobSheet(sheet);
  const doneJob = structuredClone(runningJob);
  doneJob.status = 'done'; doneJob.progress.state = 'done';
  view.renderProcessingBanner(banner, jp.jobPresentation(doneJob, 'Synthetic review', 'zh-CN'),
    {language:'zh-CN'});
  const completedCollapsed = banner.classList.contains('hidden');

  const realFetch = window.fetch.bind(window);
  const baseBundle = await realFetch('/api/meetings/_smoke/bundle').then(response => response.json());
  let materialPresent = false, imported = 0, renamed = false, alignmentCalls = 0;
  let deleted = false, analysisQueued = false;
  const photo = {
    id:'F9001',kind:'photo',page:null,title:'Synthetic whiteboard',description:'',
    display_description:'Not analyzed yet.',
    image:'page1.png',asset_path:'slides/page1.png',
    original_name:'synthetic-whiteboard.png',first:null,ranges:[],turn_indexes:[],
    display_status:'Meeting material',analysis_state:'not_requested',information_value:'unknown',
    alignment:{seconds:null,state:'unlocated',method:'none',confidence:'unlocated'},
  };
  window.fetch = async (input, init = {}) => {
    const url = String(input), method = String(init.method || 'GET').toUpperCase();
    if (url.includes('/translations/') && method === 'POST')
      return new Response(JSON.stringify({state:'missing'}), {status:200,headers:{'Content-Type':'application/json'}});
    if (url.endsWith('/photos') && method === 'POST') {
      imported += 1; materialPresent = true;
      return new Response(JSON.stringify({results:[{photo,duplicate:imported === 2}],
        imported: imported === 1 ? [photo] : [],duplicate_ids: imported === 2 ? ['F9001'] : []}),
        {status:200,headers:{'Content-Type':'application/json'}});
    }
    if (url.endsWith('/photos/analyze') && method === 'POST') {
      analysisQueued = true; photo.analysis_state = 'queued';
      photo.display_description = 'Visual analysis queued';
      return new Response(JSON.stringify({ok:true,job:{id:'synthetic-photo-job',status:'queued',kind:'photo_analysis'}}),
        {status:200,headers:{'Content-Type':'application/json'}});
    }
    if (url.endsWith('/bundle') && method === 'GET' && materialPresent) {
      const bundle = structuredClone(baseBundle);
      bundle.photos = [photo]; bundle.structure = bundle.structure || {};
      bundle.structure.visuals = [...(bundle.structure.visuals || []), photo];
      return new Response(JSON.stringify(bundle), {status:200,headers:{'Content-Type':'application/json'}});
    }
    if (url.includes('/photos/F9001/alignment') && method === 'PATCH') {
      const body = JSON.parse(init.body || '{}');
      alignmentCalls += 1; photo.alignment.seconds = body.seconds; photo.first = body.seconds;
      photo.ranges = body.seconds == null ? [] : [[body.seconds, body.seconds + 1]];
      return new Response(JSON.stringify({photo}), {status:200,headers:{'Content-Type':'application/json'}});
    }
    if (url.endsWith('/photos/F9001') && method === 'PATCH') {
      const body = JSON.parse(init.body || '{}'); renamed = true; photo.title = body.title;
      return new Response(JSON.stringify({photo}), {status:200,headers:{'Content-Type':'application/json'}});
    }
    if (url.endsWith('/photos/F9001') && method === 'DELETE') {
      deleted = true; materialPresent = false;
      return new Response(JSON.stringify({ok:true}), {status:200,headers:{'Content-Type':'application/json'}});
    }
    return realFetch(input, init);
  };

  document.querySelector('[data-ui-language="en"]').click();
  await waitFor(() => document.documentElement.lang === 'en', 'English UI');
  const englishMaterials = document.querySelector('#visuals-tab').textContent.trim() === 'Visuals & Materials';
  const qualityEntryHidden = document.querySelector('#quality-entry-btn').classList.contains('hidden');
  const qualityTab = await waitFor(() => {
    const tab = document.querySelector('#quality-tab');
    return tab && !tab.disabled && tab;
  }, 'key conclusion review route');
  qualityTab.click();
  await waitFor(() => !document.querySelector('#quality').classList.contains('hidden'), 'English quality review');
  const allEvidence = await waitFor(() => document.querySelector('[data-quality-scope="all"]'), 'all evidence');
  allEvidence.click();
  const englishQuality = document.querySelector('#quality').textContent.includes('Review key conclusions')
    && document.querySelector('#quality').textContent.includes('Conclusion matches the evidence')
    && document.querySelector('#quality').textContent.includes('Open source evidence')
    && document.querySelector('#quality-tab').classList.contains('hidden') && qualityEntryHidden;
  document.querySelector('#visuals-tab').click();
  document.querySelector('#photo-import-btn').click();
  const bytes = Uint8Array.from(atob('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII='), c => c.charCodeAt(0));
  const transfer = new DataTransfer();
  transfer.items.add(new File([bytes], 'synthetic-whiteboard.png', {type:'image/png'}));
  transfer.items.add(new File([bytes], 'synthetic-note.png', {type:'image/png'}));
  transfer.items.add(new File([bytes], 'synthetic-remove.png', {type:'image/png'}));
  const input = document.querySelector('#photo-file-input'); input.files = transfer.files;
  input.dispatchEvent(new Event('change', {bubbles:true}));
  await waitFor(() => document.querySelectorAll('[data-photo-item]').length === 3, 'material previews');
  const previews = document.querySelectorAll('.photo-import-thumb img').length === 3;
  document.querySelectorAll('[data-photo-remove]')[2].click();
  const removable = document.querySelectorAll('[data-photo-item]').length === 2;
  const firstSettings = document.querySelector('[data-photo-settings]'); firstSettings.click();
  document.querySelector('[data-photo-mode="current_time"]').click();
  const progressivePosition = !document.querySelector('[data-photo-settings]').getAttribute('aria-expanded').includes('true');
  document.querySelector('#photo-import-confirm').click();
  await waitFor(() => document.querySelector('#photo-import-mask').classList.contains('hidden'), 'material import');
  const materialCard = await waitFor(() => document.querySelector('[data-visual-select="F9001"]'), 'material card');
  materialCard.click();
  await waitFor(() => document.querySelector('[data-photo-rename]'), 'material lifecycle');
  document.querySelector('[data-photo-rename]').click();
  const titleInput = document.querySelector('.photo-rename-form input');
  titleInput.value = 'Review whiteboard';
  document.querySelector('.photo-rename-form').dispatchEvent(new Event('submit', {bubbles:true,cancelable:true}));
  await waitFor(() => renamed && document.querySelector('#visuals').textContent.includes('Review whiteboard'), 'rename');
  document.querySelector('[data-photo-align-current]').click();
  await waitFor(() => alignmentCalls >= 1 && photo.alignment.seconds != null, 'alignment');
  const unlocate = await waitFor(() => document.querySelector('[data-photo-unlocate]'), 'unlocate action');
  unlocate.click();
  await waitFor(() => alignmentCalls >= 2 && photo.alignment.seconds == null, 'unlocate');
  await waitFor(() => document.querySelector('[data-photo-delete]'), 'delete action');
  banner.classList.add('hidden');
  view.closeJobSheet(sheet);
  window.__workspaceUxCapture = 'materials';
  await new Promise(resolve => setTimeout(resolve, 350));
  document.querySelector('[data-photo-delete]').click();
  const productDelete = !document.querySelector('#photo-delete-mask').classList.contains('hidden')
    && document.querySelector('#photo-delete-title').textContent.includes('Delete');
  document.querySelector('#photo-delete-confirm').click();
  await waitFor(() => deleted && document.querySelector('#photo-delete-mask').classList.contains('hidden'), 'delete');

  window.__workspaceUxE2E = [draftReady,Boolean(detailReady),failureClear,previewClear,
    window.__recoveryStarted === true,contextKept,completedCollapsed,englishMaterials,
    englishQuality,previews,removable,progressivePosition,imported === 2,analysisQueued,renamed,
    alignmentCalls === 2,productDelete,deleted].join('|');
})().catch(error => { window.__workspaceUxE2E = `error:${error?.stack || error}`; });
""")
                result = "running"
                result_deadline = time.time() + 30
                progress_captured = False
                materials_captured = False
                while time.time() < result_deadline:
                    marker = cdp.evaluate("window.__workspaceUxCapture || ''")
                    if capture_dir and marker == "progress" and not progress_captured:
                        capture(cdp, Path(capture_dir) / "after-processing-detail.png")
                        progress_captured = True
                    if capture_dir and marker == "materials" and not materials_captured:
                        capture(cdp, Path(capture_dir) / "after-workspace-materials.png")
                        materials_captured = True
                    result = cdp.evaluate("window.__workspaceUxE2E || ''")
                    if result != "running":
                        break
                    time.sleep(0.1)
                if result != "true|true|true|true|true|true|true|true|true|true|true|true|true|true|true|true|true|true":
                    raise RuntimeError(f"unexpected browser result: {result!r}")
            finally:
                cdp.close()
            print("workspace UX browser: progress, recovery, bilingual key review and materials lifecycle passed")
            return 0
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


if __name__ == "__main__":
    raise SystemExit(main())
