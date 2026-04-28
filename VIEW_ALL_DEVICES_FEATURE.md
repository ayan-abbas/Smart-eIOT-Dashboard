# View All Devices Permission Feature

## Overview
This feature allows admins to grant specific users the ability to view all devices in the system, regardless of ownership, without giving them full admin privileges.

## How It Works
- A new column `view_all_devices` has been added to the `users` table
- Users with this permission can see all devices and groups across all users
- This permission is independent of the user's role (admin, operator, viewer)

## Setup Instructions

### 1. Run the Database Migration
Execute the migration script to add the new column:

```powershell
python run_migration.py
```

This will add the `view_all_devices` column to the users table.

### 2. Using the Feature

#### For Admins:
1. Go to the **User Management** page
2. When creating a new user:
   - Fill in username, password, and role
   - Check the **"Can view all devices"** checkbox to grant this permission
   - Click Create
3. For existing users:
   - Check/uncheck the **"View All Devices"** checkbox in their row
   - Changes are saved automatically

#### For Users with View All Permission:
- When logged in, they will see all devices from all users on the Devices page
- They will see all groups from all users on the Groups page
- Device ownership is still displayed (username column)
- State control permissions still depend on their role (operator/admin only)

## Technical Details

### Database Changes
```sql
ALTER TABLE users 
ADD COLUMN view_all_devices TINYINT(1) DEFAULT 0 NOT NULL
COMMENT 'Allow user to view all devices, not just their own';
```

### Modified Files
- `dashboard/utils.py`: Updated `get_devices()`, `get_groups()`, `authenticate_user()`, `create_user()`, `get_all_users()`, and added `update_user_view_all()`
- `dashboard/app.py`: Updated session state, cached functions, login flow, and RBAC page
- `run_migration.py`: Database migration script
- `add_view_all_devices_column.sql`: SQL migration file

### Session State
The `view_all_devices` permission is stored in `st.session_state.view_all_devices` during login.

## Use Cases
- Monitoring/support staff who need to see all devices but shouldn't have admin access
- Operators who manage devices across multiple users
- Dashboard viewers who need a complete overview without control permissions

## Notes
- Admins always see all devices (this feature doesn't change admin behavior)
- The permission only affects read access - write permissions still require operator/admin role
- The permission applies to both devices and groups
