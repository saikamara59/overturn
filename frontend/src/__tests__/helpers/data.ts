import { SAMPLE_DATA } from '../../fixtures/sample';
import type { WorkbenchData } from '../../types';

/**
 * Shared WorkbenchData fixture for worklist tests — mirrors SAMPLE_DATA
 * (CLM-0001 has days < 7, and Draft Ready claims exist for chip tests).
 */
export function makeData(): WorkbenchData {
  return SAMPLE_DATA;
}
