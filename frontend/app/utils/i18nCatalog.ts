/**
 * Barrido de claves i18n (RF-029) y paridad de catálogos (RF-030).
 *
 * Este módulo es puro: no lee archivos, no toca el DOM y no ejecuta expresiones
 * del código analizado. Recibe el texto de las fuentes y devuelve las claves
 * que usa, para que la prueba las compare con los catálogos es/en de
 * `composables/useI18n.ts`.
 *
 * Las claves se **derivan del propio código**, nunca de una lista mantenida a
 * mano:
 *
 * - llamadas al traductor con literal: `t('clave')`, `t("clave")` y
 *   `t(`clave`)` cuando la plantilla es estática (sin `${…}`);
 * - tablas declarativas: propiedades cuyo nombre acaba en `Key`
 *   (`labelKey`, `descriptionKey`, `messageKey`, `actionKey`, …);
 * - la propiedad `key` de las fuentes únicas de roles y posiciones;
 * - los mapas cuyo nombre acaba en `_LABEL_KEYS` (estados de invitación y de
 *   miembro).
 *
 * Si una vista nueva usa una clave inexistente, entra sola en el barrido y la
 * prueba falla. Una plantilla dinámica (`t(`status.${code}`)`) no se puede
 * resolver estáticamente y queda fuera: su cobertura se comprueba con el
 * vocabulario que la genera.
 */

export interface CatalogSource {
  /** Ruta relativa, solo para el mensaje de error. */
  readonly name: string;
  readonly source: string;
}

const TRANSLATOR_CALL =
  /\bt\(\s*(?:'((?:[^'\\]|\\.)*)'|"((?:[^"\\]|\\.)*)"|`([^`$\\]*)`)\s*[,)]/g;
