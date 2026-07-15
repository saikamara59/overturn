import { render, screen } from '@testing-library/react';
import { expect, test, vi } from 'vitest';
import { TopBar } from '../components/TopBar';

test('renders the brand lockup with wordmark and subtitle', () => {
  render(<TopBar screen="worklist" onNavigate={vi.fn()} generatedOn="2026-07-05" asOf="2026-07-05" />);
  expect(screen.getByText('Overturn')).toBeInTheDocument();
  expect(screen.getByText('Denial Workbench')).toBeInTheDocument();
  expect(document.querySelector('.brand-mark svg path[fill="#FFFFFF"]')).not.toBeNull();
});
