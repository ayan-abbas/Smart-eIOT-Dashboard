# Smart Enterprise IoT Dashboard

A comprehensive web-based dashboard for managing and monitoring IoT devices across an enterprise. Built with Streamlit, MySQL, and AWS Lambda integration.

## Features

- **Device Management**: Create, view, and manage IoT devices
- **Group Management**: Organize devices into groups
- **User Management**: Role-based access control (admin, operator, viewer)
- **Real-time Monitoring**: Live device status and metrics
- **Data Visualization**: Interactive charts and analytics with Plotly
- **User Permissions**: Advanced permission system (View All Devices feature)
- **Performance Monitoring**: System profiling and performance reporting
- **AWS Integration**: Lambda function support for cloud processing
- **Database**: MySQL/RDS backend with connection pooling

## Prerequisites

- **Python 3.8+**
- **MySQL/RDS Database** (with credentials configured)
- **Git**
- Optional: **AWS Account** (for Lambda deployment)
- Optional: **C++ Compiler** (for embedded components)

## Quick Start

### 1. Clone the Repository
```powershell
git clone https://github.com/ayan-abbas/Smart-eIOT-Dashboard.git
cd Smart-eIOT-Dashboard
```

### 2. Create Virtual Environment
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

### 3. Install Dependencies

First, check what packages are in your environment:
```powershell
pip list
```

Key dependencies required:
- `streamlit` - Web UI framework
- `streamlit-autorefresh` - Auto-refresh component
- `plotly` - Interactive visualizations
- `mysql-connector-python` - MySQL database connector
- `pymysql` - Alternative MySQL connector
- `sqlalchemy` - ORM and database toolkit
- `pandas` - Data manipulation

If needed, install them:
```powershell
pip install streamlit streamlit-autorefresh plotly mysql-connector-python pymysql sqlalchemy pandas
```

### 4. Configure Database Connection

Edit [dashboard/utils.py](dashboard/utils.py) and update the database credentials:

```python
pw = "YOUR_DATABASE_PASSWORD"  # Change this
```

Also set the database host and credentials:
```python
host = "your-rds-endpoint.amazonaws.com"  # or localhost
user = "admin"
```

Alternatively, set environment variables:
```powershell
$env:EIOT_DB_HOST = "your-rds-endpoint.amazonaws.com"
$env:EIOT_DB_USER = "admin"
$env:EIOT_DB_PASSWORD = "your_password"
```

### 5. Database Setup (First Time Only)

Run the migration script to initialize database tables:
```powershell
python run_migration.py
```

This will create the necessary tables and schema.

### 6. Run the Dashboard

Start the Streamlit app:
```powershell
cd dashboard
streamlit run app.py
```

The dashboard will be available at: `http://localhost:8501`

## Project Structure

```
.
├── dashboard/                 # Main Streamlit application
│   ├── app.py               # Main dashboard application
│   ├── scheduler.py         # Background task scheduler
│   ├── utils.py             # Database utilities and helpers
│   └── pages/               # Multi-page dashboard components (if exists)
├── lambda_folder/           # AWS Lambda functions
│   ├── lambda_function.py   # Lambda handler
│   ├── mysql/              # MySQL connector library
│   └── embedding.py        # AI/ML models
├── accessing_rds/           # Database access scripts
│   ├── create_devices.py    # Device creation utilities
│   ├── create_groups.py     # Group creation utilities
│   └── create_users.py      # User creation utilities
├── fetch_dump/              # Database dump utilities
│   ├── dump.py
│   └── fetch.py
├── matrix_dashboard.cpp     # C++ dashboard component
├── esp.cpp                  # ESP microcontroller code
├── run_migration.py         # Database migration script
├── perf_tester.py          # Performance testing
├── full_system_profiler.py # System profiling
└── eiot_dump.json          # Database dump (sample data)
```

## Usage

### Default Login
When you first start the dashboard, use these credentials:
- **Username**: `admin`
- **Password**: `admin` (change this in production!)

### Main Sections

