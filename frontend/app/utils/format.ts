/**
 * Formato de fecha y número por idioma (RF-030).
 *
 * Es la **única** función que elige la etiqueta regional de los idiomas
 * soportados; las pantallas no construyen `Intl.DateTimeFormat` ni
 * `Intl.NumberFormat` por su cuenta. Acepta el idioma activo como argumento y
 * no lee cookies, reloj ni estado global: es pura y se puede probar sin DOM.
 *
 * Los datos del dominio (nombres, códigos, resultados) no se formatean ni se
 * traducen: solo las fechas y los números que los acompañan.
 */

export type FormatLocale = 'es' | 'en';

const LOCALE_TAGS: Readonly<Record<FormatLocale, string>> = {
  es: 'es-CO',
  en: 'en-US',
};

/** Etiqueta regional del idioma activo; un valor desconocido cae a español. */
export function localeTag(locale: string | null | undefined): string {
  return locale === 'en' ? LOCALE_TAGS.en : LOCALE_TAGS.es;
}

function toDate(value: string | number | Date | null | undefined): Date | null {
  if (value === null || value === undefined) return null;
  const date = value instanceof Date ? value : new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}

/** Fecha y hora con el formato medio del idioma activo; vacío si no es válida. */
export function formatDateTime(
  value: string | number | Date | null | undefined,
  locale: string | null | undefined,
): string {
  const date = toDate(value);
  if (!date) return '';
  return new Intl.DateTimeFormat(localeTag(locale), {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(date);
}

/** Fecha sin hora con el formato medio del idioma activo; vacío si no es válida. */
export function formatDate(
  value: string | number | Date | null | undefined,
  locale: string | null | undefined,
): string {
  const date = toDate(value);
  if (!date) return '';
  return new Intl.DateTimeFormat(localeTag(locale), { dateStyle: 'medium' }).format(date);
}

/** Número con el formato del idioma activo; vacío si no es un número finito. */
export function formatNumber(
  value: number | null | undefined,
  locale: string | null | undefined,
  options: Intl.NumberFormatOptions = {},
): string {
  if (typeof value !== 'number' || !Number.isFinite(value)) return '';
  return new Intl.NumberFormat(localeTag(locale), options).format(value);
}
