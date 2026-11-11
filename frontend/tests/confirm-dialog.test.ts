import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { createConfirmQueue } from '../app/utils/confirmQueue.ts';

const options = { title: 'Title', message: 'Consequence', confirmLabel: 'Proceed', tone: 'danger' as const };

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
