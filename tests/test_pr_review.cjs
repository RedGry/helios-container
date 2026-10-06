const {test} = require('node:test');
const assert = require('node:assert/strict');
const {eligible, actionUpdate, run} = require('../tools/pr-review.cjs');

function pr(overrides = {}) {
  return {number: 1, state: 'open', draft: false, changed_files: 1,
    user: {login: 'developer'}, base: {ref: 'main', repo: {full_name: 'owner/repo'}},
    head: {ref: 'feature/docs', sha: 'tested', repo: {full_name: 'owner/repo'}}, ...overrides};
}
const docs = [{filename: 'docs/guide.md', status: 'modified'}];

test('only existing documentation in same-repository main PRs is approved', () => {
  assert.equal(eligible(pr(), docs), true);
  for (const change of [{draft: true}, {changed_files: 2},
    {head: {ref: 'release/0.1.0', repo: {full_name: 'owner/repo'}}},
    {head: {ref: 'feature/docs', repo: {full_name: 'other/repo'}}},
    {base: {ref: 'develop', repo: {full_name: 'owner/repo'}}}]) {
    assert.equal(eligible(pr(change), docs), false);
  }
  for (const filename of ['runtime.py', 'VERSION', 'CHANGELOG.md', 'CONTRIBUTING.md', '.agents/skills/release/SKILL.md']) {
    assert.equal(eligible(pr(), [{filename, status: 'modified'}]), false);
  }
  assert.equal(eligible(pr(), [{filename: 'docs/guide.md', status: 'removed'}]), false);
});

test('Dependabot approval requires a pure same-major action version update', () => {
  const file = {filename: '.github/workflows/check.yml', status: 'modified',
    patch: '@@ -1 +1 @@\n-      - uses: actions/checkout@v4.1.0\n+      - uses: actions/checkout@v4.2.0'};
  assert.equal(actionUpdate(file), true);
  assert.equal(eligible(pr({user: {login: 'dependabot[bot]'}}), [file]), true);
  assert.equal(eligible(pr(), [file]), false);
  assert.equal(actionUpdate({...file, patch: file.patch.replace('v4.2.0', 'v5.0.0')}), false);
  assert.equal(actionUpdate({...file, patch: file.patch + '\n+      - run: echo changed'}), false);
  assert.equal(actionUpdate({...file, patch: undefined}), false);
});

function harness({conclusion = 'success', pull = pr(), reviews = [], current = pull} = {}) {
  const calls = [];
  const github = {
    rest: {pulls: {
      get: async () => ({data: calls.some(c => c.kind === 'get') ? current : (calls.push({kind: 'get'}), pull)}),
      listFiles: 'files', listReviews: 'reviews',
      createReview: async data => calls.push({kind: 'create', ...data}),
      dismissReview: async data => calls.push({kind: 'dismiss', ...data})
    }},
    paginate: async method => method === 'files' ? docs : reviews
  };
  return {calls, input: {github, core: {info() {}}, context: {repo: {owner: 'owner', repo: 'repo'},
    payload: {workflow_run: {event: 'pull_request', head_sha: 'tested', conclusion,
      html_url: 'https://github.com/owner/repo/actions/runs/1', pull_requests: [{number: 1}]}}}}};
}

test('successful CI posts approval for the tested commit', async () => {
  const h = harness(); await run(h.input);
  const review = h.calls.find(c => c.kind === 'create');
  assert.equal(review.event, 'APPROVE');
  assert.equal(review.commit_id, 'tested');
});

test('failed CI dismisses prior approval and posts comment', async () => {
  const h = harness({conclusion: 'failure', reviews: [{id: 9, state: 'APPROVED', commit_id: 'old',
    user: {login: 'github-actions[bot]'}, body: '<!-- helios-auto-review -->'}]});
  await run(h.input);
  assert.equal(h.calls.find(c => c.kind === 'dismiss').review_id, 9);
  assert.equal(h.calls.find(c => c.kind === 'create').event, 'COMMENT');
});

test('stale CI and changed PR head cannot approve an untested commit', async () => {
  for (const options of [
    {pull: pr({head: {...pr().head, sha: 'new'}})},
    {current: pr({head: {...pr().head, sha: 'new'}})}
  ]) {
    const h = harness(options); await run(h.input);
    assert.equal(h.calls.some(c => c.kind === 'create'), false);
  }
});

test('rerunning the same CI does not duplicate its review', async () => {
  const first = harness(); await run(first.input);
  const created = first.calls.find(c => c.kind === 'create');
  const again = harness({reviews: [{...created, state: 'APPROVED', user: {login: 'github-actions[bot]'}}]});
  await run(again.input);
  assert.equal(again.calls.some(c => c.kind === 'create'), false);
});
