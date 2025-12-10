"""
Automated Daily Options Analysis Scheduler
Runs analysis at market open (6:30 AM PST) and sends email with Google Sheets
"""

import schedule
import time
import smtplib
import os
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from datetime import datetime
import pytz
import gspread
from google.oauth2.service_account import Credentials
import pandas as pd
import yfinance as yf
from threading import Thread
import logging

# Import from main app
from app import (
    analyze_all_strategies,
    get_current_rsi,
    MIN_OTM_PERCENT,
    MIN_SPREAD_WIDTH_DOLLARS
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Configuration
MARKET_OPEN_TIME = "06:30"  # 6:30 AM PST
PST_TIMEZONE = pytz.timezone('America/Los_Angeles')

# Email configuration (from environment variables)
SMTP_SERVER = os.getenv('SMTP_SERVER', 'smtp.gmail.com')
SMTP_PORT = int(os.getenv('SMTP_PORT', '587'))
SMTP_USERNAME = os.getenv('SMTP_USERNAME', '')
SMTP_PASSWORD = os.getenv('SMTP_PASSWORD', '')

# Google Sheets configuration
GOOGLE_SHEETS_CREDENTIALS = os.getenv('GOOGLE_SHEETS_CREDENTIALS', 'credentials.json')
SPREADSHEET_NAME = 'Daily Options Analysis'

# Default watchlist
DEFAULT_WATCHLIST = [
    'AAPL', 'MSFT', 'GOOGL', 'AMZN', 'NVDA', 'TSLA', 'META', 'AMD',
    'NFLX', 'DIS', 'BABA', 'INTC', 'AVGO', 'QCOM', 'ADBE', 'CRM'
]

# User settings (will be loaded from database/config)
USER_SETTINGS = {
    'email': 'sumeet@assistra.ai',
    'watchlist': DEFAULT_WATCHLIST,
    'min_roi': 1,
    'min_probability': 50,
    'max_rsi': 100,
    'max_days': 21,
    'top_n': 20,
    'otm_percent': 2.5,
    'spread_width': 5,
    'enabled': True
}


def load_user_settings():
    """Load user settings from database or config file"""
    # TODO: Implement database/file loading
    # For now, return default settings
    return USER_SETTINGS


def run_daily_analysis():
    """Execute daily options analysis for watchlist"""
    logger.info("Starting daily options analysis...")
    
    settings = load_user_settings()
    
    if not settings.get('enabled'):
        logger.info("Daily analysis is disabled for this user")
        return
    
    all_results = []
    
    for symbol in settings['watchlist']:
        try:
            logger.info(f"Analyzing {symbol}...")
            
            # Run analysis for this symbol
            result = analyze_all_strategies(
                symbol=symbol,
                max_days=settings['max_days'],
                top_n=settings['top_n']
            )
            
            if 'strategies' in result:
                for strategy in result['strategies']:
                    # Apply filters
                    roi = strategy.get('roi_percent', 0)
                    prob = strategy.get('probability_success_percent', 0)
                    rsi = strategy.get('rsi', 100)
                    
                    if (roi >= settings['min_roi'] and 
                        prob >= settings['min_probability'] and 
                        rsi <= settings['max_rsi']):
                        all_results.append(strategy)
        
        except Exception as e:
            logger.error(f"Error analyzing {symbol}: {e}")
            continue
    
    # Sort by composite score
    all_results.sort(key=lambda x: x.get('composite_score', 0), reverse=True)
    
    # Limit to top N
    top_results = all_results[:settings['top_n']]
    
    logger.info(f"Analysis complete. Found {len(top_results)} opportunities.")
    
    return top_results


def create_google_sheet(results):
    """Create Google Sheet with analysis results"""
    try:
        # Set up Google Sheets credentials
        scope = [
            'https://spreadsheets.google.com/feeds',
            'https://www.googleapis.com/auth/drive'
        ]
        
        creds = Credentials.from_service_account_file(
            GOOGLE_SHEETS_CREDENTIALS,
            scopes=scope
        )
        client = gspread.authorize(creds)
        
        # Create new spreadsheet
        today = datetime.now(PST_TIMEZONE).strftime('%Y-%m-%d')
        sheet_name = f"{SPREADSHEET_NAME} - {today}"
        
        spreadsheet = client.create(sheet_name)
        worksheet = spreadsheet.sheet1
        
        # Prepare data
        if not results:
            worksheet.update('A1', [['No results found']])
            return spreadsheet.url
        
        # Headers
        headers = [
            'Symbol', 'Strategy', 'Score', 'ROI %', 'Probability %', 
            'RSI', 'Days', 'Expiry', 'Sell Strike', 'Buy Strike', 
            'Credit', 'Max Loss', 'Breakeven', 'Current Price'
        ]
        
        # Data rows
        rows = [headers]
        for r in results:
            row = [
                r.get('symbol', ''),
                r.get('strategy', ''),
                r.get('composite_score', 0),
                r.get('roi_percent', 0),
                r.get('probability_success_percent', 0),
                r.get('rsi', ''),
                r.get('days_to_expiry', ''),
                r.get('expiry', ''),
                r.get('short_strike', ''),
                r.get('long_strike', ''),
                r.get('credit', 0),
                r.get('max_loss', 0),
                r.get('breakeven', ''),
                r.get('spot', 0)
            ]
            rows.append(row)
        
        # Update sheet
        worksheet.update('A1', rows)
        
        # Format header row
        worksheet.format('A1:N1', {
            'textFormat': {'bold': True},
            'backgroundColor': {'red': 0.26, 'green': 0.85, 'blue': 0.72}
        })
        
        # Share with user email
        settings = load_user_settings()
        spreadsheet.share(settings['email'], perm_type='user', role='writer')
        
        logger.info(f"Google Sheet created: {spreadsheet.url}")
        return spreadsheet.url
    
    except Exception as e:
        logger.error(f"Error creating Google Sheet: {e}")
        return None


def export_to_csv(results, filename='daily_analysis.csv'):
    """Export results to CSV file"""
    try:
        if not results:
            logger.warning("No results to export")
            return None
        
        # Convert to DataFrame
        df = pd.DataFrame(results)
        
        # Select relevant columns
        columns = [
            'symbol', 'strategy', 'composite_score', 'roi_percent',
            'probability_success_percent', 'rsi', 'days_to_expiry',
            'expiry', 'short_strike', 'long_strike', 'credit',
            'max_loss', 'breakeven', 'spot'
        ]
        
        df = df[[col for col in columns if col in df.columns]]
        
        # Save to CSV
        df.to_csv(filename, index=False)
        logger.info(f"CSV exported: {filename}")
        return filename
    
    except Exception as e:
        logger.error(f"Error exporting CSV: {e}")
        return None


def send_email_report(results, sheet_url=None, csv_file=None):
    """Send email with analysis results"""
    settings = load_user_settings()
    recipient = settings['email']
    
    try:
        # Create message
        msg = MIMEMultipart()
        msg['From'] = SMTP_USERNAME
        msg['To'] = recipient
        msg['Subject'] = f"Daily Options Analysis - {datetime.now(PST_TIMEZONE).strftime('%B %d, %Y')}"
        
        # Email body
        body = f"""
        <html>
        <head>
            <style>
                body {{ font-family: 'Inter', Arial, sans-serif; }}
                h2 {{ color: #0A1F44; }}
                .summary {{ background: #F7F9FC; padding: 15px; border-radius: 8px; margin: 20px 0; }}
                .stats {{ display: inline-block; margin-right: 20px; }}
                .stats strong {{ color: #43D9B8; font-size: 24px; }}
                table {{ border-collapse: collapse; width: 100%; margin-top: 20px; }}
                th {{ background: #43D9B8; color: white; padding: 12px; text-align: left; }}
                td {{ padding: 10px; border-bottom: 1px solid #E3E9F2; }}
                tr:hover {{ background: #F7F9FC; }}
                .footer {{ margin-top: 30px; color: #6E7A8A; font-size: 12px; }}
            </style>
        </head>
        <body>
            <h2>📊 Daily Options Analysis Report</h2>
            
            <div class="summary">
                <div class="stats">
                    <strong>{len(results)}</strong><br>
                    <span style="color: #6E7A8A;">Opportunities Found</span>
                </div>
                <div class="stats">
                    <strong>{len(settings['watchlist'])}</strong><br>
                    <span style="color: #6E7A8A;">Symbols Analyzed</span>
                </div>
                <div class="stats">
                    <strong>{settings['max_days']}</strong><br>
                    <span style="color: #6E7A8A;">Max Days to Expiry</span>
                </div>
            </div>
            
            <h3>Current Settings</h3>
            <ul>
                <li>Min ROI: {settings['min_roi']}%</li>
                <li>Min Probability: {settings['min_probability']}%</li>
                <li>Max RSI: {settings['max_rsi']}</li>
                <li>OTM Distance: {settings['otm_percent']}%</li>
                <li>Spread Width: ${settings['spread_width']}</li>
            </ul>
        """
        
        if results:
            body += """
            <h3>Top 10 Opportunities</h3>
            <table>
                <tr>
                    <th>Symbol</th>
                    <th>Strategy</th>
                    <th>Score</th>
                    <th>ROI %</th>
                    <th>Prob %</th>
                    <th>Days</th>
                    <th>Credit</th>
                </tr>
            """
            
            for r in results[:10]:
                body += f"""
                <tr>
                    <td><strong>{r.get('symbol', '')}</strong></td>
                    <td>{r.get('strategy', '')}</td>
                    <td>{r.get('composite_score', 0):.1f}</td>
                    <td>{r.get('roi_percent', 0):.1f}%</td>
                    <td>{r.get('probability_success_percent', 0):.1f}%</td>
                    <td>{r.get('days_to_expiry', '')}</td>
                    <td>${r.get('credit', 0):.2f}</td>
                </tr>
                """
            
            body += "</table>"
        else:
            body += "<p>No opportunities found matching your criteria.</p>"
        
        if sheet_url:
            body += f"""
            <p style="margin-top: 20px;">
                <a href="{sheet_url}" style="background: #43D9B8; color: white; padding: 10px 20px; 
                text-decoration: none; border-radius: 5px; display: inline-block;">
                📊 View Full Report in Google Sheets
                </a>
            </p>
            """
        
        body += """
            <div class="footer">
                <p>This is an automated report from Stratify Options Analysis.</p>
                <p>To modify settings or disable these emails, log in to your account.</p>
            </div>
        </body>
        </html>
        """
        
        msg.attach(MIMEText(body, 'html'))
        
        # Attach CSV if available
        if csv_file and os.path.exists(csv_file):
            with open(csv_file, 'rb') as f:
                part = MIMEBase('application', 'octet-stream')
                part.set_payload(f.read())
                encoders.encode_base64(part)
                part.add_header('Content-Disposition', f'attachment; filename={os.path.basename(csv_file)}')
                msg.attach(part)
        
        # Send email
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USERNAME, SMTP_PASSWORD)
            server.send_message(msg)
        
        logger.info(f"Email sent successfully to {recipient}")
        return True
    
    except Exception as e:
        logger.error(f"Error sending email: {e}")
        return False


