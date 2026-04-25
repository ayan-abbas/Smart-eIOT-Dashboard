import re
import mysql.connector
from mysql.connector.pooling import MySQLConnectionPool
import pandas as pd

pw = "AyansDataBase"

_DB_CONFIG = {
    "host": "eiot.cu5iw2g8er81.us-east-1.rds.amazonaws.com",
    "port": 3306,
    "database": "eiot",
    "user": "admin",
    "password": pw,
    "ssl_disabled": False,
    "ssl_ca": "C:/certs/global-bundle.pem",
}

_pool = None


def _get_pool():
    global _pool
    if _pool is None:
        _pool = MySQLConnectionPool(
            pool_name="eiot_pool",
            pool_size=10,
            pool_reset_session=True,
            **_DB_CONFIG,
        )
    return _pool


_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9_]+$")


def _validate_column_name(name: str) -> str:
    """Validate that a column name is safe for inclusion in SQL."""
    name = str(name)
    if not _SAFE_ID_RE.match(name):
        raise ValueError(f"Invalid column name: {name!r}")
    return name


def get_connection():
    return _get_pool().get_connection()


def authenticate_user(username, password) -> bool:
    conn = None
    cursor = None
    try:
        conn = get_connection()
        cursor = conn.cursor(buffered=True)
        cursor.execute(
            "SELECT password FROM users WHERE username = %s",
            (username,)
        )

        result = cursor.fetchone()

        if result is None:
            print("Username not found.")
            return False

        if result[0] == password:
            print("Login successful!")
            return True
        else:
            print("Incorrect password.")
            return False

    except Exception as e:
        print(f"Database error: {e}")
        return False

    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


def create_user(username, password) -> bool:
    conn = None
    cursor = None
    try:
        conn = get_connection()
        cursor = conn.cursor(buffered=True)

        cursor.execute(
            """
            INSERT INTO users (username, password)
            VALUES (%s, %s)
            """,
            (username, password)
        )

        conn.commit()

        print("User created successfully!")
        return True

    except mysql.connector.Error as e:
        if e.errno == 1062:
            print("User already exists.")
            return False
        else:
            print(f"Database error: {e}")
            return False

    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


def get_devices(username):
    conn = None
    cursor = None
    try:
        conn = get_connection()
        cursor = conn.cursor(buffered=True)

        cursor.execute(
            """
            SELECT deviceid, groupid, state FROM devices
            where username = %s;
            """,
            (username,)
        )

        devices = cursor.fetchall()
        return devices

    except Exception as e:
        print(f"Database error: {e}")
        return []

    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


def create_device(username, deviceid, groupid = None) -> bool:
    conn = None
    cursor = None
    try:
        conn = get_connection()
        cursor = conn.cursor(buffered=True)

        cursor.execute(
            """
            INSERT INTO devices (deviceid, username, groupid, state)
            VALUES (%s, %s, %s, %s)
            """,
            (deviceid, username, groupid, False)
        )

        conn.commit()

        print("Device created successfully!")
        return True

    except mysql.connector.Error as e:
        if e.errno == 1062:
            print("Device already exists.")
            return False
        else:
            print(f"Database error: {e}")
            return False

    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


def delete_device(username, deviceid) -> bool:
    conn = None
    cursor = None
    try:
        conn = get_connection()
        cursor = conn.cursor(buffered=True)

        cursor.execute(
            """
            DELETE FROM devices
            WHERE username = %s AND deviceid = %s;
            """,
            (username, deviceid)
        )

        conn.commit()

        print("Device deleted successfully!")
        return True

    except Exception as e:
        print(f"Database error: {e}")
        return False

    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


def get_groups(username):
    conn = None
    cursor = None
    try:
        conn = get_connection()
        cursor = conn.cursor(buffered=True)

        cursor.execute(
            """
            SELECT groupid, state FROM device_groups
            where username = %s;
            """,
            (username,)
        )

        groups = cursor.fetchall()
        return groups

    except Exception as e:
        print(f"Database error: {e}")
        return []

    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


def create_group(username, groupid) -> bool:
    conn = None
    cursor = None
    try:
        conn = get_connection()
        cursor = conn.cursor(buffered=True)

        cursor.execute(
            """
            INSERT INTO device_groups (groupid, username, state)
            VALUES (%s, %s, %s)
            """,
            (groupid, username, False)
        )

        conn.commit()

        print("Group created successfully!")
        return True

    except mysql.connector.Error as e:
        if e.errno == 1062:
            print("Group already exists.")
            return False
        else:
            print(f"Database error: {e}")
            return False

    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


def delete_group(username, groupid) -> bool:
    conn = None
    cursor = None
    try:
        conn = get_connection()
        cursor = conn.cursor(buffered=True)

        # 1️⃣ Unassign devices from group
        cursor.execute(
            """
            UPDATE devices
            SET groupid = NULL
            WHERE username = %s AND groupid = %s;
            """,
            (username, groupid)
        )

        print("Devices unassigned from group successfully!")

        # Delete the group
        cursor.execute(
            """
            DELETE FROM device_groups
            WHERE username = %s AND groupid = %s;
            """,
            (username, groupid)
        )

        print("Group deleted successfully!")

        # Commit once
        conn.commit()

        return True

    except Exception as e:
        print(f"Database error: {e}")
        if conn:
            conn.rollback()
        return False

    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


def get_group_devices(username, groupid):
    conn = None
    cursor = None
    try:
        conn = get_connection()
        cursor = conn.cursor(buffered=True)

        cursor.execute(
            """
            SELECT deviceid, state FROM devices
            where username = %s and groupid = %s;
            """,
            (username, groupid)
        )

        devices = cursor.fetchall()
        return devices

    except Exception as e:
        print(f"Database error: {e}")
        return []

    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


