const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const php = fs.readFileSync(path.join(__dirname, '../gateway.php'), 'utf8');
const source = php.slice(php.indexOf('const releaseDialog='), php.indexOf('async function api('));
function panel(update) {
  const nodes = new Map();
  function el(tag, text = '') {
    const node = {tag, textContent: text, hidden: false, open: false, children: [], handlers: {},
      setAttribute() {}, append(...children) {this.children.push(...children);},
      addEventListener(type, handler) {this.handlers[type] = handler;},
      showModal() {this.open = true;}, close() {this.open = false;}};
    Object.defineProperty(node, 'id', {set(id) {nodes.set('#' + id, node);}});
    return node;
  }
  const banner = el('button'); banner.id = 'update-notice';
  const context = vm.createContext({el, $: selector => nodes.get(selector),
    snapshot: {update}, document: {body: el('body')}});
  vm.runInContext(source, context); vm.runInContext('renderRelease()', context);
  return {nodes, context, banner, dialog: nodes.get('#release-dialog')};
}
const update = {available: true, current_version: '0.1.0', latest_version: '0.2.0',
  changelog_url: 'https://github.com/RedGry/helios-container/releases/tag/v0.2.0',
  notes: '### New Features\n- Новая панель', compatible: true};

test('new release opens changelog; closing dialog preserves the banner', () => {
  const p = panel(update);
  assert.equal(p.banner.hidden, false);
  assert.match(p.banner.textContent, /0\.2\.0/);
  p.banner.handlers.click(); assert.equal(p.dialog.open, true);
  assert.equal(p.nodes.get('#release-notes').textContent, update.notes);
  p.dialog.children[4].children[1].handlers.click();
  assert.equal(p.dialog.open, false);
  assert.equal(p.banner.hidden, false);
  vm.runInContext('renderRelease()', p.context); assert.equal(p.banner.hidden, false);
});
test('current or missing version has no notification', () => {
  for (const value of [undefined, {...update, available: false}, {...update, latest_version: 'beta'}]) {
    const p = panel(value); assert.equal(p.banner.hidden, true);
    p.banner.handlers.click(); assert.equal(p.dialog.open, false);
  }
});
test('release text is plain text and link cannot be supplied by an attacker', () => {
  const p = panel({...update, notes: '<img src=x onerror=alert(1)>', changelog_url: 'javascript:alert(1)'});
  assert.equal(p.nodes.get('#release-notes').textContent, '<img src=x onerror=alert(1)>');
  assert.equal(p.dialog.children[4].children[0].href, update.changelog_url);
});
test('incompatible release offers changelog and explains missing Rust binary', () => {
  const p = panel({...update, compatible: false, notes: ''});
  assert.equal(p.banner.hidden, false);
  assert.match(p.dialog.children[3].textContent, /нет совместимой Rust-сборки/);
  assert.match(p.nodes.get('#release-notes').textContent, /странице релиза/);
});
test('updated installation clears notification and an open changelog', () => {
  const p = panel(update); p.banner.handlers.click();
  vm.runInContext('snapshot.update.available=false; renderRelease()', p.context);
  assert.equal(p.banner.hidden, true); assert.equal(p.dialog.open, false);
});
