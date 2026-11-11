import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { runInNewContext } from 'node:vm';
import test from 'node:test';
import ts from 'typescript';
import * as vue from 'vue';
import { compileScript, parse } from 'vue/compiler-sfc';
import { renderToString } from 'vue/server-renderer';

const read = (path: string) => readFileSync(new URL(`../app/${path}`, import.meta.url), 'utf8');

function harness(locale: 'es' | 'en' = 'es') {
  const catalog = read('composables/useI18n.ts');
  const state = vue.ref('dark');
  const choices: unknown[] = [];
  const { descriptor } = parse(read('components/ThemeSwitcher.vue'));
  const source = compileScript(descriptor, { id: 'theme-test', inlineTemplate: true }).content;
  const javascript = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText;
  const exports: { default?: vue.Component & { setup: (...args: unknown[]) => (...args: unknown[]) => vue.VNode } } = {};
  runInNewContext(javascript, {
    exports,
    require: () => vue,
    useId: () => vue.getCurrentInstance() ? vue.useId() : 'event-test',
    useTheme: () => ({ preference: state, setTheme(value: unknown) { choices.push(value); state.value = String(value); } }),
    useI18n: () => ({ t(key: string) {
      const matches = [...catalog.matchAll(new RegExp(`'${key.replaceAll('.', '\\.') }': '([^']*)'`, 'g'))];
      assert.equal(matches.length, 2, key);
      return matches[locale === 'es' ? 0 : 1]![1];
    } }),
  });
  return { component: exports.default!, state, choices };
}

test('native theme select has translated label, exact choices and unique SSR IDs', async () => {
  for (const locale of ['es', 'en'] as const) {
    const { component, state } = harness(locale);
    for (const preference of ['dark', 'light', 'system']) {
      state.value = preference;
      const html = await renderToString(vue.createSSRApp({ render: () => vue.h('div', [vue.h(component), vue.h(component)]) }));
      const ids = [...html.matchAll(/<select[^>]*id="([^"]+)"/g)].map(match => match[1]);
      assert.equal(ids.length, 2);
      assert.equal(new Set(ids).size, 2);
      for (const id of ids) assert.ok(html.includes(`for="${id}"`));
      for (const value of ['dark', 'light', 'system']) assert.equal([...html.matchAll(new RegExp(`<option value="${value}"`, 'g'))].length, 2);
      for (const label of locale === 'es' ? ['Tema', 'Oscuro', 'Claro', 'Sistema'] : ['Theme', 'Dark', 'Light', 'System']) assert.ok(html.includes(label), label);
      assert.match(html, new RegExp(`value="${preference}" selected`));
    }
  }
});

test('native change delegates only to setTheme without routing, networking or duplicated state', () => {
  const { component, state, choices } = harness();
  const render = component.setup({}, { expose() {} });
  const node = render({}, []);
  const select = (node.children as vue.VNode[])[1]!;
  for (const value of ['light', 'system', 'dark']) {
    select.props!.onChange({ target: { value } });
    assert.equal(state.value, value);
  }
  assert.deepEqual(choices, ['light', 'system', 'dark']);
  const source = read('components/ThemeSwitcher.vue');
  assert.doesNotMatch(source, /navigateTo|location|fetch|document\.cookie|localStorage|ref\(|useState|@keydown/);
});

test('public group preserves the floating language control; workspace groups preferences without adding a mobile row', () => {
  const root = read('app.vue');
  const publicGroup = read('components/PublicPreferences.vue');
  const shell = read('components/WorkspaceShell.vue');
  assert.match(root, /<PublicPreferences/);
  assert.match(publicGroup, /<ThemeSwitcher/);
  assert.match(publicGroup, /<LanguageSwitcher\s*\/>/);
  assert.match(publicGroup, /position: fixed/);
  assert.match(shell, /class="workspace-mobile-preferences"/);
  assert.equal((shell.match(/<ThemeSwitcher/g) ?? []).length, 2);
});
