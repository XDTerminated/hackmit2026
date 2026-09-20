"""Grok analysis service — mock when credentials are missing.

Grok may recommend ONLY from session.allowed_next_cues.
It never invents actuator parameters and never commands the motor.
When n is small, next_experiment prioritizes gathering more evidence.
"""

from __future__ import annotations

import json
import os
import statistics
from collections import defaultdict
from typing import Optional

import httpx

from models import CueParams, EventRecord, GrokAnalysis, SessionState


def grok_configured() -> bool:
    return bool(os.getenv("GROK_API_KEY"))


async def analyze_session(session: SessionState) -> GrokAnalysis:
    mock = _mock_analysis(session)
    if not grok_configured():
        return mock

    api_key = os.getenv("GROK_API_KEY", "")
    model = os.getenv("GROK_MODEL", "grok-3")
    base = os.getenv("GROK_API_BASE", "https://api.x.ai/v1").rstrip("/")
    allowed = [
        {"pattern": c.pattern, "bpm": c.bpm} for c in session.allowed_next_cues
    ]
    events_payload = [e.model_dump() for e in session.events]
    system = (
        "You are assisting a HackMIT research prototype for wearable freeze-like "
        "gait cueing. This is NOT a medical device. Never diagnose, treat, or "
        "confirm freezing of gait. Use wording like 'possible freeze-like event' "
        "and 'freeze-like gait pattern'. Cloud analysis is observational only — "
        "you MUST NOT command the vibration motor or invent actuator parameters. "
        "Recommend the next experiment ONLY from allowed_next_cues. If the number "
        "of events is small (fewer than 8, especially 1–2 per cue), do not declare "
        "a cue effective; prioritize gathering more evidence. Return strict JSON."
    )
    user = json.dumps(
        {
            "session_id": session.session_id,
            "baseline_cadence_bpm": session.baseline_cadence_bpm,
            "allowed_next_cues": allowed,
            "events": events_payload,
            "required_keys": [
                "summary",
                "observation",
                "evidence",
                "next_experiment",
                "confidence_statement",
                "full_analysis",
                "session_summary",
                "cue_comparison",
                "observations",
                "safety",
                "limitation",
                "recommended_cue",
            ],
        }
    )
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post(
                f"{base}/chat/completions",
                headers={"Authorization": f"Bearer {api_key}"},
                json={
                    "model": model,
                    "temperature": 0.2,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    "response_format": {"type": "json_object"},
                },
            )
            resp.raise_for_status()
            body = resp.json()
        content = body["choices"][0]["message"]["content"]
        parsed = json.loads(content)
        rec = _coerce_recommended(parsed.get("recommended_cue"), session)
        return GrokAnalysis(
            summary=str(parsed.get("summary") or mock.summary),
            observation=str(parsed.get("observation") or mock.observation),
            evidence=str(parsed.get("evidence") or mock.evidence),
            next_experiment=str(parsed.get("next_experiment") or mock.next_experiment),
            confidence_statement=str(
                parsed.get("confidence_statement") or mock.confidence_statement
            ),
            full_analysis=str(parsed.get("full_analysis") or mock.full_analysis),
            session_summary=str(parsed.get("session_summary") or mock.session_summary),
            cue_comparison=str(parsed.get("cue_comparison") or mock.cue_comparison),
            observations=str(parsed.get("observations") or mock.observations),
            safety=str(parsed.get("safety") or mock.safety),
            limitation=str(parsed.get("limitation") or mock.limitation),
            recommended_cue=rec,
            mock=False,
        )
    except Exception:
        mock.limitation = (
            mock.limitation
            + " Live Grok call failed; showing local evidence-first mock analysis."
        )
        return mock


def _coerce_recommended(raw: object, session: SessionState) -> Optional[CueParams]:
    allowed = {(c.pattern, c.bpm) for c in session.allowed_next_cues}
    if not isinstance(raw, dict):
        return _under_sampled_cue(session)
    pattern = str(raw.get("pattern", "rhythmic"))
    try:
        bpm = int(raw.get("bpm"))
    except (TypeError, ValueError):
        return _under_sampled_cue(session)
    if (pattern, bpm) not in allowed:
        return _under_sampled_cue(session)
    return CueParams(pattern=pattern, bpm=bpm, active=False)  # type: ignore[arg-type]


def _under_sampled_cue(session: SessionState) -> Optional[CueParams]:
    counts: dict[int, int] = defaultdict(int)
    for event in session.events:
        counts[event.cue.bpm] += 1
    best: Optional[CueParams] = None
    best_n = 10**9
    for cue in session.allowed_next_cues:
        n = counts[cue.bpm]
        if n < best_n:
            best_n = n
            best = CueParams(pattern=cue.pattern, bpm=cue.bpm, active=False)
    return best


