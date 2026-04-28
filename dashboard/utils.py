import re
import time
import logging
import mysql.connector
from mysql.connector.pooling import MySQLConnectionPool
import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.pool import QueuePool

# ─── LOGGING SETUP ────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s.%(msecs)03d [%(levelname)s] %(funcName)s – %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("eiot")

# ─── CONFIG ───────────────────────────────────────────────────────────────────

pw = "AyansDataBase"

_DB_CONFIG = {
    "host": "eiot.c7eqmkyyitqo.ap-south-1.rds.amazonaws.com",
    "port": 3306,
    "database": "eiot",
    "user": "admin",
    "password": pw,
    "ssl_disabled": False,
    "ssl_ca": "C:/certs/global-bundle.pem",
}

_POWER_HISTORY_LIMIT = 500
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9_]+$")

# ─── CONNECTION POOLS ─────────────────────────────────────────────────────────
# Two pools with different purposes:
#   _connector_pool  → DML (INSERT/UPDATE/DELETE) via mysql-connector cursors
#   _sqlalchemy_engine → SELECT via pd.read_sql (eliminates DBAPI2 warning + faster)

_connector_pool = None
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
    """SQLAlchemy engine used exclusively for pd.read_sql SELECT queries."""
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
            pool_pre_ping=True,   # avoids stale-connection penalty
            pool_recycle=300,
        )
        log.info("SQLAlchemy engine created [%.0f ms]", (time.perf_counter() - t0) * 1000)
    return _sqlalchemy_engine


def get_connection():
    """Raw mysql-connector connection from pool (for DML only)."""
    t0 = time.perf_counter()
    conn = _get_connector_pool().get_connection()
    elapsed = (time.perf_counter() - t0) * 1000
    if elapsed > 50:
        log.warning("get_connection SLOW %.0f ms", elapsed)
    else:
        log.debug("get_connection %.0f ms", elapsed)
    return conn


def _read_sql(query: str) -> pd.DataFrame:
    """
    Wrapper for pd.read_sql using SQLAlchemy engine.
    Eliminates the pandas DBAPI2 UserWarning and ~200ms overhead from raw connectors.
    """
    t0 = time.perf_counter()
    with _get_engine().connect() as conn:
        df = pd.read_sql(text(query), conn)
    log.debug("_read_sql [%.0f ms] → %d rows", (time.perf_counter() - t0) * 1000, len(df))
    return df


# ─── AUTH ─────────────────────────────────────────────────────────────────────

def authenticate_user(username, password) -> bool:
    t0 = time.perf_counter()
    conn = cursor = None
    try:
        conn = get_connection()
        cursor = conn.cursor(buffered=True)
        cursor.execute("SELECT password FROM users WHERE username = %s", (username,))
        result = cursor.fetchone()
        ok = result is not None and result[0] == password
        log.info("authenticate_user(%s) → %s  [%.0f ms]", username, ok, (time.perf_counter() - t0) * 1000)
        return ok
    except Exception as e:
        log.error("authenticate_user error: %s", e)
        return False
    finally:
        if cursor: cursor.close()
        if conn:   conn.close()


def create_user(username, password) -> bool:
    t0 = time.perf_counter()
    conn = cursor = None
    try:
        conn = get_connection()
        cursor = conn.cursor(buffered=True)
        cursor.execute("INSERT INTO users (username, password) VALUES (%s, %s)", (username, password))
        conn.commit()
        log.info("create_user(%s) OK [%.0f ms]", username, (time.perf_counter() - t0) * 1000)
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


# ─── DEVICES ──────────────────────────────────────────────────────────────────

def get_devices(username):
    t0 = time.perf_counter()
    conn = cursor = None
    try:
        conn = get_connection()
        cursor = conn.cursor(buffered=True)
        cursor.execute("SELECT deviceid, groupid, state FROM devices WHERE username = %s", (username,))
        devices = cursor.fetchall()
        log.info("get_devices(%s) → %d rows [%.0f ms]", username, len(devices), (time.perf_counter() - t0) * 1000)
        return devices
    except Exception as e:
        log.error("get_devices error: %s", e)
        return []
    finally:
        if cursor: cursor.close()
        if conn:   conn.close()


