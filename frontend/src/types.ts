export interface Claim {
  id: string;
  payer: string;
  carc: string;
  carcText: string | null;
  rarcs: string[];
  billed: number;
  dos: string;
  denialDate: string;
  deadline: string | null;
  days: number | null;
  status: 'Draft Ready' | 'Failed';
  denialText: string;
  letter: string | null;
  refined: string | null;
  rule: string | null;
  error: string | null;
  dismissReason?: string | null;
  /** Server row id for mutations; absent in static-report (island) mode. */
  dbId?: string;
}

export interface AuditEvent {
  time: string;
  type: string;
  detail: string;
}

export interface WorkbenchData {
  generatedOn: string | null;
  asOf: string | null;
  model: string | null;
  totalBilled: number;
  claims: Claim[];
  summary: { processed: number; drafts: number; failed: number; dismissed?: number };
  audit: AuditEvent[];
}

export const EMPTY_DATA: WorkbenchData = {
  generatedOn: null,
  asOf: null,
  model: null,
  totalBilled: 0,
  claims: [],
  summary: { processed: 0, drafts: 0, failed: 0 },
  audit: [],
};

export type Screen = 'worklist' | 'detail' | 'summary';
export type SortCol = 'urgency' | 'payer' | 'billed' | 'denial' | 'deadline' | 'days';
export interface SortState { col: SortCol; dir: 'asc' | 'desc' }
export type FilterKey = 'fCarc' | 'fPayer' | 'fStatus' | 'fBucket';
export type FilterState = Record<FilterKey, string[]>;
export type StatusOverrides = Record<string, string>;
export const NO_FILTERS: FilterState = { fCarc: [], fPayer: [], fStatus: [], fBucket: [] };
