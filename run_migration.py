"""
Run migration to add view_all_devices column to users table
"""
import mysql.connector

# Database configuration
pw = "AyansDataBase"

DB_CONFIG = {
    "host": "eiot.c7eqmkyyitqo.ap-south-1.rds.amazonaws.com",
    "port": 3306,
    "database": "eiot",
    "user": "admin",
    "password": pw,
    "ssl_disabled": False,
    "ssl_ca": "C:/certs/global-bundle.pem",
}

def run_migration():
    """Add view_all_devices column to users table"""
    conn = None
    cursor = None
    try:
        print("Connecting to database...")
        conn = mysql.connector.connect(**DB_CONFIG)
        cursor = conn.cursor()
        
        # Check if column already exists
        cursor.execute("""
            SELECT COUNT(*) 
            FROM information_schema.COLUMNS 
            WHERE TABLE_SCHEMA = 'eiot' 
            AND TABLE_NAME = 'users' 
            AND COLUMN_NAME = 'view_all_devices'
        """)
        exists = cursor.fetchone()[0] > 0
        
        if exists:
            print("✓ Column 'view_all_devices' already exists in users table")
        else:
            print("Adding column 'view_all_devices' to users table...")
            cursor.execute("""
                ALTER TABLE users 
                ADD COLUMN view_all_devices TINYINT(1) DEFAULT 0 NOT NULL
                COMMENT 'Allow user to view all devices, not just their own'
            """)
            conn.commit()
            print("✓ Column 'view_all_devices' added successfully")
        
        # Show table structure
        print("\nCurrent users table structure:")
        cursor.execute("DESCRIBE users")
        for row in cursor.fetchall():
            print(f"  {row[0]:20s} {row[1]:20s} {row[2]:5s} {row[3]:5s}")
        
        print("\n✓ Migration completed successfully!")
        
    except mysql.connector.Error as e:
        print(f"✗ Error: {e}")
        if conn:
            conn.rollback()
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

if __name__ == "__main__":
    run_migration()