def create_device(username, deviceid, groupid=None) -> bool:
    t0 = time.perf_counter()
    conn = cursor = None
    try:
        conn = get_connection()
        cursor = conn.cursor(buffered=True)
        cursor.execute(
            "INSERT INTO devices (deviceid, username, groupid, state) VALUES (%s, %s, %s, %s)",
            (deviceid, username, groupid, False)
        )
        conn.commit()
        log.info("create_device(%s, %s) OK [%.0f ms]", username, deviceid, (time.perf_counter() - t0) * 1000)
        return True
    except mysql.connector.Error as e:
        if e.errno == 1062:
            log.warning("create_device(%s) already exists", deviceid)
            return False
        log.error("create_device error: %s", e)
        return False
    finally:
        if cursor: cursor.close()
        if conn:   conn.close()


def delete_device(username, deviceid) -> bool:
    t0 = time.perf_counter()
    conn = cursor = None
    try:
        conn = get_connection()
        cursor = conn.cursor(buffered=True)
        cursor.execute("DELETE FROM devices WHERE username = %s AND deviceid = %s", (username, deviceid))
        conn.commit()
        log.info("delete_device(%s, %s) OK [%.0f ms]", username, deviceid, (time.perf_counter() - t0) * 1000)
        return True
    except Exception as e:
        log.error("delete_device error: %s", e)
        return False
    finally:
        if cursor: cursor.close()
        if conn:   conn.close()


# ─── GROUPS ───────────────────────────────────────────────────────────────────

def get_groups(username):
    t0 = time.perf_counter()
    conn = cursor = None
    try:
        conn = get_connection()
        cursor = conn.cursor(buffered=True)
        cursor.execute("SELECT groupid, state FROM device_groups WHERE username = %s", (username,))
        groups = cursor.fetchall()
        log.info("get_groups(%s) → %d rows [%.0f ms]", username, len(groups), (time.perf_counter() - t0) * 1000)
        return groups
    except Exception as e:
        log.error("get_groups error: %s", e)
        return []
    finally:
        if cursor: cursor.close()
        if conn:   conn.close()


def create_group(username, groupid) -> bool:
    t0 = time.perf_counter()
    conn = cursor = None
    try:
        conn = get_connection()
        cursor = conn.cursor(buffered=True)
        cursor.execute(
            "INSERT INTO device_groups (groupid, username, state) VALUES (%s, %s, %s)",
            (groupid, username, False)
        )
        conn.commit()
        log.info("create_group(%s, %s) OK [%.0f ms]", username, groupid, (time.perf_counter() - t0) * 1000)
        return True
    except mysql.connector.Error as e:
        if e.errno == 1062:
            log.warning("create_group(%s) already exists", groupid)
            return False
        log.error("create_group error: %s", e)
        return False
    finally:
        if cursor: cursor.close()
        if conn:   conn.close()


def delete_group(username, groupid) -> bool:
    t0 = time.perf_counter()
    conn = cursor = None
    try:
        conn = get_connection()
        cursor = conn.cursor(buffered=True)
        cursor.execute("UPDATE devices SET groupid = NULL WHERE username = %s AND groupid = %s", (username, groupid))
        cursor.execute("DELETE FROM device_groups WHERE username = %s AND groupid = %s", (username, groupid))
        conn.commit()
        log.info("delete_group(%s, %s) OK [%.0f ms]", username, groupid, (time.perf_counter() - t0) * 1000)
        return True
    except Exception as e:
        log.error("delete_group error: %s", e)
        if conn: conn.rollback()
        return False
    finally:
        if cursor: cursor.close()
        if conn:   conn.close()


def get_group_devices(username, groupid):
    t0 = time.perf_counter()
    conn = cursor = None
    try:
        conn = get_connection()
        cursor = conn.cursor(buffered=True)
        cursor.execute("SELECT deviceid, state FROM devices WHERE username = %s AND groupid = %s", (username, groupid))
        devices = cursor.fetchall()
        log.info("get_group_devices(%s, %s) → %d rows [%.0f ms]", username, groupid, len(devices), (time.perf_counter() - t0) * 1000)
        return devices
    except Exception as e:
        log.error("get_group_devices error: %s", e)
        return []
    finally:
        if cursor: cursor.close()
        if conn:   conn.close()


# ─── STATE UPDATES ────────────────────────────────────────────────────────────

def update_device_state(username, deviceid, new_state):
    t0 = time.perf_counter()
    conn = cursor = None
    try:
        conn = get_connection()
        cursor = conn.cursor(buffered=True)
        cursor.execute(
            "UPDATE devices SET state = %s WHERE username = %s AND deviceid = %s",
            (new_state, username, deviceid)
        )
        conn.commit()
        log.info("update_device_state(%s, %s, %s) OK [%.0f ms]", username, deviceid, new_state, (time.perf_counter() - t0) * 1000)
        return True
    except Exception as e:
        log.error("update_device_state error: %s", e)
        return False
    finally:
        if cursor: cursor.close()
        if conn:   conn.close()


