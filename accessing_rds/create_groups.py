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

    for group_id in range(1, 11):
        cursor.execute(
            """
            INSERT INTO device_groups (groupid, username, state)
            VALUES (%s, %s, %s)
            """,
            (group_id, username, False)
        )

    conn.commit()

    print("10 groups created successfully!")

    cursor.close()

except Exception as e:
    print("Database error:", e)

finally:
    if conn:
        conn.close()