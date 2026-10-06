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
<html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Helios · Порты</title>
<style nonce="<?= $nonce ?>">
:root{font-family:system-ui,-apple-system,sans-serif;color:#1d2229;background:#f6f7f9;color-scheme:light dark}
*{box-sizing:border-box}body{margin:0;min-height:100svh;display:grid;place-items:center;padding:24px}
form{width:min(100%,480px);padding:36px;border:1px solid #dfe3e8;border-radius:20px;background:#fff;box-shadow:0 12px 48px #202a3910}
.brand{font-size:12px;font-weight:650;letter-spacing:.14em;text-transform:uppercase;color:#75808e;margin:0 0 24px}
h1{font-size:26px;letter-spacing:-.04em;margin:0 0 12px}p{line-height:1.55;font-size:14px;color:#66717f;margin:0 0 24px}
label{display:block;font-size:13px;font-weight:600;margin-bottom:8px}input{width:100%;padding:14px;border:1px solid #d0d6de;border-radius:10px;font:inherit;outline:none;background:transparent;color:inherit}
input:focus{border-color:#4667e9;box-shadow:0 0 0 3px #4667e918}button{width:100%;margin-top:12px;border:0;border-radius:10px;padding:14px;background:#263b72;color:#fff;font:inherit;font-weight:600;cursor:pointer}button:disabled{opacity:.6;cursor:wait}
small{display:block;margin-top:10px;line-height:1.5;color:#75808e}output{display:block;font-size:13px;overflow-wrap:anywhere;line-height:1.6;margin-top:20px}output a{display:block;color:#4667e9;margin-top:10px}output:empty{display:none}
@media(prefers-color-scheme:dark){:root{color:#e4e8ee;background:#11151c}form{background:#1a202a;border-color:#303947}input{border-color:#414d60}p,small{color:#9ba7b8}button{background:#526edf}}
</style></head><body>
<form id="ports-form"><div class="brand">Helios Container</div><h1>Откройте backend</h1><p>Укажите порты приложения — получите HTTPS-адреса для вашего frontend.</p>
<label for="ports">Порты backend</label><input id="ports" name="ports" placeholder="8080, 8081, host:3000" autocomplete="off" maxlength="160" aria-describedby="hint">
<small id="hint">8080 — порт внутри VM. host:3000 — порт вашего процесса на helios. Пустое поле закрывает все адреса.</small>
<button type="submit">Сохранить порты</button><output id="result" aria-live="polite"></output></form>
<script nonce="<?= $nonce ?>">
const key = new URLSearchParams(location.hash.slice(1)).get('key') || '';
history.replaceState(null, '', location.pathname + location.search);
const form = document.querySelector('form'), input = document.querySelector('input'), button = document.querySelector('button'), result = document.querySelector('output');
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
</script></body></html>
<?php
    exit;
}
if (!ini_get('allow_url_fopen')) {
    http_response_code(503); header('Content-Type: application/json'); echo '{"error":"PHP allow_url_fopen отключён."}'; exit;
}
if (!preg_match('~^/(?:_config|(?:vm|host)/[0-9]{1,5}(?:/.*)?)$~D', $path)) {
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
if ($path === '/_config') header('Cache-Control: no-store');
if ($_SERVER['REQUEST_METHOD'] !== 'HEAD') echo $data;
