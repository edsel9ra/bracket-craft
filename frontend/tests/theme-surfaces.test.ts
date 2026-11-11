import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { compileStyle } from 'vue/compiler-sfc';

const read = (path: string) => readFileSync(new URL(`../app/${path}`, import.meta.url), 'utf8');
const disabledConsumers = [
  'components/ui/Button.vue', 'components/RulesEditor.vue', 'components/workspace/setup/SetupTeams.vue',
  'pages/login.vue', 'pages/organization.vue', 'pages/admin/index.vue', 'pages/workspace/index.vue',
  'pages/workspace/tournaments/[id]/rosters.vue',
];

test('disabled consumers override opacity locally only in explicit light and system-light scopes', () => {
  for (const path of disabledConsumers) {
    const source = read(path);
    assert.match(source, /:root\[data-theme="light"\]/, path);
    assert.match(source, /@media \(prefers-color-scheme: light\)/, path);
    assert.match(source, /:root\[data-theme="system"\]/, path);
    assert.match(source, /opacity: 1;/, path);
  }
  const button = read('components/ui/Button.vue');
  assert.match(button, /background: var\(--color-surface-bright\); color: var\(--color-muted\)/);
  assert.doesNotMatch(read('assets/css/main.css'), /\[disabled\][^{]*\{[^}]*opacity: 1/);
});

test('clear dialog backdrops use one alpha layer and preserve native modal cancellation', () => {
  for (const path of ['components/ui/ConfirmDialog.vue', 'components/public/PublicLineupModal.vue']) {
    const source = read(path);
    assert.match(source, /:root\[data-theme="light"\]/, path);
    assert.match(source, /:root\[data-theme="system"\]/, path);
    assert.match(source, /::backdrop \{ background: color-mix\(in srgb, var\(--color-shadow\) 32%, transparent\); opacity: 1; \}/, path);
    assert.match(source, /showModal\(\)/);
    assert.match(source, /@cancel/);
  }
});

test('clear initials retain the mirrored avatar role and remote images are never filtered', () => {
  for (const path of ['components/TeamCrest.vue', 'components/public/PublicPlayerStatsTable.vue']) {
    const source = read(path);
    assert.match(source, /color: var\(--color-avatar-ink\)/);
    assert.doesNotMatch(source, /filter:|mix-blend-mode/);
    assert.match(source, /<img/);
    assert.match(source, /@error/);
  }
});

test('compiled conditional surface rules retain their consumer instead of styling html', () => {
  for (const path of [...disabledConsumers, 'components/ui/ConfirmDialog.vue', 'components/public/PublicLineupModal.vue']) {
    const source = read(path).match(/<style[^>]*>([\s\S]*?)<\/style>/)![1]!;
    const result = compileStyle({ source, filename: path, id: 'data-v-theme', scoped: true });
    assert.deepEqual(result.errors, []);
    assert.doesNotMatch(result.code, /:root\[data-theme="(?:light|system)"\]\s*\{/, path);
    assert.match(result.code, /:root\[data-theme="light"\][^{]*\[data-v-theme\]/, path);
  }
});
