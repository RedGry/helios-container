const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const page = fs.readFileSync(path.join(__dirname, '..', 'gateway.php'), 'utf8');
const scripts = [...page.matchAll(/<script nonce="<\?= \$nonce \?>">([\s\S]*?)<\/script>/g)].map(match => match[1]);
assert.equal(scripts.length, 2);
for (const source of scripts) new vm.Script(source);
assert(page.indexOf(scripts[0]) < page.indexOf('<style'));
assert(page.includes('id="theme" aria-label="Тема оформления"'));
assert(page.includes('id="update-notice"') && page.includes("releaseDialog.id='release-dialog'"));
assert.equal((page.match(/localStorage\./g) || []).length, 2);
assert(!page.includes('sessionStorage'));

function browser(saved, dark = true, denied = false) {
  const writes = [], listeners = [];
  const media = { matches: dark, addEventListener: (_, callback) => listeners.push(callback) };
  const context = { document: { documentElement: { dataset: {} } }, window: {}, matchMedia: () => media,
    localStorage: {
      getItem: key => { assert.equal(key, 'helios-container-theme'); if (denied) throw Error('denied'); return saved; },
      setItem: (key, value) => { assert.equal(key, 'helios-container-theme'); assert(['dark', 'light', 'system'].includes(value)); if (denied) throw Error('denied'); writes.push([key, value]); saved = value; }
    }
  };
  vm.runInNewContext(scripts[0], context);
  return { context, writes, media, listeners, saved: () => saved };
}

let instance = browser(null, false);
assert.equal(instance.context.document.documentElement.dataset.theme, 'dark');
instance.context.window.hcSetTheme('light');
assert.equal(instance.context.document.documentElement.dataset.theme, 'light');
assert.equal(instance.writes.length, 1);
assert.equal(browser(instance.saved()).context.document.documentElement.dataset.theme, 'light');
instance.context.window.hcSetTheme('panel-secret');
assert.equal(instance.writes.length, 1);
assert.equal(browser('panel-secret').context.document.documentElement.dataset.theme, 'dark');

instance = browser('system', false);
assert.equal(instance.context.document.documentElement.dataset.theme, 'light');
instance.media.matches = true;
instance.listeners[0]();
assert.equal(instance.context.document.documentElement.dataset.theme, 'dark');
instance.context.window.hcSetTheme('light');
instance.listeners[0]();
assert.equal(instance.context.document.documentElement.dataset.theme, 'light');

instance = browser(null, true, true);
instance.context.window.hcSetTheme('light');
assert.equal(instance.context.document.documentElement.dataset.theme, 'light');
assert.equal(instance.writes.length, 0);
console.log('Theme tests passed: persistence, system preference, storage denial, credential isolation and script syntax.');
