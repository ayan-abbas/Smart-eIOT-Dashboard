-- Migration: Add view_all_devices column to users table
-- This allows non-admin users to view all devices regardless of ownership

-- Add the column if it doesn't exist
ALTER TABLE users 
ADD COLUMN IF NOT EXISTS view_all_devices TINYINT(1) DEFAULT 0 NOT NULL
COMMENT 'Allow user to view all devices, not just their own';

-- Show updated table structure
DESCRIBE users;

-- Optional: Set view_all_devices = 1 for existing admin users
-- UPDATE users SET view_all_devices = 1 WHERE role = 'admin';
