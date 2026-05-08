import time
import inspect
import logging
import pandas as pd
import utils

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("utils-profiler")


# ---------- CONFIG ----------
TEST_INPUTS = {
    "authenticate_user": ("test_user", "test_pass"),
    "create_user": ("test_user_temp", "test_pass"),
    "get_devices": ("test_user",),
    "create_device": ("test_user", 9999, None),
    "delete_device": ("test_user", 9999),
    "get_groups": ("test_user",),
    "create_group": ("test_user", 999),
    "delete_group": ("test_user", 999),
    "get_group_devices": ("test_user", 1),
    "update_device_state": ("test_user", 1, 1),
    "update_group_state": ("test_user", 1, 1),
    "get_device_power_usage": (1,),
    "get_group_power_usage": ("test_user", 1),
    "get_latest_power_usage": (),
    "get_power_usage": (),
    "get_myPowerUsage": (),
}


# ---------- PROFILER ----------
class FunctionResult:
    def __init__(self, name):
        self.name = name
        self.runs = []
        self.success = 0
        self.fail = 0

    def add(self, time_ms, ok):
        self.runs.append(time_ms)
        if ok:
            self.success += 1
        else:
            self.fail += 1

    def summary(self):
        if not self.runs:
            return None
        return {
            "function": self.name,
            "calls": len(self.runs),
            "success": self.success,
            "fail": self.fail,
            "avg_ms": sum(self.runs) / len(self.runs),
            "min_ms": min(self.runs),
            "max_ms": max(self.runs),
        }


def run_function(fn_name, fn, args, runs=3):
    result = FunctionResult(fn_name)

    for i in range(runs):
        t0 = time.perf_counter()
        ok = True
        try:
            _ = fn(*args)
        except Exception as e:
            ok = False
            log.warning(f"{fn_name} failed: {e}")

        dt = (time.perf_counter() - t0) * 1000
        result.add(dt, ok)

    return result


def main():
    results = []

    functions = inspect.getmembers(utils, inspect.isfunction)

    print("\n=== RUNNING FULL UTILS PROFILER ===\n")

    for name, fn in functions:
        if name.startswith("_"):
            continue

        args = TEST_INPUTS.get(name)

        if args is None:
            print(f"[SKIP] {name} → no test inputs defined")
            continue

        print(f"[TESTING] {name} ...")

        res = run_function(name, fn, args)

        summary = res.summary()
        if summary:
            results.append(summary)

    df = pd.DataFrame(results)

    if df.empty:
        print("No results generated.")
        return

    df = df.sort_values(by="avg_ms", ascending=False)

    print("\n=== PERFORMANCE REPORT ===\n")
    print(df.to_string(index=False))

    df.to_csv("utils_perf_report.csv", index=False)

    print("\n=== TOP BOTTLENECKS ===")
    for _, row in df.head(10).iterrows():
        print(f"{row['function']} → {row['avg_ms']:.0f} ms")

    print("\nReport saved to: utils_perf_report.csv")


if __name__ == "__main__":
    main()