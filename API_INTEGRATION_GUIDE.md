# API Integration Guide for External Apps (Bubble, Zapier, etc.)

## Overview
This guide explains how to integrate the Options Analysis API with external applications like Bubble.io, Zapier, Make.com, or custom apps.

## Quick Start

### 1. Generate API Key
```bash
curl -X POST http://your-app-url.com/api/generate-key
```

Save the returned API key to your `.env` file:
```env
API_KEY=your_secure_api_key_here
```

### 2. Make Your First Request
```bash
curl -X POST http://your-app-url.com/api/webhook/analyze \
  -H "Content-Type: application/json" \
  -H "X-API-Key: your_secure_api_key_here" \
  -d '{
    "symbols": ["AAPL", "MSFT"],
    "max_days": 21,
    "top_n": 10
  }'
```

---

## API Endpoints

### 1. `/api/webhook/analyze` - Analyze Multiple Symbols

**Method:** `POST`

**Authentication:** Required (API Key)

**Description:** Analyzes options strategies for multiple stock symbols and returns the best opportunities.

**Request Headers:**
```
Content-Type: application/json
X-API-Key: your_api_key_here
```

**Request Body:**
```json
{
  "symbols": ["AAPL", "MSFT", "GOOGL"],
  "max_days": 21,
  "top_n": 20,
  "otm_percent": 2.5,
  "spread_width": 5,
  "filters": {
    "min_roi": 10,
    "min_probability": 40,
    "max_rsi": 70
  }
}
```

**Parameters:**
- `symbols` (array, required): Stock ticker symbols to analyze
- `max_days` (integer, optional, default: 21): Maximum days to expiration
- `top_n` (integer, optional, default: 20): Number of top results to return
- `otm_percent` (float, optional, default: 2.5): Minimum % out-of-the-money for short strikes
- `spread_width` (float, optional, default: 5): Width between short and long strikes in dollars
- `filters` (object, optional): Additional filters
  - `min_roi` (float): Minimum ROI %
  - `min_probability` (float): Minimum probability of profit %
  - `max_rsi` (float): Maximum RSI value

**Response:**
```json
{
  "success": true,
  "timestamp": "2025-12-04T10:30:00Z",
  "results": [
    {
      "symbol": "AAPL",
      "spot_price": 185.50,
      "strategies": [
        {
          "strategy": "Bull Put Spread",
          "composite_score": 85.5,
          "roi_percent": 25.5,
          "probability_success_percent": 65.2,
          "prob_max_profit": 58.1,
          "rsi": 45.3,
          "days_to_expiry": 14,
          "expiry": "2025-12-18",
          "short_strike": "180p",
          "long_strike": "175p",
          "credit": 1.25,
          "max_loss": 3.75,
          "breakeven": 178.75,
          "spread_width": 5.0
        }
      ]
    }
  ]
}
```

---

### 2. `/api/webhook/single-strategy` - Analyze Specific Strategy

**Method:** `POST`

**Authentication:** Required (API Key)

**Description:** Analyzes a specific options strategy for a single symbol.

**Request Body:**
```json
{
  "symbol": "AAPL",
  "strategy": "iron_condor",
  "max_days": 21,
  "otm_percent": 2.5,
  "spread_width": 5
}
```

**Parameters:**
- `symbol` (string, required): Stock ticker symbol
- `strategy` (string, required): Strategy type
  - Options: `bull_put`, `bear_call`, `iron_condor`, `covered_call`, `cash_put`, `long_call`, `bull_call`
- `max_days` (integer, optional, default: 21): Maximum days to expiration
- `otm_percent` (float, optional, default: 2.5): Minimum % OTM
- `spread_width` (float, optional, default: 5): Spread width in dollars

**Response:**
```json
{
  "success": true,
  "symbol": "AAPL",
  "strategy": "iron_condor",
  "timestamp": "2025-12-04T10:30:00Z",
  "result": {
    "strategy": "Iron Condor",
    "composite_score": 82.3,
    "roi_percent": 22.5,
    "probability_success_percent": 62.8,
    "short_strike": "180p",
    "long_strike": "190c",
    "credit": 2.50,
    "max_loss": 2.50,
    "breakeven": 182.50
  }
}
```

---

### 3. `/api/generate-key` - Generate API Key

**Method:** `POST`

**Authentication:** None (protect this in production!)

**Description:** Generates a new secure API key.

