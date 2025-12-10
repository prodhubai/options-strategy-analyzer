# Daily Analysis Scheduler Configuration

## Environment Variables Required

Create a `.env` file with the following variables:

```bash
# Email Configuration (Gmail example)
SMTP_SERVER=smtp.gmail.com
SMTP_PORT=587
SMTP_USERNAME=your-email@gmail.com
SMTP_PASSWORD=your-app-password  # Use App Password for Gmail

# Google Sheets Configuration
GOOGLE_SHEETS_CREDENTIALS=credentials.json  # Path to service account JSON

# Flask Secret Key
SECRET_KEY=your-secret-key-here
```

## Gmail Setup

1. **Enable 2-Factor Authentication** on your Gmail account
2. **Generate App Password:**
   - Go to Google Account → Security
   - Under "2-Step Verification", click "App passwords"
   - Generate new app password for "Mail"
   - Use this password in `SMTP_PASSWORD`

## Google Sheets API Setup

1. **Create Google Cloud Project:**
   - Go to [Google Cloud Console](https://console.cloud.google.com/)
   - Create new project or select existing one

2. **Enable APIs:**
   - Enable "Google Sheets API"
   - Enable "Google Drive API"

3. **Create Service Account:**
   - Go to "IAM & Admin" → "Service Accounts"
   - Create new service account
   - Grant role: "Editor"
   - Create JSON key and download as `credentials.json`
   - Place in project root directory

4. **Alternative: Use OAuth2 (for user accounts):**
   - Create OAuth 2.0 credentials
   - Download client configuration
   - Run initial authentication flow

## Installation

```bash
# Install required packages
pip install schedule gspread google-auth google-auth-oauthlib google-auth-httplib2 pandas python-dotenv

# Or add to requirements.txt
echo "schedule==1.2.0" >> requirements.txt
echo "gspread==5.12.0" >> requirements.txt
echo "google-auth==2.23.4" >> requirements.txt
echo "google-auth-oauthlib==1.1.0" >> requirements.txt
echo "google-auth-httplib2==0.1.1" >> requirements.txt
echo "pandas==2.1.3" >> requirements.txt
echo "python-dotenv==1.0.0" >> requirements.txt

pip install -r requirements.txt
```

## Usage

### Start Scheduler with Flask App

The scheduler automatically starts when you run the Flask app:

```python
# In app.py, add at the bottom:
from scheduler import start_scheduler_thread

if __name__ == '__main__':
    start_scheduler_thread()  # Start background scheduler
    app.run(host='0.0.0.0', port=5000, debug=True, use_reloader=False)
```

### Manual Testing

Run analysis immediately for testing:

```bash
python scheduler.py
```

### Configure User Settings

Create `user_settings.json`:

```json
{
  "email": "sumeet@assistra.ai",
  "watchlist": [
    "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", 
    "TSLA", "META", "AMD", "NFLX", "DIS"
  ],
  "min_roi": 1,
  "min_probability": 50,
  "max_rsi": 100,
  "max_days": 21,
  "top_n": 20,
  "otm_percent": 2.5,
  "spread_width": 5,
  "enabled": true
}
```

## Scheduler Features

### Automated Daily Analysis
- ✅ Runs every day at 6:30 AM PST (market open)
- ✅ Analyzes user's watchlist
- ✅ Applies all filter settings (ROI, Probability, RSI, etc.)
- ✅ Sorts by composite score

### Google Sheets Export
- ✅ Creates new spreadsheet daily
- ✅ Formatted with headers and colors
- ✅ Shared automatically with user
- ✅ Named: "Daily Options Analysis - YYYY-MM-DD"

### Email Report
- ✅ HTML formatted email
- ✅ Summary statistics
- ✅ Top 10 opportunities table
- ✅ Link to Google Sheet
- ✅ CSV attachment
- ✅ Current settings summary

### CSV Download
- ✅ Full data export
- ✅ Attached to email
- ✅ Saved locally: `daily_analysis_YYYYMMDD.csv`

## Schedule Configuration

Default: **6:30 AM PST daily**

To change schedule, modify in `scheduler.py`:

```python
# Every day at 6:30 AM
schedule.every().day.at("06:30").do(daily_job)

# Or every weekday only
schedule.every().monday.at("06:30").do(daily_job)
schedule.every().tuesday.at("06:30").do(daily_job)
schedule.every().wednesday.at("06:30").do(daily_job)
schedule.every().thursday.at("06:30").do(daily_job)
schedule.every().friday.at("06:30").do(daily_job)

# Multiple times per day
schedule.every().day.at("06:30").do(daily_job)  # Market open
schedule.every().day.at("13:00").do(daily_job)  # Market close
```

## User Settings API (Future Implementation)

### Enable/Disable Daily Analysis

```python
# Add to app.py
@app.route('/api/settings/daily-analysis', methods=['POST'])
@login_required
def update_daily_analysis_settings():
    data = request.json
    user_email = session['user']['email']
    
    # Update user settings in database
    update_user_setting(user_email, 'daily_analysis_enabled', data['enabled'])
    update_user_setting(user_email, 'watchlist', data['watchlist'])
    update_user_setting(user_email, 'min_roi', data['min_roi'])
    # ... etc
    
    return jsonify({'success': True})
```

### Get Current Settings

```python
@app.route('/api/settings/daily-analysis', methods=['GET'])
@login_required
def get_daily_analysis_settings():
    user_email = session['user']['email']
    settings = get_user_settings(user_email)
    return jsonify(settings)
```

## Monitoring & Logs

Logs are written to console with timestamps:

```
2025-12-04 06:30:00 - INFO - Running daily options analysis job
2025-12-04 06:30:05 - INFO - Analyzing AAPL...
2025-12-04 06:30:10 - INFO - Analyzing MSFT...
...
2025-12-04 06:35:00 - INFO - Analysis complete. Found 47 opportunities.
2025-12-04 06:35:05 - INFO - Google Sheet created: https://docs.google.com/...
2025-12-04 06:35:10 - INFO - Email sent successfully to sumeet@assistra.ai
2025-12-04 06:35:10 - INFO - Daily job completed successfully
```

## Troubleshooting

### Email not sending
- Check SMTP credentials
- Verify app password (not regular password for Gmail)
- Check firewall/network settings

### Google Sheets not creating
- Verify service account JSON file exists
- Check API is enabled in Google Cloud Console
- Ensure service account has necessary permissions

### Scheduler not running
- Check Flask is running with `use_reloader=False`
- Verify scheduler thread started
- Check system timezone matches PST

## Production Deployment

### Using systemd (Linux)

Create `/etc/systemd/system/stratify-scheduler.service`:

```ini
[Unit]
Description=Stratify Options Analysis Scheduler
After=network.target

[Service]
Type=simple
User=your-user
WorkingDirectory=/path/to/app
Environment="PATH=/path/to/venv/bin"
ExecStart=/path/to/venv/bin/python scheduler.py
Restart=always

[Install]
WantedBy=multi-user.target
```

Enable and start:
```bash
sudo systemctl enable stratify-scheduler
sudo systemctl start stratify-scheduler
sudo systemctl status stratify-scheduler
```

### Using Docker

Add to `Dockerfile`:
```dockerfile
# Install cron
RUN apt-get update && apt-get install -y cron

# Add crontab
RUN echo "30 6 * * * cd /app && /usr/local/bin/python scheduler.py" | crontab -

# Start cron and app
CMD cron && python app.py
```

### Using Heroku Scheduler

Add to `Procfile`:
```
web: python app.py
scheduler: python scheduler.py
```

Configure in Heroku dashboard → Scheduler add-on.

## Security Considerations

- ✅ Store credentials in environment variables
- ✅ Use `.env` file (add to `.gitignore`)
- ✅ Rotate API keys regularly
- ✅ Limit service account permissions
- ✅ Use OAuth2 for user-specific sheets
- ✅ Validate user inputs
- ✅ Rate limit API calls

## Next Steps

1. ✅ Install dependencies
2. ✅ Set up Gmail app password
3. ✅ Configure Google Sheets API
4. ✅ Create `.env` file
5. ✅ Test with `python scheduler.py`
6. ✅ Integrate with Flask app
7. ✅ Deploy to production
