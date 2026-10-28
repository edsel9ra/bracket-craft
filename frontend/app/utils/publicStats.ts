/**
 * Funciones puras de presentación de las estadísticas públicas (spec 022, T14).
 *
 * La foto de un jugador se muestra solo cuando la respuesta trae una URL y esa
 * URL no ha fallado al cargar en el navegador; en cualquier otro caso se
 * muestran las iniciales, sin hueco ni imagen rota (RF-007, RF-008). Un jugador
 * retirado lógicamente llega aquí con `photo_url` nulo (RF-034) y por tanto
 * también cae en las iniciales.
 */

export interface PublicStatsPhotoRow {
  player_id: string;
  photo_url: string | null;
}

export type PlayerPhotoSource = 'photo' | 'initials';

/**
 * Decide qué se pinta en la celda del jugador.
 *
 * `failedPhotoUrls` guarda, por jugador, la URL concreta que falló. Guardar la
 * URL —y no solo el identificador— reinicia el intento cuando la foto cambia
 * de enlace: una firma nueva merece una carga nueva, y el mismo enlace roto no
 * se vuelve a pedir.
 */
export function playerPhotoSource(
  row: PublicStatsPhotoRow | null | undefined,
  failedPhotoUrls?: ReadonlyMap<string, string> | null,
): PlayerPhotoSource {
  if (!row) return 'initials';

  const url = typeof row.photo_url === 'string' ? row.photo_url : '';
  if (url.trim() === '') return 'initials';

  if (failedPhotoUrls && failedPhotoUrls.get(row.player_id) === url) {
    return 'initials';
  }

  return 'photo';
}
