<?php // helios-container managed web gateway
declare(strict_types=1);
const HC_PORT = __HC_PORT__;
const HC_BRIDGE = '__HC_BRIDGE__';
ini_set('display_errors', '0');
header('X-Content-Type-Options: nosniff');
$path = $_SERVER['PATH_INFO'] ?? '';
$script = $_SERVER['SCRIPT_NAME'];
$rawPath = explode('?', $_SERVER['REQUEST_URI'] ?? '', 2)[0];
if (str_starts_with($rawPath, $script . '/')) $path = substr($rawPath, strlen($script));
if ($path === '' || $path === '/') {
    if ($_SERVER['REQUEST_METHOD'] !== 'GET' && $_SERVER['REQUEST_METHOD'] !== 'HEAD') {
        http_response_code(405); exit;
    }
    $nonce = bin2hex(random_bytes(16));
    header('Content-Type: text/html; charset=utf-8');
    header('Cache-Control: no-store');
    header('Referrer-Policy: no-referrer');
    header("Content-Security-Policy: default-src 'none'; script-src 'nonce-$nonce'; style-src 'nonce-$nonce'; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'");
?>
<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Helios · Личная панель</title>
<style nonce="<?= $nonce ?>">
:root{font-family:Inter,system-ui,-apple-system,sans-serif;color:#182536;background:#f5f7fa;color-scheme:light dark;--panel:#fff;--line:#e1e6ed;--muted:#68778a;--blue:#087be8;--soft:#edf5ff;--sidebar:#f6f8fb}
*{box-sizing:border-box}html,body{width:100%;height:100%;margin:0;overflow:hidden}body{height:100dvh}button,input,select{font:inherit}button{cursor:pointer;border:1px solid var(--line);background:var(--panel);color:inherit;border-radius:6px;padding:8px 12px;font-size:13px}button:hover{background:var(--soft)}button:disabled{opacity:.45;cursor:default}button.primary{background:var(--blue);border-color:var(--blue);color:#fff}a{color:var(--blue)}[hidden]{display:none!important}input,select{padding:9px 11px;border:1px solid var(--line);border-radius:6px;background:var(--panel);color:inherit;font-size:13px}input:focus,button:focus-visible,select:focus{outline:2px solid #087be860;outline-offset:2px}input[type=checkbox]{accent-color:var(--blue)}h1{font-size:25px;letter-spacing:-.035em;margin:0}h2{font-size:16px;margin:0 0 12px}p{color:var(--muted);line-height:1.6;font-size:13px}small{display:block;color:var(--muted);font-size:11px;margin-top:4px;font-weight:400;overflow-wrap:anywhere}
.app{height:100%;display:grid;grid-template-rows:52px minmax(0,1fr) 28px}.topbar{display:flex;align-items:center;justify-content:space-between;padding:0 20px;background:#102d4d;color:#fff}.brand{font-size:14px;font-weight:650;letter-spacing:.02em}.brand-icon{color:#69b8ff;margin-right:10px}.topbar small{color:#a4bdd6;margin:0}.layout{display:grid;grid-template-columns:208px minmax(0,1fr);min-height:0}.sidebar{background:var(--sidebar);border-right:1px solid var(--line);padding:24px 12px;display:flex;flex-direction:column;gap:5px;min-height:0;overflow:auto}.nav-label{font-size:10px;color:var(--muted);text-transform:uppercase;letter-spacing:.12em;padding:0 12px;margin:0 0 12px}.sidebar button{text-align:left;border:0;background:transparent;padding:12px;display:flex;gap:12px;align-items:center;font-size:14px}.sidebar button[aria-selected=true]{background:#e1efff;color:#086cc5;font-weight:600}.nav-icon{width:19px;font-size:17px;text-align:center}.sidebar .spacer{flex:1}.sidebar-note{padding:12px;font-size:11px;color:var(--muted);line-height:1.6}.workspace{min-width:0;min-height:0;display:flex;flex-direction:column;background:var(--panel)}.view{flex:1;min-height:0;display:flex;flex-direction:column}.view-head{padding:26px 28px 18px;flex-shrink:0}.view-head p{margin:8px 0 16px}.headline{display:flex;align-items:center;justify-content:space-between;gap:16px}.toolbar{display:flex;align-items:center;gap:12px;flex-wrap:wrap}.toolbar label{font-size:12px;display:flex;align-items:center;gap:7px;color:var(--muted)}.search{width:min(320px,100%)}.summary{display:flex;gap:36px;padding:14px 0 0;margin-top:16px;border-top:1px solid var(--line)}.summary strong{font-size:19px;font-weight:600}.summary span{display:block;color:var(--muted);font-size:11px;margin-top:3px}.scroll-area{flex:1;min-height:0;overflow:auto;padding:0 28px 24px;overscroll-behavior:contain}.table-wrap{border:1px solid var(--line);border-radius:8px;overflow:visible}table{width:100%;border-collapse:collapse;font-size:13px}td{overflow-wrap:anywhere}#containers-view th:first-child{width:25%}#containers-view th:last-child{width:95px}th{text-align:left;font-size:11px;letter-spacing:.02em;font-weight:500;color:var(--muted);background:var(--sidebar);position:sticky;top:0;z-index:1}th,td{padding:14px 16px;border-bottom:1px solid var(--line);vertical-align:middle}tbody tr:last-child td{border-bottom:0}tbody tr:hover{background:#087be804}.name-button{border:0;padding:0;background:transparent;text-align:left;font-weight:600;color:var(--blue);overflow-wrap:anywhere}.name-button:hover{background:transparent;text-decoration:underline}.actions{display:flex;gap:6px;justify-content:flex-end;white-space:nowrap}.actions button{font-size:16px;padding:4px 9px;min-width:34px}.badge{display:inline-flex;align-items:center;gap:6px;font-size:11px;color:var(--muted);white-space:nowrap}.badge:before{content:'';width:7px;height:7px;border-radius:50%;background:#9ca9b7}.badge.running{color:#248452}.badge.running:before{background:#29a668}.badge.exited:before,.badge.dead:before{background:#da6470}.project{background:var(--sidebar);font-weight:600}.project button.disclosure{border:0;background:transparent;text-align:left;padding:0;font-weight:600}.child td:first-child{padding-left:40px}.notice{font-size:12px;color:var(--muted);line-height:1.6;margin:14px 0}.error{color:#c84553}.empty{padding:40px;text-align:center;color:var(--muted)}.footer{background:var(--sidebar);border-top:1px solid var(--line);display:flex;align-items:center;justify-content:space-between;padding:0 16px;font-size:10px;color:var(--muted)}.footer span:first-child:before{content:'●';color:#29a668;margin-right:8px}.message{font-size:12px;line-height:1.5;margin-top:12px;min-height:18px}.detail-head{padding:20px 28px 0;flex-shrink:0}.back{border:0;padding-left:0;color:var(--blue);margin-bottom:14px}.detail-meta{color:var(--muted);font-size:12px;margin:10px 0 18px;overflow-wrap:anywhere}.detail-tabs{display:flex;gap:24px;border-bottom:1px solid var(--line)}.detail-tabs button{border:0;border-radius:0;padding:12px 0;background:transparent;color:var(--muted)}.detail-tabs button[aria-selected=true]{border-bottom:2px solid var(--blue);color:var(--blue)}.detail-body{flex:1;min-height:0;display:flex;flex-direction:column;padding:18px 28px 22px}.log-toolbar{flex-shrink:0;margin-bottom:12px}.log-toolbar select{padding:7px}.log-status{font-size:11px;color:var(--muted);margin:0 0 10px;flex-shrink:0}pre{flex:1;min-height:0;margin:0;overflow:auto;padding:20px;background:#111a27;color:#d7e4f3;border-radius:8px;font:12px/1.7 ui-monospace,SFMono-Regular,Consolas,monospace;white-space:pre-wrap;overflow-wrap:anywhere;overscroll-behavior:contain}.detail-info{overflow:auto;flex:1;min-height:0}.detail-info dl{display:grid;grid-template-columns:150px minmax(0,1fr);gap:14px;font-size:13px}.detail-info dt{color:var(--muted)}.detail-info dd{margin:0;overflow-wrap:anywhere}.port-card{width:min(100%,520px);margin:35px auto;padding:28px;border:1px solid var(--line);border-radius:12px}.port-card label{font-size:13px;font-weight:600;display:block;margin-bottom:8px}.port-card input{width:100%;padding:12px}.port-card button{margin-top:18px}.port-card output{display:block;font-size:13px;line-height:1.7;overflow-wrap:anywhere;margin-top:18px}.port-card output a{display:block;margin-top:8px}.port-card h1{margin-bottom:8px}.routes-list>div{padding:12px 0;border-bottom:1px solid var(--line);font-size:13px;line-height:1.8}
@media(prefers-color-scheme:dark){:root{color:#d7e1ed;background:#141c27;--panel:#182230;--sidebar:#131e2c;--line:#2a3748;--muted:#95a7bd;--soft:#223951}.sidebar button[aria-selected=true]{background:#203e5c;color:#84c3ff}.topbar{background:#0c1c2f}.badge.running{color:#77d4a2}}
@media(max-width:760px){.layout{grid-template-columns:62px minmax(0,1fr)}.sidebar{padding:20px 6px}.sidebar button{justify-content:center;padding:12px 8px}.nav-text,.nav-label,.sidebar-note{display:none}.view-head,.detail-head{padding:18px 16px 12px}.scroll-area{padding:0 16px 18px}.detail-body{padding:14px 16px}.summary{gap:18px}.summary strong{font-size:16px}.topbar{padding:0 14px}.topbar small{display:none}th,td{padding:12px 10px}.table-wrap{min-width:670px}.port-card{padding:20px}.headline{align-items:flex-start}.actions{flex-wrap:wrap}}
:root{color-scheme:dark;color:#dce6f2;background:#0f141b;--panel:#0f141b;--sidebar:#111922;--line:#303b48;--muted:#899bad;--blue:#2b91ff;--soft:#172b40}.topbar{background:#101f32}.sidebar button[aria-selected=true]{background:#17334f;color:#76baff}.view-head{padding:22px 24px 14px}.scroll-area{padding:0 24px 20px}.summary{margin-top:14px;padding-top:12px;gap:50px}.summary strong{font-size:17px;color:#38c2ad}.summary span{font-size:11px}.table-wrap{border:0;border-radius:0}table{font-size:12px}th,td{padding:9px 12px;border-bottom:1px solid var(--line);white-space:nowrap}td{max-width:290px;overflow:hidden;text-overflow:ellipsis}th{background:var(--panel);border-right:1px solid var(--line);font-size:11px}th:last-child{border-right:0}#containers-view th:first-child,.state-cell{width:25px;padding:9px 4px}#containers-view th:nth-child(2){width:20%}#containers-view th:last-child{width:85px}.child td:first-child{padding-left:4px}.child td:nth-child(2){padding-left:32px}.badge{font-size:0;gap:0}.badge:before{width:7px;height:7px}.project{background:transparent}.mono{font-family:ui-monospace,monospace;font-size:11px}.image-cell{color:var(--blue)}.actions button{border:0;background:transparent;color:var(--blue);padding:2px 5px;min-width:25px}.actions button:hover{background:var(--soft)}.actions button.danger-icon{color:#e77180}.project .disclosure{color:#dce6f2}.name-button{color:#dce6f2;font-size:12px}.log-line{display:block;min-height:1.7em}.log-time{color:#72869e}.log-error{color:#ff8791}.log-warn{color:#f0c46a}.log-info{color:#87c7f5}.log-debug{color:#91a1b5}dialog{width:min(480px,calc(100vw - 32px));border:1px solid var(--line);border-radius:12px;background:var(--sidebar);color:inherit;padding:26px}dialog::backdrop{background:#0009}.delete-name{font:12px/1.6 ui-monospace,monospace;overflow-wrap:anywhere;color:#c1d7ef}.dialog-actions{display:flex;justify-content:flex-end;gap:10px;margin-top:22px}button.danger{background:#b84050;color:white;border-color:#b84050}
@media(max-width:760px){.table-wrap{min-width:980px}.summary{gap:18px;flex-wrap:wrap}.summary strong{font-size:14px}.view-head{padding:18px 16px 12px}.scroll-area{padding:0 16px 18px}}
.actions button.danger-icon{border-left:1px solid var(--line);border-radius:0;margin-left:7px;padding-left:12px}
.app{grid-template-rows:52px minmax(0,1fr) 38px}.footer{gap:16px;overflow-x:auto;white-space:nowrap}.engine-panel{display:flex;align-items:center;gap:12px}.engine-panel button{padding:3px 6px;font-size:11px}.engine-controls{display:flex;align-items:center;gap:5px}.engine-resources{font-size:10px;color:var(--muted)}.kit-version{margin-left:auto;color:var(--blue)}.footer #operation-status{max-width:300px;overflow:hidden;text-overflow:ellipsis}
.topbar{gap:12px}.topbar .update-notice{background:#edf5ff;color:#075aab;border-color:#69b8ff;font-weight:600;white-space:nowrap}.update-notice:before{content:'↑';margin-right:8px}#release-dialog{width:min(700px,calc(100vw - 32px));max-height:85dvh}#release-notes{white-space:pre-wrap;overflow-wrap:anywhere;max-height:45dvh;overflow:auto;font:13px/1.7 inherit;padding:16px;background:var(--panel);border:1px solid var(--line);border-radius:8px}#release-version{color:var(--muted);font-size:13px}.release-command{font:12px/1.6 ui-monospace,monospace;overflow-wrap:anywhere}@media(max-width:760px){.topbar small{display:none}.topbar{padding:0 12px}.topbar .update-notice{font-size:11px;padding:7px}.brand{font-size:12px}}
</style></head><body>
<main class="app"><header class="topbar"><div class="brand"><span class="brand-icon">▦</span>Helios Container</div><button id="update-notice" class="update-notice" type="button" aria-haspopup="dialog" aria-controls="release-dialog" hidden></button><small>Личный Docker · FreeBSD → Linux VM</small></header>
<div class="layout"><nav class="sidebar" role="tablist" aria-label="Личная панель" aria-orientation="vertical"><div class="nav-label">Навигация</div>
<button id="containers-tab" role="tab" aria-selected="true" aria-controls="containers-view" title="Контейнеры"><span class="nav-icon">▦</span><span class="nav-text">Контейнеры</span></button>
<button id="images-tab" role="tab" aria-selected="false" aria-controls="images-view" tabindex="-1" title="Образы"><span class="nav-icon">◈</span><span class="nav-text">Образы</span></button>
<button id="volumes-tab" role="tab" aria-selected="false" aria-controls="volumes-view" tabindex="-1" title="Volumes"><span class="nav-icon">▤</span><span class="nav-text">Volumes</span></button>
<button id="ports-tab" role="tab" aria-selected="false" aria-controls="ports-view" tabindex="-1" title="Порты"><span class="nav-icon">⇄</span><span class="nav-text">Порты</span></button>
<div class="spacer"></div><div class="sidebar-note">Доступ по личному ключу.<br>Ресурсы вашей VM.</div></nav>
<div class="workspace">
<section id="containers-view" class="view" role="tabpanel" aria-labelledby="containers-tab"><header class="view-head"><div class="headline"><h1>Контейнеры</h1><div class="toolbar"><button id="refresh" class="primary">Обновить</button><label><input id="auto" type="checkbox" checked>Polling · 10 с</label></div></div><p>Проекты Compose и отдельные контейнеры.</p><div class="toolbar"><input id="search" class="search" type="search" placeholder="Поиск проекта, контейнера или образа" aria-label="Поиск контейнеров"><label><input id="running-only" type="checkbox">Только запущенные</label></div><div class="summary"><div><strong id="count-card">—</strong><span>Запущено / всего</span></div><div><strong id="cpu-card">—</strong><span id="cpu-caption">Загрузка CPU контейнеров</span></div><div><strong id="memory-card">—</strong><span>Память контейнеров / память VM</span></div></div><div id="dashboard-status" class="message" role="status"></div><div id="action-status" class="message" role="status" hidden></div></header><div class="scroll-area"><div class="table-wrap"><table><thead><tr><th aria-label="Состояние"></th><th>Имя</th><th>ID контейнера</th><th>Образ</th><th>Порты</th><th>CPU (%)</th><th>Память</th><th>Последний запуск</th><th>Действия</th></tr></thead><tbody id="containers"></tbody></table></div><div id="filter-result" class="notice"></div></div></section>
<section id="images-view" class="view" role="tabpanel" aria-labelledby="images-tab" hidden><header class="view-head"><h1>Образы</h1><p>Локальный каталог образов в вашей VM.</p><input id="image-search" class="search" type="search" placeholder="Поиск образа" aria-label="Поиск образов"><div id="image-count" class="message"></div></header><div class="scroll-area"><div class="table-wrap"><table><thead><tr><th aria-label="Использование"></th><th>Имя</th><th>Тег</th><th>ID образа</th><th>Создан</th><th>Размер</th><th>Контейнеры</th><th>Действия</th></tr></thead><tbody id="images"></tbody></table></div><div class="notice">Образ хранится на диске. Запуск и остановка относятся к его контейнерам.</div></div></section>
<section id="volumes-view" class="view" role="tabpanel" aria-labelledby="volumes-tab" hidden><header class="view-head"><h1>Volumes</h1><p>Тома данных и контейнеры, которые их используют.</p><input id="volume-search" class="search" type="search" placeholder="Поиск volume" aria-label="Поиск volumes"><div id="volume-count" class="message"></div></header><div class="scroll-area"><div class="table-wrap"><table><thead><tr><th aria-label="Использование"></th><th>Имя</th><th>Проект</th><th>Контейнеры</th><th>Создан</th><th>Размер</th><th>Действия</th></tr></thead><tbody id="volumes"></tbody></table></div><div class="notice">Размеры измеряются Docker в фоне не чаще раза в минуту. Удалить можно только том, не связанный с контейнерами.</div></div></section>
<section id="ports-view" class="view" role="tabpanel" aria-labelledby="ports-tab" hidden><div class="scroll-area"><form id="ports-form" class="port-card"><h1>Порты приложения</h1><p>Получите HTTPS-адрес backend для вашего frontend.</p><label for="ports">Порты backend</label><input id="ports" name="ports" placeholder="8080, 8081, host:3000" autocomplete="off" maxlength="160"><small>8080 — порт VM. host:3000 — ваш процесс на helios. Пустое поле закрывает публичные адреса.</small><button class="primary" type="submit">Сохранить порты</button><output id="result" aria-live="polite"></output></form><h2>Опубликованные адреса</h2><div id="routes" class="routes-list"></div><p>Браузер → HTTPS → PHP-шлюз → HTTP backend. WebSocket и SSE через этот шлюз не поддерживаются. Polling панели работает через HTTPS.</p></div></section>
<section id="detail-view" class="view" hidden><header class="detail-head"><button id="back" class="back">← Контейнеры</button><div class="headline"><h1 id="detail-title">Контейнер</h1><div id="detail-actions" class="actions"></div></div><div id="detail-meta" class="detail-meta"></div><nav class="detail-tabs" role="tablist" aria-label="Информация о контейнере"><button id="logs-tab" role="tab" aria-selected="true" aria-controls="logs-content">Логи</button><button id="info-tab" role="tab" aria-selected="false" aria-controls="info-content" tabindex="-1">Обзор</button></nav></header><div class="detail-body"><div id="logs-content" class="view" role="tabpanel" aria-labelledby="logs-tab"><div class="toolbar log-toolbar"><label for="tail">Последние строки</label><select id="tail"><option>100</option><option selected>200</option><option>500</option><option>1000</option></select><button id="refresh-logs">Обновить логи</button></div><div id="log-status" class="log-status" role="status"></div><pre id="logs"></pre></div><div id="info-content" class="detail-info" role="tabpanel" aria-labelledby="info-tab" hidden></div></div></section>
</div></div><footer class="footer"><span id="engine-status">Docker Engine · состояние неизвестно</span><span id="operation-status" role="status">Helios Container · HTTPS polling</span></footer></main><dialog id="delete-dialog" aria-labelledby="delete-title" aria-describedby="delete-warning"><h2 id="delete-title"></h2><div id="delete-name" class="delete-name"></div><p id="delete-warning"></p><div class="dialog-actions"><button id="delete-cancel">Отмена</button><button id="delete-confirm" class="danger">Удалить</button></div></dialog>
<script nonce="<?= $nonce ?>">
const key = new URLSearchParams(location.hash.slice(1)).get('key') || '';
history.replaceState(null, '', location.pathname + location.search);
const $ = selector => document.querySelector(selector);
let activeView = 'containers', snapshot = null, busy = false, selected = '', logBusy = false, pending = '', actionBusy = false;
const collapsed = new Set(), views = ['containers','images','volumes','ports'];
let deleteTarget = null;
const relative = new Intl.RelativeTimeFormat('ru', {numeric:'auto'});
function bytesText(bytes) { if (bytes == null) return '—'; const units=['Б','КиБ','МиБ','ГиБ','ТиБ']; let n=Number(bytes), index=0; while(n>=1024 && index<4){n/=1024;index++;} return n.toLocaleString('ru-RU',{maximumFractionDigits:index>1?2:0}) + ' ' + units[index]; }
function age(value) { if (!value || value.startsWith('0001-')) return 'Не запускался'; const stamp=Date.parse(value); if (!Number.isFinite(stamp)) return value; const seconds=(stamp-Date.now())/1000; for (const [unit,scale] of [['year',31536000],['month',2592000],['day',86400],['hour',3600],['minute',60]]) if (Math.abs(seconds)>=scale) return relative.format(Math.round(seconds/scale),unit); return relative.format(Math.round(seconds),'second'); }
const stateNames = {running:'Запущен',exited:'Остановлен',created:'Создан',paused:'Приостановлен',restarting:'Перезапуск',dead:'Ошибка'};
function el(tag, text='') { const node = document.createElement(tag); node.textContent = text; return node; }
function badge(state, text) { const node = el('span', text || stateNames[state] || state); node.className = 'badge ' + state; return node; }
function empty(body, columns, text) { const row = el('tr'), cell = el('td', text); cell.colSpan = columns; cell.className = 'empty'; row.append(cell); body.append(row); }
const releaseDialog=el('dialog'); releaseDialog.id='release-dialog'; releaseDialog.setAttribute('aria-labelledby','release-title');
const releaseTitle=el('h2','Что нового'); releaseTitle.id='release-title';
const releaseVersion=el('p'); releaseVersion.id='release-version';
const releaseNotes=el('div'); releaseNotes.id='release-notes';
const releaseHelp=el('p'); releaseHelp.className='release-command';
const releaseButtons=el('div'); releaseButtons.className='dialog-actions';
const releaseLink=el('a','Открыть полный changelog'); releaseLink.target='_blank'; releaseLink.rel='noopener noreferrer';
const releaseClose=el('button','Закрыть'); releaseClose.type='button'; releaseClose.addEventListener('click',()=>releaseDialog.close());
releaseButtons.append(releaseLink,releaseClose); releaseDialog.append(releaseTitle,releaseVersion,releaseNotes,releaseHelp,releaseButtons); document.body.append(releaseDialog);
function renderRelease() {
  const update=snapshot && snapshot.update, button=$('#update-notice');
  const valid=update && update.available===true && /^\d+\.\d+\.\d+$/.test(update.latest_version || '');
  button.hidden=!valid;
  if(!valid) { if(releaseDialog.open) releaseDialog.close(); return; }
  button.textContent='Доступна версия '+update.latest_version+' · Что нового';
  button.title='Посмотреть изменения версии '+update.latest_version;
  releaseVersion.textContent='Установлена '+update.current_version+' → доступна '+update.latest_version;
  releaseNotes.textContent=update.notes || 'Описание изменений доступно на странице релиза.';
  releaseHelp.textContent=update.compatible ? 'Для обновления на helios: helios-container stop, затем helios-container update. Данные сохранятся.' : 'Для этой версии пока нет совместимой Rust-сборки FreeBSD amd64. Можно ознакомиться с изменениями на GitHub.';
  // Construct the URL ourselves; release text is always plain text, never HTML.
  const expected='https://github.com/RedGry/helios-container/releases/tag/';
  releaseLink.href=expected+'v'+update.latest_version;
  if(typeof update.changelog_url==='string' && new RegExp('^'+expected+'v?'+update.latest_version.replaceAll('.','\\.')+'$').test(update.changelog_url)) releaseLink.href=update.changelog_url;
}
$('#update-notice').addEventListener('click',()=>{renderRelease(); if(!$('#update-notice').hidden && !releaseDialog.open) releaseDialog.showModal();});
async function api(path, method='GET', body) {
  if (!key) throw new Error('Откройте приватную ссылку из helios-container web info.');
  const response = await fetch(new URL('index.php/' + path, location.href), {method,headers:{'X-HC-Admin':key,'Content-Type':'application/json'},body:body && JSON.stringify(body),cache:'no-store'});
  const data = await response.json(); if (!response.ok) throw new Error(data.error || 'Шлюз недоступен.'); return data;
}
function actions(kind, id, running) {
  const box = el('div'); box.className = 'actions';
  for (const [action, title] of [[running ? 'stop' : 'start',running ? 'Остановить' : 'Запустить'],['restart','Перезапустить']]) {
    const button = el('button',({start:'▶',stop:'■',restart:'↻'}[action])); button.type = 'button'; button.title = title; button.setAttribute('aria-label',title); button.disabled = Boolean(pending || actionBusy); button.addEventListener('click', () => runAction(kind,id,action)); box.append(button);
  }
  if(kind==='container' && snapshot) { const item=snapshot.containers.find(c=>c.ID===id); if(item) box.append(removeButton('container',item)); }
  if(kind==='project' && snapshot) { const members=snapshot.containers.filter(c=>c.project===id); box.append(removeButton('project',{ID:id,Name:id,members})); }
  return box;
}
function actionStatus(text) { $('#action-status').hidden = false; $('#action-status').textContent = text; $('#operation-status').textContent = text; }
async function runAction(kind,id,action,extra={}) {
  if (pending || actionBusy) return;
  actionBusy = true; actionStatus('Отправляю команду…'); render();
  try { const job = await api('_action','POST',{kind,id,action,...extra}); pending = job.id; actionStatus('Выполняется ' + ({start:'запуск',stop:'остановка',restart:'перезапуск',delete:'удаление'}[action]) + '…'); await pollAction(); }
  catch (error) { actionStatus(error.message); }
  finally { actionBusy = false; render(); }
}
async function pollAction() {
  if (!pending) return;
  try { const job = await api('_action?' + new URLSearchParams({id:pending})); if (job.status !== 'running') { pending = ''; actionStatus(job.error || 'Операция завершена. Приложение может ещё загружаться.'); await refresh(); render(); } }
  catch (error) { pending = ''; actionStatus(error.message); render(); }
}
function portText(value) {
  const parts=value.split(',').map(x=>x.trim()), mapped=parts.filter(x=>x.includes('->'));
  return [...new Set((mapped.length?mapped:parts).map(x=>x.replace(/^(?:[0-9.]+|\[::\]):/,'')))].join(', ') || '—';
}
function containerRow(item, child) {
  const row=el('tr'); if(child) row.className='child';
  const state=el('td'); state.className='state-cell'; const dot=badge(item.State,''); dot.textContent=''; dot.title=(stateNames[item.State] || item.State) + ' · ' + item.Status; dot.setAttribute('aria-label',dot.title); state.append(dot);
  const name=el('td'), open=el('button',item.service || item.Names); open.className='name-button'; open.title=item.Names; open.addEventListener('click',()=>openContainer(item.ID)); name.append(open);
  const id=el('td',item.ID.slice(0,12)); id.className='mono'; id.title=item.ID;
  const image=el('td',item.Image.startsWith('sha256:')?item.Image.slice(0,19)+'…':item.Image); image.className='image-cell'; image.title=item.Image;
  const ports=el('td',portText(item.Ports)); ports.title=item.Ports;
  const buttons=el('td'); buttons.append(actions('container',item.ID,item.State==='running'));
  row.append(state,name,id,image,ports,el('td',item.metrics.CPUPerc || '—'),el('td',item.metrics.MemUsage || '—'),el('td',age(item.started_at)),buttons); return row;
}
function renderContainers() {
  const body = $('#containers'); body.replaceChildren(); if (!snapshot) return;
  const query = $('#search').value.trim().toLowerCase(), runningOnly = $('#running-only').checked;
  const visible = snapshot.containers.filter(c => (!runningOnly || c.State === 'running') && [c.Names,c.Image,c.project,c.service].join(' ').toLowerCase().includes(query));
  const projects = new Map(); for (const item of visible) { const name = item.project || ''; if (!projects.has(name)) projects.set(name,[]); projects.get(name).push(item); }
  for (const [project, items] of projects) {
    if (!project) { for (const item of items) body.append(containerRow(item,false)); continue; }
    const all = snapshot.containers.filter(c => c.project === project), count = all.filter(c => c.State === 'running').length;
    const row = el('tr'); row.className = 'project'; const name = el('td'), toggle = el('button',(collapsed.has(project) ? '▸ ' : '▾ ') + project); toggle.className = 'disclosure'; toggle.setAttribute('aria-expanded',String(!collapsed.has(project))); toggle.addEventListener('click',() => { collapsed.has(project) ? collapsed.delete(project) : collapsed.add(project); renderContainers(); });
    name.append(toggle); name.title='Проект Compose · ' + all.length + ' контейнеров'; const state = el('td'); state.className='state-cell'; const dot=badge(count?'running':'exited',''); dot.textContent=''; dot.title=count+' / '+all.length+' запущено'; dot.setAttribute('aria-label',dot.title); state.append(dot);
    const cpu = el('td',count ? all.reduce((sum,c) => sum + (parseFloat(c.metrics.CPUPerc) || 0),0).toFixed(2) + '%' : '—'); const used = all.reduce((sum,c) => { const match = (c.metrics.MemUsage || '').match(/^([0-9.]+)([A-Za-z]+)\s*\//); return sum + (match ? Number(match[1]) * ({B:1,KiB:1024,MiB:1048576,GiB:1073741824,kB:1000,MB:1000000,GB:1000000000}[match[2]] || 0) : 0); },0); const memory = el('td',count ? (used / 1048576).toLocaleString('ru-RU',{maximumFractionDigits:1}) + ' МиБ' : '—'); const ports = el('td','—'); const buttons = el('td'); buttons.append(actions('project',project,count > 0)); row.append(state,name,el('td','—'),el('td','—'),ports,cpu,memory,el('td','—'),buttons); body.append(row);
    if (!collapsed.has(project)) for (const item of items) body.append(containerRow(item,true));
  }
  $('#filter-result').textContent = '';
  if (!visible.length) empty(body,9,snapshot.error || (snapshot.vm.running ? 'Контейнеров по этому фильтру нет.' : 'VM остановлена. Выполните helios-container start.'));
}
function removeButton(kind,item) {
  const id=kind==='volume'?item.Name:item.ID, reference=kind==='container'?item.Names:kind==='image'?(item.Repository==='<none>'||item.Tag==='<none>'?item.ID:item.Repository+':'+item.Tag):item.Name;
  const blocked=kind==='project'?item.members.some(c=>!['exited','created','dead'].includes(c.State)):kind==='container'?!['exited','created','dead'].includes(item.State):item.containers.length;
  const button=el('button'); const icon=document.createElementNS('http://www.w3.org/2000/svg','svg'); icon.setAttribute('viewBox','0 0 24 24'); icon.setAttribute('width','15'); icon.setAttribute('height','15'); icon.setAttribute('fill','none'); icon.setAttribute('stroke','currentColor'); icon.setAttribute('stroke-width','1.6'); icon.setAttribute('stroke-linecap','round'); icon.setAttribute('stroke-linejoin','round'); icon.setAttribute('aria-hidden','true'); const path=document.createElementNS('http://www.w3.org/2000/svg','path'); path.setAttribute('d','M3 6h18M9 6V3h6v3M5 6l1 15h12l1-15M10 10v7M14 10v7'); icon.append(path); button.append(icon); button.className='danger-icon'; button.type='button'; button.title='Удалить'; button.setAttribute('aria-label','Удалить '+reference); button.disabled=Boolean(blocked || pending || actionBusy);
  if(blocked) button.title=kind==='project'?'Сначала остановите все контейнеры группы':kind==='container'?'Сначала остановите контейнер':'Используется контейнерами, включая остановленные';
  button.addEventListener('click',()=>{
    deleteTarget={kind,id,reference,container_ids:kind==='project'?item.members.map(c=>c.ID).sort():undefined};
    $('#delete-title').textContent=kind==='project'?'Удалить все контейнеры группы?':kind==='container'?'Удалить контейнер?':kind==='image'?'Удалить образ?':'Удалить volume?';
    $('#delete-name').textContent=kind==='project'?reference+' · '+item.members.length+' контейнеров: '+item.members.map(c=>c.Names).join(', '):reference;
    $('#delete-warning').textContent=kind==='project'?'Все перечисленные контейнеры, их логи и записываемые слои будут удалены без возможности восстановления. Образы, volumes, подключённые каталоги и сети сохранятся. Чтобы создать контейнеры снова, выполните docker compose up -d.':kind==='container'?'Контейнер, его логи и данные в записываемом слое будут удалены без возможности восстановления. Образ, volumes и файлы в подключённых каталогах сохранятся. Для восстановления контейнера потребуется повторный запуск из образа или Compose.':kind==='image'?'Этот образ или тег будет удалён из вашей VM. Для повторного запуска может потребоваться загрузка или сборка.':'Все данные этого тома будут удалены без возможности восстановления. Остановка контейнера не удаляет его связь с томом.';
    $('#delete-dialog').showModal(); $('#delete-cancel').focus();
  }); return button;
}
function renderImages() {
  const body=$('#images'); body.replaceChildren(); if(!snapshot) return; const query=$('#image-search').value.toLowerCase();
  if(snapshot.inventory_pending) { $('#image-count').textContent='Каталог загружается…'; empty(body,8,'Загружаю каталог образов…'); return; }
  const images=snapshot.images.filter(i=>(i.Repository+':'+i.Tag+' '+i.ID).toLowerCase().includes(query));
  const unique=new Map(snapshot.images.map(i=>[i.ID,i.size_bytes])); $('#image-count').textContent=unique.size+' образов · суммарный размер '+bytesText([...unique.values()].reduce((a,b)=>a+(b || 0),0))+' (общие слои учитываются повторно)';
  for(const item of images){const row=el('tr'), state=el('td'); state.className='state-cell'; const dot=badge(item.containers.length?'running':'exited',''); dot.textContent=''; dot.title=item.containers.length?'Используется':'Не используется'; state.append(dot); const buttons=el('td'); buttons.append(removeButton('image',item)); row.append(state,el('td',item.Repository),el('td',item.Tag),el('td',item.ID.replace('sha256:','').slice(0,12)),el('td',age(item.CreatedAt)),el('td',bytesText(item.size_bytes)),el('td',item.containers.join(', ') || '—'),buttons); body.append(row);}
  if(!images.length) empty(body,8,snapshot.error || (snapshot.vm.running?'Образов по этому фильтру нет.':'VM остановлена. Каталог доступен после запуска.'));
}
function renderVolumes() {
  const body=$('#volumes'); body.replaceChildren(); if(!snapshot) return; const query=$('#volume-search').value.toLowerCase();
  if(snapshot.inventory_pending) { $('#volume-count').textContent='Каталог загружается…'; empty(body,7,'Загружаю каталог volumes…'); return; }
  const volumes=snapshot.volumes.filter(v=>(v.Name+' '+v.project).toLowerCase().includes(query));
  const measured=snapshot.volumes.filter(v=>v.size_bytes!=null), total=measured.reduce((sum,v)=>sum+v.size_bytes,0); $('#volume-count').textContent=snapshot.volumes.length+' томов · '+(measured.length===snapshot.volumes.length?bytesText(total):'Размеры рассчитываются…')+(snapshot.storage.updated_at?' · измерено '+age(new Date(snapshot.storage.updated_at*1000).toISOString()):'');
  if(snapshot.storage.error) $('#volume-count').textContent += ' · '+snapshot.storage.error;
  for(const item of volumes){const row=el('tr'), state=el('td'); state.className='state-cell'; const dot=badge(item.containers.length?'running':'exited',''); dot.textContent=''; dot.title=item.containers.length?'Используется':'Не используется'; state.append(dot); const buttons=el('td'); buttons.append(removeButton('volume',item)); row.append(state,el('td',item.Name),el('td',item.project || '—'),el('td',item.containers.join(', ') || '—'),el('td',item.CreatedAt?age(item.CreatedAt):'—'),el('td',bytesText(item.size_bytes)),buttons); body.append(row);}
  if(!volumes.length) empty(body,7,snapshot.error || (snapshot.vm.running?'Томов по этому фильтру нет.':'VM остановлена. Каталог доступен после запуска.'));
}
function renderRoutes() {
  const root = $('#routes'); root.replaceChildren(); if (!snapshot) return;
  for (const route of snapshot.routes) { const line = el('div',`${route.kind === 'host' ? 'Процесс helios' : 'Порт VM'} ${route.port} · ${route.listening ? 'TCP слушает' : 'TCP недоступен'} · `); const link = el('a','Открыть HTTPS'); link.href = new URL('index.php' + route.path,location.href).href; link.target = '_blank'; link.rel = 'noopener'; line.append(link); root.append(line); }
  if (!snapshot.routes.length) root.textContent = 'Публичные адреса закрыты.';
}
function renderDetail() {
  const item = snapshot && snapshot.containers.find(c => c.ID === selected); if (!item) { if(snapshot && selected) selectView('containers'); return; }
  $('#detail-title').textContent = item.Names; $('#detail-meta').textContent = [stateNames[item.State] || item.State,item.Image,item.ID.slice(0,12)].join(' · '); $('#detail-actions').replaceChildren(actions('container',item.ID,item.State === 'running'));
  const info = $('#info-content'); info.replaceChildren(); const list = el('dl');
  const values = [['ID',item.ID],['Образ',item.Image],['Проект Compose',item.project || '—'],['Сервис',item.service || '—'],['Состояние',item.Status],['Порты',item.Ports || '—'],['Протокол',item.protocol === 'unknown' ? 'Не указан' : item.protocol],['Polling приложения',({true:'Заявлен',false:'Не используется',unknown:'Не указан'}[item.polling])],['CPU',item.metrics.CPUPerc || '—'],['Память',item.metrics.MemUsage || '—'],['Сеть I/O',item.metrics.NetIO || '—'],['Диск I/O',item.metrics.BlockIO || '—'],['Процессы',item.metrics.PIDs || '—']];
  for (const [name,value] of values) list.append(el('dt',name),el('dd',value));
  for (const mount of item.mounts) list.append(el('dt',mount.Type === 'volume' ? 'Volume' : 'Mount'),el('dd',(mount.Name || mount.Type) + ' → ' + mount.Destination + (mount.RW ? ' · rw' : ' · ro')));
  info.append(list,el('p','Протокол и polling приложения заявляются через labels контейнера. Номер TCP-порта не определяет протокол.'));
}
function renderEngine() {
  if(!snapshot) return;
  renderRelease();
  const vm=snapshot.vm, busy=Boolean(pending || actionBusy), root=$('#engine-controls'); root.replaceChildren();
  for(const [kind,name,running] of [['vm','VM',vm.running],['engine','Docker',vm.docker_running]]) {
    const button=el('button',(running?'■ ':'▶ ')+name); button.title=(running?'Остановить ':'Запустить ')+name; button.setAttribute('aria-label',button.title); button.disabled=busy || (kind==='engine'&&!vm.running);
    button.addEventListener('click',()=>{const action=running?'stop':'start'; if(running&&!confirm(kind==='vm'?'Остановить VM и все приложения внутри неё? Данные сохранятся.':'Остановить Docker? Контейнерные приложения станут недоступны. Данные сохранятся.'))return; runAction(kind,kind,action,{confirm:kind});}); root.append(button);
  }
  $('#engine-status').textContent='VM '+(vm.running?'запущена':'остановлена')+' · Docker '+(snapshot.inventory_pending?'проверяется':vm.docker_running?'работает':'недоступен')+(vm.docker_version?' '+vm.docker_version:'');
  $('#engine-resources').textContent='VM: CPU '+(vm.cpu_percent==null?'—':vm.cpu_percent.toLocaleString('ru-RU')+'%')+' / '+vm.cpus+' vCPU · RAM '+bytesText(vm.memory_used_bytes)+' / '+bytesText(vm.memory_total_bytes || vm.memory_mib*1048576)+' · Диск '+bytesText(vm.disk_used_bytes)+' / '+bytesText(vm.disk_total_bytes);
  $('#kit-version').textContent='kit '+snapshot.kit_version;
}
const enginePanel=el('div'); enginePanel.className='engine-panel'; $('#engine-status').before(enginePanel); enginePanel.append($('#engine-status')); const engineControls=el('div'); engineControls.id='engine-controls'; engineControls.className='engine-controls'; enginePanel.append(engineControls); const engineResources=el('div'); engineResources.id='engine-resources'; engineResources.className='engine-resources'; enginePanel.append(engineResources); const kitVersion=el('span'); kitVersion.id='kit-version'; kitVersion.className='kit-version'; $('.footer').append(kitVersion);
function render() { renderContainers(); renderImages(); renderVolumes(); renderRoutes(); renderDetail(); renderEngine(); if(snapshot && snapshot.loading) { $('#count-card').textContent='—'; $('#cpu-card').textContent='—'; $('#memory-card').textContent='—'; $('#dashboard-status').textContent=snapshot.error || 'Получаю первый снимок. Статистика загружается в фоне…'; for(const [name,columns] of [['containers',9],['images',8],['volumes',7]]) { const body=$('#'+name); body.replaceChildren(); empty(body,columns,'Загружаю список…'); } $('#engine-status').textContent='VM '+(snapshot.vm.running?'запущена':'остановлена')+' · Docker проверяется'; $('#engine-controls').querySelectorAll('button').forEach(button=>{button.disabled=true;}); } else if(snapshot && snapshot.refreshing && !snapshot.error) { $('#dashboard-status').textContent+=' · обновляю в фоне'; } if(snapshot && !snapshot.metrics_ready && snapshot.vm.running) { $('#cpu-card').textContent='—'; $('#memory-card').textContent='—'; } if(snapshot && snapshot.metrics_error) $('#dashboard-status').textContent+=' · '+snapshot.metrics_error; }
async function refresh() {
  if (busy || document.hidden) return; busy = true; $('#refresh').disabled = true;
  try { snapshot = await api('_dashboard'); $('#count-card').textContent = snapshot.containers.filter(c => c.State === 'running').length + ' / ' + snapshot.containers.length; $('#cpu-card').textContent = snapshot.resources.cpu_percent.toLocaleString('ru-RU',{maximumFractionDigits:2}) + '% / ' + snapshot.resources.cpu_capacity_percent + '%'; $('#cpu-caption').textContent = 'Загрузка CPU контейнеров · доступно ' + snapshot.vm.cpus + ' vCPU'; $('#memory-card').textContent = (snapshot.resources.memory_used_bytes/1073741824).toLocaleString('ru-RU',{maximumFractionDigits:2}) + ' ГиБ / ' + (snapshot.resources.memory_total_bytes/1073741824).toLocaleString('ru-RU',{maximumFractionDigits:2}) + ' ГиБ'; $('#dashboard-status').textContent = snapshot.error || 'Обновлено ' + new Date(snapshot.updated_at * 1000).toLocaleTimeString('ru-RU'); $('#dashboard-status').classList.toggle('error',Boolean(snapshot.error)); $('#engine-status').textContent = 'Docker Engine · ' + (snapshot.error ? 'недоступен' : snapshot.vm.running ? 'VM запущена' : 'VM остановлена'); render(); }
  catch (error) { $('#dashboard-status').textContent = error.message; $('#dashboard-status').classList.add('error'); $('#engine-status').textContent = 'Docker Engine · нет доступа'; }
  finally { busy = false; $('#refresh').disabled = false; }
}
function selectView(name) { activeView = name; for (const current of views) { $('#' + current + '-view').hidden = current !== name; const tab = $('#' + current + '-tab'); tab.setAttribute('aria-selected',String(current === name)); tab.tabIndex = current === name ? 0 : -1; } $('#detail-view').hidden = true; selected = ''; if (name !== 'ports' || !snapshot) refresh(); }
function detailTab(name) { for (const current of ['logs','info']) { $('#' + current + '-content').hidden = current !== name; const button = $('#' + current + '-tab'); button.setAttribute('aria-selected',String(current === name)); button.tabIndex = current === name ? 0 : -1; } }
function openContainer(id) { selected = id; activeView = 'detail'; for (const name of views) $('#' + name + '-view').hidden = true; $('#detail-view').hidden = false; $('#logs').textContent = ''; detailTab('logs'); renderDetail(); loadLogs(); }
function highlightLogs(text) {
  const root=$('#logs'), bottom=root.scrollHeight-root.scrollTop-root.clientHeight<40 || !root.textContent;
  const fragment=document.createDocumentFragment();
  for(const raw of text.replace(/\u001b\[[0-?]*[ -/]*[@-~]/g,'').split('\n')){
    const line=el('span'); line.className='log-line';
    const level=/\b(ERROR|FATAL|SEVERE|PANIC|EXCEPTION)\b/i.test(raw)||/HTTP\/[0-9.]+"\s+5[0-9]{2}/.test(raw)?'error':/\b(WARN|WARNING)\b/i.test(raw)||/HTTP\/[0-9.]+"\s+4[0-9]{2}/.test(raw)?'warn':/\b(INFO|NOTICE)\b/i.test(raw)||/HTTP\/[0-9.]+"\s+2[0-9]{2}/.test(raw)?'info':/\b(DEBUG|TRACE)\b/i.test(raw)?'debug':'';
    if(level) line.classList.add('log-'+level);
    const stamp=raw.match(/^(\d{4}-\d{2}-\d{2}T[0-9:.]+Z)\s*/);
    if(stamp){const time=el('span',stamp[0]); time.className='log-time'; line.append(time,document.createTextNode(raw.slice(stamp[0].length)));}else line.textContent=raw;
    fragment.append(line);
  }
  root.replaceChildren(fragment); if(bottom) root.scrollTop=root.scrollHeight;
}
async function loadLogs() { if (logBusy || !selected) return; logBusy = true; const id = selected; $('#refresh-logs').disabled = true; $('#log-status').textContent = 'Загружаю…'; try { const data = await api('_logs?' + new URLSearchParams({id,tail:$('#tail').value})); if (id !== selected) return; highlightLogs(data.text || 'Лог пуст.'); $('#log-status').textContent = (data.truncated ? 'Конец лога, максимум 128 КиБ. ' : '') + 'Обновлено ' + new Date().toLocaleTimeString('ru-RU'); } catch (error) { if (id === selected) $('#log-status').textContent = error.message; } finally { logBusy = false; $('#refresh-logs').disabled = false; } }
for (const [index,name] of views.entries()) { const tab = $('#' + name + '-tab'); tab.addEventListener('click',() => selectView(name)); tab.addEventListener('keydown',event => { if (['ArrowUp','ArrowDown','Home','End'].includes(event.key)) { event.preventDefault(); const next = event.key === 'Home' ? 0 : event.key === 'End' ? views.length - 1 : (index + (event.key === 'ArrowDown' ? 1 : -1) + views.length) % views.length; selectView(views[next]); $('#' + views[next] + '-tab').focus(); } }); }
$('#delete-cancel').addEventListener('click',()=>{$('#delete-dialog').close(); deleteTarget=null;}); $('#delete-confirm').addEventListener('click',()=>{if(!deleteTarget)return; const target=deleteTarget; deleteTarget=null; $('#delete-dialog').close(); runAction(target.kind,target.id,'delete',{reference:target.reference,confirm:target.reference,container_ids:target.container_ids});});
$('#back').addEventListener('click',() => selectView('containers')); $('#logs-tab').addEventListener('click',() => detailTab('logs')); $('#info-tab').addEventListener('click',() => detailTab('info'));
$('#refresh').addEventListener('click',refresh); $('#search').addEventListener('input',renderContainers); $('#running-only').addEventListener('change',renderContainers); $('#image-search').addEventListener('input',renderImages); $('#volume-search').addEventListener('input',renderVolumes); $('#refresh-logs').addEventListener('click',loadLogs); $('#tail').addEventListener('change',loadLogs);
function showConfig(data) { const result = $('#result'); result.replaceChildren(); result.textContent = data.routes.length ? 'Адреса backend:' : 'Публичные адреса закрыты.'; for (const route of data.routes) { const link = el('a',new URL('index.php' + route.path,location.href).href); link.href = link.textContent; link.target = '_blank'; link.rel = 'noopener'; result.append(link); } }
$('#ports-form').addEventListener('submit',async event => { event.preventDefault(); const button = event.currentTarget.querySelector('button'); button.disabled = true; try { showConfig(await api('_config','POST',{ports:$('#ports').value})); await refresh(); } catch (error) { $('#result').textContent = error.message; } finally { button.disabled = false; } });
if (key) api('_config').then(data => { $('#ports').value = data.ports; showConfig(data); }).catch(error => { $('#result').textContent = error.message; }); else $('#result').textContent = 'Откройте приватную ссылку из helios-container web info.';
let nextPoll=0; refresh(); setInterval(() => { if (!document.hidden) { if (pending) pollAction(); else if ((snapshot && (snapshot.loading || snapshot.refreshing)) || ($('#auto').checked && Date.now()>=nextPoll)) { nextPoll=Date.now()+10000; refresh(); if (activeView === 'detail' && !$('#logs-content').hidden) loadLogs(); } } },2000); document.addEventListener('visibilitychange',() => { if (!document.hidden) refresh(); });
</script></body></html>

<?php
    exit;
}
if (!ini_get('allow_url_fopen')) {
    http_response_code(503); header('Content-Type: application/json'); echo '{"error":"PHP allow_url_fopen отключён."}'; exit;
}
if (!preg_match('~^/(?:_config|_dashboard|_logs|_action|(?:vm|host)/[0-9]{1,5}(?:/.*)?)$~D', $path)) {
    http_response_code(404); exit;
}
if (str_starts_with(strtolower($_SERVER['CONTENT_TYPE'] ?? ''), 'multipart/form-data')) {
    http_response_code(415); header('Content-Type: application/json; charset=utf-8');
    echo '{"error":"Multipart-загрузка через PHP-шлюз не поддерживается. Используйте JSON или application/octet-stream."}'; exit;
}
$body = file_get_contents('php://input', false, null, 0, 8 * 1024 * 1024 + 1);
if ($body === false || strlen($body) > 8 * 1024 * 1024) {
    http_response_code(413); exit;
}
$hop = ['host', 'connection', 'keep-alive', 'proxy-authenticate', 'proxy-authorization', 'te', 'trailer', 'transfer-encoding', 'upgrade', 'content-length', 'expect'];
foreach (explode(',', $_SERVER['HTTP_CONNECTION'] ?? '') as $name) $hop[] = strtolower(trim($name));
$headers = [];
foreach (getallheaders() as $name => $value) {
    $lower = strtolower($name);
    if (in_array($lower, $hop, true) || str_starts_with($lower, 'x-forwarded-') || str_starts_with($lower, 'x-hc-') && $lower !== 'x-hc-admin') continue;
    $headers[] = $name . ': ' . $value;
}
$headers[] = 'X-HC-Bridge: ' . HC_BRIDGE;
$headers[] = 'X-HC-Prefix: ' . $script;
$headers[] = 'Content-Length: ' . strlen($body);
$headers[] = 'Connection: close';
$query = $_SERVER['QUERY_STRING'] ?? '';
$url = 'http://127.0.0.1:' . HC_PORT . $path . ($query !== '' ? '?' . $query : '');
$context = stream_context_create(['http' => ['method' => $_SERVER['REQUEST_METHOD'], 'header' => $headers,
    'content' => $body, 'ignore_errors' => true, 'follow_location' => 0, 'timeout' => 20, 'protocol_version' => 1.1]]);
$stream = @fopen($url, 'rb', false, $context);
if ($stream === false) {
    http_response_code(502); header('Content-Type: application/json; charset=utf-8');
    echo '{"error":"Шлюз недоступен. Выполните helios-container web start."}'; exit;
}
$meta = stream_get_meta_data($stream);
$data = stream_get_contents($stream, 16 * 1024 * 1024 + 1);
fclose($stream);
if ($data === false || strlen($data) > 16 * 1024 * 1024) { http_response_code(502); exit; }
http_response_code(502);
foreach ($meta['wrapper_data'] ?? [] as $line) {
    if (preg_match('~^HTTP/\S+ ([0-9]{3})~', $line, $match)) { http_response_code((int)$match[1]); continue; }
    $colon = strpos($line, ':');
    if ($colon === false) continue;
    $name = strtolower(substr($line, 0, $colon));
    if (in_array($name, $hop, true) && !($name === 'content-length' && $_SERVER['REQUEST_METHOD'] === 'HEAD')) continue;
    header($line, $name !== 'set-cookie');
}
if (in_array($path, ['/_config', '/_dashboard', '/_logs', '/_action'], true)) { header('Cache-Control: no-store'); header('Referrer-Policy: no-referrer'); }
if ($_SERVER['REQUEST_METHOD'] !== 'HEAD') echo $data;