def update_device_state(username, deviceid, new_state):
    conn = None
    cursor = None
    try:
        conn = get_connection()
        cursor = conn.cursor(buffered=True)

        cursor.execute(
            """
            UPDATE devices
            SET state = %s
            WHERE username = %s AND deviceid = %s;
            """,
            (new_state, username, deviceid)
        )

        conn.commit()

        print("Device state updated successfully!")
        return True

    except Exception as e:
        print(f"Database error: {e}")
        return False

    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


def update_group_state(username, groupid, new_state):
    conn = None
    cursor = None
    try:
        conn = get_connection()
        cursor = conn.cursor(buffered=True)

        cursor.execute(
            """
            UPDATE device_groups
            SET state = %s
            WHERE username = %s AND groupid = %s;
            """,
            (new_state, username, groupid)
        )

        conn.commit()

        print("Group state updated successfully!")

        cursor.execute(
            """
            UPDATE devices
            SET state = %s
            WHERE username = %s AND groupid = %s;
            """,
            (new_state, username, groupid)
        )

        conn.commit()

        print("All devices in group updated successfully!")
        return True

    except Exception as e:
        print(f"Database error: {e}")
        return False

    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


def get_power_usage():
    conn = get_connection()

    query = """
        SELECT * FROM power_usage
        ORDER BY time
    """

    df = pd.read_sql(query, conn)

    conn.close()

    return df


def get_device_power_usage(deviceid):
    """
    Returns time series power usage for a single device.
    """

    conn = None

    try:
        safe_col = _validate_column_name(deviceid)
        conn = get_connection()

        query = f"""
            SELECT time, `{safe_col}`
            FROM power_usage
            ORDER BY time
        """

        df = pd.read_sql(query, conn)

        # rename device column to 'power'
        df = df.rename(columns={str(deviceid): "power"})

        return df

    except Exception as e:
        print(f"Database error: {e}")
        return pd.DataFrame()

    finally:
        if conn:
            conn.close()


def get_group_power_usage(username, groupid):
    conn = None
    cursor = None

    try:
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)

        # Get device IDs in the group
        cursor.execute("""
            SELECT deviceid
            FROM devices
            WHERE username = %s AND groupid = %s
        """, (username, groupid))

        devices = [str(row["deviceid"]) for row in cursor.fetchall()]

        if not devices:
            return pd.DataFrame()

        # Build column selection (validated to prevent injection)
        device_columns = ", ".join([f"`{_validate_column_name(d)}`" for d in devices])

        query = f"""
            SELECT time, {device_columns}
            FROM power_usage
            ORDER BY time
        """

        # Load into DataFrame
        df = pd.read_sql(query, conn)

        return df

    except Exception as e:
        print(f"Database error: {e}")
        return pd.DataFrame()

    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


def get_myPowerUsage():
    conn = get_connection()

    query = """
        SELECT * FROM myPowerUsage
        WHERE time >= DATE_SUB(NOW(), INTERVAL 1 HOUR)
        ORDER BY TIME;
    """

    df = pd.read_sql(query, conn)
    conn.close()
    return df


def get_latest_power_usage():
    """
    Returns the latest power usage row from the power_usage table.
    Each device is stored as a column.
    """

    conn = None
    cursor = None

    try:
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)

        cursor.execute("""
            SELECT *
            FROM power_usage
            ORDER BY time DESC
            LIMIT 1;
        """)

        row = cursor.fetchone()

        return row if row else {}

    except Exception as e:
        print(f"Database error: {e}")
        return {}

    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


if __name__ == "__main__":
    
    # print("\n--- CREATE USER TEST ---")
    # print(create_user("localtest", "1234"))

    # print("\n--- LOGIN SUCCESS TEST ---")
    # print(authenticate_user("sa3421@srmist.edu.in", "password"))

    # print("\n--- LOGIN WRONG PASSWORD ---")
    # print(authenticate_user("localtest", "wrongpass"))

    # print("\n--- LOGIN USER NOT FOUND ---")
    # print(authenticate_user("nouser", "1234"))

    print("\n--- GET DEVICES ---")
    print(get_devices("sa3421@srmist.edu.in"))

    # print("\n--- CREATE DEVICE ---")
    # print(create_device("sa3421@srmist.edu.in", 501, 1))

    # print("\n--- DELETE DEVICE ---")
    # print(delete_device("sa3421@srmist.edu.in", 501))

    # print("\n--- GET GROUPS ---")
    # print(get_groups("sa3421@srmist.edu.in"))

    # print("\n--- CREATE GROUP ---")
    # print(create_group("sa3421@srmist.edu.in", 11))

    # print("\n--- DELETE GROUP ---")
    # print(delete_group("sa3421@srmist.edu.in", 11))

    # print("\n--- GET GROUP DEVICES ---")
    # print(get_group_devices("sa3421@srmist.edu.in", 1))

    # print("\n--- UPDATE DEVICE STATE ---")
    # print(update_device_state("sa3421@srmist.edu.in", 1, True))

    # print("\n--- UPDATE GROUP STATE ---")
    # print(update_group_state("sa3421@srmist.edu.in", 1, True))

    # print("\n--- GET GROUP DEVICES AFTER UPDATE ---")
    # print(get_group_devices("sa3421@srmist.edu.in", 1))

    # print("\n--- GET POWER USAGE ---")
    # print(get_power_usage())

    # print("\n--- GET GROUP POWER USAGE ---")
    # print(get_group_power_usage("sa3421@srmist.edu.in", 1))

    # print("\n--- GET MY POWER USAGE ---")
    # print(get_myPowerUsage())

    # print("\n--- GET LATEST POWER USAGE ---")
    # print(get_latest_power_usage())