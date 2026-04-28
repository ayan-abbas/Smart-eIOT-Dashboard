import datetime
import random
import mysql.connector

DB = dict(
    host     = "eiot.c7eqmkyyitqo.ap-south-1.rds.amazonaws.com",
    port     = 3306,
    database = "eiot",
    user     = "admin",
    password = "AyansDataBase",
    ssl_disabled = False,
    ssl_ca   = "C:/certs/global-bundle.pem",
)

conn = mysql.connector.connect(**DB)
cur  = conn.cursor()

now = datetime.datetime.now() 
power = random.randint(100, 500)

cur.execute(
    "INSERT INTO power_usage_normalized (time, deviceid, power) VALUES (%s, %s, %s)",
    (now, 1, power)
)
conn.commit()

print(f"✅ Inserted — device 1 | {now} | {power} W")

cur.close()
conn.close()