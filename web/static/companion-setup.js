const $ = id => document.getElementById(id);
let language = 'zh', snapshot = '', pairing = null, qrUrl = null, refreshing = false;
const copy = {
  zh: {title:'连接一台设备', intro:'在电脑上处理，在手机、平板或笔记本上回顾。先让设备接入同一个受控私有网络，再生成配对码。',
    generate:'生成配对码', scan:'用另一台设备扫描或打开配对地址', expiry:'配对码有效期为 5 分钟。对方申请后，在下方批准连接。',
    requests:'等待批准', refresh:'刷新', sessions:'已配对设备', back:'返回工作台', allow:'批准连接', deny:'拒绝',
    revoke:'撤销连接', confirmRevoke:'确认撤销此设备？', cancel:'保留连接', active:'已连接', revoked:'已撤销',
    noRequests:'没有待批准的请求', noSessions:'还没有配对设备', error:'暂时无法完成操作，请检查服务连接后重试。',
    code:'配对码', missingAddress:'尚未配置跨设备访问地址，请联系部署者完成私有网络设置。', qr:'一次性配对二维码'},
  en: {title:'Connect a device', intro:'Process on this computer. Review on a phone, tablet, or laptop. Join the same controlled private network before creating a pairing code.',
    generate:'Create pairing code', scan:'Scan or open this address on the other device', expiry:'The code expires in 5 minutes. Approve the request below after the other device applies.',
    requests:'Waiting for approval', refresh:'Refresh', sessions:'Paired devices', back:'Back to workspace', allow:'Approve connection', deny:'Decline',
    revoke:'Revoke connection', confirmRevoke:'Revoke this device?', cancel:'Keep connection', active:'Connected', revoked:'Revoked',
    noRequests:'No pending requests', noSessions:'No paired devices yet', error:'Unable to complete this action. Check the service connection and try again.',
    code:'Pairing code', missingAddress:'A cross-device address has not been configured. Ask your maintainer to finish private network setup.', qr:'One-time pairing QR code'}
};
const t = key => copy[language][key];
async function call(path, options = {}) {
  const response = await fetch('/api/companion' + path, {...options, headers:{'Content-Type':'application/json', ...options.headers}});
  if (!response.ok) throw new Error(t('error'));
  return response.json();
}
function translate() {
  document.documentElement.lang = language === 'zh' ? 'zh-CN' : 'en';
  document.querySelectorAll('[data-i18n]').forEach(node => node.textContent = t(node.dataset.i18n));
  $('language').textContent = language === 'zh' ? 'EN' : '中文';
  $('qr').alt = t('qr');
  if (pairing) renderPair();
  snapshot = ''; refresh();
}
function action(label, fn) {
  const button = document.createElement('button'); button.type = 'button'; button.textContent = label;
  button.onclick = async () => {
    button.disabled = true;
    try { await fn(button); $('status').textContent = ''; }
    catch (_) { $('status').textContent = t('error'); }
    finally { button.disabled = false; }
  };
  return button;
}
function row(title, state) {
  const node = document.createElement('div'); node.className = 'device-row';
  const heading = document.createElement('strong'); heading.textContent = title; node.append(heading);
  if (state) { const detail = document.createElement('span'); detail.textContent = state; node.append(detail); }
  return node;
}
async function refresh() {
  if (refreshing) return;
  refreshing = true;
  try {
    const [a,b] = await Promise.all([call('/admin/requests'), call('/admin/sessions')]);
    const signature = JSON.stringify([language,a,b]);
    if (signature === snapshot) return;
    // Do not destroy keyboard focus or an open revoke confirmation during polling.
    if (document.activeElement?.closest('.device-row') || document.querySelector('[data-revoke-confirm]')) return;
    snapshot = signature;
    $('requests').replaceChildren(...a.requests.map(x => {
      const node = row(x.display_name, x.identity?.name || '');
      for (const allow of [true,false]) node.append(action(t(allow ? 'allow' : 'deny'), async button => {
        await call('/admin/decide', {method:'POST',body:JSON.stringify({request_id:x.request_id, allow})});
        button.blur(); snapshot=''; await refresh();
      }));
      return node;
    }));
    $('sessions').replaceChildren(...b.sessions.map(x => {
      const node = row(x.display_name, t(x.revoked ? 'revoked' : 'active'));
      if (!x.revoked) node.append(action(t('revoke'), async () => {
        const confirm = document.createElement('div'); confirm.dataset.revokeConfirm = 'true';
        confirm.append(action(t('confirmRevoke'), async button => {
          await call(`/admin/sessions/${encodeURIComponent(x.id)}/revoke`, {method:'POST'});
          button.blur(); confirm.remove(); snapshot=''; await refresh();
        }), action(t('cancel'), async () => { confirm.remove(); node.querySelector('button').focus(); }));
        node.querySelector('[data-revoke-confirm]')?.remove(); node.append(confirm); confirm.querySelector('button').focus();
      }));
      return node;
    }));
    if (!a.requests.length) $('requests').textContent=t('noRequests');
    if (!b.sessions.length) $('sessions').textContent=t('noSessions');
  } catch (_) { $('status').textContent = t('error'); }
  finally { refreshing = false; }
}
function renderPair() {
  $('pair').hidden=false; $('code').textContent=`${t('code')}: ${pairing.short_code}`;
  $('url').textContent=pairing.pairing_url || t('missingAddress');
  $('qr').hidden=!pairing.qr_svg;
}
$('generate').onclick = async () => {
  $('generate').disabled=true;
  try {
    pairing=await call('/admin/pairings',{method:'POST'});
    if (qrUrl) URL.revokeObjectURL(qrUrl);
    if (pairing.qr_svg) { qrUrl=URL.createObjectURL(new Blob([pairing.qr_svg],{type:'image/svg+xml'})); $('qr').src=qrUrl; }
    renderPair(); $('status').textContent='';
  } catch (_) { $('status').textContent=t('error'); }
  finally { $('generate').disabled=false; }
};
$('refresh').onclick=refresh;
$('language').onclick=()=>{language=language==='zh'?'en':'zh';translate();};
translate();setInterval(refresh,3000);
