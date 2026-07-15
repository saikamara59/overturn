import { useEffect, useState } from 'react';

export const MOBILE_QUERY = '(max-width: 759px)';

/** True below the 760px design breakpoint; live-updates on resize. */
export function useIsMobile(): boolean {
  const [mobile, setMobile] = useState(
    () => typeof window !== 'undefined' && window.matchMedia(MOBILE_QUERY).matches,
  );
  useEffect(() => {
    const mq = window.matchMedia(MOBILE_QUERY);
    const onChange = (e: { matches: boolean }) => setMobile(e.matches);
    mq.addEventListener('change', onChange);
    setMobile(mq.matches);
    return () => mq.removeEventListener('change', onChange);
  }, []);
  return mobile;
}
