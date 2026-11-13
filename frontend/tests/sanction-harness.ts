import { readFileSync } from 'node:fs';
import { runInNewContext } from 'node:vm';
import ts from 'typescript';
import * as vue from 'vue';
import { compileScript, parse } from 'vue/compiler-sfc';
import * as helpers from '../app/utils/sanctions.ts';

export function sanctionComponent(name: string, globals: Record<string, unknown> = {}) {
  const source = readFileSync(new URL(`../app/components/sanction/${name}.vue`, import.meta.url), 'utf8');
  const { descriptor } = parse(source);
  const javascript = ts.transpileModule(compileScript(descriptor, { id: name, inlineTemplate: true }).content, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText;
  const exports: { default?: vue.Component } = {};
  const passthrough = vue.defineComponent({ setup(_, { slots }) { return () => vue.h('div', slots.default?.({ id: 'field' })); } });
  runInNewContext(javascript, { exports, ...vue,
    require: (path: string) => path === 'vue' ? vue : path.endsWith('.vue') ? { __esModule: true, default: passthrough } : helpers,
    useI18n: () => ({ t: (key: string) => key, formatDateTime: (value: string) => value }),
    useId: () => 'sanction', useConfirm: () => ({ confirm: async () => true }),
    useSanctionCases: () => ({}), useAuthStore: () => ({ access: null }), ...globals,
    useSanctionErrorFocus: () => vue.ref(null),
  });
  return exports.default!;
}

export function nodes(value: unknown): vue.VNode[] {
  if (Array.isArray(value)) return value.flatMap(nodes);
  if (typeof value === 'function') return nodes(value());
  if (!value || typeof value !== 'object') return [];
  if (vue.isVNode(value)) return [value, ...nodes(value.children)];
  return Object.values(value).flatMap(nodes);
}
