#!/usr/bin/env python3
"""Dump telematics ROS .mcap bags from the terminal (no GUI).

Install once:
  pip3 install --user mcap

Examples:
  python3 tools/mcap_dump.py /path/to/ros_topics_part001.mcap
  python3 tools/mcap_dump.py bag.mcap --list
  python3 tools/mcap_dump.py bag.mcap --topic /ros2_controller/odom --limit 20
  python3 tools/mcap_dump.py bag.mcap --topic /telemetry_tx --jsonl > tx.jsonl

Notes:
  - Prefer a closed bag (after telematics stop/rotate). Live files are truncated;
    this tool still reads until the last complete record.
  - This prints JSON in time order. It does not publish to a live ROS graph
    (use Foxglove for timeline UI, or ros2 bag record on main compute for
    ros2 bag play).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

from mcap.records import Channel, Message, Schema
from mcap.stream_reader import StreamReader


def iter_bag(path: Path):
    channels: dict[int, Channel] = {}
    with path.open("rb") as f:
        try:
            for rec in StreamReader(f, record_size_limit=64 * 1024 * 1024).records:
                if isinstance(rec, Schema):
                    continue
                if isinstance(rec, Channel):
                    channels[rec.id] = rec
                    continue
                if isinstance(rec, Message):
                    ch = channels.get(rec.channel_id)
                    topic = ch.topic if ch else f"channel_{rec.channel_id}"
                    yield topic, rec.log_time, rec.data
        except Exception as exc:  # truncated live bag, etc.
            print(f"# stopped early: {type(exc).__name__}: {exc}", file=sys.stderr)


def main() -> int:
    ap = argparse.ArgumentParser(description="Dump telematics ROS MCAP bags in the terminal")
    ap.add_argument("mcap", type=Path, help="Path to .mcap file")
    ap.add_argument("--list", action="store_true", help="List topics + message counts only")
    ap.add_argument("--topic", action="append", default=[], help="Filter topic (repeatable)")
    ap.add_argument("--limit", type=int, default=0, help="Max messages to print (0 = all)")
    ap.add_argument("--jsonl", action="store_true", help="One JSON object per line")
    args = ap.parse_args()

    if not args.mcap.is_file():
        print(f"not found: {args.mcap}", file=sys.stderr)
        return 1

    want = set(args.topic)
    counts: Counter[str] = Counter()
    printed = 0

    for topic, log_time_ns, data in iter_bag(args.mcap):
        counts[topic] += 1
        if args.list:
            continue
        if want and topic not in want:
            continue
        if args.limit and printed >= args.limit:
            continue

        text = data.decode("utf-8", errors="replace")
        if args.jsonl:
            try:
                payload = json.loads(text)
            except json.JSONDecodeError:
                payload = {"_raw": text}
            print(json.dumps({"topic": topic, "log_time_ns": log_time_ns, "msg": payload},
                             separators=(",", ":")))
        else:
            print(f"[{log_time_ns}] {topic}")
            print(text)
            print("---")
        printed += 1

    if args.list or not printed:
        print("topics:")
        for topic, n in counts.most_common():
            print(f"  {n:8d}  {topic}")
        print(f"total_messages={sum(counts.values())}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
