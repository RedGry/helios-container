// Rule-based review after CI. No PR code is executed by this workflow.
const marker = '<!-- helios-auto-review -->';

function actionUpdate(file) {
  if (!/^\.github\/workflows\/[^/]+\.ya?ml$/.test(file.filename) || file.status !== 'modified' || !file.patch) return false;
  const removed = [], added = [];
  for (const line of file.patch.split('\n')) {
    if (!/^[+-]/.test(line) || line.startsWith('+++') || line.startsWith('---')) continue;
    const match = line.slice(1).match(/^\s*-?\s*uses:\s*([\w.-]+\/[\w./-]+)@v(\d+)(?:[.\w-]*)\s*(?:#.*)?$/);
    if (!match) return false;
    (line[0] === '-' ? removed : added).push(`${match[1]}@${match[2]}`);
  }
  return removed.length > 0 && JSON.stringify(removed) === JSON.stringify(added);
}

function eligible(pr, files) {
  if (pr.draft || !files.length || files.length !== pr.changed_files || pr.head.repo?.full_name !== pr.base.repo.full_name) return false;
  if (pr.base.ref !== 'develop' || pr.head.ref.startsWith('release/')) return false;
  const docs = files.every(file => file.status === 'modified' &&
    (file.filename === 'README.md' || /^docs\/.*\.md$/.test(file.filename)));
  return docs || (pr.user.login === 'dependabot[bot]' && files.every(actionUpdate));
}

async function run({github, context, core}) {
  const ci = context.payload.workflow_run;
  if (ci.event !== 'pull_request') return;
  const repo = context.repo;
  // Fork runs may omit pull_requests; fetch associations by the tested commit.
  const associated = ci.pull_requests?.length ? ci.pull_requests :
    await github.paginate(github.rest.repos.listPullRequestsAssociatedWithCommit, {...repo, commit_sha: ci.head_sha, per_page: 100});
  for (const item of associated) {
    const {data: pr} = await github.rest.pulls.get({...repo, pull_number: item.number});
    if (pr.state !== 'open' || pr.head.sha !== ci.head_sha || !['main', 'develop'].includes(pr.base.ref)) continue;
    const params = {...repo, pull_number: pr.number};
    const files = await github.paginate(github.rest.pulls.listFiles, {...params, per_page: 100});
    const reviews = await github.paginate(github.rest.pulls.listReviews, {...params, per_page: 100});
    const botReviews = reviews.filter(review => review.user?.login === 'github-actions[bot]' && review.body?.includes(marker));
    const approve = ci.conclusion === 'success' && eligible(pr, files);
    // A green review of an older revision must not survive a failed or ineligible update.
    for (const review of botReviews.filter(review => review.state === 'APPROVED' && (!approve || review.commit_id !== pr.head.sha))) {
      await github.rest.pulls.dismissReview({...params, review_id: review.id,
        message: 'После изменения PR автоматическое одобрение требуется проверить заново.'});
    }
    const success = ci.conclusion === 'success';
    const body = `${marker}\n## Automated Review\n\n` +
      `Коммит: \`${pr.head.sha.slice(0, 12)}\`. Изменено файлов: ${files.length}.\n\n` +
      `Проверки: ${success ? 'пройдены' : 'не пройдены'} ([Check](${ci.html_url})).\n\n` +
      (approve ? 'PR соответствует правилам автоматического одобрения: документация или обновления Actions от Dependabot в пределах основной версии.' :
        'Автоматическое одобрение не выдано. Требуется ревью кода или выпуска человеком; отчёт проверяет CI и правила PR.') +
      '\n\nСлияние и публикация релиза выполняются отдельно.';
    if (botReviews.some(review => review.commit_id === pr.head.sha && review.body === body &&
        review.state === (approve ? 'APPROVED' : 'COMMENTED'))) continue;
    // Recheck the revision immediately before posting feedback.
    const {data: current} = await github.rest.pulls.get(params);
    if (current.head.sha !== pr.head.sha || current.state !== 'open') continue;
    await github.rest.pulls.createReview({...params, commit_id: pr.head.sha,
      event: approve ? 'APPROVE' : 'COMMENT', body});
    core.info(`PR #${pr.number}: ${approve ? 'одобрен по правилам' : 'отчёт опубликован'}`);
  }
}

module.exports = {eligible, actionUpdate, run};