def update_group_state(username, groupid, new_state):
    t0 = time.perf_counter()
    conn = cursor = None
    try:
        conn = get_connection()
        cursor = conn.cursor(buffered=True)
        cursor.execute(
            "UPDATE device_groups SET state = %s WHERE username = %s AND groupid = %s",
            (new_state, username, groupid)
        )
        cursor.execute(
            "UPDATE devices SET state = %s WHERE username = %s AND groupid = %s",
            (new_state, username, groupid)
        )
        conn.commit()
        log.info("update_group_state(%s, %s, %s) OK [%.0f ms]", username, groupid, new_state, (time.perf_counter() - t0) * 1000)
        return True
    except Exception as e:
        log.error("update_group_state error: %s", e)
        return False
    finally:
        if cursor: cursor.close()
        if conn:   conn.close()


# ─── POWER USAGE ──────────────────────────────────────────────────────────────

def get_device_power_usage(deviceid):
    """Time-series for a single device — last _POWER_HISTORY_LIMIT rows."""
    t0 = time.perf_counter()
    try:
        safe_col = _validate_column_name(deviceid)
        df = _read_sql(f"""
            SELECT time, `{safe_col}`
            FROM (
                SELECT time, `{safe_col}`
                FROM power_usage
                ORDER BY time DESC
                LIMIT {_POWER_HISTORY_LIMIT}
            ) sub
            ORDER BY time ASC
        """)
        df = df.rename(columns={str(deviceid): "power"})
        log.info("get_device_power_usage(%s) → %d rows [%.0f ms]", deviceid, len(df), (time.perf_counter() - t0) * 1000)
        return df
    except Exception as e:
        log.error("get_device_power_usage error: %s", e)
        return pd.DataFrame()


def get_group_power_usage(username, groupid):
    """Time-series for all devices in a group — last _POWER_HISTORY_LIMIT rows."""
    t0 = time.perf_counter()
    conn = cursor = None
    try:
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            "SELECT deviceid FROM devices WHERE username = %s AND groupid = %s",
            (username, groupid)
        )
        devices = [str(row["deviceid"]) for row in cursor.fetchall()]
        log.debug("get_group_power_usage: %d devices in group %s", len(devices), groupid)

        if not devices:
            return pd.DataFrame()

        device_columns = ", ".join([f"`{_validate_column_name(d)}`" for d in devices])

        df = _read_sql(f"""
            SELECT time, {device_columns}
            FROM (
                SELECT time, {device_columns}
                FROM power_usage
                ORDER BY time DESC
                LIMIT {_POWER_HISTORY_LIMIT}
            ) sub
            ORDER BY time ASC
        """)
        log.info("get_group_power_usage(%s, %s) → %d rows × %d cols [%.0f ms]",
                 username, groupid, len(df), len(df.columns), (time.perf_counter() - t0) * 1000)
        return df
    except Exception as e:
        log.error("get_group_power_usage error: %s", e)
        return pd.DataFrame()
    finally:
        if cursor: cursor.close()
        if conn:   conn.close()


def get_latest_power_usage():
    """Returns dict {deviceid_str: power_value} from the most recent row."""
    t0 = time.perf_counter()
    conn = cursor = None
    try:
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM power_usage ORDER BY time DESC LIMIT 1")
        row = cursor.fetchone()
        if not row:
            return {}
        row.pop("time", None)
        log.info("get_latest_power_usage() → %d device values [%.0f ms]",
                 len(row), (time.perf_counter() - t0) * 1000)
        return row
    except Exception as e:
        log.error("get_latest_power_usage error: %s", e)
        return {}
    finally:
        if cursor: cursor.close()
        if conn:   conn.close()


# ─── LEGACY ───────────────────────────────────────────────────────────────────

def get_power_usage():
    log.warning("get_power_usage() called — fetches ENTIRE table!")
    return _read_sql("SELECT * FROM power_usage ORDER BY time")


def get_myPowerUsage():
    t0 = time.perf_counter()
    df = _read_sql("""
        SELECT * FROM myPowerUsage
        WHERE time >= DATE_SUB(NOW(), INTERVAL 1 HOUR)
        ORDER BY time
    """)
    log.info("get_myPowerUsage() → %d rows [%.0f ms]", len(df), (time.perf_counter() - t0) * 1000)
    return df


if __name__ == "__main__":
    print("\n--- GET DEVICES ---")
    print(get_devices("sa3421@srmist.edu.in"))