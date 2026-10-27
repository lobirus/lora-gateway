from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from ..db import ApiKey, User, get_db, ll_engine
from ..security import current_user

router = APIRouter(prefix="/api", tags=["analytics"])

LAT = 'COALESCE(s.request_duration_ms, EXTRACT(EPOCH FROM (s."endTime" - s."startTime")) * 1000)'
TTFT = ('CASE WHEN s."completionStartTime" IS NOT NULL AND s."completionStartTime" < s."endTime" '
        'THEN EXTRACT(EPOCH FROM (s."completionStartTime" - s."startTime")) * 1000 END')
FAIL = "(COALESCE(s.status, 'success') <> 'success')"
KEYNAME = "COALESCE(NULLIF(s.metadata->>'user_api_key_alias', ''), CASE WHEN s.api_key = '' THEN 'unknown' ELSE 'admin/master' END)"
CALLS = "s.call_type NOT IN ('aembedding_health_check', 'health_check', 'IGNORE_THIS') AND NOT (s.request_tags @> '[\"catalog-probe\"]'::jsonb)"
# request source, from LiteLLM request tags: console Playground, console model test, or a regular API client
SOURCE = ("CASE WHEN s.request_tags @> '[\"source:playground\"]'::jsonb THEN 'playground' "
          "WHEN s.request_tags @> '[\"gateway-test\"]'::jsonb THEN 'test' ELSE 'api' END")
SOURCES = ("playground", "test", "api")
# request type, from LiteLLM's call_type (audio-chat models with audio in/out count as chat)
TYPE = ("CASE WHEN s.call_type IN ('atranscription', 'transcription') THEN 'transcription' "
        "WHEN s.call_type IN ('aspeech', 'speech') THEN 'speech' "
        "WHEN s.call_type ILIKE '%realtime%' THEN 'realtime' "
        "WHEN s.call_type IN ('aembedding', 'embedding') THEN 'embedding' ELSE 'chat' END")
TYPES = ("chat", "transcription", "speech", "realtime", "embedding")
AUDIO_TYPES = ("transcription", "speech", "realtime")
# audio quantities derived from the logged cost and the deployment's unit price (LiteLLM keeps both per request)
_MAPV = "(s.metadata::jsonb->'model_map_information'->'model_map_value')"
AUDIO_SECONDS = (f"CASE WHEN {TYPE} = 'transcription' THEN s.spend / NULLIF(({_MAPV}->>'input_cost_per_second')::float, 0) "
                 f"WHEN {TYPE} = 'realtime' THEN EXTRACT(EPOCH FROM (s.\"endTime\" - s.\"startTime\")) END")
CHARS = f"CASE WHEN {TYPE} = 'speech' THEN s.spend / NULLIF(({_MAPV}->>'input_cost_per_character')::float, 0) END"

DIMS = {
    "model": "COALESCE(NULLIF(s.model_group, ''), NULLIF(s.model, ''), '(none)')",
    # gateway provider of the deployment (audio models are called through LiteLLM's OpenAI client, so LiteLLM's own
    # custom_llm_provider would say "openai" for Together Whisper); falls back to LiteLLM's value
    "provider": "COALESCE(gp.slug, NULLIF(s.custom_llm_provider, ''), 'unknown')",
    "key": KEYNAME,
    "day": "to_char(date_trunc('day', s.\"startTime\"), 'YYYY-MM-DD')",
    "upstream": "s.model",
    "status": "COALESCE(s.status, 'success')",
    "source": SOURCE,
    "type": TYPE,
}


_prov_cache: dict = {"at": 0.0, "sql": ""}


def _from() -> str:
    """FROM clause with a VALUES map deployment-id -> provider slug from the control-plane DB (cached 60 s)."""
    import time as _t
    if _t.time() - _prov_cache["at"] > 60:
        from ..db import Alias, Model, SessionLocal
        db = SessionLocal()
        try:
            pairs = [(f"gw-m-{m.id}", m.provider.slug) for m in db.scalars(select(Model)).all()]
            pairs += [(f"gw-a-{a.id}", a.target.provider.slug) for a in db.scalars(select(Alias)).all() if a.target]
        finally:
            db.close()
        vals = ", ".join("('%s', '%s')" % (i, p.replace("'", "")) for i, p in pairs) or "('', '')"
        _prov_cache.update(at=_t.time(), sql=f'"LiteLLM_SpendLogs" s LEFT JOIN (VALUES {vals}) AS gp(id, slug) ON gp.id = s.model_id')
    return _prov_cache["sql"]


