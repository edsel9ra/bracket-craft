import { nextTick } from 'vue';

/** Guarda un archivo descargado con un enlace temporal, como la plantilla de importación de plantillas. */
export function saveExportFile(blob: Blob, fileName: string): void {
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = fileName;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
}

// Un botón nativo deshabilitado durante la descarga pierde el foco; al
// terminar se devuelve al mismo botón si nadie lo ha movido.
export async function keepFocusDuring<T>(target: EventTarget | null, task: () => Promise<T>): Promise<T> {
  const element = target instanceof HTMLElement ? target : null;
  try {
    return await task();
  } finally {
    await nextTick();
    const active = document.activeElement;
    if (element?.isConnected && (!active || active === document.body)) element.focus();
  }
}
