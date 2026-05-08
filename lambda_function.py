import mysql.connector
import json

def lambda_handler(event, context):
    print(event)

    method = event["requestContext"]["http"]["method"]
    path = event["rawPath"]


    # GET /device/states
    # Returns all device states for the authenticated user in one response.
    if method == "GET" and path == "/device/states":

        query_params = event.get("queryStringParameters") or {}

        username = query_params.get("username")
        password = query_params.get("password")

        if not username or not password:
            return {
                "statusCode": 400,
                "body": json.dumps({"error": "Missing username/password"})
            }

        conn = None

        try:
            conn = mysql.connector.connect(
                host="eiot.cu5iw2g8er81.us-east-1.rds.amazonaws.com",
                port=3306,
                user="admin",
                password="AyansDataBase",
                database="eiot"
            )

            cursor = conn.cursor(buffered=True)

            cursor.execute(
                "SELECT password FROM users WHERE username = %s",
                (username,)
            )
            row = cursor.fetchone()
            if not row or row[0] != password:
                return {
                    "statusCode": 401,
                    "body": json.dumps({"error": "Unauthorized"})
                }

            cursor.execute(
                "SELECT deviceid, state FROM devices WHERE username = %s ORDER BY deviceid",
                (username,)
            )
            rows = cursor.fetchall() or []

            device_ids = [int(r[0]) for r in rows]
            states = [int(r[1]) for r in rows]

            cursor.close()

            return {
                "statusCode": 200,
                "body": json.dumps({
                    "username": username,
                    "device_ids": device_ids,
                    "states": states
                })
            }

        except Exception as e:
            print(f"Database error: {e}")
            raise

        finally:
            if conn:
                conn.close()

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
                host="eiot.cu5iw2g8er81.us-east-1.rds.amazonaws.com",
                port=3306,
                user="admin",
                password="AyansDataBase",
                database="eiot"
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

            # Insert power data
            cursor.execute(
                "INSERT INTO myPowerUsage (power_consumption) VALUES (%s)",
                (wattage,)
            )

            conn.commit()

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
                host="eiot.cu5iw2g8er81.us-east-1.rds.amazonaws.com",
                port=3306,
                user="admin",
                password="AyansDataBase",
                database="eiot"
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

if __name__ == "__main__":

    # # Simulate GET request
    # event = {
    #     "requestContext": {
    #         "http": {
    #             "method": "GET"
    #         }
    #     },
    #     "rawPath": "/device/state/1",
    #     "queryStringParameters": {
    #         "username": "sa3421@srmist.edu.in",
    #         "password": "password"
    #     }
    # }

    # Simulate POST request
    event = {
        "requestContext": {
            "http": {
                "method": "POST"
            }
        },
        "rawPath": "/device/data",
        "body": json.dumps({
            "username": "sa3421@srmist.edu.in",
            "password": "password",
            "device_id": 1,
            "wattage": 150.5
        })
    }

    response = lambda_handler(event, None)

    print("Response:")
    print(response)