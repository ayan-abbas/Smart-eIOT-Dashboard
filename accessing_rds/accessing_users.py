import mysql.connector
# import boto3

password = "AyansDataBase"

conn = None
try:
    conn = mysql.connector.connect(
        host='eiot.cu5iw2g8er81.us-east-1.rds.amazonaws.com',
        port=3306,
        database='mysql',
        user='admin',
        password=password,
        ssl_disabled=False,
    ssl_ca='/certs/global-bundle.pem'
    )
    cursor = conn.cursor()
    
    cursor.execute("use eiot")

    username = input("Enter username: ")
    cursor.execute(f"SELECT username FROM users WHERE username = {username}")

    if cursor.fetchone():
        password = input("Enter password: ")
        cursor.execute(f"SELECT password FROM users WHERE username = {username}")

        if cursor.fetchone()[0] == password:
            print("Login successful!")  
        else:
            print("Incorrect password.")
    else:
        print("Username not found.")


    cursor.close()
except Exception as e:
    print(f"Database error: {e}")
    raise
finally:
    if conn:
        conn.close()