import assert from 'node:assert/strict';
import test from 'node:test';

import {
  createLocalDraftResolver,
  type LocalDraftChoice,
} from '../app/utils/matchLiveLocalDraft.ts';
import { createLiveEditorState } from '../app/utils/matchLiveEditor.ts';

function harness(overrides: {
  hasDraft?: boolean;
  confirm?: () => Promise<LocalDraftChoice | null>;
} = {}) {
  const calls: string[] = [];
  let draftText: { events: string[]; result: string } | null = overrides.hasDraft
    ? { events: ['goal m-1'], result: 'sin confirmar' }
    : null;
  const editor = createLiveEditorState();
  const resolver = createLocalDraftResolver({
    hasLocalDraft: () => draftText !== null && draftText.events.length > 0,
    confirmResolve: async () => {
      calls.push('confirm');
      return overrides.confirm ? overrides.confirm() : 'keep';
    },
    clearDraft: () => {
      calls.push('clear');
      draftText = null;
    },
    markPending: (raw) => {
      calls.push('markPending');
      void raw;
    },
  });
  return { resolver, editor, calls, draft: () => draftText };
}

test('sin borrador local el inicio procede sin confirmar ni limpiar', async () => {
  const { resolver, calls } = harness({ hasDraft: false });
  assert.equal(await resolver.resolveBeforeStart(), 'proceed');
  assert.deepEqual(calls, []);
});

test('con borrador, mantenerlo lo conserva intacto y el inicio procede', async () => {
  const { resolver, calls, draft } = harness({ hasDraft: true, confirm: async () => 'keep' });
  assert.equal(await resolver.resolveBeforeStart(), 'proceed');
  assert.deepEqual(calls, ['confirm']);
  assert.equal(draft()!.events.length, 1);
  assert.equal(draft()!.result, 'sin confirmar');
});

test('descartar el borrador lo limpia de forma expresa antes de iniciar', async () => {
  const { resolver, calls, draft } = harness({ hasDraft: true, confirm: async () => 'discard' });
  assert.equal(await resolver.resolveBeforeStart(), 'proceed');
  assert.deepEqual(calls, ['confirm', 'clear']);
  assert.equal(draft(), null);
});

test('cancelar la confirmación aborta el inicio y conserva el texto', async () => {
  const { resolver, calls, draft } = harness({ hasDraft: true, confirm: async () => null });
  assert.equal(await resolver.resolveBeforeStart(), 'cancelled');
  assert.deepEqual(calls, ['confirm']);
  assert.equal(draft()!.events.length, 1);
});

test('un fallo de la confirmación conserva el borrador y aborta sin tocarlo', async () => {
  const { resolver, draft } = harness({
    hasDraft: true,
    confirm: async () => { throw new Error('dialog unavailable'); },
  });
  assert.equal(await resolver.resolveBeforeStart(), 'cancelled');
  assert.equal(draft()!.events.length, 1);
});

test('el borrador clásico jamás se reenvía como hechos del compartido', async () => {
  // Ni 'keep' ni 'discard' alimentan el editor compartido: los eventos locales
  // solo se aceptan cuando el servidor los devuelve en un snapshot autorizado.
  for (const choice of ['keep', 'discard'] as const) {
    const { resolver, editor, calls } = harness({ hasDraft: true, confirm: async () => choice });
    await resolver.resolveBeforeStart();
    assert.equal(editor.shared, null, choice);
    assert.equal(editor.pending.length, 0, choice);
    assert.equal(calls.includes('markPending'), false, choice);
  }
});

test('la resolución no se repite: cada inicio con borrador pide decisión expresa', async () => {
  let confirmed = 0;
  const { resolver } = harness({ hasDraft: true, confirm: async () => { confirmed += 1; return 'keep'; } });
  assert.equal(await resolver.resolveBeforeStart(), 'proceed');
  assert.equal(await resolver.resolveBeforeStart(), 'proceed');
  // 'keep' conserva el texto, así que el siguiente inicio vuelve a preguntar.
  assert.equal(confirmed, 2);
});
