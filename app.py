#!/usr/bin/env python3
import argparse
import sys

from replaykit.cli import build_record_parser, build_replay_parser, run_record, run_replay
from replaykit.control import ControlState
from replaykit.web import serve_in_background


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="app.py",
        description="replaykit: record and replay browser flows",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    build_record_parser(subparsers.add_parser("record", help="discover a new flow with an LLM"))
    build_replay_parser(subparsers.add_parser("replay", help="deterministically replay a saved flow"))
    serve_parser = subparsers.add_parser("serve", help="replay with a live operator dashboard")
    build_replay_parser(serve_parser)
    serve_parser.add_argument("--port", type=int, default=5000)
    args = parser.parse_args(argv)

    if args.command == "record":
        import anthropic

        control = ControlState() if args.serve else None
        if control is not None:
            serve_in_background(control, args.port)
            print(f"Dashboard: http://127.0.0.1:{args.port}")
        return run_record(args, control=control, client=anthropic.Anthropic())
    if args.command == "replay":
        return run_replay(args, control=None)
    if args.command == "serve":
        control = ControlState()
        serve_in_background(control, args.port)
        print(f"Dashboard: http://127.0.0.1:{args.port}")
        return run_replay(args, control=control)
    return 2


if __name__ == "__main__":
    sys.exit(main())
