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
    cursor.execute("SELECT username FROM users")  
    print(cursor.fetchall())  
    # username = input("Enter username: ")
    username = "sa3421@srmist.edu.in"
    cursor.execute("SELECT username FROM users WHERE username = %s", (username,))
    result = cursor.fetchone()
    print(result)
    if result:
        # password = input("Enter password: ")
        password = "password"
        cursor.execute("SELECT password FROM users WHERE username = %s", (username,))
        user_password = cursor.fetchone()
        if user_password and user_password[0] == password:
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