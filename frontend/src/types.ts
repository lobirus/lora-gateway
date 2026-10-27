export interface Provider {
  id: number; slug: string; name: string; kind: string; api_base: string; enabled: boolean; description: string | null
  has_key: boolean; key_masked: string | null; last_test_at: string | null; last_test_ok: boolean | null; last_test_msg: string | null
  model_count: number; enabled_model_count: number; status: 'active' | 'missing_key' | 'disabled'
  auto_sync: boolean; last_sync_at: string | null; last_sync_ok: boolean | null; last_sync_msg: string | null
  synced_count: number; pinned_count: number; can_sync: boolean
}
export interface Model {
  id: number; provider_id: number; provider_slug: string; provider_name: string; provider_enabled: boolean
  model_name: string; upstream_id: string; display_name: string; input_price_per_m: number; output_price_per_m: number
  context_window: number | null; enabled: boolean; tags: string[]; live: boolean
  max_output_tokens: number | null; default_max_tokens: number | null; supports_reasoning: boolean | null; supports_vision: boolean | null
  reasoning_efforts: ('off' | 'low' | 'medium' | 'high')[]
  kind: ModelKind; voices: string[]; default_voice: string | null
  price_per_minute: number | null; price_per_m_chars: number | null
  audio_input_price_per_m: number | null; audio_output_price_per_m: number | null
  api_base: string | null; synced: boolean; pinned: boolean; available: boolean | null; status_note: string | null; pipeline: boolean
}
export type ModelKind = 'chat' | 'transcription' | 'input' | 'speech' | 'realtime' | 'embedding'
export const KIND_LABELS: Record<ModelKind, string> = { chat: 'Chat', transcription: 'Transcription', input: 'Audio chat', speech: 'Speech', realtime: 'Realtime', embedding: 'Embedding' }
export type RequestType = 'chat' | 'transcription' | 'speech' | 'realtime' | 'embedding'
export const TYPE_LABELS: Record<RequestType, string> = { chat: 'Chat', transcription: 'Transcription', speech: 'Speech', realtime: 'Realtime', embedding: 'Embedding' }
export interface AudioTypeAgg { requests: number; errors: number; cost: number; seconds: number; characters: number; tokens_in: number; tokens_out: number; latency_avg: number | null }
export interface AudioSummary { hours: number; cost: number; minutes_transcribed: number; characters_spoken: number; realtime_minutes: number; types: Record<'transcription' | 'speech' | 'realtime', AudioTypeAgg> }
export interface Alias { id: number; name: string; description: string | null; target_model_id: number | null; target: Model | null; live: boolean; updated_at: string }
export interface ApiKey {
  id: number; name: string; key_prefix: string; max_budget: number | null; budget_duration: string | null
  rpm_limit: number | null; tpm_limit: number | null; models: string[]; expires_at: string | null; revoked: boolean
  revoked_at: string | null; created_at: string; spend: number; requests: number; tokens: number; last_used_at: string | null; key?: string
}
export interface Agg {
  requests: number; errors: number; tokens_in: number; tokens_out: number; cost: number
  latency_avg: number | null; latency_p50: number | null; latency_p95: number | null; ttft_avg: number | null; ttft_p50: number | null
  error_rate: number
}
export interface Summary extends Agg { previous: { requests: number; cost: number; tokens: number; latency_avg: number | null }; hours: number }
export interface Point extends Agg { t: string }
export interface BreakdownRow extends Agg { name: string }
export interface LogRow {
  request_id: string; call_type: string; start_time: string; end_time: string; model: string; upstream_model: string
  provider: string; key_name: string; tokens_in: number; tokens_out: number; total_tokens: number; cost: number
  latency_ms: number | null; ttft_ms: number | null; status: string; error_message: string | null; error_code: string | null
  ip: string | null; cache_hit: string | null; source: 'playground' | 'test' | 'api'; tags: string[]
  type: RequestType; audio_seconds: number | null; characters: number | null
}
export interface TestResult { ok: boolean; model: string; latency_ms: number; ttft_ms: number | null; output: string; reasoning_chars: number; usage: Record<string, number> | null; error: string | null }
export interface ConnectInfo { public_host: string; openai_base_url: string; anthropic_base_url: string; local_openai_base_url: string; local_anthropic_base_url: string; models: string[]; aliases: string[] }
