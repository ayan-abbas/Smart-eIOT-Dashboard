"""
seed_demo.py
────────────────────────────────────────────────────────────────
Creates 500 devices (10 groups of 50) for sa3421@srmist.edu.in
and fills power_usage_normalized with 30 days of hourly data.

Realistic pattern:
  - Weekday daytime (07-22h): higher baseline, noisy peaks
  - Weeknight / weekend:      lower baseline
  - Each device has its own random offset so they don't all look identical
  - ~5 % of readings deliberately missing per device (simulates outages)

Run once:
    pip install mysql-connector-python tqdm
    python seed_demo.py
"""

import random
import math
import time
import datetime
import mysql.connector
from tqdm import tqdm

# ── CONFIG ────────────────────────────────────────────────────
DB = dict(
    host     = "eiot.c7eqmkyyitqo.ap-south-1.rds.amazonaws.com",
    port     = 3306,
    database = "eiot",
    user     = "admin",
    password = "AyansDataBase",
    ssl_disabled = False,
    ssl_ca   = "C:/certs/global-bundle.pem",
)

OWNER        = "sa3421@srmist.edu.in"
N_DEVICES    = 500
N_GROUPS     = 10
DEVICES_PER_GROUP = N_DEVICES // N_GROUPS   # 50
DAYS         = 30
MISSING_RATE = 0.05     # fraction of hourly readings to skip per device
BATCH_SIZE   = 5_000    # rows per INSERT batch

# ── HELPERS ──────────────────────────────────────────────────

def is_weekday(dt: datetime.datetime) -> bool:
    return dt.weekday() < 5          # Mon-Fri

def hour_factor(dt: datetime.datetime) -> float:
    """
    Returns a multiplier 0.3 – 1.0 based on time-of-day.
    Peaks around 10:00 and 19:00, low overnight.
    """
    h = dt.hour
    # smooth double-hump curve
    morning = math.exp(-0.5 * ((h - 10) / 3) ** 2)
    evening = math.exp(-0.5 * ((h - 19) / 2.5) ** 2)
    base = max(morning, evening)
    return 0.3 + 0.7 * base

def device_power(dt: datetime.datetime, base: int, noise_seed: float) -> int:
    """Compute a noisy, time-aware power reading (Watts)."""
    h = hour_factor(dt)
    day_mult = 1.0 if is_weekday(dt) else 0.65
    random.seed(noise_seed + dt.timestamp())
    noise = random.gauss(0, 0.12)           # ±12 % Gaussian noise
    spike = 0
    if random.random() < 0.04:              # 4 % chance of a brief spike
        spike = random.uniform(0.2, 0.5)
    raw = base * h * day_mult * (1 + noise + spike)
    return max(5, int(raw))                 # floor at 5 W

# ── MAIN ─────────────────────────────────────────────────────

def main():
    t_start = time.perf_counter()
    conn = mysql.connector.connect(**DB)
    cur  = conn.cursor()

    print("Connected to RDS.")

    # ── 1. Create groups ──────────────────────────────────────
    print(f"Creating {N_GROUPS} groups …")
    for g in range(1, N_GROUPS + 1):
        cur.execute(
            "INSERT INTO device_groups (groupid, username, state) VALUES (%s, %s, 0) "
            "ON DUPLICATE KEY UPDATE username = username",
            (g, OWNER)
        )
    conn.commit()

    # ── 2. Create devices ─────────────────────────────────────
    print(f"Creating {N_DEVICES} devices …")
    for d in range(1, N_DEVICES + 1):
        gid = ((d - 1) // DEVICES_PER_GROUP) + 1
        cur.execute(
            "INSERT INTO devices (deviceid, username, groupid, state) VALUES (%s, %s, %s, 0) "
            "ON DUPLICATE KEY UPDATE groupid = %s",
            (d, OWNER, gid, gid)
        )
    conn.commit()

    # ── 3. Seed power_usage_normalized ───────────────────────
    # Each device gets a random base load between 50 W and 600 W
    random.seed(42)
    device_bases = {d: random.randint(50, 600) for d in range(1, N_DEVICES + 1)}
    device_seeds = {d: random.random() * 1e6   for d in range(1, N_DEVICES + 1)}

    now   = datetime.datetime.utcnow().replace(minute=0, second=0, microsecond=0)
    start = now - datetime.timedelta(days=DAYS)

    READING_HOURS = [8, 20]  # 08:00 AM and 08:00 PM — change freely

    readings_per_device = DAYS * len(READING_HOURS)
    print(f"Generating {N_DEVICES} × {readings_per_device} readings (~{N_DEVICES*readings_per_device:,} rows) …")

    # Build time list once — one slot per reading per day
    timestamps = [
        start.replace(hour=0, minute=0, second=0, microsecond=0)
        + datetime.timedelta(days=d, hours=h)
        for d in range(DAYS)
        for h in READING_HOURS
    ]

    rows_inserted = 0
    batch: list = []

    def flush(batch):
        if not batch:
            return 0
        cur.executemany(
            "INSERT INTO power_usage_normalized (time, deviceid, power) VALUES (%s, %s, %s)",
            batch
        )
        conn.commit()
        return len(batch)

    for d in tqdm(range(1, N_DEVICES + 1), desc="devices"):
        base  = device_bases[d]
        seed  = device_seeds[d]
        for ts in timestamps:
            # Simulate missing data
            if random.random() < MISSING_RATE:
                continue
            pwr = device_power(ts, base, seed)
            batch.append((ts.strftime("%Y-%m-%d %H:%M:%S"), d, pwr))
            if len(batch) >= BATCH_SIZE:
                rows_inserted += flush(batch)
                batch.clear()

    rows_inserted += flush(batch)

    cur.close()
    conn.close()

    elapsed = time.perf_counter() - t_start
    print(f"\n✅ Done in {elapsed:.1f}s")
    print(f"   Devices:  {N_DEVICES}")
    print(f"   Groups:   {N_GROUPS}")
    print(f"   Rows:     {rows_inserted:,}")


if __name__ == "__main__":
    main()