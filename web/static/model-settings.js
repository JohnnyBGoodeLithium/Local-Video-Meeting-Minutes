/* Model secrets never enter localStorage or meeting exports. */
(() => {
  'use strict';
  const form = document.querySelector('#model-settings-form');
  const status = document.querySelector('#model-settings-status');
  const fields = document.querySelector('#model-settings-fields');
  const labels = {text: '文本与纪要', vision: '画面理解'};
  const escape = value => String(value || '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  function render(data) {
    fields.innerHTML = Object.entries(labels).map(([role, title]) => {
      const c = data.settings[role];
      return `<fieldset data-role="${role}" style="max-width:760px;margin:16px 0;padding:20px"><legend>${title}</legend>
      <label>来源 <select name="source"><option value="local" ${c.source === 'local' ? 'selected' : ''}>本地服务</option><option value="cloud" ${c.source === 'cloud' ? 'selected' : ''}>云端服务</option></select></label>
      <label>API Base URL <input name="api" type="url" required value="${escape(c.api)}" placeholder="http://127.0.0.1:11435/v1"></label>
      <label>模型 ID <input name="model" required value="${escape(c.model)}"></label>
      ${role === 'text' ? `<label>正式纪要模型 ID <input name="minutes_model" required value="${escape(c.minutes_model)}"></label>` : ''}
      <label>API Key <input name="api_key" type="password" autocomplete="new-password" placeholder="${c.key_configured ? '已保存；留空保留' : '本地无认证服务可留空'}"></label>
      <label><input name="clear_key" type="checkbox">清除已保存密钥</label>
      <label><input name="allow_cloud" type="checkbox" ${c.allow_cloud ? 'checked' : ''}>允许将此类任务的内容发送到所配置云端服务</label>
      <button type="button" data-test="${role}">测试连接</button></fieldset>`;
    }).join('');
    document.querySelector('#model-recommendations').innerHTML = data.recommendations.map(r => `<li><a href="${escape(r.url)}" target="_blank" rel="noopener noreferrer">${escape(r.name)} · Hugging Face</a> — ${escape(r.use)}</li>`).join('');
    status.textContent = data.restart_required ? '已保存的配置尚未生效，请在当前任务结束后重启服务。' : '当前配置已加载。';
  }
  function collect() {
    const result = {};
    fields.querySelectorAll('fieldset').forEach(group => {
      const c = {};
      group.querySelectorAll('[name]').forEach(input => c[input.name] = input.type === 'checkbox' ? input.checked : input.value.trim());
      result[group.dataset.role] = c;
    });
    return result;
  }
  async function send(path, method, body) {
    const response = await fetch('/api/settings/models' + path, {method, headers: {'Content-Type':'application/json'}, body: JSON.stringify(body)});
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail || '请求失败');
    return result;
  }
  async function busy(action) {
    form.querySelectorAll('button').forEach(b => b.disabled = true);
    try { await action(); } catch (error) { status.textContent = error.message; }
    finally { form.querySelectorAll('button').forEach(b => b.disabled = false); }
  }
  form.addEventListener('submit', event => {
    event.preventDefault();
    busy(async () => render(await send('', 'PUT', collect())));
  });
  fields.addEventListener('click', event => {
    const button = event.target.closest('[data-test]');
    if (!button) return;
    busy(async () => { status.textContent = '正在发送合成测试内容…'; const data = await send('/test', 'POST', {role:button.dataset.test, settings:collect()}); status.textContent = data.message; });
  });
  fetch('/api/settings/models').then(async response => {if (!response.ok) throw new Error('模型配置仅支持在服务所在机器管理');return response.json();}).then(render).catch(error => status.textContent = error.message);
})();
