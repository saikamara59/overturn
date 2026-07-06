import { render, screen } from '@testing-library/react';
import App from '../App';
import { EMPTY_DATA } from '../types';

test('renders the Overturn brand', () => {
  render(<App data={EMPTY_DATA} />);
  expect(screen.getByText('Overturn')).toBeInTheDocument();
});
