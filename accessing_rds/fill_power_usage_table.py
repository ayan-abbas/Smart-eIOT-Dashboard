import mysql.connector
import numpy as np
from datetime import datetime, timedelta

pw = "AyansDataBase"

conn = mysql.connector.connect(
    host='eiot.cu5iw2g8er81.us-east-1.rds.amazonaws.com',
    port=3306,
    database='eiot',
    user='admin',
    password=pw,
    ssl_disabled=False,
    ssl_ca='/certs/global-bundle.pem'
)

cursor = conn.cursor()

# -------------------------------
# Date generation
# -------------------------------

today = datetime.now().date()
yesterday = today - timedelta(days=1)

dates = [
    datetime.combine(
        yesterday - timedelta(days=i),
        datetime.strptime("23:59", "%H:%M").time()
    )
    for i in range(29, -1, -1)
]

# -------------------------------
# Group means
# -------------------------------

weekday_means = [80 + 40*i for i in range(10)]

weekend_means = np.linspace(1600, 2400, 10)

# -------------------------------
# Generate rows
# -------------------------------

rows = []

for dt in dates:

    is_weekend = dt.weekday() >= 5

    device_values = []

    for g in range(10):

        if is_weekend:
            mean = weekend_means[g]
            values = np.random.normal(mean, 120, 50)
            values = np.clip(values, 1500, 2500)
        else:
            mean = weekday_means[g]
            values = np.random.normal(mean, 25, 50)
            values = np.clip(values, 0, 500)

        device_values.extend([int(v) for v in values])

    row = [dt] + device_values
    rows.append(row)

# -------------------------------
# SQL insert
# -------------------------------

columns = ["time"] + [f"`{i}`" for i in range(1,501)]

placeholders = ",".join(["%s"] * 501)

query = f"""
INSERT INTO power_usage ({",".join(columns)})
VALUES ({placeholders})
"""

cursor.executemany(query, rows)

conn.commit()

print("Inserted", len(rows), "rows successfully")

cursor.close()
conn.close()