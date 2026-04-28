import re
import time
import logging
import mysql.connector
from mysql.connector.pooling import MySQLConnectionPool
import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.pool import QueuePool
import datetime

# ─── LOGGING ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s.%(msecs)03d [%(levelname)s] %(funcName)s – %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("eiot")

# ─── CONFIG ───────────────────────────────────────────────────────────────────
pw = "AyansDataBase"

_DB_CONFIG = {
    "host":         "eiot.c7eqmkyyitqo.ap-south-1.rds.amazonaws.com",
    "port":         3306,
    "database":     "eiot",
    "user":         "admin",
    "password":     pw,
    "ssl_disabled": False,
    "ssl_ca":       "C:/certs/global-bundle.pem",
}

_POWER_HISTORY_LIMIT = 500
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9_]+$")

# ─── VALID ROLES ──────────────────────────────────────────────────────────────
ROLES = ("admin", "operator", "viewer")


# ─── CONNECTION POOLS ─────────────────────────────────────────────────────────
_connector_pool    = None
_sqlalchemy_engine = None


def _validate_column_name(name: str) -> str:
    name = str(name)
    if not _SAFE_ID_RE.match(name):
        raise ValueError(f"Invalid column name: {name!r}")
    return name


def _get_connector_pool():
    global _connector_pool
    if _connector_pool is None:
        t0 = time.perf_counter()
        _connector_pool = MySQLConnectionPool(
            pool_name="eiot_pool",
            pool_size=10,
            pool_reset_session=True,
            connect_timeout=5,
            **_DB_CONFIG,
        )
        log.info("mysql-connector pool created [%.0f ms]", (time.perf_counter() - t0) * 1000)
    return _connector_pool


def _get_engine():
    global _sqlalchemy_engine
    if _sqlalchemy_engine is None:
        t0 = time.perf_counter()
        url = (
            f"mysql+mysqlconnector://{_DB_CONFIG['user']}:{_DB_CONFIG['password']}"
            f"@{_DB_CONFIG['host']}:{_DB_CONFIG['port']}/{_DB_CONFIG['database']}"
        )
        _sqlalchemy_engine = create_engine(
            url,
            connect_args={"ssl_ca": _DB_CONFIG["ssl_ca"]},
            poolclass=QueuePool,
            pool_size=5,
            max_overflow=5,
            pool_pre_ping=True,
            pool_recycle=300,
        )
        log.info("SQLAlchemy engine created [%.0f ms]", (time.perf_counter() - t0) * 1000)
    return _sqlalchemy_engine


def get_connection():
    t0 = time.perf_counter()
    conn = _get_connector_pool().get_connection()
    elapsed = (time.perf_counter() - t0) * 1000
    if elapsed > 50:
        log.warning("get_connection SLOW %.0f ms", elapsed)
    else:
        log.debug("get_connection %.0f ms", elapsed)
    return conn


def _read_sql(query: str, params: dict | None = None) -> pd.DataFrame:
    t0 = time.perf_counter()
    with _get_engine().connect() as conn:
        df = pd.read_sql(text(query), conn, params=params)
    log.debug("_read_sql [%.0f ms] → %d rows", (time.perf_counter() - t0) * 1000, len(df))
    return df


# ─── AUTH + ROLES ─────────────────────────────────────────────────────────────

def authenticate_user(username: str, password: str) -> dict | None:
    """
    Returns dict {username, role} on success, None on failure.
    """
    t0 = time.perf_counter()
    conn = cursor = None
    try:
        conn = get_connection()
        cursor = conn.cursor(dictionary=True, buffered=True)
        cursor.execute(
            "SELECT password, role FROM users WHERE username = %s", (username,)
        )
        row = cursor.fetchone()
        if row and row["password"] == password:
            log.info("authenticate_user(%s) OK [%.0f ms]", username, (time.perf_counter() - t0) * 1000)
            return {"username": username, "role": row["role"]}
        log.info("authenticate_user(%s) FAIL [%.0f ms]", username, (time.perf_counter() - t0) * 1000)
        return None
    except Exception as e:
        log.error("authenticate_user error: %s", e)
        return None
    finally:
        if cursor: cursor.close()
        if conn:   conn.close()


