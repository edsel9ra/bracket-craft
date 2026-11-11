import { existsSync, readFileSync, statSync } from 'node:fs';
import { dirname, isAbsolute, relative, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const app = fileURLToPath(new URL('../../app/', import.meta.url));

export function featureSource(entry: string | URL): string {
  if (!String(entry)) throw new Error('A feature entry is required');
  const start = entry instanceof URL ? fileURLToPath(entry) : resolve(app, entry);
  const visited = new Set<string>();
  const sources: string[] = [];

  function visit(file: string): void {
    if (visited.has(file)) return;
    visited.add(file);
    const source = readFileSync(file, 'utf8');
    const dependencies = [
      ...source.matchAll(/^\s*import\s+(?:(?!['"])[^;]*?\s+from\s+)?(['"])([^'"]+)\1/gm),
      ...source.matchAll(/<style\b[^>]*\bsrc=(['"])([^'"]+)\1/g),
    ];
    for (const match of dependencies) {
      const name = match[2]!;
      const local = name.startsWith('~/') || name.startsWith('@/')
        ? resolve(app, name.slice(2))
        : name.startsWith('.') ? resolve(dirname(file), name) : null;
      if (!local) continue;
      const path = relative(app, local).replaceAll('\\', '/');
      if (!/^(?:components\/(?:workspace|match)\/|composables\/use[^/]*$)/.test(path)) continue;
      if (isAbsolute(path) || path.startsWith('../')) continue;
      const dependency = [local, `${local}.ts`, `${local}.vue`, resolve(local, 'index.ts')].find((candidate) => existsSync(candidate) && statSync(candidate).isFile());
      if (!dependency) throw new Error(`Missing local feature source: ${name} from ${file}`);
      visit(dependency);
    }
    sources.push(source);
  }

  visit(start);
  return sources.join('\n');
}
