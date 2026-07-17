export type RiskTier = 'Low' | 'Moderate' | 'High';
export type Position = 'GK' | 'DEF' | 'MID' | 'FWD';

export interface ScoredPlayer {
  playerId: number;
  playerName: string;
  team: string;
  position: Position;
  age: number;
  number: number | null;
  riskProbability: number;
  riskScore: number;
  riskTier: RiskTier;
  reasons: string[];
  acwr: number;
  acute7: number;
  chronic28: number;
  restDays: number;
  backToBack14: number;
  matches14: number;
  fatigue?: number | null;
  form?: number | null;
  priorInjuries?: number;
  daysSinceReturn?: number | null;
  confidence?: number;
  confidenceLabel?: string;
  confidenceDriver?: string;
  price?: number | null;
  available?: boolean;
  injuryType?: string;
  expectedReturn?: string;
  startWarning?: string;
}

export interface Coefficient {
  feature: string;
  weight: number;
}

export interface Overview {
  counts: {
    players: number;
    games: number;
    injuries: number;
    activeInjuries: number;
    teams: number;
  };
  model: {
    auc: number | null;
    baseRate: number;
    coefficients: Coefficient[];
    modelType?: 'logistic' | 'gradient-boost' | 'rules';
    note?: string;
    learnedAuc?: number | null;
  };
  riskTiers: Record<RiskTier, number>;
  topRisk: ScoredPlayer[];
}

export interface AcwrBucket {
  _id: number | string;
  samples: number;
  injuries: number;
  avgAcute: number;
  injuryRate: number;
}

export interface BodyPart {
  _id: string;
  count: number;
  avgDaysOut: number;
  avgAcwrAtOnset: number;
}

export interface Correlation {
  acwrBuckets: AcwrBucket[];
  bodyParts: BodyPart[];
  coefficients: Coefficient[];
  modelAuc: number | null;
}

export interface Injury {
  _id: number;
  playerId: number;
  playerName: string;
  team: string;
  position: Position;
  type: string;
  bodyPart: string;
  severity: 'Minor' | 'Moderate' | 'Severe';
  mechanism: string;
  dateInjured: string;
  daysOut: number;
  expectedReturn: string;
  status: 'Active' | 'Recovered';
  acwrAtOnset: number;
  notes: string;
}

export interface TimelinePoint {
  date: string;
  minutes: number;
  opponent: string;
  home: boolean;
  started: boolean;
  competition: string;
  season?: number;
  acute7: number;
  chronic28: number;
  acwr: number;
}

export interface PlayerDetail {
  player: {
    _id: number;
    name: string;
    team: string;
    position: Position;
    age: number | null;
    nationality: string;
    number: number;
  };
  risk: ScoredPlayer | null;
  timeline: TimelinePoint[];
  injuries: Injury[];
}

export interface Gameweek {
  round: number;
  start: string;
  backtestable?: boolean;
}

export interface TransferSuggestions {
  out: ScoredPlayer;
  suggestions: ScoredPlayer[];
}

export interface TickerFixture {
  round: number;
  opponent: string;
  home: boolean;
  difficulty: number | null;
}

export interface FixtureTickerTeam {
  team: string;
  fixtures: TickerFixture[];
  avgDifficulty: number | null;
}

export interface FixtureTicker {
  rounds: number[];
  teams: FixtureTickerTeam[];
}

export interface PublicStats {
  players: number;
  teams: number;
  games: number;
  injuries: number;
  europeanClubs: number;
  riskTiers: Partial<Record<RiskTier, number>>;
  topRisk: { playerId: number; playerName: string; team: string; riskScore: number; riskTier: RiskTier; acwr: number }[];
  season: number | null;
}

export interface Pick extends ScoredPlayer {
  opponent: string;
  home: boolean;
  difficulty: number | null;
  confidence: number;
  confidenceLabel: string;
  confidenceDriver: string;
}

export interface Picks {
  gameweek: number;
  asOf: string;
  ranked: number;
  captainPicks: Pick[];
  avoid: Pick[];
}

export interface FplPick extends ScoredPlayer {
  isCaptain: boolean;
  isViceCaptain: boolean;
  onBench: boolean;
}

export interface FplUnmapped {
  fplId: number;
  webName: string;
  team: string;
  position: string;
}

export interface FplSquad {
  managerName: string;
  teamName: string;
  gameweek: number;
  matchedCount: number;
  pickCount: number;
  players: FplPick[];
  unmapped: FplUnmapped[];
}

export interface BacktestTierStat {
  tier: RiskTier;
  players: number;
  injured: number;
  rate: number;
}

export interface BacktestInjury {
  playerId: number;
  playerName: string;
  team: string;
  position: Position;
  riskScore: number;
  riskTier: RiskTier;
  form: number | null;
  fatigue: number | null;
  injuryType: string;
  dateInjured: string;
  daysOut: number;
  flagged: boolean;
}

export interface CalibrationBin {
  label: string;
  n: number;
  predicted: number;
  actual: number;
}

export interface BacktestSummary {
  gameweeks: number[];
  windowDays: number;
  observations: number;
  injuries: number;
  auc: number | null;
  brier: number | null;
  lift: number | null;
  tierStats: BacktestTierStat[];
  calibration: CalibrationBin[];
  precision: number | null;
  recall: number | null;
  flaggedPlayers: number;
}

export interface SimMatch {
  daysFromNow: number;
  minutes: number;
}

export interface SimPathPoint {
  match: number;
  daysFromNow: number;
  minutes: number;
  riskScore: number;
  riskTier: RiskTier;
  acwr: number;
  fatigue: number | null;
}

export interface Simulation {
  player: { id: number; name: string; position: Position; team: string };
  referenceDate: string;
  baseline: ScoredPlayer;
  path: SimPathPoint[];
  peakRisk: number;
  projected: ScoredPlayer;
}

export interface Backtest {
  gameweek: number;
  asOf: string;
  windowDays: number;
  windowEnd: string;
  truncated: boolean;
  candidates: number;
  tierStats: BacktestTierStat[];
  injured: BacktestInjury[];
  summary: {
    totalInjured: number;
    flagged: number;
    flaggedPct: number | null;
    lift: number | null;
  };
}

export interface RotationPlan {
  team: string;
  european?: string | null;
  teamRank?: number | null;
  gameweek?: number | null;
  asOf?: string;
  squad?: ScoredPlayer[];
  fixture: {
    opponent: string;
    home: boolean;
    date: string;
    competition: string;
    difficulty?: number | null;
    opponentRank?: number | null;
  } | null;
  recommendedXI: ScoredPlayer[];
  restRecommendations: ScoredPlayer[];
  unavailable: ScoredPlayer[];
  squadRiskAvg: number;
}
