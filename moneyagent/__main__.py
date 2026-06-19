"""Command line interface.

    python -m moneyagent providers          # show provider status & quota
    python -m moneyagent chat "..."          # one-off prompt through the router
    python -m moneyagent content --topic ... # draft client content
    python -m moneyagent signals --ticker BTC-USD
    python -m moneyagent ledger              # show progress toward the goal
    python -m moneyagent ledger --add --source content --desc "blog x" --amount 150
    python -m moneyagent serve               # run the SaaS API (needs fastapi)
"""
from __future__ import annotations

import argparse
import json
import logging
import sys

from .agent import Agent
from .config import load_config
from .ledger import Ledger
from .router import LLMRouter
from .workflows.content import ContentWorkflow
from .workflows.trading_signals import TradingSignalsWorkflow


def _router(args) -> LLMRouter:
    cfg = load_config()
    cfg.ensure_dirs()
    return LLMRouter(cfg)


def cmd_providers(args) -> int:
    router = _router(args)
    rows = router.status()
    print(json.dumps(rows, indent=2))
    usable = [r for r in rows if r["available"] and not r["at_limit"]]
    if not usable:
        print(
            "\n⚠  No usable provider. Either run Ollama locally, or set an API key "
            "in .env (see .env.example).",
            file=sys.stderr,
        )
        return 1
    print(f"\n✓ {len(usable)} provider(s) ready: {', '.join(r['name'] for r in usable)}")
    return 0


def cmd_chat(args) -> int:
    router = _router(args)
    agent = Agent(router)
    res = agent.run(args.prompt, self_review=not args.fast)
    print(res.output)
    if args.verbose:
        print("\n--- route ---", file=sys.stderr)
        for a in router.last_attempts:
            mark = "✓" if a.ok else "✗"
            print(f"  {mark} {a.provider}/{a.model} {a.error or ''}", file=sys.stderr)
    return 0


def _save_output(router: LLMRouter, name: str, text: str) -> str:
    out_dir = router.config.output_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / name
    path.write_text(text, encoding="utf-8")
    return str(path)


def cmd_content(args) -> int:
    router = _router(args)
    wf = ContentWorkflow(router)
    res = wf.run(
        topic=args.topic,
        kind=args.kind,
        words=args.words,
        language=args.language,
        tone=args.tone,
    )
    body = f"# {res.title}\n\n> {res.disclaimer}\n\n{res.output}\n"
    safe = "".join(c if c.isalnum() else "_" for c in args.topic)[:40]
    path = _save_output(router, f"content_{safe}.md", body)
    print(res.output)
    print(f"\n[saved -> {path}]  ({res.disclaimer})", file=sys.stderr)
    return 0


def cmd_signals(args) -> int:
    router = _router(args)
    wf = TradingSignalsWorkflow(router)
    prices = [float(x) for x in args.prices.split(",")] if args.prices else None
    res = wf.run(ticker=args.ticker, prices=prices, period=args.period)
    print(json.dumps(res.meta, indent=2))
    print("\n" + res.output)
    print(f"\n⚠ {res.disclaimer}", file=sys.stderr)
    return 0


def cmd_ledger(args) -> int:
    cfg = load_config()
    cfg.ensure_dirs()
    ledger = Ledger(cfg.data_dir / "ledger.json", cfg.monthly_target_usd)
    if args.add:
        if not (args.source and args.desc and args.amount is not None):
            print("--add requires --source, --desc and --amount", file=sys.stderr)
            return 1
        entry = ledger.add(args.source, args.desc, args.amount, args.status)
        print(f"Recorded ${entry.amount_usd} from {entry.source} ({entry.status}).")
    summary = ledger.month_summary()
    print(json.dumps(summary, indent=2))
    bar_len = 30
    filled = int(bar_len * min(summary["progress_pct"], 100) / 100)
    print(
        f"\n[{'#' * filled}{'-' * (bar_len - filled)}] "
        f"{summary['progress_pct']}% of ${summary['target_usd']:.0f}"
    )
    return 0


def cmd_serve(args) -> int:
    try:
        import uvicorn
    except ImportError:
        print("pip install fastapi uvicorn to use 'serve'", file=sys.stderr)
        return 1
    from .workflows.saas_automation import create_app

    uvicorn.run(create_app(), host=args.host, port=args.port)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="moneyagent", description="Multi-provider AI agent framework")
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("providers", help="show provider status & quota").set_defaults(func=cmd_providers)

    c = sub.add_parser("chat", help="run a prompt through the agent")
    c.add_argument("prompt")
    c.add_argument("--fast", action="store_true", help="skip self-review pass")
    c.set_defaults(func=cmd_chat)

    ct = sub.add_parser("content", help="draft client content")
    ct.add_argument("--topic", required=True)
    ct.add_argument("--kind", default="blog post")
    ct.add_argument("--words", type=int, default=600)
    ct.add_argument("--language", default="English")
    ct.add_argument("--tone", default="clear and professional")
    ct.set_defaults(func=cmd_content)

    sg = sub.add_parser("signals", help="educational market-indicator briefing")
    sg.add_argument("--ticker", default="")
    sg.add_argument("--prices", default="", help="comma-separated closing prices, oldest first")
    sg.add_argument("--period", default="3mo")
    sg.set_defaults(func=cmd_signals)

    lg = sub.add_parser("ledger", help="track real revenue toward the goal")
    lg.add_argument("--add", action="store_true")
    lg.add_argument("--source")
    lg.add_argument("--desc")
    lg.add_argument("--amount", type=float)
    lg.add_argument("--status", default="invoiced", choices=["invoiced", "paid"])
    lg.set_defaults(func=cmd_ledger)

    sv = sub.add_parser("serve", help="run the SaaS automation API")
    sv.add_argument("--host", default="127.0.0.1")
    sv.add_argument("--port", type=int, default=8000)
    sv.set_defaults(func=cmd_serve)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
