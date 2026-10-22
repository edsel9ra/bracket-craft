/**
 * Modelo puro del observador de estados visibles del escenario (B1).
 *
 * El escenario tiene **dos fuentes de observación** de la interfaz y no
 * siempre coinciden:
 *
 * - El **muestreo periódico** (`sample`) mira cada 40 ms y solo interesa un
 *   cambio de estado: repetir el mismo estado en cada ciclo llenaría el
 *   artefacto de ruido.
 * - La **espera directa** (`observe`) mira el estado como condición de un paso
 *   y lo ve aunque dure menos que un ciclo de muestreo. Cuando el producto
 *   muestra el estado manual dos veces (un ciclo de pulsación por clic) y entre
 *   medias pasa por `error` en menos de 40 ms, la segunda observación coincide
 *   con el último estado registrado y **también** debe quedar registrada: si no,
 *   el artefacto no puede atribuir el estado al segundo clic y el ciclo falla
 *   como `manual-not-sampled` sin que el producto tenga defecto alguno.
 *
 * Los instantes entran siempre por parámetro y se conservan **tal cual**: el
 * modelo no lee el reloj ni desplaza una marca para forzar un orden.
 */

import type { StateSample } from './artifacts.ts';
import type { VisibleRealtimeStatus } from './labels.ts';

export interface StatusModel {
  /**
   * Muestra del bucle periódico: registra el estado solo cuando **cambia**
   * respecto al último observado. `null` (la vista no anuncia estado) no es una
   * muestra.
   */
  sample(status: VisibleRealtimeStatus | null, at: number): void;
  /**
   * Observación directa de una espera: registra **siempre** una muestra con el
   * instante real, aunque repita el último estado.
   */
  observe(status: VisibleRealtimeStatus, at: number): void;
  /** Copia de las muestras, en orden de registro. */
  samples(): readonly StateSample[];
  /** Último estado observado (de cualquiera de las dos fuentes). */
  current(): VisibleRealtimeStatus | null;
  /**
   * Primera muestra registrada desde `after` (incluido) cuyo estado es distinto
   * de `status`: es la transición real de desaparición, sin fabricar instantes.
   */
  firstChangeAfter(status: VisibleRealtimeStatus, after: number): StateSample | null;
}

export function createStatusModel(): StatusModel {
  const recorded: StateSample[] = [];
  let latest: VisibleRealtimeStatus | null = null;

  return {
    sample(status: VisibleRealtimeStatus | null, at: number): void {
      if (status === null || status === latest) return;
      latest = status;
      recorded.push({ status, at });
    },
    observe(status: VisibleRealtimeStatus, at: number): void {
      latest = status;
      recorded.push({ status, at });
    },
    samples(): readonly StateSample[] {
      return [...recorded];
    },
    current(): VisibleRealtimeStatus | null {
      return latest;
    },
    firstChangeAfter(status: VisibleRealtimeStatus, after: number): StateSample | null {
      for (const sample of recorded) {
        if (sample.at >= after && sample.status !== status) return sample;
      }
      return null;
    },
  };
}
