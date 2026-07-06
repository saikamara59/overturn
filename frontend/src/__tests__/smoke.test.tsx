import { render, screen } from '@testing-library/react';
import App from '../App';

test('renders the Overturn brand', () => {
  render(<App data={{}} />);
  expect(screen.getByText('Overturn')).toBeInTheDocument();
});
