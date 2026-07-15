import { act, renderHook } from '@testing-library/react';
import { afterEach, expect, test } from 'vitest';
import { useIsMobile } from '../lib/useIsMobile';
import { resetViewport, setViewportMobile } from './helpers/matchMedia';

afterEach(() => resetViewport());

test('defaults to desktop', () => {
  const { result } = renderHook(() => useIsMobile());
  expect(result.current).toBe(false);
});

test('tracks viewport changes both ways', () => {
  const { result } = renderHook(() => useIsMobile());
  act(() => setViewportMobile(true));
  expect(result.current).toBe(true);
  act(() => setViewportMobile(false));
  expect(result.current).toBe(false);
});

test('starts mobile when mounted under a mobile viewport', () => {
  setViewportMobile(true);
  const { result } = renderHook(() => useIsMobile());
  expect(result.current).toBe(true);
});
