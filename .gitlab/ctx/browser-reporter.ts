import { createHash } from 'node:crypto';
import { execFileSync } from 'node:child_process';
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { resolve, relative, isAbsolute } from 'node:path';
import type { FullResult, Reporter, Suite } from '@playwright/test/reporter';

// Test annotations connect actual executed browser journeys to stable AC IDs.
export default class AcceptanceReporter implements Reporter {
  private suite!: Suite;

  onBegin(_config: unknown, suite: Suite) { this.suite = suite; }

  async onEnd(result: FullResult): Promise<{ status: 'passed' | 'failed' }> {
    try {
      const env = (key: string): string => {
        if (!process.env[key]) throw new Error(`Missing ${key}`);
        return process.env[key]!;
      };
      const sourceSha = env('CI_COMMIT_SHA');
      const git = (args: string[]) => execFileSync('git', args, { encoding: 'utf8' }).trim();
      if (git(['rev-parse', 'HEAD']) !== sourceSha
          || git(['status', '--porcelain', '--untracked-files=normal'])) {
        throw new Error('Browser candidate changed or checkout is dirty');
      }
      const path = resolve(env('CTX_AC_MANIFEST'));
      const local = relative(process.cwd(), path);
      if (isAbsolute(local) || local.startsWith('..')) throw new Error('Manifest outside checkout');
      const raw = readFileSync(path);
      const manifest = JSON.parse(raw.toString());
      const scope = env('CTX_AC_SCOPE');
      if (manifest.version !== 1 || !/^E[1-9][0-9]*$/.test(manifest.epic)
          || !(scope === manifest.epic || new RegExp(`^${manifest.epic}-[1-9][0-9]*$`).test(scope))) {
        throw new Error('Invalid manifest or scope');
      }
      const required = manifest.criteria.filter((c: any) =>
        (scope === manifest.epic || c.id.split('.')[0] === scope) && c.methods.includes('browser'));
      if (!required.length) throw new Error('No browser ACs for the requested scope');
      const tests = this.suite.allTests();
      const job = new URL(env('CI_JOB_URL'));
      if (job.protocol !== 'https:' || job.username || job.password) throw new Error('Invalid job URL');
      const criteria = required.map((c: any) => {
        const matches = tests.filter(t => t.annotations.some(a => a.type === 'ac' && a.description === c.id));
        const passed = matches.length > 0 && matches.every(t => t.expectedStatus === 'passed'
          && t.outcome() === 'expected' && t.results.length > 0
          && t.results.every(r => r.status === 'passed'));
        return { id: c.id, evidence: { browser: {
          status: passed ? 'passed' : 'failed',
          test_ids: matches.map(t => t.titlePath().join(' > ')),
          url: `${job.href.replace(/\/$/, '')}/artifacts/browse/.ctx/browser/`,
        } } };
      });
      const passed = result.status === 'passed'
        && criteria.every((c: any) => c.evidence.browser.status === 'passed');
      // A failure anywhere in the browser job invalidates its coverage claim.
      if (!passed) for (const c of criteria) c.evidence.browser.status = 'failed';
      const report = {
        version: 1, project_id: env('CI_PROJECT_ID'), pipeline_id: env('CI_PIPELINE_ID'),
        source_sha: sourceSha, scope,
        manifest_sha256: createHash('sha256').update(raw).digest('hex'), criteria,
      };
      mkdirSync('.ctx/browser', { recursive: true });
      writeFileSync('.ctx/browser/acceptance.json', JSON.stringify(report, null, 2) + '\n');
      return { status: passed ? 'passed' : 'failed' };
    } catch (error) {
      console.error(`Browser acceptance blocked: ${error}`);
      return { status: 'failed' };
    }
  }
}