#### Dashboard
- Overview of all devices and their status
- Real-time metrics and KPIs
- Performance analytics

#### Devices
- View all registered IoT devices
- Create new devices
- Monitor device status and metrics
- View device-specific data

#### Groups
- Create and manage device groups
- Add/remove devices from groups
- Bulk operations on grouped devices

#### Users (Admin Only)
- Create new user accounts
- Assign roles (admin, operator, viewer)
- Grant permissions (e.g., View All Devices)
- Manage user access

## Advanced Features

### View All Devices Permission

Grant specific users the ability to see all devices without full admin privileges:

```powershell
python run_migration.py
```

Then in the User Management interface, check "Can view all devices" for the user.

### Performance Monitoring

Run system profiler:
```powershell
python full_system_profiler.py
```

Run performance tester:
```powershell
python perf_tester.py
```

### Database Backup

Export database dump:
```powershell
cd fetch_dump
python dump.py
```

### Lambda Deployment

Deploy AWS Lambda functions:
```powershell
cd lambda_folder
# Package and deploy to AWS
```

## Database Configuration

### Environment Variables

Set these for production:
```powershell
$env:EIOT_DB_HOST = "your-rds-endpoint"
$env:EIOT_DB_USER = "admin"
$env:EIOT_DB_PASSWORD = "secure_password"
$env:EIOT_SSL_CA = "path/to/ca-bundle.pem"  # For RDS SSL
```

### SSL/TLS Connection

For AWS RDS, you can use SSL certificates:
1. Download the global CA bundle from AWS
2. Set `EIOT_SSL_CA` environment variable to its path
3. The connection will automatically use SSL

## Troubleshooting

### Database Connection Issues

1. **Check credentials** in [dashboard/utils.py](dashboard/utils.py)
2. **Verify database is running** and accessible
3. **Check firewall** rules allow connection
4. **For RDS**: Ensure security group allows inbound traffic on port 3306

### Streamlit Issues

1. **Clear cache**:
   ```powershell
   streamlit cache clear
   ```

2. **Check logs**:
   ```powershell
   # Look in .streamlit/logs/
   ```

### Migration Issues

If migration script fails:
1. Check database credentials
2. Ensure database user has CREATE TABLE permissions
3. Run [add_view_all_devices_column.sql](add_view_all_devices_column.sql) manually if needed

## Performance Tips

- The application includes **connection pooling** for efficient database access
- Uses **caching** to reduce redundant queries
- Implements **auto-refresh** for real-time updates
- Optimized queries for fast data retrieval

## Testing

### Run Tests
```powershell
# Performance test
python perf_tester.py

# System profiler
python full_system_profiler.py
```

### HTTP Endpoints (for API testing)
- GET request: [get_test1.http](get_test1.http)
- POST request: [post_test1.http](post_test1.http)

## Security

⚠️ **IMPORTANT FOR PRODUCTION**:

1. **Change default passwords** - Update `admin` user password immediately
2. **Use environment variables** - Don't hardcode credentials
3. **Enable SSL/TLS** - Use SSL certificates for database and web connections
4. **Role-based access** - Properly configure user roles
5. **Regular backups** - Set up automated database backups
6. **Update dependencies** - Keep libraries current for security patches

## Contributing

1. Create a feature branch
2. Make your changes
3. Test thoroughly
4. Submit a pull request

## License

[Add your license information here]

## Support

For issues or questions:
1. Check the troubleshooting section
2. Review [VIEW_ALL_DEVICES_FEATURE.md](VIEW_ALL_DEVICES_FEATURE.md) for feature documentation
3. Check database logs for errors
4. Review Streamlit logs

## Authors

- **Ayan Abbas** - Initial development

## Additional Resources

- [Streamlit Documentation](https://docs.streamlit.io/)
- [MySQL Connector Python](https://dev.mysql.com/doc/connector-python/en/)
- [Plotly Dash](https://plotly.com/python/)
- [AWS Lambda](https://aws.amazon.com/lambda/)

---

**Last Updated**: May 8, 2026
