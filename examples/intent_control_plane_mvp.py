"""
Starstream Core - Datacenter MVP (reference design)

Concept:
- Intent-driven control plane that plans + executes resource changes
- Works with a SimulationAdapter now; hardware adapters later

This is intentionally lightweight: credible API, minimal dependencies.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Protocol, Any, Tuple
import time
import uuid


# -----------------------------
# Types / Inventory
# -----------------------------

@dataclass
class Link:
    src: str
    dst: str
    capacity_gbps: float
    base_latency_ms: float
    tags: Dict[str, str] = field(default_factory=dict)

@dataclass
class Topology:
    nodes: List[str]
    links: List[Link]

    def neighbors(self, node: str) -> List[str]:
        out = []
        for l in self.links:
            if l.src == node:
                out.append(l.dst)
            if l.dst == node:
                out.append(l.src)
        return list(sorted(set(out)))


@dataclass
class ResourceSnapshot:
    """Current state of resources (from telemetry)"""
    timestamp: float
    link_utilization: Dict[Tuple[str, str], float]  # 0..1 utilization
    link_loss: Dict[Tuple[str, str], float]         # 0..1 loss
    link_latency_ms: Dict[Tuple[str, str], float]   # measured latency
    notes: Dict[str, Any] = field(default_factory=dict)


# -----------------------------
# Intents + Policies
# -----------------------------

@dataclass
class Intent:
    intent_id: str
    created_at: float
    kind: str
    payload: Dict[str, Any]

    @staticmethod
    def bandwidth(
        source: str,
        destination: str,
        bandwidth_gbps: float,
        max_latency_ms: Optional[float] = None,
        priority: int = 3,
    ) -> "Intent":
        return Intent(
            intent_id=str(uuid.uuid4()),
            created_at=time.time(),
            kind="bandwidth",
            payload={
                "source": source,
                "destination": destination,
                "bandwidth_gbps": bandwidth_gbps,
                "max_latency_ms": max_latency_ms,
                "priority": priority,
            },
        )


@dataclass
class Policy:
    """Guardrails. Keep these simple for MVP; expand later."""
    max_link_utilization: float = 0.85
    max_packet_loss: float = 0.02
    require_verification: bool = True


# -----------------------------
# Plans + Execution
# -----------------------------

@dataclass
class Action:
    """An atomic change the executor can apply."""
    action_type: str
    params: Dict[str, Any]

@dataclass
class Plan:
    plan_id: str
    intent_id: str
    created_at: float
    actions: List[Action]
    expected_impact: Dict[str, Any] = field(default_factory=dict)

@dataclass
class ExecutionResult:
    plan_id: str
    ok: bool
    applied_actions: List[Action]
    before: ResourceSnapshot
    after: ResourceSnapshot
    message: str = ""


# -----------------------------
# Adapter Interfaces
# -----------------------------

class TelemetryProvider(Protocol):
    def snapshot(self) -> ResourceSnapshot: ...

class ExecutorAdapter(Protocol):
    def apply(self, actions: List[Action]) -> None: ...


# -----------------------------
# Planner
# -----------------------------

class Planner:
    """
    MVP planner:
    - Very simple: chooses a "preferred path" action (stub)
    - In a real system this becomes: TE solver, ILP, heuristic, or RL policy
    """

    def plan(self, topology: Topology, snapshot: ResourceSnapshot, intent: Intent, policy: Policy) -> Plan:
        if intent.kind != "bandwidth":
            raise ValueError(f"Unsupported intent kind: {intent.kind}")

        src = intent.payload["source"]
        dst = intent.payload["destination"]
        bw = float(intent.payload["bandwidth_gbps"])
        max_lat = intent.payload.get("max_latency_ms")

        # --- MVP "planning" logic (placeholder) ---
        # In production, compute candidate paths + score them (latency, util, loss).
        # Here we emit one action: "allocate_flow" with constraints.
        actions = [
            Action(
                action_type="allocate_flow",
                params={
                    "source": src,
                    "destination": dst,
                    "bandwidth_gbps": bw,
                    "max_latency_ms": max_lat,
                    "policy_max_util": policy.max_link_utilization,
                    "policy_max_loss": policy.max_packet_loss,
                },
            )
        ]

        return Plan(
            plan_id=str(uuid.uuid4()),
            intent_id=intent.intent_id,
            created_at=time.time(),
            actions=actions,
            expected_impact={
                "goal": "satisfy_bandwidth_intent",
                "notes": "MVP stub planner emits allocate_flow action.",
            },
        )


# -----------------------------
# Control Plane Engine
# -----------------------------

class Engine:
    def __init__(
        self,
        topology: Topology,
        telemetry: TelemetryProvider,
        executor: ExecutorAdapter,
        policy: Optional[Policy] = None,
    ):
        self.topology = topology
        self.telemetry = telemetry
        self.executor = executor
        self.policy = policy or Policy()
        self.planner = Planner()
        self.audit_log: List[Dict[str, Any]] = []

    def submit_intent(self, intent: Intent) -> ExecutionResult:
        before = self.telemetry.snapshot()

        plan = self.planner.plan(self.topology, before, intent, self.policy)

        # Apply
        self.executor.apply(plan.actions)

        after = self.telemetry.snapshot()

        # Verify (MVP: simple checks; expand to SLA evaluation)
        ok = True
        msg = "applied"

        if self.policy.require_verification:
            # Example verification: if any link loss exceeds policy, fail
            for _, loss in after.link_loss.items():
                if loss > self.policy.max_packet_loss:
                    ok = False
                    msg = f"verification_failed: loss {loss:.3f} > {self.policy.max_packet_loss:.3f}"
                    break

        # Audit
        self.audit_log.append(
            {
                "intent_id": intent.intent_id,
                "plan_id": plan.plan_id,
                "ok": ok,
                "message": msg,
                "ts": time.time(),
            }
        )

        return ExecutionResult(
            plan_id=plan.plan_id,
            ok=ok,
            applied_actions=plan.actions,
            before=before,
            after=after,
            message=msg,
        )


# -----------------------------
# Simulation Adapter (MVP)
# -----------------------------

class SimTelemetry:
    """Tiny simulation telemetry provider for MVP demos."""
    def __init__(self):
        self._t = time.time()

    def snapshot(self) -> ResourceSnapshot:
        # Replace with real metrics later (Prometheus, OpenTelemetry, switch counters)
        now = time.time()
        self._t = now
        return ResourceSnapshot(
            timestamp=now,
            link_utilization={("A", "B"): 0.50, ("B", "C"): 0.60, ("A", "C"): 0.90},
            link_loss={("A", "B"): 0.005, ("B", "C"): 0.010, ("A", "C"): 0.030},
            link_latency_ms={("A", "B"): 8.0, ("B", "C"): 12.0, ("A", "C"): 30.0},
        )

class SimExecutor:
    def apply(self, actions: List[Action]) -> None:
        # In a real executor, this calls SDN controller, optical controller, etc.
        for a in actions:
            print(f"[sim] applying action={a.action_type} params={a.params}")


# -----------------------------
# Example Usage
# -----------------------------

def example():
    topo = Topology(
        nodes=["A", "B", "C"],
        links=[
            Link("A", "B", capacity_gbps=100, base_latency_ms=8),
            Link("B", "C", capacity_gbps=100, base_latency_ms=12),
            Link("A", "C", capacity_gbps=50, base_latency_ms=30),
        ],
    )

    engine = Engine(
        topology=topo,
        telemetry=SimTelemetry(),
        executor=SimExecutor(),
        policy=Policy(max_link_utilization=0.85, max_packet_loss=0.02),
    )

    intent = Intent.bandwidth(source="A", destination="C", bandwidth_gbps=50, max_latency_ms=25, priority=5)
    result = engine.submit_intent(intent)

    print("OK:", result.ok)
    print("MSG:", result.message)
    print("Plan:", result.plan_id)

if __name__ == "__main__":
    example()

