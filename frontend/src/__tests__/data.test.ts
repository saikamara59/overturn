import { describe, expect, test } from 'vitest';
import { parseWorkbenchData } from '../data';
import { EMPTY_DATA } from '../types';

describe('parseWorkbenchData', () => {
  test('unreplaced marker falls back to empty batch', () => {
    expect(parseWorkbenchData('/*__OVERTURN_DATA__*/{}')).toEqual(EMPTY_DATA);
  });
  test('valid JSON parses', () => {
    const d = parseWorkbenchData(JSON.stringify({ ...EMPTY_DATA, totalBilled: 5 }));
    expect(d.totalBilled).toBe(5);
  });
  test('malformed JSON falls back to empty batch', () => {
    expect(parseWorkbenchData('{nope')).toEqual(EMPTY_DATA);
  });
});
