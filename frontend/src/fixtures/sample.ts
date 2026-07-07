import type { WorkbenchData } from '../types';

// Synthetic data only — dev fixture for `npm run dev`; never shipped as real output.
export const SAMPLE_DATA: WorkbenchData = {
  generatedOn: '2026-07-06',
  asOf: '2026-07-06',
  model: null,
  totalBilled: 60920.25,
  summary: { processed: 4, drafts: 3, failed: 1 },
  audit: [
    { time: '06:11:42', type: 'batch_started', detail: 'records=4' },
    { time: '06:11:44', type: 'phi_redacted', detail: 'count=2 · types=[NAME, DOB]' },
    { time: '06:12:41', type: 'batch_completed', detail: 'records=4 · succeeded=3 · failed=1' },
  ],
  claims: [
    {
      id: 'CLM-0001', payer: 'Synthetic Payer A', carc: 'CO-50',
      carcText: 'These are non-covered services because this is not deemed a medical necessity',
      rarcs: ['N115'], billed: 12500, dos: '2026-04-10', denialDate: '2026-05-01',
      deadline: '2026-06-30', days: -6, status: 'Draft Ready',
      denialText: 'Patient: [PATIENT_NAME], DOB: [DOB]. Non-covered: not deemed a medical necessity.',
      letter: 'July 6, 2026\n\n[PATIENT_NAME]\n\nRE: Formal Appeal of Denied Claim (CO-50)\n\nTo Whom It May Concern, ...',
      refined: '[dry run — LLM refinement skipped]',
      rule: 'Medicare Benefit Policy Manual, Ch. 15', error: null,
    },
    {
      id: 'CLM-0002', payer: 'Synthetic Payer B', carc: 'CO-29',
      carcText: 'The time limit for filing has expired', rarcs: ['N30'],
      billed: 430.25, dos: '2026-03-02', denialDate: '2026-04-15',
      deadline: '2026-07-15', days: 9, status: 'Draft Ready',
      denialText: 'The time limit for filing has expired.',
      letter: 'RE: Formal Appeal of Denied Claim (CO-29) ...', refined: null,
      rule: '42 CFR §424.44', error: null,
    },
    {
      id: 'CLM-0003', payer: 'Synthetic Payer A', carc: 'CO-97',
      carcText: 'Benefit included in another adjudicated service', rarcs: [],
      billed: 8300, dos: '2026-05-20', denialDate: '2026-06-10',
      deadline: null, days: null, status: 'Draft Ready',
      denialText: 'Benefit for this service is included in another service.',
      letter: 'RE: Formal Appeal of Denied Claim (CO-97) ...', refined: null,
      rule: 'NCCI Policy Manual, Ch. 1', error: null,
    },
    {
      id: 'CLM-0004', payer: 'Synthetic Payer C', carc: 'CO-16',
      carcText: 'Claim lacks information needed for adjudication', rarcs: ['M76'],
      billed: 39690, dos: '2026-05-25', denialDate: '2026-06-20',
      deadline: '2026-08-19', days: 44, status: 'Failed',
      denialText: 'Claim lacks information or has submission errors.',
      letter: null, refined: null, rule: null, error: 'APIError: synthetic failure',
    },
  ],
};
