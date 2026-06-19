"""Autopilot — run workflows on a schedule, continuously and within guardrails.

This is the "runs by itself" piece (in the spirit of AutoGPT / Hermes-style
continuous agents), but kept honest and bounded:
  * Each job maps to a workflow + parameters + an interval.
  * The loop respects the router's per-provider quotas and an optional daily USD
    budget, and stops after max_iterations.
  * Outputs are written to disk and logged to memory. Nothing is published or
    sent to a client automatically — a human still reviews and delivers.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path

from .agent import Agent
from .config import Config
from .memory import Memory
from .router import LLMRouter
from .workflows.content import ContentWorkflow
from .workflows.trading_signals import TradingSignalsWorkflow

logger = logging.getLogger("moneyagent.autopilot")


@dataclass
class JobSpec:
    name: str
    workflow: str                       # "content" | "signals" | "chat"
    params: dict = field(default_factory=dict)
    every_seconds: int = 3600
    max_runs: int = 0                   # 0 = unlimited
    _runs: int = 0
    _next_at: float = 0.0


def load_jobs(path: str | Path) -> list[JobSpec]:
    import yaml

    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    specs = []
    for j in raw.get("jobs", []):
        specs.append(
            JobSpec(
                name=j["name"],
                workflow=j["workflow"],
                params=j.get("params", {}),
                every_seconds=int(j.get("every_seconds", 3600)),
                max_runs=int(j.get("max_runs", 0)),
            )
        )
    return specs


class Autopilot:
    def __init__(self, config: Config, router: LLMRouter | None = None,
                 daily_budget_usd: float = 0.0):
        self.config = config
        config.ensure_dirs()
        self.router = router or LLMRouter(config, daily_budget_usd=daily_budget_usd)
        self.memory = Memory(config.data_dir / "memory.jsonl")

    def _run_workflow(self, spec: JobSpec) -> str:
        wf = spec.workflow
        if wf == "content":
            res = ContentWorkflow(self.router).run(**spec.params)
            return self._persist(spec, res.title, res.output)
        if wf == "signals":
            res = TradingSignalsWorkflow(self.router).run(**spec.params)
            return self._persist(spec, res.title, str(res.meta) + "\n\n" + res.output)
        if wf == "chat":
            out = Agent(self.router).run(spec.params.get("task", ""), self_review=False).output
            return self._persist(spec, spec.name, out)
        raise ValueError(f"Unknown workflow '{wf}' in job '{spec.name}'")

    def _persist(self, spec: JobSpec, title: str, body: str) -> str:
        out_dir = self.config.output_dir
        out_dir.mkdir(parents=True, exist_ok=True)
        safe = "".join(c if c.isalnum() else "_" for c in spec.name)[:40]
        path = out_dir / f"{safe}_{spec._runs:04d}.md"
        path.write_text(f"# {title}\n\n{body}\n", encoding="utf-8")
        self.memory.add("job_run", title, job=spec.name, output=str(path))
        return str(path)

    def run_once(self, spec: JobSpec) -> str:
        spec._runs += 1
        logger.info("Running job '%s' (run %d)", spec.name, spec._runs)
        return self._run_workflow(spec)

    def run_forever(self, jobs: list[JobSpec], *, max_iterations: int = 0,
                    poll_seconds: float = 1.0) -> None:
        """Loop until every job is exhausted or max_iterations is hit."""
        iterations = 0
        logger.info("Autopilot started with %d job(s). Ctrl-C to stop.", len(jobs))
        while True:
            now = time.time()
            pending = [j for j in jobs if (j.max_runs == 0 or j._runs < j.max_runs)]
            if not pending:
                logger.info("All jobs reached max_runs. Stopping.")
                return
            for job in pending:
                if now < job._next_at:
                    continue
                if self.router.daily_budget_usd and self.router.usage.over_budget(
                    self.router.daily_budget_usd
                ):
                    logger.warning("Daily budget reached; pausing autopilot.")
                    return
                try:
                    path = self.run_once(job)
                    logger.info("  -> %s", path)
                except Exception as exc:  # noqa: BLE001 - keep the loop alive
                    logger.error("Job '%s' failed: %s", job.name, exc)
                    self.memory.add("job_error", str(exc), job=job.name)
                job._next_at = time.time() + job.every_seconds
                iterations += 1
                if max_iterations and iterations >= max_iterations:
                    logger.info("Reached max_iterations=%d. Stopping.", max_iterations)
                    return
            time.sleep(poll_seconds)
