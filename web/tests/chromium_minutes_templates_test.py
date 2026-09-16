"""Preset editing journey using the synthetic smoke workspace only."""


def assert_minutes_templates(cdp):
    result = cdp.evaluate(r"""
(async () => {
  const $ = s => document.querySelector(s);
  const assert = (ok, message) => { if (!ok) throw new Error(message); };
  const wait = async fn => {
    for (let i = 0; i < 100; i++) {
      if (fn()) return;
      await new Promise(resolve => setTimeout(resolve, 30));
    }
    throw new Error('preset preview timed out');
  };
  const realFetch = window.fetch;
  const requests = [];
  window.fetch = async (url, init) => {
    if (String(url).includes('/assistant/')) {
      requests.push({url:String(url), body:JSON.parse(init.body)});
      assert(String(url).endsWith('/assistant/restructure/preview'), 'preset must only preview');
      return new Response(JSON.stringify({proposal_id:'synthetic-preset',scope:'document',
        summary:'Synthetic study notes', target_heading:'Learning guide', sources:[],
        before:'# Original', after:'# Study notes\n\n## Concepts\n\n- Synthetic concept.'}),
        {status:200,headers:{'Content-Type':'application/json'}});
    }
    return realFetch(url, init);
  };
  try {
    $('#minutes-tab').click();
    const trigger = $('#restructure-minutes');
    assert(!trigger.disabled, 'ready minutes allow restructure');
    trigger.focus(); trigger.click();
    const dialog = $('#minutes-template-dialog');
    const select = $('#minutes-template-select');
    const input = $('#minutes-template-prompt');
    const generate = dialog.querySelector('[type=submit]');
    assert(dialog.open && document.activeElement === select, 'native modal focus');
    assert(select.options.length === 5 && input.value.includes('学习导览'), 'training preset');
    const edited = input.value + '\n优先解释虚构案例。';
    input.value = edited; input.dispatchEvent(new Event('input'));
    select.value = 'review'; select.dispatchEvent(new Event('change'));
    assert(input.value.includes('评审目标'), 'switch preset');
    select.value = 'training'; select.dispatchEvent(new Event('change'));
    assert(input.value === edited, 'switch preserves edits');
    dialog.querySelector('[data-template-cancel]').click();
    assert(!dialog.open && document.activeElement === trigger, 'cancel restores focus');
    trigger.click();
    assert(input.value === edited && requests.length === 0, 'reopen preserves edits without model call');
    select.value = 'custom'; select.dispatchEvent(new Event('change'));
    assert(input.value === '' && generate.disabled, 'empty custom prompt cannot generate');
    select.value = 'training'; select.dispatchEvent(new Event('change'));
    generate.click();
    await wait(() => $('.apply-edit[data-id="synthetic-preset"]'));
    assert(requests.length === 1 && requests[0].body.message === edited, 'edited prompt sent once');
    assert(requests[0].body.transcript_revision && requests[0].body.minutes_revision, 'revision bound preview');
    assert($('.apply-edit[data-id="synthetic-preset"]').textContent.includes('阅读版本'), 'separate reading view');
    $('.dismiss-edit').click();
    $('#utility-close').click();
    return true;
  } finally { window.fetch = realFetch; }
})()
""")
    assert result is True, result


def assert_minutes_templates_responsive(cdp):
    result = cdp.evaluate(r"""
(async () => {
  const source = document.querySelector('script[type="module"][src*="app.js"]').src;
  const version = new URL(source).search;
  const { createMinutesTemplateDialog, minutesTemplate, MINUTES_TEMPLATES } =
    await import(`/static/modules/minutes-templates.js${version}`);
  const dialog = document.querySelector('#minutes-template-dialog').cloneNode(true);
  document.body.appendChild(dialog);
  const editor = createMinutesTemplateDialog(dialog);
  const root = document.documentElement;
  const originalTheme = root.getAttribute('data-theme');
  try {
    for (const item of MINUTES_TEMPLATES) for (const english of [false, true]) {
      const prompt = minutesTemplate(item.id, english).prompt;
      if (prompt.length > 8000 || (item.id !== 'custom' && !prompt)) throw new Error('invalid template');
    }
    for (const theme of ['dark', 'light']) {
      root.setAttribute('data-theme', theme);
      editor.show({english:true,onGenerate:()=>{throw new Error('unexpected generation');}});
      if (!dialog.textContent.includes('Knowledge sharing / training')) throw new Error('missing English copy');
      if (dialog.scrollWidth > dialog.clientWidth + 1 || dialog.getBoundingClientRect().right > innerWidth)
        throw new Error('preset dialog overflows narrow viewport');
      const text = dialog.querySelector('textarea');
      text.value = 'Discard this meeting draft';
      text.dispatchEvent(new Event('input'));
      editor.reset();
      editor.show({english:true});
      if (!text.value.includes('Learning guide')) throw new Error('draft leaked across meetings');
      editor.reset();
    }
    return true;
  } finally {
    editor.reset(); dialog.remove();
    if (originalTheme === null) root.removeAttribute('data-theme');
    else root.setAttribute('data-theme', originalTheme);
  }
})()
""")
    assert result is True, result
