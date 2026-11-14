import { isTauri } from '@tauri-apps/api/core';

// F11: the desktop window goes full screen through Tauri; in a browser the page uses the Fullscreen API.
export async function toggleFullscreen() {
  if (isTauri()) {
    const { getCurrentWindow } = await import('@tauri-apps/api/window');
    const window = getCurrentWindow();
    await window.setFullscreen(!(await window.isFullscreen()));
    return;
  }
  if (document.fullscreenElement) await document.exitFullscreen();
  else await document.documentElement.requestFullscreen();
}