def daily_job():
    """Main daily job - run analysis and send report"""
    logger.info("=" * 50)
    logger.info("Running daily options analysis job")
    logger.info("=" * 50)
    
    # Run analysis
    results = run_daily_analysis()
    
    # Export to CSV
    csv_file = export_to_csv(results, f"daily_analysis_{datetime.now(PST_TIMEZONE).strftime('%Y%m%d')}.csv")
    
    # Create Google Sheet
    sheet_url = create_google_sheet(results)
    
    # Send email
    send_email_report(results, sheet_url, csv_file)
    
    logger.info("Daily job completed successfully")


def run_scheduler():
    """Run the scheduler in background"""
    # Schedule daily job at 6:30 AM PST
    schedule.every().day.at(MARKET_OPEN_TIME).do(daily_job)
    
    logger.info(f"Scheduler started. Daily analysis scheduled for {MARKET_OPEN_TIME} PST")
    
    while True:
        schedule.run_pending()
        time.sleep(60)  # Check every minute


def start_scheduler_thread():
    """Start scheduler in background thread"""
    scheduler_thread = Thread(target=run_scheduler, daemon=True)
    scheduler_thread.start()
    logger.info("Scheduler thread started")


if __name__ == "__main__":
    # For testing, run immediately
    logger.info("Running test analysis...")
    daily_job()