def create_user(username: str, password: str, role: str = "viewer") -> bool:
    if role not in ROLES:
        raise ValueError(f"Invalid role: {role!r}")
    t0 = time.perf_counter()
    conn = cursor = None
    try:
        conn = get_connection()
        cursor = conn.cursor(buffered=True)
        cursor.execute(
            "INSERT INTO users (username, password, role) VALUES (%s, %s, %s)",
            (username, password, role)
        )
        conn.commit()
        log.info("create_user(%s, role=%s) OK [%.0f ms]", username, role, (time.perf_counter() - t0) * 1000)
        return True
    except mysql.connector.Error as e:
        if e.errno == 1062:
            log.warning("create_user(%s) already exists", username)
            return False
        log.error("create_user error: %s", e)
        return False
    finally:
        if cursor: cursor.close()
        if conn:   conn.close()


def update_user_role(username: str, new_role: str) -> bool:
    if new_role not in ROLES:
        raise ValueError(f"Invalid role: {new_role!r}")
    conn = cursor = None
    try:
        conn = get_connection()
        cursor = conn.cursor(buffered=True)
        cursor.execute("UPDATE users SET role = %s WHERE username = %s", (new_role, username))
        conn.commit()
        return cursor.rowcount > 0
    except Exception as e:
        log.error("update_user_role error: %s", e)
        return False
    finally:
        if cursor: cursor.close()
        if conn:   conn.close()


def delete_user(username: str) -> bool:
    conn = cursor = None
    try:
        conn = get_connection()
        cursor = conn.cursor(buffered=True)
        cursor.execute("DELETE FROM users WHERE username = %s", (username,))
        conn.commit()
        return cursor.rowcount > 0
    except Exception as e:
        log.error("delete_user error: %s", e)
        return False
    finally:
        if cursor: cursor.close()
        if conn:   conn.close()


def get_all_users() -> list[dict]:
    """Admin only: returns all users with their roles."""
    conn = cursor = None
    try:
        conn = get_connection()
        cursor = conn.cursor(dictionary=True, buffered=True)
        cursor.execute("SELECT username, role FROM users ORDER BY role, username")
        return cursor.fetchall()
    except Exception as e:
        log.error("get_all_users error: %s", e)
        return []
    finally:
        if cursor: cursor.close()
        if conn:   conn.close()


# ─── DEVICES ──────────────────────────────────────────────────────────────────

def get_devices(username: str, is_admin: bool = False):
    """
    Admin sees all devices across all users.
    Regular user sees only their own.
    Returns list of (deviceid, groupid, state, owner_username).
    """
    t0 = time.perf_counter()
    conn = cursor = None
    try:
        conn = get_connection()
        cursor = conn.cursor(buffered=True)
        if is_admin:
            cursor.execute(
                "SELECT deviceid, groupid, state, username FROM devices ORDER BY deviceid"
            )
        else:
            cursor.execute(
                "SELECT deviceid, groupid, state, username FROM devices WHERE username = %s",
                (username,)
            )
        devices = cursor.fetchall()
        log.info("get_devices(%s, admin=%s) → %d rows [%.0f ms]",
                 username, is_admin, len(devices), (time.perf_counter() - t0) * 1000)
        return devices
    except Exception as e:
        log.error("get_devices error: %s", e)
        return []
    finally:
        if cursor: cursor.close()
        if conn:   conn.close()


def create_device(username: str, deviceid: int, groupid=None) -> bool:
    t0 = time.perf_counter()
    conn = cursor = None
    try:
        conn = get_connection()
        cursor = conn.cursor(buffered=True)
        cursor.execute(
            "INSERT INTO devices (deviceid, username, groupid, state) VALUES (%s, %s, %s, 0)",
            (deviceid, username, groupid)
        )
        conn.commit()
        log.info("create_device(%s) OK [%.0f ms]", deviceid, (time.perf_counter() - t0) * 1000)
        return True
    except mysql.connector.Error as e:
        if e.errno == 1062:
            return False
        log.error("create_device error: %s", e)
        return False
    finally:
        if cursor: cursor.close()
        if conn:   conn.close()