def _iso(v):
    if isinstance(v, datetime):
        if v.tzinfo is None:
            v = v.replace(tzinfo=timezone.utc)
        return v.isoformat().replace("+00:00", "Z")
    return v


def _where(hours: int, model: str | None, provider: str | None, key: str | None, params: dict,
           source: str | None = None, type: str | None = None) -> str:
    w = [f's."startTime" >= (now() at time zone \'utc\') - make_interval(hours => :hours)', CALLS]
    params["hours"] = hours
    if model:
        w.append(f"{DIMS['model']} = :model")
        params["model"] = model
    if provider:
        w.append(f"{DIMS['provider']} = :provider")
        params["provider"] = provider
    if key:
        w.append(f"{KEYNAME} = :key")
        params["key"] = key
    if source:
        if source not in SOURCES:
            raise HTTPException(400, f"source must be one of {list(SOURCES)}")
        w.append(f"{SOURCE} = :source")
        params["source"] = source
    if type:
        if type == "audio":
            w.append(f"{TYPE} IN ('transcription', 'speech', 'realtime')")
        elif type in TYPES:
            w.append(f"{TYPE} = :rtype")
            params["rtype"] = type
        else:
            raise HTTPException(400, f"type must be one of {list(TYPES) + ['audio']}")
    return " AND ".join(w)


def _agg_cols() -> str:
    return f"""count(*) AS requests,
      count(*) FILTER (WHERE {FAIL}) AS errors,
      COALESCE(sum(s.prompt_tokens), 0) AS tokens_in,
      COALESCE(sum(s.completion_tokens), 0) AS tokens_out,
      COALESCE(sum(s.spend), 0) AS cost,
      avg({LAT}) FILTER (WHERE NOT {FAIL}) AS latency_avg,
      percentile_cont(0.5) WITHIN GROUP (ORDER BY {LAT}) FILTER (WHERE NOT {FAIL}) AS latency_p50,
      percentile_cont(0.95) WITHIN GROUP (ORDER BY {LAT}) FILTER (WHERE NOT {FAIL}) AS latency_p95,
      avg({TTFT}) AS ttft_avg,
      percentile_cont(0.5) WITHIN GROUP (ORDER BY {TTFT}) AS ttft_p50"""


def _row(r) -> dict:
    d = dict(r._mapping)
    for k, v in list(d.items()):
        if isinstance(v, float) and k.startswith(("latency", "ttft")):
            d[k] = round(v, 1)
        d[k] = _iso(d[k])
    req = d.get("requests") or 0
    d["error_rate"] = round((d.get("errors") or 0) / req, 4) if req else 0
    d["cost"] = float(d.get("cost") or 0)
    return d


@router.get("/analytics/summary")
def summary(hours: int = Query(24 * 7, ge=1, le=24 * 400), model: str | None = None, provider: str | None = None,
            key: str | None = None, source: str | None = None, type: str | None = None, _: User = Depends(current_user)):
    params: dict = {}
    w = _where(hours, model, provider, key, params, source, type)
    sql = f'SELECT {_agg_cols()} FROM {_from()} WHERE {w}'
    prev = dict(params)
    prev_sql = f'''SELECT count(*) AS requests, COALESCE(sum(s.spend),0) AS cost,
        COALESCE(sum(s.total_tokens),0) AS tokens, avg({LAT}) AS latency_avg
        FROM {_from()} WHERE s."startTime" >= (now() at time zone 'utc') - make_interval(hours => :hours2)
        AND s."startTime" < (now() at time zone 'utc') - make_interval(hours => :hours) AND {CALLS}'''
    if source:
        prev_sql += f" AND {SOURCE} = :source"
    if type in TYPES:
        prev_sql += f" AND {TYPE} = :rtype"
    elif type == "audio":
        prev_sql += f" AND {TYPE} IN ('transcription', 'speech', 'realtime')"
    prev["hours2"] = hours * 2
    with ll_engine.connect() as c:
        cur = _row(c.execute(text(sql), params).one())
        p = dict(c.execute(text(prev_sql), prev).one()._mapping)
    cur["previous"] = {k: (float(v) if v is not None else None) for k, v in p.items()}
    cur["hours"] = hours
    return cur


