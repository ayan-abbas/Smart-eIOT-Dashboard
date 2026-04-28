import mysql.connector
import json

MUMBAI_HOST = "eiot.c7eqmkyyitqo.ap-south-1.rds.amazonaws.com"  

conn = mysql.connector.connect(
    host=MUMBAI_HOST,
    port=3306,
    user='admin',
    password='AyansDataBase',
)

cursor = conn.cursor()
cursor.execute("CREATE DATABASE IF NOT EXISTS eiot")
cursor.execute("USE eiot")

with open("eiot_dump.json", "r") as f:
    dump = json.load(f)

# Only process power_usage table
table = "power_usage"
if table in dump:
    data = dump[table]
    columns = data["columns"]
    rows = data["rows"]

    if not rows:
        print(f"  {table}: no rows, skipping")
    else:
        placeholders = ", ".join(["%s"] * len(columns))
        col_names = ", ".join([f"`{c}`" for c in columns])
        sql = f"INSERT IGNORE INTO `{table}` ({col_names}) VALUES ({placeholders})"

        inserted = 0
        for row in rows:
            try:
                cursor.execute(sql, row)
                inserted += 1
            except Exception as e:
                print(f"  Warning on {table} row {row}: {e}")

        conn.commit()
        print(f"  {table}: {inserted}/{len(rows)} rows inserted")
else:
    print(f"  {table}: table not found in dump")

print("Restore complete.")

cursor.close()
conn.close()