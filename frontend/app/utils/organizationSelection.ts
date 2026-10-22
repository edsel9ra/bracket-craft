/**
 * Elección de la organización activa en el navegador (RF-017, R32c).
 *
 * El servidor devuelve solo las organizaciones de la persona, activas y con
 * membresía activa, en orden estable por nombre y, en empate, por
 * identificador. El navegador es el único que recuerda la última usada; estas
 * funciones son puras para poder probarlas sin Nuxt ni almacenamiento.
 */

export interface OrganizationCandidate {
  id: string;
}

/**
 * Devuelve la organización recordada solo si aparece en la lista recibida.
 * Si no hay historial válido (nunca hubo, la organización ya no es accesible
 * o es de otra persona), cae a la primera del orden estable del servidor.
 *
 * La función no reordena ni lee `localStorage`: la persistencia es del store.
 */
export function selectActiveOrganization<T extends OrganizationCandidate>(
  organizations: readonly T[] | null | undefined,
  remembered: string | null | undefined,
): T | null {
  const available = organizations ?? [];
  if (!available.length) return null;
  if (remembered) {
    const match = available.find((organization) => organization.id === remembered);
    if (match) return match;
  }
  return available[0] ?? null;
}

/**
 * Decide qué identificador debe quedar en el historial del navegador.
 *
 * Solo se escribe una organización que la persona puede activar en este
 * momento; un identificador ajeno, eliminado o todavía no cargado no se
 * guarda. Devuelve `null` cuando no hay nada que registrar.
 */
export function organizationHistoryEntry(
  organizations: readonly OrganizationCandidate[] | null | undefined,
  candidate: string | null | undefined,
): string | null {
  if (!candidate) return null;
  const available = organizations ?? [];
  return available.some((organization) => organization.id === candidate) ? candidate : null;
}
