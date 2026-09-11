#!/usr/bin/env python3
"""Synthetic multi-surface appearance and offline portability journey; no model calls."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request

from chromium_speaker_correction_test import CDP, wait_devtools_port
from chromium_product_site_test import capture, set_viewport, wait_for_page

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'bin'))
from export_meeting import _viewer_html  # noqa: E402


def contrast(a, b):
    def luminance(value):
        value = value.strip().lstrip('#')
        if len(value) == 3:
            value = ''.join(c * 2 for c in value)
        channels = [int(value[i:i+2], 16) / 255 for i in (0, 2, 4)]
        channels = [x / 12.92 if x <= .04045 else ((x + .055) / 1.055) ** 2.4 for x in channels]
        return sum(x * w for x, w in zip(channels, [.2126, .7152, .0722]))
    a, b = sorted([luminance(a), luminance(b)])
    return (b + .05) / (a + .05)


def main():
    chrome = shutil.which('chromium') or shutil.which('chromium-browser') or shutil.which('google-chrome')
    if not chrome:
        raise RuntimeError('Chromium required for appearance validation')
    base = os.environ['MM_TEST_BASE']
    screenshots = os.environ.get('MM_APPEARANCE_SCREENSHOT_DIR')
    evidence = {'sources': {'transcript': [
        {'id': 'T0001', 'index': 0, 'speaker': 'Presenter', 'start': 0, 'end': 75, 'text': 'Synthetic demonstration.'}],
        'pages': [{'id': 'P0001', 'number': 1, 'first': 12, 'last': 75, 'title': '第1页屏幕内容',
                   'visual_description': '', 'image': None}]}, 'claims': [], 'actions': []}
    with tempfile.TemporaryDirectory(prefix='appearance-', ignore_cleanup_errors=True) as tmp:
        viewer = Path(tmp) / 'viewer.html'
        viewer.write_bytes(_viewer_html('Example launch', '2026-01-01', '<h2>Overview</h2><p>Fictional notes for review.</p>',
            evidence, {}, {'state': 'missing', 'topics': []}, None, None, content_type='media',
            minutes_languages={'zh-CN': {'html': '<h2>概览</h2><p>虚构纪要。</p>'},
                               'en': {'html': '<h2>Overview</h2><p>Fictional notes.</p>'}},
            visuals_languages={'en': [{'number': 1, 'title': 'Page 1'}]}))
        process = subprocess.Popen([chrome, '--headless=new', '--disable-gpu', '--no-sandbox',
            '--remote-debugging-port=0', '--remote-allow-origins=*', f'--user-data-dir={tmp}/profile', 'about:blank'],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            port = wait_devtools_port(Path(tmp) / 'profile/DevToolsActivePort')
            with urllib.request.urlopen(f'http://127.0.0.1:{port}/json/list') as response:
                target = next(x for x in json.load(response) if x['type'] == 'page')
            cdp = CDP(target['webSocketDebuggerUrl'])
            cdp.call('Page.enable')
            cdp.call('Runtime.enable')
            for name, url in [('server', base + '/'), ('settings', base + '/admin'),
                              ('companion', base + '/companion'), ('setup', base + '/companion/setup'),
                              ('product', base + '/product'), ('viewer', viewer.as_uri())]:
                cdp.call('Page.navigate', {'url': url})
                wait_for_page(cdp, 'document.readyState === "complete" && !!document.querySelector(".appearance-control")', name)
                if name == 'settings':
                    cdp.evaluate("document.querySelector('[data-admin-view=models]').click()")
                    wait_for_page(cdp, "document.querySelectorAll('#model-settings-fields fieldset').length===2", 'model settings')
                    assert cdp.evaluate("document.querySelector('[name=api_key]').type==='password'")
                    assert cdp.evaluate("document.querySelectorAll('#model-recommendations a[href^=\"https://huggingface.co/\"]').length>=2")
                    cdp.evaluate("const modelFetch=window.fetch;window.__modelTest=null;window.fetch=async(url,options)=>{if(String(url).endsWith('/api/settings/models/test')){window.__modelTest=JSON.parse(options.body);return new Response(JSON.stringify({ok:true,message:'Synthetic connection passed'}));}return modelFetch(url,options);};document.querySelector('[data-test=text]').click()")
                    wait_for_page(cdp, "document.querySelector('#model-settings-status').textContent==='Synthetic connection passed'", 'synthetic model test')
                    assert cdp.evaluate('window.__modelTest.role') == 'text'
                if name == 'server':
                    # Exercise long synthetic data through the real bundle-loading path.
                    fixture = json.load(urllib.request.urlopen(base + '/api/meetings/_smoke/bundle'))
                    fixture['content_type'] = 'media'
                    fixture['document_state'] = 'ready'
                    fixture['topic_map'] = {'state': 'ready', 'topics': [
                        {'id': f'topic-{i}', 'title': f'Example topic {i}', 'summary': 'Synthetic discussion',
                         'ranges': [[i, i + 1]], 'children': [], 'claim_ids': [], 'page_ids': [], 'turn_ids': []}
                        for i in range(60)]}
                    fixture['topic_map']['topics'][40]['page_ids'] = ['P0001']  # wrong cross-time citation
                    original = (fixture.get('structure', {}).get('visuals') or [{}])[0]
                    fixture.setdefault('structure', {})['visuals'] = [
                        {**original, 'id': f'P{i:04}', 'page': i, 'kind': 'slide', 'shot': True,
                         'title': f'Example frame {i}', 'first': i, 'last': i + 1, 'ranges': [[i, i + 1]],
                         'content_role': 'content', 'talking_head': False}
                        for i in range(1, 301)]
                    for visual in fixture['structure']['visuals']:
                        visual.pop('observation', None)
                    fixture['structure']['visuals'][0].update(title='无', observation={'kind':'table','tables':[], 'summary':'合成设备场景，没有数据表格。','status':'partial'})
                    fixture['structure']['visuals'][1]['observation'] = {'kind':'table','tables':[{'columns':['A'],'rows':[['1']]}], 'status':'complete'}
                    hook = 'const fixture=' + json.dumps(fixture) + ";const realFetch=window.fetch;window.fetch=async(...args)=>{const url=String(args[0]);if(url.includes('/translations/'))return new Response(JSON.stringify({state:'ready',target_language:'zh-CN',topic_map:fixture.topic_map,pages:[]}));return url.endsWith('/bundle')?new Response(JSON.stringify(fixture),{headers:{'Content-Type':'application/json'}}):realFetch(...args);};"
                    injection = cdp.call('Page.addScriptToEvaluateOnNewDocument', {'source': hook})
                    cdp.call('Page.reload')
                    wait_for_page(cdp, "!!document.querySelector('#chapters-tab:not([disabled])')", 'long fixture')
                    cdp.evaluate("document.querySelector('#chapters-tab').click()")
                    wait_for_page(cdp, "document.querySelectorAll('[data-topic-select]').length===60", 'many topics')
                    cdp.evaluate("document.querySelector('[data-topic-select=topic-45]').scrollIntoView({block:'center'});window.__topicTop=document.querySelector('.topic-map-view').scrollTop")
                    assert cdp.evaluate('window.__topicTop > 500')
                    cdp.evaluate("document.querySelector('[data-topic-select=topic-45]').click()")
                    time.sleep(.3)
                    assert cdp.evaluate('Math.abs(document.querySelector(".topic-map-view").scrollTop-window.__topicTop)<5'), 'Topic expansion lost scroll position'
                    cdp.evaluate("document.querySelector('#visuals-tab').click()")
                    wait_for_page(cdp, "!!document.querySelector('.visual-list')", 'visual panel')
                    assert cdp.evaluate("document.querySelector('[data-visual-filter=table]').textContent.trim().endsWith('1')"), 'Empty table candidate entered table filter'
                    assert cdp.evaluate("document.querySelector('.visual-detail h2').textContent !== '无'"), 'Missing title not normalized'
                    assert cdp.evaluate("document.querySelector('[data-visual-select]').closest('.media-visual-section').querySelector('summary b').textContent === 'Example topic 1'"), 'Frame followed a wrong citation instead of its time interval'
                    assert cdp.evaluate("[...document.querySelectorAll('.media-visual-section summary b')].some(x => x.textContent.includes('未关联议题的时段'))"), 'Unmatched frames lack navigable time groups'
                    assert cdp.evaluate("document.querySelector('.visual-list').scrollHeight > document.querySelector('.visual-list').clientHeight")
                    assert cdp.evaluate("document.querySelector('.visual-list').getBoundingClientRect().bottom <= document.querySelector('#visuals').getBoundingClientRect().bottom+1"), 'Visual list escaped panel'
                    cdp.evaluate("document.querySelector('.visual-list').scrollTop=2000;window.__visualTop=document.querySelector('.visual-list').scrollTop")
                    cdp.evaluate("document.querySelectorAll('[data-visual-select]')[30]?.click()")
                    assert cdp.evaluate('Math.abs(document.querySelector(".visual-list").scrollTop-window.__visualTop)<5'), 'Frame selection lost scroll position'
                    cdp.call('Page.removeScriptToEvaluateOnNewDocument', {'identifier': injection['identifier']})
                if name == 'setup':
                    cdp.evaluate('''(() => {
                      const original = window.fetch.bind(window); window.__setupWrites=[];
                      window.fetch=async (url,options={})=>{
                        if(String(url).endsWith('/admin/requests')) return new Response(JSON.stringify({requests:window.__setupApproved?[]:[{request_id:'fictional-request',display_name:'Example phone'}]}));
                        if(String(url).endsWith('/admin/sessions')) return new Response(JSON.stringify({sessions:[{id:'fictional-session',display_name:'Example tablet',revoked:!!window.__setupRevoked}]}));
                        if(String(url).endsWith('/admin/decide')) {window.__setupWrites.push(JSON.parse(options.body));window.__setupApproved=true;return new Response('{}');}
                        if(String(url).includes('/admin/sessions/fictional-session/revoke')) {window.__setupRevoked=true;return new Response('{}');}
                        return original(url,options);
                      }; document.querySelector('#refresh').click();
                    })()''')
                    wait_for_page(cdp, '!!document.querySelector("#requests button")', 'pending device')
                    cdp.evaluate('document.querySelector("#requests button").click()')
                    wait_for_page(cdp, 'window.__setupWrites.length===1', 'approve device')
                    assert cdp.evaluate('window.__setupWrites[0].allow') is True
                    cdp.evaluate('document.querySelector("#sessions button").click()')
                    wait_for_page(cdp, '!!document.querySelector("[data-revoke-confirm]")', 'revoke preview')
                    assert not cdp.evaluate('!!window.__setupRevoked'), 'Revoke skipped confirmation'
                    cdp.evaluate('document.querySelector("[data-revoke-confirm] button").click()')
                    wait_for_page(cdp, '!!window.__setupRevoked', 'confirmed revoke')
                if name == 'companion':
                    # Layout-only synthetic content; pairing behavior has a separate real API journey.
                    cdp.evaluate('document.querySelector("#pair-view").hidden=true;document.querySelector("#home-view").hidden=false; document.querySelector("#offline").hidden=true')
                for width, height in [(1440, 900), (390, 844)]:
                    set_viewport(cdp, width, height)
                    for mode in ['light', 'dark']:
                        cdp.evaluate('window.__themePlayer=document.querySelector("audio,video")')
                        cdp.evaluate(f'''(() => {{const s=document.querySelector('[name="appearance-mode"]');s.value='{mode}';s.dispatchEvent(new Event('change',{{bubbles:true}}));}})()''')
                        theme = cdp.evaluate('document.documentElement.dataset.fluentTheme')
                        assert theme == mode, (name, theme)
                        assert cdp.evaluate('window.__themePlayer === document.querySelector("audio,video")'), 'Theme recreated the player'
                        colors = cdp.evaluate('''(() => {const s=getComputedStyle(document.body);return {bg:s.backgroundColor,fg:s.color,width:document.documentElement.scrollWidth,viewport:innerWidth};})()''')
                        assert colors['bg'] != colors['fg'], (name, mode, colors)
                        assert colors['width'] <= colors['viewport'] + 1, (name, mode, colors)
                        time.sleep(.25)
                        if screenshots:
                            capture(cdp, Path(screenshots) / f'{name}-{width}-{mode}.png')
                cdp.evaluate('document.querySelector(".appearance-control").open=true')
                for accent in ['blue', 'teal', 'violet', 'amber']:
                    cdp.evaluate(f'''(() => {{const s=document.querySelector('[name="appearance-accent"]');s.value='{accent}';s.dispatchEvent(new Event('change',{{bubbles:true}}));}})()''')
                    assert cdp.evaluate('document.documentElement.dataset.accent') == accent
                    for mode in ['light', 'dark']:
                        cdp.evaluate(f'''(() => {{const s=document.querySelector('[name="appearance-mode"]');s.value='{mode}';s.dispatchEvent(new Event('change',{{bubbles:true}}));}})()''')
                        palette = cdp.evaluate('''(() => {const s=getComputedStyle(document.documentElement);return Object.fromEntries(['colorNeutralBackground1','colorNeutralForeground1','colorNeutralForeground3','colorBrandBackground','colorBrandForeground1'].map(k=>[k,s.getPropertyValue('--'+k).trim()]));})()''')
                        bg = palette['colorNeutralBackground1']
                        for foreground in ['colorNeutralForeground1', 'colorNeutralForeground3', 'colorBrandForeground1']:
                            assert contrast(bg, palette[foreground]) >= 4.5, (name, mode, accent, foreground, palette)
                        assert contrast('#fff', palette['colorBrandBackground']) >= 4.5, (mode, accent, palette)

                cdp.call('Input.dispatchKeyEvent', {'type': 'keyDown', 'key': 'Escape', 'code': 'Escape', 'windowsVirtualKeyCode': 27})
                assert not cdp.evaluate('document.querySelector(".appearance-control").open')
                assert cdp.evaluate('document.activeElement === document.querySelector(".appearance-control > summary")')
                cdp.call('Page.reload')
                wait_for_page(cdp, 'document.readyState === "complete" && !!document.querySelector(".appearance-control")', name + ' reload')
                assert cdp.evaluate('document.documentElement.dataset.accent') == 'amber'
                cdp.evaluate('document.documentElement.lang="en"')
                wait_for_page(cdp, 'document.querySelector(".appearance-label").textContent === "Appearance"', 'English appearance')
                cdp.call('Emulation.setEmulatedMedia', {'features': [{'name': 'prefers-reduced-motion', 'value': 'reduce'}]})
                assert cdp.evaluate('getComputedStyle(document.querySelector("summary")).transitionDuration') == '1e-05s'
                cdp.call('Emulation.setEmulatedMedia', {'features': []})
                if name == 'viewer':
                    cdp.evaluate("document.querySelector('[data-language=\"en\"]').click()")
                    assert cdp.evaluate('pageTitle(pages[0])') == 'Key frame · 00:12', cdp.evaluate('pageTitle(pages[0])')
                    assert not cdp.evaluate('performance.getEntriesByType("resource").some(r => /^https?:/.test(r.name))')
            cdp.sock.close()
        finally:
            process.terminate()
            process.wait(timeout=10)
    print('appearance: six surfaces, two themes, four accents, mobile, persistence, keyboard, reduced motion and offline Viewer passed')


if __name__ == '__main__':
    main()
