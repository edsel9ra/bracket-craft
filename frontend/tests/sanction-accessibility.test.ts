import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { runInNewContext } from 'node:vm';
import test from 'node:test';
import ts from 'typescript';
import * as vue from 'vue';

test('localized form errors receive focus after rendering without native dialogs', async () => {
  const exports: { useSanctionErrorFocus?: (error: vue.Ref<string>) => vue.Ref<{ focus: () => void } | null> } = {};
  const source = readFileSync(new URL('../app/composables/useSanctionErrorFocus.ts', import.meta.url), 'utf8');
  runInNewContext(ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText, { exports, ...vue });
  const error = vue.ref(''); const target = exports.useSanctionErrorFocus!(error); let focused = 0;
  target.value = { focus: () => { focused++; } }; error.value = 'sanction.error.validation';
  await vue.nextTick(); await new Promise<void>((resolve) => setImmediate(resolve)); assert.equal(focused, 1);
  error.value = ''; await vue.nextTick(); assert.equal(focused, 1);
});

test('all sanction forms expose a keyboard-focusable localized error and Workspace-only detail', () => {
  for (const name of ['SanctionAppealForm', 'SanctionProposalForm', 'SanctionDecisionForm', 'SanctionWithdrawalForm', 'SanctionAuthorizations']) {
    const source = readFileSync(new URL(`../app/components/sanction/${name}.vue`, import.meta.url), 'utf8');
    assert.match(source, /useSanctionErrorFocus\(error\)/);
    assert.match(source, /ref="errorTarget" tabindex="-1"/);
    assert.equal(/window\.(confirm|alert|prompt)/.test(source), false);
  }
});
