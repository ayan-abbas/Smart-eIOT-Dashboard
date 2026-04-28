
"""
Performance tester for the Enterprise IoT dashboard.

What it measures:
- connection acquisition
- auth
- devices / groups fetches
- latest power snapshot
- single-device power history
- group power history

What it does NOT do:
- mutate data by default
- import Streamlit app.py directly (that file runs UI code at import time)

Usage examples:
    python perf_tester.py --username you@example.com --password secret --deviceid 34 --groupid 1
    python perf_tester.py --username you@example.com --deviceid 34 --groupid 1 --repeat 5 --warmup 1

Output:
- console timing summary
- perf_results.csv in the current directory
"""

from __future__ import annotations

import argparse
import csv
import logging
import statistics as stats
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Callable, Iterable

import utils


LOG_FORMAT = "%(asctime)s.%(msecs)03d [%(levelname)s] %(name)s - %(message)s"


@dataclass
class BenchResult:
    name: str
    run: int
    seconds: float
    ok: bool
    note: str = ""


def setup_logging(level: int = logging.INFO) -> logging.Logger:
    logging.basicConfig(level=level, format=LOG_FORMAT, datefmt="%H:%M:%S")
    return logging.getLogger("eiot.perf")


def timed_call(name: str, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> tuple[Any, float, bool, str]:
    t0 = time.perf_counter()
    try:
        result = fn(*args, **kwargs)
        ok = True
        note = ""
    except Exception as exc:  # noqa: BLE001
        result = None
        ok = False
        note = f"{type(exc).__name__}: {exc}"
    elapsed = time.perf_counter() - t0
    return result, elapsed, ok, note


def run_benchmark(
    name: str,
    fn: Callable[..., Any],
    repeat: int = 3,
    warmup: int = 1,
    *args: Any,
    **kwargs: Any,
) -> tuple[list[BenchResult], Any]:
    results: list[BenchResult] = []
    last_result: Any = None

    for i in range(warmup):
        _, elapsed, ok, note = timed_call(name, fn, *args, **kwargs)
        results.append(BenchResult(name=f"{name} [warmup]", run=i + 1, seconds=elapsed, ok=ok, note=note))

    for i in range(repeat):
        last_result, elapsed, ok, note = timed_call(name, fn, *args, **kwargs)
        results.append(BenchResult(name=name, run=i + 1, seconds=elapsed, ok=ok, note=note))

    return results, last_result


def summarize(results: list[BenchResult]) -> list[dict[str, Any]]:
    grouped: dict[str, list[BenchResult]] = {}
    for r in results:
        if "[warmup]" in r.name:
            continue
        grouped.setdefault(r.name, []).append(r)

    summary: list[dict[str, Any]] = []
    for name, rows in grouped.items():
        secs = [r.seconds for r in rows if r.ok]
        fails = sum(1 for r in rows if not r.ok)
        if secs:
            summary.append(
                {
                    "name": name,
                    "runs": len(rows),
                    "failures": fails,
                    "min_ms": round(min(secs) * 1000, 2),
                    "avg_ms": round(stats.mean(secs) * 1000, 2),
                    "median_ms": round(stats.median(secs) * 1000, 2),
                    "max_ms": round(max(secs) * 1000, 2),
                }
            )
        else:
            summary.append(
                {
                    "name": name,
                    "runs": len(rows),
                    "failures": fails,
                    "min_ms": None,
                    "avg_ms": None,
                    "median_ms": None,
                    "max_ms": None,
                }
            )

    summary.sort(key=lambda d: (d["avg_ms"] is None, -(d["avg_ms"] or -1)))
    return summary


def write_csv(path: Path, results: Iterable[BenchResult]) -> None:
    rows = [asdict(r) for r in results]
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["name", "run", "seconds", "ok", "note"])
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark the slow parts of the EIOT dashboard.")
    parser.add_argument("--username", required=True, help="Dashboard username")
    parser.add_argument("--password", default=None, help="Password for authenticate_user benchmark")
    parser.add_argument("--deviceid", default=None, help="Device id to benchmark single-device queries")
    parser.add_argument("--groupid", default=None, help="Group id to benchmark group queries")
    parser.add_argument("--repeat", type=int, default=3, help="Measured runs per benchmark")
    parser.add_argument("--warmup", type=int, default=1, help="Warmup runs before measuring")
    parser.add_argument("--csv", default="perf_results.csv", help="CSV output file")
    parser.add_argument("--include-writes", action="store_true", help="Also benchmark write operations (not recommended)")
    args = parser.parse_args()

    log = setup_logging(logging.INFO)
    log.info("Starting benchmark: repeat=%d warmup=%d", args.repeat, args.warmup)

    results: list[BenchResult] = []

    bench_plan: list[tuple[str, Callable[..., Any], tuple[Any, ...], dict[str, Any]]] = [
        ("get_connection", utils.get_connection, tuple(), {}),
        ("get_devices", utils.get_devices, (args.username,), {}),
        ("get_latest_power_usage", utils.get_latest_power_usage, tuple(), {}),
        ("get_groups", utils.get_groups, (args.username,), {}),
    ]

    if args.password is not None:
        bench_plan.insert(1, ("authenticate_user", utils.authenticate_user, (args.username, args.password), {}))

    if args.deviceid is not None:
        bench_plan.append(("get_device_power_usage", utils.get_device_power_usage, (args.deviceid,), {}))

    if args.groupid is not None:
        bench_plan.append(("get_group_power_usage", utils.get_group_power_usage, (args.username, args.groupid), {}))
        bench_plan.append(("get_group_devices", utils.get_group_devices, (args.username, args.groupid), {}))

    if args.include_writes:
        # These are measured only if explicitly requested because they mutate data.
        bench_plan.extend(
            [
                ("update_device_state", utils.update_device_state, (args.username, args.deviceid, 1 if args.deviceid is not None else 0), {}),
                ("update_group_state", utils.update_group_state, (args.username, args.groupid, True), {}),
            ]
        )

    for name, fn, fn_args, fn_kwargs in bench_plan:
        log.info("Benchmarking %s ...", name)
        bench_rows, _ = run_benchmark(name, fn, repeat=args.repeat, warmup=args.warmup, *fn_args, **fn_kwargs)
        results.extend(bench_rows)
        last = [r for r in bench_rows if r.name == name and r.ok]
        if last:
            log.info("%s last run = %.2f ms", name, last[-1].seconds * 1000)
        else:
            log.warning("%s failed in all measured runs", name)

    summary = summarize(results)

    print("\n=== PERFORMANCE SUMMARY (sorted by avg_ms desc) ===")
    for row in summary:
        print(
            f"{row['name']:<28} "
            f"avg={row['avg_ms']} ms  "
            f"median={row['median_ms']} ms  "
            f"min={row['min_ms']} ms  "
            f"max={row['max_ms']} ms  "
            f"failures={row['failures']}"
        )

    csv_path = Path(args.csv)
    write_csv(csv_path, results)
    log.info("Wrote raw results to %s", csv_path.resolve())

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
