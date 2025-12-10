# Stratify - Google OAuth Setup Guide

## 1. Create Google OAuth Credentials

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project or select existing one
3. Navigate to **APIs & Services** > **Credentials**
4. Click **Create Credentials** > **OAuth client ID**
5. Configure OAuth consent screen if prompted:
   - User Type: External
   - App name: Stratify
   - User support email: your email
   - Developer contact: your email
6. Application type: **Web application**
7. Add authorized redirect URIs:
   - Development: `http://localhost:5000/auth/callback`
   - Production: `https://yourdomain.com/auth/callback` (replace with your actual domain)
8. Click **Create**
9. Copy the **Client ID** and **Client Secret**

## 2. Configure Environment Variables

Create a `.env` file in the project root:

```bash
cp .env.example .env
```

Edit `.env` and add your credentials:

```
GOOGLE_CLIENT_ID=your_actual_client_id.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=your_actual_client_secret
SECRET_KEY=run_this_command_to_generate_key
FLASK_ENV=development
```

Generate a secure secret key:
```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

Copy the output and paste it as the `SECRET_KEY` value.

## 3. Update for Production

When deploying to production (Render, Railway, etc.):

1. Add environment variables in your platform's dashboard:
   - `GOOGLE_CLIENT_ID`
   - `GOOGLE_CLIENT_SECRET`
   - `SECRET_KEY`
   - `FLASK_ENV=production`

2. Update authorized redirect URIs in Google Console:
   - Add your production URL: `https://yourapp.onrender.com/auth/callback`

## 4. Run the Application

Development:
```bash
python app.py
```

The app will run on `http://localhost:5000`

## 5. Test Authentication

1. Navigate to `http://localhost:5000`
2. Click "Sign in with Google"
3. Authorize the app
4. You should be redirected back and logged in

## Security Notes

- Never commit `.env` file to git (it's in `.gitignore`)
- Use different OAuth credentials for development and production
- SECRET_KEY must be a long random string in production
- Enable HTTPS in production (automatic on Render/Railway)

## Troubleshooting

**Error: redirect_uri_mismatch**
- Make sure the redirect URI in Google Console exactly matches your app URL
- Include `/auth/callback` path

**Error: invalid_client**
- Double-check GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in `.env`
- Ensure no extra spaces or quotes

**Session not persisting**
- Verify SECRET_KEY is set
- Check browser allows cookies
