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
:root{font-family:system-ui,-apple-system,sans-serif;color:#1d2229;background:#f6f7f9;color-scheme:light dark}
*{box-sizing:border-box}body{margin:0;min-height:100svh;display:grid;place-items:center;padding:24px}
main{width:min(100%,940px)}section{padding:32px;border:1px solid #dfe3e8;border-radius:20px;background:#fff;box-shadow:0 12px 48px #202a3910}#ports-panel{max-width:480px;margin:auto} [hidden]{display:none!important}
.brand{font-size:12px;font-weight:650;letter-spacing:.14em;text-transform:uppercase;color:#75808e;margin:0 0 24px}
h1{font-size:26px;letter-spacing:-.04em;margin:0 0 12px}p{line-height:1.55;font-size:14px;color:#66717f;margin:0 0 24px}
label{display:block;font-size:13px;font-weight:600;margin-bottom:8px}input{width:100%;padding:14px;border:1px solid #d0d6de;border-radius:10px;font:inherit;outline:none;background:transparent;color:inherit}
input:focus{border-color:#4667e9;box-shadow:0 0 0 3px #4667e918}button{width:100%;margin-top:12px;border:0;border-radius:10px;padding:14px;background:#263b72;color:#fff;font:inherit;font-weight:600;cursor:pointer}button:disabled{opacity:.6;cursor:wait}
small{display:block;margin-top:10px;line-height:1.5;color:#75808e}output{display:block;font-size:13px;overflow-wrap:anywhere;line-height:1.6;margin-top:20px}output a{display:block;color:#4667e9;margin-top:10px}output:empty{display:none}
@media(prefers-color-scheme:dark){:root{color:#e4e8ee;background:#11151c}form{background:#1a202a;border-color:#303947}input{border-color:#414d60}p,small{color:#9ba7b8}button{background:#526edf}}
nav{display:flex;gap:8px;margin:0 auto 20px;max-width:480px}nav button{margin:0;background:transparent;color:inherit;border:1px solid #dfe3e8;font-size:14px}nav button[aria-selected=true]{background:#263b72;color:white;border-color:#263b72}
.toolbar{display:flex;gap:12px;align-items:center;flex-wrap:wrap}.toolbar button{width:auto;margin:0;padding:10px 14px}.toolbar label{display:flex;gap:8px;align-items:center;margin:0;font-weight:400}.toolbar input{width:auto}select{font:inherit;padding:10px;border:1px solid #d0d6de;border-radius:8px;background:transparent;color:inherit}a{color:#4667e9}.table-wrap{overflow-x:auto;margin:20px 0}table{width:100%;border-collapse:collapse;font-size:13px}th,td{text-align:left;padding:12px 8px;border-bottom:1px solid #dfe3e8;vertical-align:top}th{color:#75808e;font-weight:500}td small{margin:4px 0 0}td button{width:auto;padding:7px 10px;margin:0;font-size:12px}.summary{line-height:1.7;margin:16px 0}.notice{font-size:13px;color:#75808e;line-height:1.6;margin-top:12px}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#11151c;color:#dae3ed;padding:20px;border-radius:12px;max-height:480px;overflow:auto;font:12px/1.6 ui-monospace,monospace}.error{color:#bc3845}
@media(prefers-color-scheme:dark){section{background:#1a202a;border-color:#303947}nav button,th,td{border-color:#303947}.notice,th{color:#9ba7b8}select{border-color:#414d60}}
@media(max-width:600px){body{padding:12px}section{padding:22px}h1{font-size:23px}}
#dashboard-panel{padding:0;overflow:hidden}.desktop-head{padding:28px 28px 20px;border-bottom:1px solid #dfe3e8}.desktop-head .brand{margin-bottom:12px}.desktop-head h1{margin-bottom:6px}.desktop-head p{margin-bottom:16px}.desktop-content{padding:20px 28px}.resource-cards{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px;margin-top:18px}.resource-card{border:1px solid #dfe3e8;border-radius:10px;padding:14px 16px}.resource-card strong{display:block;font-size:23px;font-weight:600;letter-spacing:-.03em}.resource-card span{font-size:12px;color:#75808e}.desktop-head button,td button{background:#087be8}.toolbar .search{width:min(100%,300px);padding:10px 12px;font-size:13px}.badge{display:inline-flex;align-items:center;gap:6px;border-radius:6px;padding:4px 8px;background:#edf0f4;font-size:12px}.badge::before{content:'';width:6px;height:6px;border-radius:50%;background:#8794a3}.badge.running{background:#e9f7ef;color:#197047}.badge.running::before{background:#27a36a}.badge.exited,.badge.dead{background:#f7eded;color:#9c4545}h2{font-size:16px;letter-spacing:-.02em;margin:26px 0 12px}#containers td:first-child{font-weight:600}#containers td small{font-weight:400}#log-panel{border-top:1px solid #dfe3e8;margin-top:24px}#dashboard-status{font-size:12px;color:#75808e;margin:12px 0 0}.desktop-content .table-wrap{margin-top:16px}#routes>div{font-size:13px;line-height:2}.desktop-content input:focus{border-color:#087be8}
@media(prefers-color-scheme:dark){.desktop-head,.resource-card,#log-panel{border-color:#303947}.badge{background:#2b3441;color:#c6d0de}.badge.running{background:#193a2e;color:#87d9b0}.badge.exited,.badge.dead{background:#40282d;color:#edaaaa}.resource-card span,#dashboard-status{color:#9ba7b8}}
@media(max-width:600px){.desktop-head,.desktop-content{padding:20px}.resource-card{padding:12px 10px}.resource-card strong{font-size:19px}}
</style></head><body>
<main><nav role="tablist" aria-label="Личная панель"><button id="ports-tab" role="tab" aria-selected="true" aria-controls="ports-panel">Порты</button><button id="dashboard-tab" role="tab" aria-selected="false" aria-controls="dashboard-panel" tabindex="-1">Контейнеры и логи</button></nav>
<section id="ports-panel" role="tabpanel" aria-labelledby="ports-tab"><form id="ports-form"><div class="brand">Helios Container</div><h1>Откройте backend</h1><p>Укажите порты приложения — получите HTTPS-адреса для вашего frontend.</p>
<label for="ports">Порты backend</label><input id="ports" name="ports" placeholder="8080, 8081, host:3000" autocomplete="off" maxlength="160" aria-describedby="hint">
<small id="hint">8080 — порт внутри VM. host:3000 — порт вашего процесса на helios. Пустое поле закрывает все адреса.</small>
<button type="submit">Сохранить порты</button><output id="result" aria-live="polite"></output></form></section>
<section id="dashboard-panel" role="tabpanel" aria-labelledby="dashboard-tab" hidden><header class="desktop-head"><div class="brand">Helios Container · Personal</div><h1>Контейнеры</h1><p>Ваши приложения, ресурсы и логи в одном месте.</p>
<div class="toolbar"><button id="refresh" type="button">Обновить</button><label><input id="auto" type="checkbox" checked>Polling каждые 10 секунд</label></div>
<div class="resource-cards"><div class="resource-card"><strong id="count-card">—</strong><span>Контейнеры · запущено / всего</span></div><div class="resource-card"><strong id="cpu-card">—</strong><span>CPU выделено VM</span></div><div class="resource-card"><strong id="memory-card">—</strong><span>RAM выделено VM</span></div></div><div id="dashboard-status" class="summary" role="status"></div></header>
<div class="desktop-content"><div class="toolbar"><input id="search" class="search" type="search" placeholder="Поиск контейнера или образа" aria-label="Поиск контейнера или образа"><label><input id="running-only" type="checkbox">Только запущенные</label></div><div class="table-wrap"><table><thead><tr><th>Имя / образ</th><th>Статус</th><th>CPU / RAM</th><th>Порты / протокол</th><th></th></tr></thead><tbody id="containers"></tbody></table></div><div id="filter-result" class="notice"></div>
<h2>Опубликованные адреса</h2><div id="routes"></div><div class="notice">Браузер → HTTPS → PHP-шлюз → HTTP backend. Открытый TCP-порт не определяет протокол приложения. Протокол и polling контейнера показываются по его labels. WebSocket и SSE через этот шлюз не поддерживаются. Polling панели работает через обычные HTTPS-запросы.</div>
<div id="log-panel" hidden><h2 id="log-title">Логи</h2><div class="toolbar"><label for="tail">Последние строки</label><select id="tail"><option>100</option><option selected>200</option><option>500</option><option>1000</option></select><button id="refresh-logs" type="button">Обновить логи</button></div><div id="log-status" class="notice" role="status"></div><pre id="logs"></pre></div>
</div></section></main>
<script nonce="<?= $nonce ?>">
const key = new URLSearchParams(location.hash.slice(1)).get('key') || '';
history.replaceState(null, '', location.pathname + location.search);
const form = document.querySelector('#ports-form'), input = document.querySelector('#ports'), button = form.querySelector('button'), result = document.querySelector('#result');
const endpoint = new URL('index.php/_config', location.href);
function show(data) {
  result.replaceChildren();
  if (data.error) { result.textContent = data.error; return; }
  result.textContent = data.routes.length ? 'Адреса backend:' : 'Публичные адреса закрыты.';
  for (const route of data.routes) {
    const link = document.createElement('a');
    link.href = new URL('index.php' + route.path, location.href).href;
    link.textContent = link.href; link.target = '_blank'; link.rel = 'noopener'; result.append(link);
  }
}
async function request(method, body) {
  const response = await fetch(endpoint, {method, headers: {'X-HC-Admin': key, 'Content-Type': 'application/json'}, body: body && JSON.stringify(body)});
  const data = await response.json(); show(data); return data;
}
form.addEventListener('submit', async event => {
  event.preventDefault(); button.disabled = true; result.textContent = 'Настраиваю доступ…';
  try { await request('POST', {ports: input.value}); }
  catch { result.textContent = 'Шлюз недоступен. Выполните helios-container web start.'; }
  finally { button.disabled = false; }
});
if (key) request('GET').then(data => { if (!data.error) input.value = data.ports; }).catch(() => { result.textContent = 'Запустите шлюз: helios-container web start.'; });
else result.textContent = 'Для настройки откройте приватную ссылку из helios-container web info.';
const status = document.querySelector('#dashboard-status'), refresh = document.querySelector('#refresh');
let activeTab = 'ports', busy = false, selectedLog = '', logBusy = false;
function element(tag, text) { const node = document.createElement(tag); node.textContent = text; return node; }
async function privateGet(path) {
  if (!key) throw new Error('Откройте приватную ссылку из helios-container web info.');
  const response = await fetch(new URL('index.php/' + path, location.href), {headers: {'X-HC-Admin': key}, cache: 'no-store'});
  const data = await response.json();
  if (!response.ok || data.error && !data.vm) throw new Error(data.error || 'Шлюз недоступен.');
  return data;
}
async function loadLogs(ident, name) {
  if (logBusy) return;
  if (ident) { selectedLog = ident; document.querySelector('#log-title').textContent = 'Логи · ' + name; }
  if (!selectedLog) return;
  logBusy = true; document.querySelector('#refresh-logs').disabled = true;
  document.querySelector('#log-panel').hidden = false;
  const message = document.querySelector('#log-status'); message.textContent = 'Загружаю…';
  try {
    const data = await privateGet('_logs?' + new URLSearchParams({id: selectedLog, tail: document.querySelector('#tail').value}));
    document.querySelector('#logs').textContent = data.text || 'Лог пуст.';
    message.textContent = (data.truncated ? 'Показан конец лога, максимум 128 КиБ. ' : '') + 'Обновлено ' + new Date().toLocaleTimeString('ru-RU');
  } catch (error) { message.textContent = error.message; }
  finally { logBusy = false; document.querySelector('#refresh-logs').disabled = false; }
}
async function loadDashboard() {
  if (busy || document.hidden || activeTab !== 'dashboard') return;
  busy = true; refresh.disabled = true; status.textContent = 'Обновляю состояние…';
  try {
    const data = await privateGet('_dashboard');
    document.querySelector('#count-card').textContent = data.containers.filter(item => item.State === 'running').length + ' / ' + data.containers.length;
    document.querySelector('#cpu-card').textContent = data.vm.cpus + ' vCPU';
    document.querySelector('#memory-card').textContent = (data.vm.memory_mib / 1024).toLocaleString('ru-RU') + ' ГиБ';
    status.textContent = `VM ${data.vm.running ? 'запущена' : 'остановлена'} · ${data.vm.cpus} vCPU · ${data.vm.memory_mib} МиБ RAM · ${new Date(data.updated_at * 1000).toLocaleTimeString('ru-RU')}`;
    status.classList.toggle('error', Boolean(data.error));
    if (data.error) status.append(element('div', data.error));
    const rows = document.querySelector('#containers'); rows.replaceChildren();
    for (const item of data.containers) {
      const tr = element('tr', ''), name = element('td', item.Names); tr.dataset.search = (item.Names + ' ' + item.Image).toLowerCase(); tr.dataset.state = item.State;
      name.append(element('small', item.Image), element('small', item.ID.slice(0, 12)));
      const state = element('td', ''), badge = element('span', ({running:'Запущен',exited:'Остановлен',created:'Создан',paused:'Приостановлен',restarting:'Перезапуск',dead:'Ошибка'}[item.State] || item.State)); badge.className = 'badge ' + item.State; state.append(badge, element('small', item.Status));
      const metrics = element('td', 'CPU ' + (item.metrics.CPUPerc || '—'));
      metrics.append(element('small', 'RAM ' + (item.metrics.MemUsage || '—')), element('small', 'Сеть ' + (item.metrics.NetIO || '—')), element('small', 'Диск I/O ' + (item.metrics.BlockIO || '—')), element('small', 'Процессов ' + (item.metrics.PIDs || '—')));
      const ports = element('td', item.Ports || 'Не опубликованы');
      ports.append(element('small', 'Приложение: ' + (item.protocol === 'unknown' ? 'не указан' : item.protocol.toUpperCase())), element('small', 'Polling: ' + ({true:'заявлен',false:'не используется',unknown:'не указан'}[item.polling])));
      const cell = element('td', ''), open = element('button', 'Смотреть'); open.type = 'button'; open.addEventListener('click', () => loadLogs(item.ID, item.Names)); cell.append(open);
      tr.append(name, state, metrics, ports, cell); rows.append(tr);
    }
    applyFilters();
    if (!data.containers.length) { const row = element('tr', ''); const cell = element('td', data.error || (data.vm.running ? 'Контейнеров пока нет.' : 'Панель не запускает VM автоматически.')); cell.colSpan = 5; row.append(cell); rows.append(row); }
    const routes = document.querySelector('#routes'); routes.replaceChildren();
    for (const route of data.routes) {
      const line = element('div', `${route.kind === 'host' ? 'Процесс на helios' : 'Порт VM'} ${route.port} · ${route.listening ? 'TCP слушает' : 'TCP недоступен'} · `);
      const link = element('a', 'HTTPS-адрес'); link.href = new URL('index.php' + route.path, location.href).href; link.target = '_blank'; link.rel = 'noopener'; line.append(link); routes.append(line);
    }
    if (!data.routes.length) routes.textContent = 'Адреса не опубликованы. Добавьте их во вкладке «Порты».';
  } catch (error) { status.textContent = error.message; status.classList.add('error'); document.querySelector('#containers').replaceChildren(); document.querySelector('#routes').replaceChildren(); for (const id of ['count-card', 'cpu-card', 'memory-card']) document.querySelector('#' + id).textContent = '—'; document.querySelector('#filter-result').textContent = ''; }
  finally { busy = false; refresh.disabled = false; }
}
function selectTab(name) {
  activeTab = name;
  for (const current of ['ports', 'dashboard']) {
    const tab = document.querySelector('#' + current + '-tab'); tab.setAttribute('aria-selected', String(current === name)); tab.tabIndex = current === name ? 0 : -1;
    document.querySelector('#' + current + '-panel').hidden = current !== name;
  }
  if (name === 'dashboard') loadDashboard();
}
for (const name of ['ports', 'dashboard']) {
  const tab = document.querySelector('#' + name + '-tab');
  tab.addEventListener('click', () => selectTab(name));
  tab.addEventListener('keydown', event => { if (['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) { event.preventDefault(); const next = event.key === 'Home' ? 'ports' : event.key === 'End' ? 'dashboard' : name === 'ports' ? 'dashboard' : 'ports'; selectTab(next); document.querySelector('#' + next + '-tab').focus(); } });
}
refresh.addEventListener('click', loadDashboard);
function applyFilters() {
  const query = document.querySelector('#search').value.trim().toLowerCase(), running = document.querySelector('#running-only').checked;
  const rows = document.querySelectorAll('#containers tr[data-search]'); let visible = 0;
  for (const row of rows) { row.hidden = !row.dataset.search.includes(query) || running && row.dataset.state !== 'running'; if (!row.hidden) visible++; }
  document.querySelector('#filter-result').textContent = rows.length && !visible ? 'По вашему фильтру контейнеров нет.' : '';
}
document.querySelector('#search').addEventListener('input', applyFilters);
document.querySelector('#running-only').addEventListener('change', applyFilters);
document.querySelector('#refresh-logs').addEventListener('click', () => loadLogs());
document.querySelector('#tail').addEventListener('change', () => loadLogs());
setInterval(() => { if (document.querySelector('#auto').checked) loadDashboard(); }, 10000);
document.addEventListener('visibilitychange', () => { if (!document.hidden) loadDashboard(); });
</script></body></html>
<?php
    exit;
}
if (!ini_get('allow_url_fopen')) {
    http_response_code(503); header('Content-Type: application/json'); echo '{"error":"PHP allow_url_fopen отключён."}'; exit;
}
if (!preg_match('~^/(?:_config|_dashboard|_logs|(?:vm|host)/[0-9]{1,5}(?:/.*)?)$~D', $path)) {
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
if (in_array($path, ['/_config', '/_dashboard', '/_logs'], true)) { header('Cache-Control: no-store'); header('Referrer-Policy: no-referrer'); }
if ($_SERVER['REQUEST_METHOD'] !== 'HEAD') echo $data;