const KEY_PROPERTY = /\b[A-Za-z_$][\w$]*Key\s*:\s*'((?:[^'\\]|\\.)*)'/g;
const DEFINITION_KEY = /\bkey\s*:\s*'((?:[^'\\]|\\.)*)'/g;
const LABEL_KEYS_TABLE = /\b[A-Z][A-Z0-9_]*_LABEL_KEYS\s*=\s*\{([\s\S]*?)\}\s*as const;/g;
const LABEL_KEYS_VALUE = /:\s*'((?:[^'\\]|\\.)*)'/g;
const CATALOG_ENTRY = /^\s*'((?:[^'\\]|\\.)*)':\s*'((?:[^'\\]|\\.)*)'/gm;

function unescapeKey(key: string): string {
  return key.replace(/\\(['"\\])/g, '$1');
}

/**
 * Descarta los comentarios de bloque antes de buscar: la documentación puede
 * citar ejemplos como `t('clave')` sin que sean usos reales. No toca las
 * cadenas, así que una URL (`https://…`) sigue intacta.
 */
function stripBlockComments(source: string): string {
  return source.replace(/\/\*[\s\S]*?\*\//g, '');
}

function matches(pattern: RegExp, source: string): string[] {
  return Array.from(source.matchAll(pattern), (match) => unescapeKey(match[1] ?? ''));
}

/**
 * Claves usadas por las fuentes indicadas, en orden de aparición y sin
 * repetirlas dentro del mismo archivo. Un `key:` sin punto no es una clave i18n
 * (por ejemplo, la tecla `'Escape'`) y se ignora.
 */
export function extractUsedKeys(sources: readonly CatalogSource[]): Map<string, string[]> {
  const used = new Map<string, string[]>();

  const add = (key: string, file: string): void => {
    if (!key) return;
    const files = used.get(key);
    if (!files) {
      used.set(key, [file]);
      return;
    }
    if (!files.includes(file)) files.push(file);
  };

  for (const { name, source } of sources) {
    const code = stripBlockComments(source);
    for (const match of code.matchAll(TRANSLATOR_CALL)) {
      add(unescapeKey(match[1] ?? match[2] ?? match[3] ?? ''), name);
    }
    for (const key of matches(KEY_PROPERTY, code)) add(key, name);
    for (const key of matches(DEFINITION_KEY, code)) {
      if (key.includes('.')) add(key, name);
    }
    for (const table of code.matchAll(LABEL_KEYS_TABLE)) {
      for (const key of matches(LABEL_KEYS_VALUE, table[1] ?? '')) {
        if (key.includes('.')) add(key, name);
      }
    }
  }

  return used;
}

/** Claves declaradas por un catálogo (un idioma), en orden de aparición. */
export function catalogKeys(catalog: string): string[] {
  return Array.from(catalog.matchAll(CATALOG_ENTRY), (match) => unescapeKey(match[1] ?? ''));
}

/** Claves usadas que no existen en el catálogo, ordenadas y sin duplicados. */
export function findMissingKeys(
  used: Iterable<string>,
  catalog: Iterable<string>,
): string[] {
  const available = new Set(catalog);
  return [...new Set(used)].filter((key) => !available.has(key)).sort();
}

export interface CatalogParity {
  readonly onlySpanish: string[];
  readonly onlyEnglish: string[];
}

/** Atributos cuyo valor se muestra o se anuncia al usuario. */
const VISIBLE_ATTRIBUTES = ['placeholder', 'title', 'aria-label', 'aria-description', 'alt'] as const;

export interface VisibleLiteral {
  /** Ruta relativa, solo para el mensaje de error. */
  readonly file: string;
  readonly text: string;
}

function stripHtmlComments(source: string): string {
  return source.replace(/<!--[\s\S]*?-->/g, ' ');
}

/**
 * Nodos de texto de una plantilla Vue. Recorre el texto llevando el estado de
 * etiqueta y de comilla: un `>` dentro de un atributo (`v-if="a > b"`) no cierra
 * la etiqueta ni convierte en visible lo que queda a su derecha.
 */
function templateTextNodes(template: string): string[] {
  const nodes: string[] = [];
  let buffer = '';
  let inTag = false;
  let quote: '"' | "'" | null = null;

  const flush = (): void => {
    const text = buffer.replace(/\s+/g, ' ').trim();
    buffer = '';
    if (/\p{L}/u.test(text)) nodes.push(text);
  };

  for (const char of template) {
    if (!inTag) {
      if (char === '<') {
        flush();
        inTag = true;
      } else {
        buffer += char;
      }
      continue;
    }
    if (quote) {
      if (char === quote) quote = null;
    } else if (char === '"' || char === "'") {
      quote = char;
    } else if (char === '>') {
      inTag = false;
    }
  }
  flush();
  return nodes;
}

/**
 * Valores estáticos de atributos visibles. Los atributos enlazados (`:title`,
 * `v-bind:aria-label`) quedan fuera: su texto debe venir de `t()` y el barrido
 * de claves ya cubre sus claves estáticas.
 */
function staticVisibleAttributes(template: string): string[] {
  const values: string[] = [];
  const pattern = new RegExp(`\\s(?:${VISIBLE_ATTRIBUTES.join('|')})="([^"]*)"`, 'g');
  for (const match of template.matchAll(pattern)) {
    const text = (match[1] ?? '').replace(/\s+/g, ' ').trim();
    if (/\p{L}/u.test(text)) values.push(text);
  }
  return values;
}

/**
 * Literales visibles de una vista: nodos de texto del `<template>` (ya sin
 * interpolaciones) y valores estáticos de atributos visibles. Un texto que sale
 * de `t(…)` no aparece aquí, porque la interpolación se descarta; uno escrito a
 * mano sí, y la prueba lo contrasta con su lista blanca de marcas y símbolos
 * (RNF-004).
 */
export function extractVisibleLiterals(sources: readonly CatalogSource[]): VisibleLiteral[] {
  const found: VisibleLiteral[] = [];
  // Una marca de una sola letra («v» de versión) o un signo no son copia: se
  // exige al menos una palabra de dos letras para considerarlo texto visible.
  const add = (file: string, raw: string): void => {
    const text = raw.replace(/\s+/g, ' ').trim();
    if (!text || !/\p{L}{2,}/u.test(text)) return;
    if (found.some((entry) => entry.file === file && entry.text === text)) return;
    found.push({ file, text });
  };

  for (const { name, source } of sources) {
    // Solo plantillas de componentes y páginas: un `.ts` puede citar
    // `<template>` dentro de una cadena y no se muestra nunca.
    if (!name.endsWith('.vue')) continue;
    const start = source.indexOf('<template>');
    const end = source.lastIndexOf('</template>');
    if (start < 0 || end <= start) continue;
    const template = stripHtmlComments(source.slice(start + '<template>'.length, end))
      .replace(/\{\{[\s\S]*?\}\}/g, ' ');
    for (const node of templateTextNodes(template)) add(name, node);
    for (const text of staticVisibleAttributes(template)) add(name, text);
  }

  return found;
}

/** Diferencias entre los dos catálogos; ambos vacíos significan paridad. */
export function catalogParity(
  spanish: Iterable<string>,
  english: Iterable<string>,
): CatalogParity {
  const spanishKeys = new Set(spanish);
  const englishKeys = new Set(english);
  return {
    onlySpanish: [...spanishKeys].filter((key) => !englishKeys.has(key)).sort(),
    onlyEnglish: [...englishKeys].filter((key) => !spanishKeys.has(key)).sort(),
  };
}