def delete_device(username: str, deviceid: int) -> bool:
    t0 = time.perf_counter()
    conn = cursor = None
    try:
        conn = get_connection()
        cursor = conn.cursor(buffered=True)
        cursor.execute(
            "DELETE FROM devices WHERE username = %s AND deviceid = %s", (username, deviceid)
        )
        conn.commit()
        return True
    except Exception as e:
        log.error("delete_device error: %s", e)
        return False
    finally:
        if cursor: cursor.close()
        if conn:   conn.close()


# ─── GROUPS ───────────────────────────────────────────────────────────────────

def get_groups(username: str, is_admin: bool = False):
    t0 = time.perf_counter()
    conn = cursor = None
    try:
        conn = get_connection()
        cursor = conn.cursor(buffered=True)
        if is_admin:
            cursor.execute("SELECT groupid, state, username FROM device_groups ORDER BY groupid")
        else:
            cursor.execute(
                "SELECT groupid, state, username FROM device_groups WHERE username = %s",
                (username,)
            )
        return cursor.fetchall()
    except Exception as e:
        log.error("get_groups error: %s", e)
        return []
    finally:
        if cursor: cursor.close()
        if conn:   conn.close()


def create_group(username: str, groupid: int) -> bool:
    t0 = time.perf_counter()
    conn = cursor = None
    try:
        conn = get_connection()
        cursor = conn.cursor(buffered=True)
        cursor.execute(
            "INSERT INTO device_groups (groupid, username, state) VALUES (%s, %s, 0)",
            (groupid, username)
        )
        conn.commit()
        return True
    except mysql.connector.Error as e:
        if e.errno == 1062:
            return False
        log.error("create_group error: %s", e)
        return False
    finally:
        if cursor: cursor.close()
        if conn:   conn.close()


def delete_group(username: str, groupid: int) -> bool:
    conn = cursor = None
    try:
        conn = get_connection()
        cursor = conn.cursor(buffered=True)
        cursor.execute(
            "UPDATE devices SET groupid = NULL WHERE username = %s AND groupid = %s",
            (username, groupid)
        )
        cursor.execute(
            "DELETE FROM device_groups WHERE username = %s AND groupid = %s",
            (username, groupid)
        )
        conn.commit()
        return True
    except Exception as e:
        log.error("delete_group error: %s", e)
        if conn: conn.rollback()
        return False
    finally:
        if cursor: cursor.close()
        if conn:   conn.close()


def get_group_devices(username: str, groupid: int):
    conn = cursor = None
    try:
        conn = get_connection()
        cursor = conn.cursor(buffered=True)
        cursor.execute(
            "SELECT deviceid, state FROM devices WHERE username = %s AND groupid = %s",
            (username, groupid)
        )
        return cursor.fetchall()
    except Exception as e:
        log.error("get_group_devices error: %s", e)
        return []
    finally:
        if cursor: cursor.close()
        if conn:   conn.close()


# ─── STATE UPDATES ────────────────────────────────────────────────────────────

def update_device_state(username: str, deviceid: int, new_state: int) -> bool:
    conn = cursor = None
    try:
        conn = get_connection()
        cursor = conn.cursor(buffered=True)
        cursor.execute(
            "UPDATE devices SET state = %s WHERE username = %s AND deviceid = %s",
            (new_state, username, deviceid)
        )
        conn.commit()
        rows_affected = cursor.rowcount
        log.info("update_device_state(%s, %s, %s) → %d rows updated",
                 username, deviceid, new_state, rows_affected)
        return rows_affected > 0
    except Exception as e:
        log.error("update_device_state error: %s", e)
        return False
    finally:
        if cursor: cursor.close()
        if conn:   conn.close()


