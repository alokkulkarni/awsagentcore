// src/types/evaluation.ts

export interface DimensionScore {
  score: number;         // 0–10
  justification: string;
  evidence?: string;
}

export interface EvalResult {
  runId: string;
  scenarioName: string;
  overallScore: number;  // 0–10
  passed: boolean;       // score >= passingThreshold
  dimensionScores: Record<string, DimensionScore>;
  summary: string;
  recommendation?: string;
  judgeModel: string;
  evaluatedAt: string;   // ISO-8601
  /** 'security' for injection/adversarial scenarios; 'quality' for normal scenarios */
  scenarioType?: 'security' | 'quality';
}

export interface Dimension {
  id: string;
  name: string;
  description: string;
  weight: number;        // 0–1 (must sum to 1 across all active dims)
  passingScore: number;  // minimum score to pass this dimension
}
