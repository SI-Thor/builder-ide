"""``python -m mcsnap`` — the command line for the world snapshot tool.

The commands:

``snapshot``
    take a snapshot of a world into a store, and write its manifest;
``restore``
    put a snapshot back into a server's world directory, by swap, and
    check every file by its hash;
``verify``
    check a snapshot against its own manifest;
``list``
    the snapshots in a store, with the ledger row each one sits behind;
``server start|stop|status``
    the private server;
``rewind``
    the join to the world's story: a rewind point on the ledger, the
    nearest snapshot at or before it, and the work that can be put back.

Every command prints a short human summary; ``--json`` prints the machine
form instead.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .manifest import MANIFEST_NAME, read_manifest, verify_directory
from .restore import restore
from .server import PrivateServer
from .snapshot import take_snapshot
from .world import SECTION_LABELS


def _print(payload: dict[str, Any], as_json: bool, lines: list[str]) -> None:
    if as_json:
        print(json.dumps(payload, indent=2, default=str))
        return
    for line in lines:
        print(line)


def _server_for(args: argparse.Namespace) -> PrivateServer:
    return PrivateServer(
        args.server_dir,
        label=getattr(args, "label", "world-snapshot.server"),
        peak=getattr(args, "peak", "4G"),
    )


def cmd_snapshot(args: argparse.Namespace) -> int:
    server = _server_for(args)
    world_dir = Path(args.world_dir) if args.world_dir else server.world_dir
    command = None
    if not args.no_server:
        try:
            server.command("version")
            command = server.command
        except Exception as error:
            print(f"the server is not answering on RCON ({error}); "
                  "the world's files will be copied as they are", file=sys.stderr)
    result = take_snapshot(
        world_dir,
        args.out,
        ledger_path=args.ledger,
        command=command,
        snapshot_id=args.snapshot_id,
    )
    manifest = result.manifest
    payload = result.summary()
    lines = [
        f"snapshot {manifest.snapshot_id} -> {result.directory}",
        f"  files       {manifest.totals.get('files', 0)}",
        f"  bytes       {manifest.totals.get('bytes', 0)}",
        f"  ledger seq  {manifest.ledger_seq}",
        f"  tick        {manifest.world.get('tick')} "
        f"(time of day {manifest.world.get('day_time')})",
    ]
    for section, totals in manifest.sections.items():
        lines.append(
            f"  {section:<14} {totals['files']:>4} files  {totals['bytes']:>10} B"
            f"  {SECTION_LABELS.get(section, '')}"
        )
    lines.append("  timings      " + ", ".join(
        f"{key}={value:.3f}s" for key, value in result.timings.items()
    ))
    _print(payload, args.json, lines)
    return 0


def cmd_restore(args: argparse.Namespace) -> int:
    server = _server_for(args)
    stop = None
    start = None
    if not args.no_server:
        stop = server.stop
        start = server.start
    result = restore(
        args.server_dir,
        args.snapshot,
        stop=stop,
        start=start,
    )
    payload = result.summary()
    lines = [
        f"restored {result.manifest.snapshot_id} into {result.new_world}",
        f"  previous world kept at {result.previous_world}",
        f"  verified    {'yes' if result.verified else 'NO'}",
        f"  timings     " + ", ".join(
            f"{key}={value:.3f}s" for key, value in result.timings.items()
        ),
    ]
    for problem in result.problems:
        lines.append(f"  ! {problem}")
    _print(payload, args.json, lines)
    return 0 if result.verified else 1


def cmd_verify(args: argparse.Namespace) -> int:
    snapshot = Path(args.snapshot)
    manifest = read_manifest(snapshot / MANIFEST_NAME)
    problems = verify_directory(snapshot / "world", manifest)
    payload = {
        "snapshot_id": manifest.snapshot_id,
        "files": len(manifest.files),
        "problems": problems,
        "verified": not problems,
    }
    lines = [
        f"{manifest.snapshot_id}: {len(manifest.files)} files",
        "  verified    " + ("yes" if not problems else f"NO ({len(problems)} problems)"),
    ]
    lines.extend(f"  ! {problem}" for problem in problems)
    _print(payload, args.json, lines)
    return 0 if not problems else 1


def cmd_list(args: argparse.Namespace) -> int:
    store = Path(args.out)
    snapshots = []
    if store.is_dir():
        for directory in sorted(store.iterdir()):
            manifest_path = directory / MANIFEST_NAME
            if not manifest_path.is_file():
                continue
            manifest = read_manifest(manifest_path)
            snapshots.append(
                {
                    "snapshot_id": manifest.snapshot_id,
                    "taken_at": manifest.taken_at,
                    "ledger_seq": manifest.ledger_seq,
                    "tick": manifest.world.get("tick"),
                    "bytes": manifest.total_bytes,
                    "files": manifest.totals.get("files", 0),
                    "directory": str(directory),
                }
            )
    snapshots.sort(key=lambda item: (item["ledger_seq"] is None, item["ledger_seq"]))
    lines = [
        f"{item['snapshot_id']}  ledger {item['ledger_seq']}  tick {item['tick']}  "
        f"{item['bytes']} B"
        for item in snapshots
    ]
    _print({"snapshots": snapshots}, args.json, lines or ["no snapshots"])
    return 0


def cmd_server(args: argparse.Namespace) -> int:
    server = _server_for(args)
    if args.action == "start":
        result = server.start()
        payload = result.to_dict()
        _print(payload, args.json, [f"start: {result.ok} — {result.detail}"])
        return 0 if result.ok else 1
    if args.action == "stop":
        result = server.stop()
        payload = result.to_dict()
        _print(payload, args.json, [f"stop: {result.ok} — {result.detail}"])
        return 0 if result.ok else 1
    status = server.status()
    _print(status, args.json, [
        f"running    {status['running']}",
        f"pid        {status['pid']}",
        f"rcon       {status['rcon']['host']}:{status['rcon']['port']}",
        f"world      {status['world_dir']}",
        f"version    {status['version']}",
    ])
    return 0


def cmd_rewind(args: argparse.Namespace) -> int:
    # The join to the world's story is the core's vocabulary, not this
    # tool's, so it is imported here and not at the top of the module.
    from core.rewind.snapshot import rewind_plan_from_store

    plan = rewind_plan_from_store(
        args.out,
        args.ledger,
        point_seq=args.point,
        selection_text=args.selection,
        placements_path=args.placements,
    )
    payload = plan.to_dict()
    lines = [
        f"rewind point seq {plan.point_seq}",
        f"  snapshot        {plan.snapshot_id}",
        f"  snapshot seq    {plan.snapshot_seq}",
        f"  kept events    {len(plan.kept)}",
        f"  re-appliable   {len(plan.reappliable)}",
        f"  not re-applied {len(plan.recorded) + len(plan.lost)}",
        f"  lost           {len(plan.lost)}",
    ]
    _print(payload, args.json, lines)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mcsnap", description=__doc__)
    parser.add_argument("--json", action="store_true", help="print the machine form")
    subparsers = parser.add_subparsers(dest="command", required=True)

    def add_server_args(target: argparse.ArgumentParser) -> None:
        target.add_argument("--server-dir", required=True, help="the Paper server directory")
        target.add_argument("--label", default="world-snapshot.server", help="the thor-admit label")
        target.add_argument("--peak", default="4G", help="the honest memory peak to lease")

    snapshot = subparsers.add_parser("snapshot", help="take a snapshot of a world")
    add_server_args(snapshot)
    snapshot.add_argument("--out", required=True, help="the snapshot store")
    snapshot.add_argument("--ledger", default=None, help="the world ledger to read the head of")
    snapshot.add_argument("--world-dir", default=None, help="the world directory (default: the server's)")
    snapshot.add_argument("--snapshot-id", default=None, help="the snapshot's name")
    snapshot.add_argument("--no-server", action="store_true", help="copy a stopped world's files")
    snapshot.set_defaults(func=cmd_snapshot)

    restore_parser = subparsers.add_parser("restore", help="put a snapshot back")
    add_server_args(restore_parser)
    restore_parser.add_argument("--snapshot", required=True, help="the snapshot directory")
    restore_parser.add_argument("--no-server", action="store_true", help="do not stop or start the server")
    restore_parser.set_defaults(func=cmd_restore)

    verify = subparsers.add_parser("verify", help="check a snapshot against its manifest")
    verify.add_argument("--snapshot", required=True)
    verify.set_defaults(func=cmd_verify)

    listing = subparsers.add_parser("list", help="the snapshots in a store")
    listing.add_argument("--out", required=True)
    listing.set_defaults(func=cmd_list)

    server = subparsers.add_parser("server", help="the private server")
    add_server_args(server)
    server.add_argument("action", choices=["start", "stop", "status"])
    server.set_defaults(func=cmd_server)

    rewind = subparsers.add_parser("rewind", help="a rewind point, and the snapshot under it")
    rewind.add_argument("--out", required=True, help="the snapshot store")
    rewind.add_argument("--ledger", required=True, help="the world ledger")
    rewind.add_argument("--point", type=int, required=True, help="the rewind point's seq")
    rewind.add_argument("--selection", default=None, help="what to keep (the selection language)")
    rewind.add_argument(
        "--placements",
        default=None,
        help="the placement journal the bots wrote (the coordinates)",
    )
    rewind.set_defaults(func=cmd_rewind)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