@router.get("/analytics/timeseries")
def timeseries(hours: int = Query(24 * 7, ge=1, le=24 * 400), bucket: str | None = None, model: str | None = None,
               provider: str | None = None, key: str | None = None, split: str | None = None,
               source: str | None = None, type: str | None = None, _: User = Depends(current_user)):
    bucket = bucket or ("hour" if hours <= 72 else "day")
    if bucket not in ("minute", "hour", "day"):
        raise HTTPException(400, "bucket must be minute|hour|day")
    params: dict = {"bucket": bucket}
    w = _where(hours, model, provider, key, params, source, type)
    sql = f'''WITH series AS (
        SELECT generate_series(date_trunc(:bucket, (now() at time zone 'utc') - make_interval(hours => :hours)),
                               date_trunc(:bucket, now() at time zone 'utc'), ('1 ' || :bucket)::interval) AS t),
      agg AS (SELECT date_trunc(:bucket, s."startTime") AS at, {_agg_cols()} FROM {_from()} WHERE {w} GROUP BY 1)
      SELECT series.t AS t, agg.* FROM series LEFT JOIN agg ON agg.at = series.t ORDER BY series.t'''
    out = {"bucket": bucket, "points": []}
    with ll_engine.connect() as c:
        for r in c.execute(text(sql), params):
            d = _row(r)
            d.pop("at", None)
            d["t"] = _iso(r._mapping["t"])
            for k in ("requests", "errors", "tokens_in", "tokens_out"):
                d[k] = int(d.get(k) or 0)
            out["points"].append(d)
        if split in DIMS:
            sql2 = f'''SELECT date_trunc(:bucket, s."startTime") AS t, {DIMS[split]} AS dim, count(*) AS requests,
                       COALESCE(sum(s.spend),0) AS cost FROM {_from()} WHERE {w} GROUP BY 1, 2 ORDER BY 1'''
            out["split"] = [{"t": _iso(r.t), "dim": r.dim, "requests": r.requests, "cost": float(r.cost)}
                            for r in c.execute(text(sql2), params)]
    return out


@router.get("/analytics/breakdown")
def breakdown(by: str = "model", hours: int = Query(24 * 7, ge=1, le=24 * 400), model: str | None = None,
              provider: str | None = None, key: str | None = None, source: str | None = None, limit: int = 50,
              type: str | None = None, _: User = Depends(current_user)):
    if by not in DIMS:
        raise HTTPException(400, f"by must be one of {list(DIMS)}")
    params: dict = {"limit": limit}
    w = _where(hours, model, provider, key, params, source, type)
    sql = f'''SELECT {DIMS[by]} AS name, {_agg_cols()} FROM {_from()} WHERE {w}
              GROUP BY 1 ORDER BY {"1 DESC" if by == "day" else "requests DESC"} LIMIT :limit'''
    with ll_engine.connect() as c:
        return [_row(r) for r in c.execute(text(sql), params)]


@router.get("/analytics/filters")
def filters(hours: int = Query(24 * 30, ge=1, le=24 * 400), _: User = Depends(current_user)):
    params: dict = {}
    w = _where(hours, None, None, None, params)
    out = {}
    with ll_engine.connect() as c:
        for dim in ("model", "provider", "key", "source", "type"):
            out[dim] = [r[0] for r in c.execute(text(f'SELECT DISTINCT {DIMS[dim]} FROM {_from()} WHERE {w} ORDER BY 1'), params) if r[0]]
    return out


