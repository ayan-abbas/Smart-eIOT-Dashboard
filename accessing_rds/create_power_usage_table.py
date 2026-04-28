import mysql.connector

pw = "AyansDataBase"

conn = mysql.connector.connect(
    host='eiot.c7eqmkyyitqo.ap-south-1.rds.amazonaws.com',
    port=3306,
    database='eiot',
    user='admin',
    password=pw,
    ssl_disabled=False,
    ssl_ca='/certs/global-bundle.pem'
)

cursor = conn.cursor()

# Generate column definitions
columns = ["time DATETIME"]

for i in range(1, 501):
    columns.append(f"`{i}` INT")

columns_sql = ",\n".join(columns)

query = f"""
CREATE TABLE power_usage (
{columns_sql}
);
"""

cursor.execute(query)

conn.commit()

print("Table created successfully!")

cursor.close()
conn.close()