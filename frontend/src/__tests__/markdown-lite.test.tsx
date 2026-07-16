import { render, screen } from '@testing-library/react';
import { expect, test } from 'vitest';
import { MarkdownLite } from '../components/ui/MarkdownLite';

test('renders headings without the ## syntax', () => {
  render(<MarkdownLite text={'## Additional Appeal Arguments\n\nBody text.'} />);
  expect(screen.getByText('Additional Appeal Arguments')).toBeInTheDocument();
  expect(document.body.textContent).not.toContain('##');
  expect(document.querySelector('.md-h')).not.toBeNull();
});

test('renders **bold** as bold without asterisks', () => {
  render(<MarkdownLite text={'Attach the **operative report** and notes.'} />);
  const strong = document.querySelector('strong');
  expect(strong?.textContent).toBe('operative report');
  expect(document.body.textContent).not.toContain('**');
});

test('renders bullet and numbered lists as list items', () => {
  render(<MarkdownLite text={'- first ground\n- second ground\n\n1. step one\n2. step two'} />);
  const items = screen.getAllByRole('listitem');
  expect(items.map((li) => li.textContent)).toEqual(
    ['first ground', 'second ground', 'step one', 'step two'],
  );
});

test('plain paragraphs pass through unchanged', () => {
  render(<MarkdownLite text={'First paragraph.\n\nSecond paragraph.'} />);
  expect(screen.getByText('First paragraph.')).toBeInTheDocument();
  expect(screen.getByText('Second paragraph.')).toBeInTheDocument();
});

test('treats markdown syntax as text, never as HTML', () => {
  render(<MarkdownLite text={'<script>alert(1)</script> **<b>x</b>**'} />);
  expect(document.querySelector('script')).toBeNull();
  expect(document.querySelector('b')).toBeNull();
  expect(document.body.textContent).toContain('<script>alert(1)</script>');
});

test('mixed real-world recommendation renders clean', () => {
  const sample = [
    '## Recommended Appeal Strategy',
    '',
    'The denial under **CO-197** is contestable.',
    '',
    '### Documentation to attach',
    '- Prior authorization confirmation number',
    '- Payer portal screenshot',
    '',
    '1. File within 30 days',
    '2. Request peer-to-peer review',
  ].join('\n');
  render(<MarkdownLite text={sample} />);
  expect(document.body.textContent).not.toMatch(/[#*]{2}|^- /m);
  expect(screen.getByText('Recommended Appeal Strategy')).toBeInTheDocument();
  expect(screen.getByText('Documentation to attach')).toBeInTheDocument();
  expect(screen.getAllByRole('listitem')).toHaveLength(4);
});
