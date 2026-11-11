import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { createConfirmQueue, singleFlightConfirm } from '../app/utils/confirmQueue.ts';

const options = { title: 'Title', message: 'Consequence', confirmLabel: 'Proceed', tone: 'danger' as const };

test('single-flight callers ignore duplicate activations without bypassing the shared queue', async () => {
  const queue = createConfirmQueue();
  const confirm = singleFlightConfirm(queue.confirm);
  let sent = 0;
  const action = async () => { if (await confirm(options)) sent++; };
  const first = action();
  const id = queue.active!.id;
  await action();
  assert.equal(queue.active!.id, id);
  assert.equal(sent, 0);
  queue.settle(false, id);
  await first;
  assert.equal(sent, 0);
  const accepted = action();
  const otherCaller = singleFlightConfirm(queue.confirm);
  const queued = otherCaller(options);
  queue.settle(true, queue.active!.id);
  await accepted;
  assert.equal(sent, 1);
  assert.ok(queue.active);
  queue.cancelAll();
  assert.equal(await queued, false);
});

test('single-flight lock releases after rejection or navigation cancellation', async () => {
  const failing = singleFlightConfirm(async () => { throw new Error('dialog unavailable'); });
  await assert.rejects(failing(options), /dialog unavailable/);
  await assert.rejects(failing(options), /dialog unavailable/);
  const queue = createConfirmQueue();
  const confirm = singleFlightConfirm(queue.confirm);
  const first = confirm(options);
  queue.cancelAll();
  assert.equal(await first, false);
  const next = confirm(options);
  queue.settle(true, queue.active!.id);
  assert.equal(await next, true);
});

test('version selector restores its value before waiting and route guards preserve cancellation', () => {
  const page = readFileSync(new URL('../app/pages/workspace/tournaments/[id]/index.vue', import.meta.url), 'utf8');
  const handler = page.slice(page.indexOf('async function onVersionChange'), page.indexOf('onBeforeRouteLeave('));
  assert.ok(handler.indexOf('select.value = selectedVersionId.value') < handler.indexOf('await confirm('));
  assert.ok(handler.indexOf('if (!effect.proceed)') < handler.indexOf('selectedVersionId.value = next'));
  assert.match(page, /onBeforeRouteLeave\(async \(to\) =>/);
  assert.match(page, /if \(!effect.proceed\) return false;/);
  const match = readFileSync(new URL('../app/pages/workspace/matches/[id].vue', import.meta.url), 'utf8');
  assert.match(match, /return confirm\(\{ title: t\('confirm.leaveMatch.title'\)/);
  assert.match(match, /closeResolutionDecision\(\{ \.\.\.closeInput, confirmed: true \}\)/);
  const resolutionHandler = match.slice(match.indexOf('async function onResolutionChange'), match.indexOf('const eventSubstitutionTeam'));
  assert.ok(resolutionHandler.indexOf('select.value = resolution.value') < resolutionHandler.indexOf('await changeResolution(next)'));
  assert.match(match, /@change="onResolutionChange"/);
});

test('every confirmation action has a localized title and verb in both catalogs', () => {
  const catalog = readFileSync(new URL('../app/composables/useI18n.ts', import.meta.url), 'utf8');
  for (const action of ['discardChanges', 'deactivate', 'revokeInvitation', 'reopenInvitation', 'changeResolution', 'discardDraft', 'leaveMatch', 'closeReport', 'publish', 'changeVersion', 'leaveTournament', 'replaceRules', 'removeCrest', 'saveRules', 'regenerateSchedule', 'revokePhotoConsent']) {
    for (const field of ['title', 'action']) {
      const key = `confirm.${action}.${field}`;
      assert.equal(catalog.split(`'${key}':`).length - 1, 2, key);
    }
  }
});

test('confirmation opens one request at a time and preserves FIFO order', async () => {
  const queue = createConfirmQueue();
  const first = queue.confirm(options);
  const firstId = queue.active!.id;
  const second = queue.confirm({ ...options, title: 'Second' });
  assert.equal(queue.active!.options.title, 'Title');
  queue.settle(true, firstId);
  assert.equal(await first, true);
  assert.equal(queue.active!.options.title, 'Second');
  queue.settle(false, queue.active!.id);
  assert.equal(await second, false);
  assert.equal(queue.active, null);
});

test('double clicks and stale close events cannot settle the next request', async () => {
  const queue = createConfirmQueue();
  const first = queue.confirm(options);
  const id = queue.active!.id;
  const second = queue.confirm(options);
  queue.settle(true, id);
  queue.settle(false, id);
  assert.notEqual(queue.active!.id, id);
  assert.equal(await first, true);
  queue.settle(true, queue.active!.id);
  assert.equal(await second, true);
});

test('navigation cancellation resolves active and queued promises, including an empty queue', async () => {
  const queue = createConfirmQueue();
  queue.cancelAll();
  const first = queue.confirm(options);
  const second = queue.confirm(options);
  queue.cancelAll();
  queue.cancelAll();
  assert.deepEqual(await Promise.all([first, second]), [false, false]);
  assert.equal(queue.active, null);
  const third = queue.confirm(options);
  queue.settle(true, queue.active!.id);
  assert.equal(await third, true);
});

test('queues are isolated per app and snapshot their options', async () => {
  const left = createConfirmQueue();
  const right = createConfirmQueue();
  const mutable = { ...options };
  const result = left.confirm(mutable);
  mutable.title = 'Changed';
  assert.equal(left.active!.options.title, 'Title');
  assert.equal(right.active, null);
  left.cancelAll();
  assert.equal(await result, false);
});

test('dialog uses native modality, cancellation, safe initial focus and focus restoration', () => {
  const dialog = readFileSync(new URL('../app/components/ui/ConfirmDialog.vue', import.meta.url), 'utf8');
  assert.match(dialog, /<dialog/);
  assert.match(dialog, /showModal\(\)/);
  assert.match(dialog, /@cancel.prevent=/);
  assert.match(dialog, /tone === 'danger' \? cancelButton : confirmButton/);
  assert.match(dialog, /opener\?\.isConnected/);
  assert.match(dialog, /opener.focus\(\)/);
  assert.match(dialog, /prefers-reduced-motion: reduce/);
  const composable = readFileSync(new URL('../app/composables/useConfirm.ts', import.meta.url), 'utf8');
  assert.match(composable, /beforeEach\(\(\) => \{ created.cancelAll\(\); \}\)/);
  const app = readFileSync(new URL('../app/app.vue', import.meta.url), 'utf8');
  assert.equal([...app.matchAll(/<ConfirmDialog\s*\/>/g)].length, 1);
});
