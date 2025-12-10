# Stratify - Daily Analysis Settings
Environment variables template for scheduler configuration.
Copy to `.env` and update with your credentials.

```bash
# Email Configuration
SMTP_SERVER=smtp.gmail.com
SMTP_PORT=587
SMTP_USERNAME=your-email@gmail.com
SMTP_PASSWORD=your-gmail-app-password

# Google Sheets
GOOGLE_SHEETS_CREDENTIALS=credentials.json

# Flask
SECRET_KEY=change-this-secret-key

# API Authentication (for external integrations like Bubble, Zapier, etc.)
# Generate using: curl -X POST http://localhost:5000/api/generate-key
API_KEY=dev-api-key-change-in-production

# Scheduler
DAILY_ANALYSIS_ENABLED=true
MARKET_OPEN_TIME=06:30
```
