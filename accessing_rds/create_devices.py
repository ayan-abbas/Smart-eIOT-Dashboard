import mysql.connector

conn = None

try:
    conn = mysql.connector.connect(
        host="eiot.cu5iw2g8er81.us-east-1.rds.amazonaws.com",
        port=3306,
        user="admin",
        password="AyansDataBase",
        database="eiot"
    )

    cursor = conn.cursor()

    username = "sa3421@srmist.edu.in"

    data = []

    for device_id in range(1, 501):
        group_id = ((device_id - 1) // 50) + 1
        data.append((device_id, username, group_id, False))

    query = """
    INSERT INTO devices (deviceid, username, groupid, state)
    VALUES (%s, %s, %s, %s)
    """

    cursor.executemany(query, data)

    conn.commit()

    print("500 devices inserted successfully!")

    cursor.close()

except Exception as e:
    print("Database error:", e)

finally:
    if conn:
        conn.close()