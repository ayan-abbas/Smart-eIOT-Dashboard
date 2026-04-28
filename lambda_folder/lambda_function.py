import mysql.connector
import json
from datetime import datetime, timezone, timedelta

def lambda_handler(event, context):
    print(event)

    method = event["requestContext"]["http"]["method"]
    path = event["rawPath"].replace("/default", "", 1)
    print(f"METHOD: {method}, PATH: {path}")  # add this


# POST /device/data
    if method == "POST" and path == "/device/data":

        body = json.loads(event["body"])

        username = body["username"]
        password = body["password"]
        device_id = body["device_id"]
        wattage = float(body["wattage"])

        conn = None

        try:
            conn = mysql.connector.connect(
                host="eiot.c7eqmkyyitqo.ap-south-1.rds.amazonaws.com",
                port=3306,
                user="admin",
                password="AyansDataBase",
                database="eiot",
                ssl_disabled=False
            )

            cursor = conn.cursor()

            # Check user
            cursor.execute(
                "SELECT password FROM users WHERE username = %s",
                (username,)
            )

            user = cursor.fetchone()

            if not user or user[0] != password:
                return {
                    "statusCode": 401,
                    "body": json.dumps({"error": "Unauthorized"})
                }

            # Check device belongs to user
            cursor.execute(
                "SELECT deviceid FROM devices WHERE username = %s AND deviceid = %s",
                (username, device_id)
            )

            device = cursor.fetchone()

            if not device:
                return {
                    "statusCode": 403,
                    "body": json.dumps({"error": "Forbidden"})
                }

            # Insert power data into normalized table
            # Use IST timezone (UTC+5:30)
            IST = timezone(timedelta(hours=5, minutes=30))
            now = datetime.now(IST).replace(tzinfo=None)
            
            print(f"Inserting data: time={now}, deviceid={device_id}, power={wattage}")
            
            cursor.execute(
                "INSERT INTO power_usage_normalized (time, deviceid, power) VALUES (%s, %s, %s)",
                (now, device_id, wattage)
            )

            conn.commit()
            cursor.close()
            
            print(f"Data committed successfully for device {device_id}")

            return {
                "statusCode": 200,
                "body": json.dumps({
                    "message": "Data inserted successfully",
                    "device": device_id,
                    "power": wattage
                })
            }

        except Exception as e:
            print(f"Database error: {e}")
            raise

        finally:
            if conn:
                conn.close()

        

    # GET /device/state/{device_id}
    if method == "GET" and path.startswith("/device/state/"):

        device_id = path.split("/")[-1]

        query_params = event.get("queryStringParameters") or {}

        username = query_params.get("username")
        password = query_params.get("password")

        conn = None

        try:
            conn = mysql.connector.connect(
                host="eiot.c7eqmkyyitqo.ap-south-1.rds.amazonaws.com",
                port=3306,
                user="admin",
                password="AyansDataBase",
                database="eiot",
                ssl_disabled=False
            )

            cursor = conn.cursor()
            cursor.execute(
                "SELECT password FROM users WHERE username = %s",
                (username,)
            )
            if cursor.fetchone()[0] != password:
                return {
                    "statusCode": 401,
                    "body": json.dumps({"error": "Unauthorized"})
                }
            else:
                cursor.execute(
                    "SELECT state FROM devices WHERE username = %s AND deviceid = %s",
                    (username, device_id)
                )
                state = cursor.fetchone()
                if not state:
                    return {
                        "statusCode": 403,
                        "body": json.dumps({"error": "Forbidden"})
                    }
                else:
                    return {"state": state[0]}
            
        except Exception as e:
            print(f"Database error: {e}")
            raise

        finally:
            if conn:
                conn.close()

    return {
        "statusCode": 404,
        "body": json.dumps({"error": "Route not found"})
    }