def _group_recoveries(events: list[EventRecord]) -> dict[int, list[int]]:
    grouped: dict[int, list[int]] = defaultdict(list)
    for event in events:
        if event.recovery.detected and event.recovery.time_ms is not None:
            grouped[event.cue.bpm].append(event.recovery.time_ms)
    return grouped


def _mock_analysis(session: SessionState) -> GrokAnalysis:
    events = session.events
    n = len(events)
    grouped = _group_recoveries(events)
    medians: dict[int, float] = {}
    for bpm, times in grouped.items():
        medians[bpm] = statistics.median(times)

    shortest_bpm = None
    if medians:
        shortest_bpm = min(medians, key=medians.get)  # type: ignore[arg-type]

    counts = {c.bpm: 0 for c in session.allowed_next_cues}
    for event in events:
        if event.cue.bpm in counts:
            counts[event.cue.bpm] += 1
        else:
            counts[event.cue.bpm] = counts.get(event.cue.bpm, 0) + 1

    evidence_n = grouped.get(shortest_bpm, []) if shortest_bpm is not None else []
    evidence = (
        f"{len(evidence_n)} observation{'s' if len(evidence_n) != 1 else ''}"
        if shortest_bpm is not None
        else f"{n} events"
    )

    if n == 0:
        observation = (
            "No freeze-like episodes logged yet. Continue walking capture "
            "to build a baseline."
        )
        next_experiment = (
            "Collect the first freeze-like observations at 95 BPM "
            "(within allowed_next_cues) before comparing tempos."
        )
        confidence = "No ranking is possible with zero events."
    elif n <= 2:
        observation = (
            "Too few freeze-like episodes to compare cue tempos. "
            "Any apparent difference is still noise."
        )
        next_experiment = (
            "Keep the current allowed cue set and collect more freeze-like "
            "observations before ranking 80 / 95 / 102 BPM."
        )
        confidence = "Insufficient data to rank cues reliably."
    else:
        if shortest_bpm is not None:
            sec = medians[shortest_bpm] / 1000.0
            observation = (
                f"{shortest_bpm} BPM currently has the shortest observed "
                f"median recovery ({sec:.2f}s). This is a prototype signal, "
                "not evidence that the cue treats freezing of gait."
            )
        else:
            observation = (
                "Logged episodes lack recovery timings needed for a cue comparison."
            )
        unused = [c.bpm for c in session.allowed_next_cues if counts.get(c.bpm, 0) == 0]
        if unused:
            next_experiment = (
                f"Collect more observations comparing {shortest_bpm} BPM and "
                f"{unused[0]} BPM."
            )
        else:
            next_experiment = (
                "Collect more observations across 80, 95, and 102 BPM before "
                "ranking tempos. Do not lock a cue after a handful of trials."
            )
        confidence = "Insufficient data to rank cues reliably."

    rec = _under_sampled_cue(session)

    comparison_lines = []
    for cue in session.allowed_next_cues:
        times = grouped.get(cue.bpm, [])
        if times:
            med = statistics.median(times) / 1000.0
            comparison_lines.append(
                f"- {cue.pattern} {cue.bpm} BPM: n={len(times)}, "
                f"median recovery {med:.2f}s"
            )
        else:
            comparison_lines.append(
                f"- {cue.pattern} {cue.bpm} BPM: n=0 (no observations yet)"
            )
    cue_comparison = "\n".join(comparison_lines) or "No cue data yet."

    session_summary = (
        f"Session {session.session_id} logged {n} possible freeze-like "
        f"episode{'s' if n != 1 else ''} against a baseline cadence of "
        f"{session.baseline_cadence_bpm:.0f} BPM. "
        "All cues were dispatched by the local/edge loop; cloud models "
        "only scored or summarized after the fact."
    )
    observations = (
        observation
        + " Edge and RunPod confidences are research scores for freeze-like "
        "gait patterns — they are not a clinical confirmation of FoG."
    )
    full_analysis = "\n\n".join(
        [
            "## SESSION SUMMARY",
            session_summary,
            "## CUE COMPARISON",
            cue_comparison,
            "## OBSERVATIONS",
            observations,
            "## NEXT EXPERIMENT",
            next_experiment,
            "## SAFETY",
            "Grok and RunPod must not control the vibration motor. "
            "Intervention remains local/edge-first. Operators may arm a next "
            "cue only from allowed_next_cues.",
            "## LIMITATION",
            "Small-n prototype, often simulated IMU. Findings are hypotheses "
            "for the next walking trial, not treatment recommendations.",
        ]
    )

    return GrokAnalysis(
        summary=f"{n} event{'s' if n != 1 else ''} analyzed.",
        observation=observation,
        evidence=evidence,
        next_experiment=next_experiment,
        confidence_statement=confidence,
        full_analysis=full_analysis,
        session_summary=session_summary,
        cue_comparison=cue_comparison,
        observations=observations,
        recommended_cue=rec,
        mock=True,
    )