def update_group_state(username: str, groupid: int, new_state: bool) -> bool:
    conn = cursor = None
    try:
        conn = get_connection()
        cursor = conn.cursor(buffered=True)
        cursor.execute(
            "UPDATE device_groups SET state = %s WHERE username = %s AND groupid = %s",
            (int(new_state), username, groupid)
        )
        cursor.execute(
            "UPDATE devices SET state = %s WHERE username = %s AND groupid = %s",
            (int(new_state), username, groupid)
        )
        conn.commit()
        log.info("update_group_state(%s, %s, %s) → group and devices updated",
                 username, groupid, new_state)
        return True
    except Exception as e:
        log.error("update_group_state error: %s", e)
        return False
    finally:
        if cursor: cursor.close()
        if conn:   conn.close()


# ─── POWER USAGE (normalized table) ──────────────────────────────────────────

def _fmt_dt(dt: datetime.datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def get_device_power_usage(
    deviceid: int,
    start: datetime.datetime,
    end: datetime.datetime,
) -> pd.DataFrame:
    """
    Returns time-series for a single device within [start, end].
    Missing timestamps are NOT filled — caller handles gaps.
    """
    t0 = time.perf_counter()
    try:
        df = _read_sql(
            """
            SELECT time, power
            FROM power_usage_normalized
            WHERE deviceid = :did
              AND time BETWEEN :start AND :end
            ORDER BY time ASC
            """,
            params={"did": int(deviceid), "start": _fmt_dt(start), "end": _fmt_dt(end)},
        )
        log.info("get_device_power_usage(%s) → %d rows [%.0f ms]",
                 deviceid, len(df), (time.perf_counter() - t0) * 1000)
        return df
    except Exception as e:
        log.error("get_device_power_usage error: %s", e)
        return pd.DataFrame(columns=["time", "power"])


def get_group_power_usage(
    username: str,
    groupid: int,
    start: datetime.datetime,
    end: datetime.datetime,
    is_admin: bool = False,
) -> pd.DataFrame:
    """
    Returns a wide DataFrame: columns = [time, <deviceid1>, <deviceid2>, …]
    Missing readings appear as NaN (handled gracefully by plotly connectgaps=False).
    """
    t0 = time.perf_counter()
    conn = cursor = None
    try:
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        if is_admin:
            cursor.execute(
                "SELECT deviceid FROM devices WHERE groupid = %s", (groupid,)
            )
        else:
            cursor.execute(
                "SELECT deviceid FROM devices WHERE username = %s AND groupid = %s",
                (username, groupid)
            )
        device_ids = [str(row["deviceid"]) for row in cursor.fetchall()]
    finally:
        if cursor: cursor.close()
        if conn:   conn.close()

    if not device_ids:
        return pd.DataFrame()

    # Fetch long-format data then pivot
    id_list = ",".join(device_ids)
    df_long = _read_sql(
        f"""
        SELECT time, deviceid, power
        FROM power_usage_normalized
        WHERE deviceid IN ({id_list})
          AND time BETWEEN :start AND :end
        ORDER BY time ASC
        """,
        params={"start": _fmt_dt(start), "end": _fmt_dt(end)},
    )

    if df_long.empty:
        return pd.DataFrame()

    # Pivot: rows = timestamps, columns = deviceid
    df_wide = df_long.pivot_table(
        index="time", columns="deviceid", values="power", aggfunc="mean"
    ).reset_index()
    df_wide.columns.name = None
    df_wide.columns = ["time"] + [str(c) for c in df_wide.columns[1:]]

    log.info("get_group_power_usage(%s, %s) → %d rows × %d devices [%.0f ms]",
             username, groupid, len(df_wide), len(df_wide.columns) - 1,
             (time.perf_counter() - t0) * 1000)
    return df_wide


def get_latest_power_usage() -> dict:
    """Returns most recent power reading per device (not global max time)."""
    t0 = time.perf_counter()
    try:
        df = _read_sql(
            """
            SELECT p.deviceid, p.power
            FROM power_usage_normalized p
            INNER JOIN (
                SELECT deviceid, MAX(time) AS max_time
                FROM power_usage_normalized
                GROUP BY deviceid
            ) latest ON p.deviceid = latest.deviceid AND p.time = latest.max_time
            """
        )
        result = {str(row["deviceid"]): row["power"] for _, row in df.iterrows()}
        log.info("get_latest_power_usage() → %d devices [%.0f ms]",
                 len(result), (time.perf_counter() - t0) * 1000)
        return result
    except Exception as e:
        log.error("get_latest_power_usage error: %s", e)
        return {}


# ─── LEGACY FALLBACK ──────────────────────────────────────────────────────────

def get_power_usage():
    """Legacy wide-table fallback — fetches entire table."""
    log.warning("get_power_usage() called — fetches ENTIRE legacy table!")
    return _read_sql("SELECT * FROM power_usage ORDER BY time")



# ─── SCHEDULES ────────────────────────────────────────────────────────────────
# Add these functions to the bottom of your existing utils.py

import datetime as _dt

WEEKDAY_NAMES = ["Monday","Tuesday","Wednesday","Thursday","Friday","Saturday","Sunday"]


def get_schedules(created_by: str | None = None) -> list[dict]:
    """
    Admin: pass created_by=None to get all schedules.
    Regular user: pass their username.
    """
    conn = cursor = None
    try:
        conn = get_connection()
        cursor = conn.cursor(dictionary=True, buffered=True)
        if created_by is None:
            cursor.execute(
                """
                SELECT id, created_by, target_type, target_id,
                       action, mode, run_at, run_date, weekday, active, last_fired
                FROM schedules ORDER BY active DESC, id DESC
                """
            )
        else:
            cursor.execute(
                """
                SELECT id, created_by, target_type, target_id,
                       action, mode, run_at, run_date, weekday, active, last_fired
                FROM schedules
                WHERE created_by = %s
                ORDER BY active DESC, id DESC
                """,
                (created_by,)
            )
        return cursor.fetchall()
    except Exception as e:
        log.error("get_schedules error: %s", e)
        return []
    finally:
        if cursor: cursor.close()
        if conn:   conn.close()


def create_schedule(
    created_by:  str,
    target_type: str,           # 'device' or 'group'
    target_id:   int,
    action:      str,           # 'on' or 'off'
    mode:        str,           # 'once' | 'daily' | 'weekly'
    run_at:      _dt.time,      # IST time
    run_date:    _dt.date | None = None,   # required for mode='once'
    weekday:     int  | None = None,       # 0-6, required for mode='weekly'
) -> bool:
    conn = cursor = None
    try:
        conn = get_connection()
        cursor = conn.cursor(buffered=True)
        cursor.execute(
            """
            INSERT INTO schedules
                (created_by, target_type, target_id, action,
                 mode, run_at, run_date, weekday, active)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 1)
            """,
            (created_by, target_type, int(target_id),
             action, mode,
             run_at.strftime("%H:%M:%S"),
             run_date, weekday)
        )
        conn.commit()
        log.info("create_schedule OK → id=%s", cursor.lastrowid)
        return True
    except Exception as e:
        log.error("create_schedule error: %s", e)
        return False
    finally:
        if cursor: cursor.close()
        if conn:   conn.close()


def toggle_schedule(schedule_id: int, active: bool) -> bool:
    conn = cursor = None
    try:
        conn = get_connection()
        cursor = conn.cursor(buffered=True)
        cursor.execute(
            "UPDATE schedules SET active = %s WHERE id = %s",
            (int(active), schedule_id)
        )
        conn.commit()
        return cursor.rowcount > 0
    except Exception as e:
        log.error("toggle_schedule error: %s", e)
        return False
    finally:
        if cursor: cursor.close()
        if conn:   conn.close()


def delete_schedule(schedule_id: int) -> bool:
    conn = cursor = None
    try:
        conn = get_connection()
        cursor = conn.cursor(buffered=True)
        cursor.execute("DELETE FROM schedules WHERE id = %s", (schedule_id,))
        conn.commit()
        return cursor.rowcount > 0
    except Exception as e:
        log.error("delete_schedule error: %s", e)
        return False
    finally:
        if cursor: cursor.close()
        if conn:   conn.close()