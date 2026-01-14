"""Scheduler Baselines (Reference Implementations)

This module provides simplified baseline scheduling strategies intended for simulation,
comparison, and discussion within hybrid optical–electronic system models.

These implementations are illustrative and abstract by design. They do not assume
specific hardware, vendors, or deployment environments, and are not intended for
production use.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Tuple
import random


@dataclass(frozen=True)
class SLO:
    """Service level objective constraints for a request/workload."""

    latency_p95_ms: float
    cost_per_1k: float
    energy_j_max: float


def score(est: Dict[str, float], slo: SLO) -> float:
    """Higher is better.

    Penalize latency vs SLO, cost vs budget, energy vs cap.
    """

    lat_pen = est["lat_ms"] / max(slo.latency_p95_ms, 1e-6)
    cost_pen = est["cost"] / max(slo.cost_per_1k, 1e-9)
    energy_pen = est["energy"] / max(slo.energy_j_max, 1e-9)
    return 1.0 / (0.55 * lat_pen + 0.30 * cost_pen + 0.15 * energy_pen)


class Models:
    """Toy estimator.

    In a real system this would be replaced by:
      - calibrated empirical curves
      - learned predictors
      - vendor telemetry / counters
      - queueing models
    """

    def __init__(self) -> None:
        self.mean = {
            "photonic": {"lat_ms": 0.4, "cost": 0.0002, "energy": 1.0},
            "gpu": {"lat_ms": 1.2, "cost": 0.0005, "energy": 5.0},
            "cpu": {"lat_ms": 4.0, "cost": 0.0001, "energy": 2.0},
        }

    def estimate(self, target: str, context: Dict) -> Dict[str, float]:
        """Estimate latency/cost/energy given a workload context.

        Context fields are optional; defaults keep this runnable.
        """

        base = dict(self.mean[target])

        batch = float(context.get("batch_size", 1.0))
        tokens = float(context.get("tokens", 512.0))
        concurrency = float(context.get("concurrency", 1.0))

        load = (tokens / 512.0) * (batch**0.5) * (concurrency**0.6)
        base["lat_ms"] *= (1.0 + 0.25 * load)
        base["energy"] *= (1.0 + 0.35 * load)
        base["cost"] *= (1.0 + 0.20 * load)

        return base


class ConstrainedBestScore:
    """Pick the best-scoring target subject to basic safety constraints."""

    def __init__(self) -> None:
        self.models = Models()

    def decide(self, slo: SLO, context: Dict) -> Tuple[str, Dict]:
        cands = ["photonic", "gpu", "cpu"]
        safe = []

        for t in cands:
            est = self.models.estimate(t, context)
            if est["lat_ms"] <= slo.latency_p95_ms * 1.05 and est["energy"] <= slo.energy_j_max * 1.1:
                safe.append((t, est))

        if not safe:
            safe = [(t, self.models.estimate(t, context)) for t in cands]

        best_t, best_est, best_score = max(
            [(t, est, score(est, slo)) for t, est in safe],
            key=lambda x: x[2],
        )

        return best_t, {"target": best_t, "expected": best_est, "score": best_score}


class ConstrainedEpsilonGreedy:
    """A minimal explore/exploit policy with SLO-aware candidate filtering."""

    def __init__(self, eps: float = 0.1, canary: float = 0.05) -> None:
        self.models = Models()
        self.eps = eps
        self.canary = canary
        self.mu = {t: 0.0 for t in ["photonic", "gpu", "cpu"]}
        self.n = {t: 1 for t in self.mu}

    def _safe(self, est: Dict[str, float], slo: SLO) -> bool:
        return est["lat_ms"] <= slo.latency_p95_ms * 1.05 and est["energy"] <= slo.energy_j_max * 1.1

    def decide(self, slo: SLO, context: Dict) -> Tuple[str, Dict]:
        cands = ["photonic", "gpu", "cpu"]
        ests = {t: self.models.estimate(t, context) for t in cands}
        safe = [t for t in cands if self._safe(ests[t], slo)] or cands

        if random.random() < self.eps:
            choice = random.choice(safe)
            mode = "explore"
        else:
            vals = {t: score(ests[t], slo) + self.mu[t] / self.n[t] for t in safe}
            choice = max(vals.items(), key=lambda kv: kv[1])[0]
            mode = "exploit"

        return choice, {
            "target": choice,
            "expected": ests[choice],
            "mode": mode,
            "canary_fraction": self.canary,
        }

    def observe(self, target: str, actual: Dict[str, float]) -> None:
        """Update internal preference estimates.

        Reward is intentionally simplistic: cheaper + faster is better.
        """

        r = 1.0 / max(float(actual.get("cost", 1e-4)), 1e-4) - 0.5 * max(0.0, float(actual.get("lat_ms", 0.0)))
        self.mu[target] += r
        self.n[target] += 1


def _demo() -> None:
    slo = SLO(latency_p95_ms=2.0, cost_per_1k=0.0005, energy_j_max=6.0)
    ctx = {"tokens": 1024, "batch_size": 2, "concurrency": 3}

    best = ConstrainedBestScore()
    t1, meta1 = best.decide(slo, ctx)
    print("BestScore:", t1, meta1)

    eg = ConstrainedEpsilonGreedy(eps=0.2)
    t2, meta2 = eg.decide(slo, ctx)
    print("EpsilonGreedy:", t2, meta2)

    # Simulate an observation callback
    eg.observe(t2, {"lat_ms": meta2["expected"]["lat_ms"], "cost": meta2["expected"]["cost"]})


if __name__ == "__main__":
    _demo()
