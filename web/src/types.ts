export type MeetingStatus = "recording" | "finished" | "done";
export type AnalysisStatus = "pending" | "done" | "failed" | "skipped";

export interface Meeting {
  id: number;
  title: string;
  project: string;
  status: MeetingStatus;
  analysis_status: AnalysisStatus;
  analysis_error: string | null;
  created_at: string;
  finished_at: string | null;
}

export interface Progress {
  chunks_total: number;
  chunks_pending: number;
  chunks_processing: number;
  chunks_done: number;
  chunks_failed: number;
  segments: number;
  events: number;
}

export interface Segment {
  id: number;
  source: string;
  start: number;
  end: number;
  text: string;
  avg_logprob: number | null;
  low_confidence: boolean;
}

export type EventKind = "new_requirement" | "changed_requirement" | "decision" | "open_question";

export interface MtEvent {
  id: number;
  requirement_id: number | null;
  meeting_id: number;
  segment_id: number | null;
  kind: EventKind;
  summary: string;
  quote: string;
  timestamp: number | null;
  created_at: string;
}

export interface Requirement {
  id: number;
  project: string;
  title: string;
  created_at: string;
}

export interface RequirementHistory {
  requirement: Requirement;
  events: MtEvent[];
}

export interface SearchHit {
  meeting_id: number;
  segment_id: number;
  start: number;
  text: string;
}

export interface SystemInfo {
  whisper_model: string;
  whisper_language: string;
  analyzer: string;
  ollama_model: string;
  ollama_reachable: boolean;
  ollama_model_installed: boolean;
  queue: number;
}