**Response:**
```json
{
  "api_key": "random_secure_32_character_key",
  "message": "Add this to your .env file as API_KEY=<key>",
  "note": "Store this securely - it will not be shown again"
}
```

---

## Integration Examples

### Bubble.io Integration

#### 1. API Connector Setup

1. **Install API Connector Plugin** in Bubble
2. **Add New API:**
   - Name: `Options Analysis API`
   - Authentication: `None` (we'll use headers)

3. **Create API Call: "Analyze Options"**
   - Use as: `Action`
   - Data type: `JSON`
   - Method: `POST`
   - URL: `https://your-app-url.com/api/webhook/analyze`
   
4. **Add Headers:**
   ```
   Key: Content-Type
   Value: application/json
   
   Key: X-API-Key
   Value: <dynamic> your_api_key_here
   ```

5. **Request Body:**
   ```json
   {
     "symbols": <dynamic>,
     "max_days": <dynamic>,
     "filters": {
       "min_roi": <dynamic>,
       "min_probability": <dynamic>
     }
   }
   ```

6. **Initialize Call** with test data to parse response structure

#### 2. Bubble Workflow Example

**Trigger:** Button clicked "Analyze Stocks"

**Actions:**
1. **API Call: Analyze Options**
   - symbols: `Input Stock Symbols's value split by ","` 
   - max_days: `Input Max Days's value`
   - min_roi: `Slider ROI's value`
   - min_probability: `Slider Probability's value`

2. **Display Results:**
   - Create Repeating Group
   - Data source: `Result of step 1's results`
   - Display fields: `Current cell's strategies:first item's strategy`, `roi_percent`, etc.

---

### Zapier Integration

#### 1. Webhook by Zapier

1. **Trigger:** Choose your trigger (e.g., "New Row in Google Sheets")
2. **Action:** `Webhooks by Zapier` → `POST`
3. **URL:** `https://your-app-url.com/api/webhook/analyze`
4. **Headers:**
   ```
   Content-Type: application/json
   X-API-Key: your_api_key_here
   ```
5. **Data:**
   ```json
   {
     "symbols": ["{{trigger.symbol}}"],
     "max_days": 21
   }
   ```

---

### JavaScript/React Integration

```javascript
async function analyzeOptions(symbols) {
  const response = await fetch('https://your-app-url.com/api/webhook/analyze', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-API-Key': 'your_api_key_here'
    },
    body: JSON.stringify({
      symbols: symbols,
      max_days: 21,
      filters: {
        min_roi: 10,
        min_probability: 40
      }
    })
  });
  
  const data = await response.json();
  
  if (data.success) {
    console.log('Results:', data.results);
    return data.results;
  } else {
    console.error('Error:', data.error);
    throw new Error(data.error);
  }
}

// Usage
analyzeOptions(['AAPL', 'MSFT', 'GOOGL'])
  .then(results => {
    results.forEach(stock => {
      console.log(`${stock.symbol}: ${stock.strategies.length} strategies`);
      stock.strategies.forEach(s => {
        console.log(`  - ${s.strategy}: ${s.composite_score} score`);
      });
    });
  });
```

---

### Python Integration

```python
import requests

def analyze_options(symbols, api_key):
    url = "https://your-app-url.com/api/webhook/analyze"
    headers = {
        "Content-Type": "application/json",
        "X-API-Key": api_key
    }
    payload = {
        "symbols": symbols,
        "max_days": 21,
        "filters": {
            "min_roi": 10,
            "min_probability": 40
        }
    }
    
    response = requests.post(url, json=payload, headers=headers)
    data = response.json()
    
    if data.get('success'):
        return data['results']
    else:
        raise Exception(data.get('error'))

# Usage
results = analyze_options(['AAPL', 'MSFT'], 'your_api_key_here')
for stock in results:
    print(f"{stock['symbol']}: {len(stock['strategies'])} strategies")
```

---

## Making Your App Publicly Accessible

### Option 1: GitHub Codespaces (Current Setup)

Your Codespace has a forwarded port. To make it public:

1. Go to **Ports** tab in VS Code
2. Find port **5000**
3. Right-click → **Port Visibility** → **Public**
4. Copy the **Forwarded Address** (e.g., `https://xxx-5000.app.github.dev`)
5. Use this URL in your external app

**Note:** Codespace URLs change when you rebuild. Not ideal for production.

---

### Option 2: Deploy to Render.com (Free)

1. **Push to GitHub:**
   ```bash
   git add .
   git commit -m "Add API endpoints"
   git push
   ```

2. **Connect to Render:**
   - Go to [render.com](https://render.com)
   - New → Web Service
   - Connect your GitHub repo
   - Configure:
     - Name: `options-analysis-api`
     - Environment: `Python 3`
     - Build Command: `pip install -r requirements.txt`
     - Start Command: `gunicorn app:app`
     - Add Environment Variable: `API_KEY=your_secure_key`

3. **Deploy** - Render will give you a public URL like `https://options-analysis-api.onrender.com`

---

### Option 3: Deploy to Heroku

```bash
# Install Heroku CLI, then:
heroku login
heroku create your-app-name
heroku config:set API_KEY=your_secure_key
git push heroku main
```

Your app will be at: `https://your-app-name.herokuapp.com`

---

### Option 4: Deploy to Railway.app

1. Go to [railway.app](https://railway.app)
2. New Project → Deploy from GitHub
3. Select your repo
4. Add environment variables
5. Deploy

---

## Security Best Practices

### Production Configuration

1. **Change API Key:**
   ```bash
   # Generate strong key
   python -c "import secrets; print(secrets.token_urlsafe(32))"
   ```

2. **Restrict CORS Origins:**
   ```python
   # In app.py, change from "*" to specific domains:
   CORS(app, resources={
       r"/api/*": {
           "origins": ["https://yourbubbleapp.bubbleapps.io"],
           ...
       }
   })
   ```

3. **Rate Limiting:**
   ```bash
   pip install Flask-Limiter
   ```
   
   ```python
   from flask_limiter import Limiter
   
   limiter = Limiter(
       app=app,
       key_func=lambda: request.headers.get('X-API-Key'),
       default_limits=["100 per hour"]
   )
   
   @app.route('/api/webhook/analyze')
   @limiter.limit("20 per minute")
   @require_api_key
   def webhook_analyze():
       ...
   ```

4. **HTTPS Only:**
   - Use SSL certificates (free with Render/Heroku)
   - Reject HTTP requests in production

5. **Environment Variables:**
   - Never commit `.env` file
   - Store `API_KEY` securely
   - Rotate keys periodically

---

## Testing the API

### Using cURL

```bash
# Test analyze endpoint
curl -X POST http://localhost:5000/api/webhook/analyze \
  -H "Content-Type: application/json" \
  -H "X-API-Key: dev-api-key-change-in-production" \
  -d '{
    "symbols": ["AAPL"],
    "max_days": 21
  }'

# Test single strategy
curl -X POST http://localhost:5000/api/webhook/single-strategy \
  -H "Content-Type: application/json" \
  -H "X-API-Key: dev-api-key-change-in-production" \
  -d '{
    "symbol": "AAPL",
    "strategy": "iron_condor"
  }'
```

### Using Postman

1. **Import Collection** (create `postman_collection.json`)
2. **Set Environment Variables:**
   - `base_url`: `http://localhost:5000`
   - `api_key`: `your_key_here`
3. **Create Requests** for each endpoint

---

## Error Handling

### Common Error Responses

**401 Unauthorized:**
```json
{
  "error": "Unauthorized",
  "message": "Invalid or missing API key"
}
```

**400 Bad Request:**
```json
{
  "error": "symbols array is required"
}
```

**404 Not Found:**
```json
{
  "error": "No options data for XYZ"
}
```

**500 Server Error:**
```json
{
  "success": false,
  "error": "Internal server error message",
  "timestamp": "2025-12-04T10:30:00Z"
}
```

---

## Support & Troubleshooting

### Check API Status
```bash
curl http://your-app-url.com/
```
Should return the main web interface (200 OK).

### Verify API Key
```bash
curl -X POST http://your-app-url.com/api/webhook/analyze \
  -H "X-API-Key: wrong_key" \
  -d '{}'
```
Should return 401 Unauthorized.

### Enable Debug Logging
```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

---

## Next Steps

1. ✅ Generate and secure your API key
2. ✅ Test endpoints locally
3. ✅ Deploy to a cloud platform
4. ✅ Configure CORS for your domain
5. ✅ Integrate with your external app (Bubble, etc.)
6. ✅ Add rate limiting and monitoring
7. ✅ Set up error tracking (Sentry, etc.)

---

**Last Updated:** December 4, 2025
**Version:** 1.0
