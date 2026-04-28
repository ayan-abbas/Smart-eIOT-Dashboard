import mysql.connector
import json

conn = mysql.connector.connect(
    host='eiot.cu5iw2g8er81.us-east-1.rds.amazonaws.com',
    port=3306,
    database='eiot',
    user='admin',
    password='AyansDataBase',
    ssl_disabled=False,
    ssl_ca='/certs/global-bundle.pem'
)

cursor = conn.cursor()

cursor.execute("SHOW TABLES")
tables = [row[0] for row in cursor.fetchall()]
print(f"Found tables: {tables}")

dump = {}

for table in tables:
    cursor.execute(f"SELECT * FROM `{table}`")
    rows = cursor.fetchall()
    columns = [desc[0] for desc in cursor.description]
    dump[table] = {
        "columns": columns,
        "rows": [list(row) for row in rows]
    }
    print(f"  {table}: {len(rows)} rows")

with open("eiot_dump.json", "w") as f:
    json.dump(dump, f, indent=2, default=str)

print("Dump saved to eiot_dump.json")

cursor.close()
conn.close()