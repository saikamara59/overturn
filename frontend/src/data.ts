import { EMPTY_DATA, type WorkbenchData } from './types';
import { SAMPLE_DATA } from './fixtures/sample';

export function parseWorkbenchData(raw: string): WorkbenchData {
  const text = raw.trim();
  if (text.startsWith('/*')) return EMPTY_DATA; // unreplaced marker
  try {
    return JSON.parse(text) as WorkbenchData;
  } catch {
    return EMPTY_DATA;
  }
}

export function readWorkbenchData(): WorkbenchData {
  const el = document.getElementById('overturn-data');
  const parsed = parseWorkbenchData(el?.textContent ?? '');
  if (parsed === EMPTY_DATA && import.meta.env.DEV) return SAMPLE_DATA;
  return parsed;
}
