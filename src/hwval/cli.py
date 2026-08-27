"""Command-line entry point: ``python -m hwval.cli <command>``.

One CLI for the whole pipeline so the demo is reproducible from a clean clone:

    hwval init            create the schema
    hwval seed            generate synthetic validation data
    hwval train           train the anomaly models
    hwval evaluate        model vs spec-limit-screen comparison
    hwval score           score runs and persist anomaly events
    hwval report          build the validation report
    hwval testplan        generate a test plan
    hwval maintain        run the DB maintenance plan
    hwval ask "..."       ask the agent a question
    hwval demo            run the whole pipeline end to end
"""
from __future__ import annotations

import argparse
import json
import sys

from hwval.config import get_settings


def _print(obj) -> None:
    print(json.dumps(obj, indent=2, default=str) if not isinstance(obj, str) else obj)


def cmd_init(args) -> None:
    from hwval.db.engine import init_db

    init_db(drop=args.drop)
    _print({"ok": True, "dropped": args.drop})


def cmd_seed(args) -> None:
    from hwval.db.seed import GenConfig, seed_database

    cfg = GenConfig(
        n_duts=args.duts,
        runs_per_dut=args.runs_per_dut,
        samples_per_run=args.samples,
        seed=args.seed,
    )
    _print(seed_database(cfg, drop=not args.keep))


def cmd_train(args) -> None:
    from hwval.ml.train_sklearn import train_sklearn

    out = {"sklearn": train_sklearn()}
    if not args.no_autoencoder:
        from hwval.ml.train_tf import train_autoencoder

        out["autoencoder"] = train_autoencoder(epochs=args.epochs)
    _print(out)


def cmd_evaluate(args) -> None:
    from hwval.ml.evaluate import evaluate_all

    _print(evaluate_all())


def cmd_score(args) -> None:
    from hwval.ml.predict import persist_anomaly_events, score_runs

    df = score_runs()
    flagged = df[df["severity"].isin(["MEDIUM", "HIGH", "CRITICAL"])]
    n = persist_anomaly_events(flagged)
    _print({"scored": len(df), "persisted_events": n})
    print(df.sort_values("fused_score", ascending=False).head(10).to_string(index=False))


def cmd_report(args) -> None:
    from hwval.reporting.report import build_validation_report

    _print({"path": str(build_validation_report(fmt=args.fmt))})


def cmd_testplan(args) -> None:
    from hwval.agent.llm import get_chat_model, resolve_provider
    from hwval.reporting.testplan import generate_test_plan, save_test_plan

    llm = get_chat_model() if resolve_provider() != "rulebased" else None
    md = generate_test_plan(args.product, args.requirements, args.standard, llm=llm)
    pid = save_test_plan(f"{args.product} — {args.standard} validation", "1.0", md,
                         "llm" if llm else "template")
    out = get_settings().reports_dir / f"test_plan_{args.product.replace('/', '_')}.md"
    out.write_text(md, encoding="utf-8")
    _print({"test_plan_id": pid, "path": str(out), "chars": len(md)})


def cmd_maintain(args) -> None:
    from hwval.db.maintenance import run_maintenance_plan

    _print(run_maintenance_plan(dry_run=not args.execute))


def cmd_ask(args) -> None:
    from hwval.agent.core import ask

    run = ask(" ".join(args.question))
    print(run.answer)
    print("\n--- tool trace ---")
    for c in run.tool_calls:
        print(f"  {c['name']}({json.dumps(c.get('args', {}), default=str)[:120]})")
    print(f"provider={run.provider}  elapsed={run.elapsed_s:.2f}s")


def cmd_demo(args) -> None:
    from hwval.agent.core import DEMO_QUESTIONS, ask, build_agent
    from hwval.db.seed import GenConfig, seed_database
    from hwval.ml.evaluate import evaluate_all
    from hwval.ml.predict import persist_anomaly_events, score_runs
    from hwval.ml.train_sklearn import train_sklearn
    from hwval.reporting.report import build_validation_report

    print("1/6 seeding ...")
    seed_database(GenConfig(n_duts=args.duts), verbose=False)
    print("2/6 training sklearn models ...")
    train_sklearn()
    if not args.no_autoencoder:
        print("3/6 training autoencoder ...")
        from hwval.ml.train_tf import train_autoencoder

        train_autoencoder()
    print("4/6 scoring + persisting anomaly events ...")
    df = score_runs()
    persist_anomaly_events(df[df["severity"].isin(["MEDIUM", "HIGH", "CRITICAL"])])
    print("5/6 evaluating ...")
    _print(evaluate_all().get("comparison", evaluate_all()))
    print("6/6 building report ...")
    print("report:", build_validation_report(fmt="html"))
    agent = build_agent()
    for q in DEMO_QUESTIONS[: args.questions]:
        run = ask(q, agent)
        print(f"\nQ: {q}\n  tools: {[c['name'] for c in run.tool_calls]}\n  {run.answer[:400]}")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="hwval", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("init"); s.add_argument("--drop", action="store_true"); s.set_defaults(fn=cmd_init)
    s = sub.add_parser("seed")
    s.add_argument("--duts", type=int, default=60)
    s.add_argument("--runs-per-dut", type=int, default=4)
    s.add_argument("--samples", type=int, default=48)
    s.add_argument("--seed", type=int, default=42)
    s.add_argument("--keep", action="store_true", help="append instead of dropping")
    s.set_defaults(fn=cmd_seed)

    s = sub.add_parser("train")
    s.add_argument("--epochs", type=int, default=30)
    s.add_argument("--no-autoencoder", action="store_true")
    s.set_defaults(fn=cmd_train)

    sub.add_parser("evaluate").set_defaults(fn=cmd_evaluate)
    sub.add_parser("score").set_defaults(fn=cmd_score)

    s = sub.add_parser("report"); s.add_argument("--fmt", default="md", choices=["md", "html", "pdf"])
    s.set_defaults(fn=cmd_report)

    s = sub.add_parser("testplan")
    s.add_argument("--product", default="S32K344")
    s.add_argument("--requirements", default="Supply-droop and thermal robustness over PVT corners")
    s.add_argument("--standard", default="AEC-Q100")
    s.set_defaults(fn=cmd_testplan)

    s = sub.add_parser("maintain"); s.add_argument("--execute", action="store_true")
    s.set_defaults(fn=cmd_maintain)

    s = sub.add_parser("ask"); s.add_argument("question", nargs="+"); s.set_defaults(fn=cmd_ask)

    s = sub.add_parser("demo")
    s.add_argument("--duts", type=int, default=60)
    s.add_argument("--questions", type=int, default=3)
    s.add_argument("--no-autoencoder", action="store_true")
    s.set_defaults(fn=cmd_demo)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    get_settings()
    args.fn(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