@router.get("/logs")
def logs(limit: int = Query(50, ge=1, le=500), offset: int = Query(0, ge=0), hours: int = Query(24 * 30, ge=1, le=24 * 400),
         model: str | None = None, provider: str | None = None, key: str | None = None, status: str | None = None,
         q: str | None = None, source: str | None = None, type: str | None = None, _: User = Depends(current_user)):
    params: dict = {"limit": limit, "offset": offset}
    w = _where(hours, model, provider, key, params, source, type)
    if status == "error":
        w += f" AND {FAIL}"
    elif status == "success":
        w += f" AND NOT {FAIL}"
    if q:
        w += " AND (s.request_id ILIKE :q OR s.model ILIKE :q OR s.model_group ILIKE :q)"
        params["q"] = f"%{q}%"
    sql = f'''SELECT s.request_id, s.call_type, s."startTime" AS start_time, s."endTime" AS end_time,
        {DIMS['model']} AS model, s.model AS upstream_model, {DIMS['provider']} AS provider, {KEYNAME} AS key_name,
        s.prompt_tokens AS tokens_in, s.completion_tokens AS tokens_out, s.total_tokens, s.spend AS cost,
        {LAT} AS latency_ms, {TTFT} AS ttft_ms, COALESCE(s.status, 'success') AS status,
        s.metadata->'error_information'->>'error_message' AS error_message,
        s.metadata->'error_information'->>'error_code' AS error_code,
        s.requester_ip_address AS ip, s.cache_hit, {SOURCE} AS source, {TYPE} AS type,
        {AUDIO_SECONDS} AS audio_seconds, {CHARS} AS characters,
        COALESCE(s.request_tags, '[]'::jsonb) AS tags,
        count(*) OVER () AS total_count
        FROM {_from()} WHERE {w} ORDER BY s."startTime" DESC LIMIT :limit OFFSET :offset'''
    with ll_engine.connect() as c:
        rows = c.execute(text(sql), params).all()
    items = []
    for r in rows:
        d = {k: _iso(v) for k, v in dict(r._mapping).items()}
        d["latency_ms"] = round(float(d["latency_ms"]), 1) if d["latency_ms"] is not None else None
        d["ttft_ms"] = round(float(d["ttft_ms"]), 1) if d["ttft_ms"] is not None else None
        d["cost"] = float(d["cost"] or 0)
        d["audio_seconds"] = round(float(d["audio_seconds"]), 2) if d.get("audio_seconds") is not None else None
        d["characters"] = round(float(d["characters"])) if d.get("characters") is not None else None
        if d.get("error_message"):
            d["error_message"] = d["error_message"][:500]
        items.append(d)
    total = rows[0].total_count if rows else 0
    for d in items:
        d.pop("total_count", None)
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.get("/analytics/audio")
def audio_summary(hours: int = Query(24 * 7, ge=1, le=24 * 400), model: str | None = None, provider: str | None = None,
                  key: str | None = None, source: str | None = None, _: User = Depends(current_user)):
    """Minutes transcribed, characters spoken, realtime minutes and cost, per audio request type."""
    params: dict = {}
    w = _where(hours, model, provider, key, params, source, "audio")
    sql = f'''SELECT {TYPE} AS type, count(*) AS requests, count(*) FILTER (WHERE {FAIL}) AS errors,
        COALESCE(sum(s.spend), 0) AS cost, COALESCE(sum({AUDIO_SECONDS}) FILTER (WHERE NOT {FAIL}), 0) AS seconds,
        COALESCE(sum({CHARS}) FILTER (WHERE NOT {FAIL}), 0) AS characters,
        COALESCE(sum(s.prompt_tokens), 0) AS tokens_in, COALESCE(sum(s.completion_tokens), 0) AS tokens_out,
        avg({LAT}) FILTER (WHERE NOT {FAIL}) AS latency_avg
        FROM {_from()} WHERE {w} GROUP BY 1'''
    out = {t: {"requests": 0, "errors": 0, "cost": 0.0, "seconds": 0.0, "characters": 0, "tokens_in": 0, "tokens_out": 0,
               "latency_avg": None} for t in AUDIO_TYPES}
    with ll_engine.connect() as c:
        for r in c.execute(text(sql), params):
            d = dict(r._mapping)
            out[d.pop("type")] = {"requests": d["requests"], "errors": d["errors"], "cost": float(d["cost"]),
                                  "seconds": round(float(d["seconds"]), 1), "characters": round(float(d["characters"])),
                                  "tokens_in": int(d["tokens_in"]), "tokens_out": int(d["tokens_out"]),
                                  "latency_avg": round(float(d["latency_avg"]), 1) if d["latency_avg"] is not None else None}
    total = sum(v["cost"] for v in out.values())
    return {"hours": hours, "types": out, "cost": total,
            "minutes_transcribed": round(out["transcription"]["seconds"] / 60, 2),
            "characters_spoken": out["speech"]["characters"],
            "realtime_minutes": round(out["realtime"]["seconds"] / 60, 2)}
