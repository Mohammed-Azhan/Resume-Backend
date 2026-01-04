# Railway Deployment Guide

## Prerequisites
- GitHub account
- Railway account (sign up at [railway.app](https://railway.app))
- Google Gemini API key

## Step-by-Step Deployment

### 1. Push Code to GitHub

```bash
# Initialize git (if not already done)
git init

# Add all files
git add .

# Commit changes
git commit -m "Prepare for Railway deployment"

# Create a new repository on GitHub, then:
git remote add origin https://github.com/YOUR_USERNAME/AI-Resume-Parser.git
git branch -M main
git push -u origin main
```

### 2. Create Railway Project

1. Go to [railway.app](https://railway.app) and sign in
2. Click "New Project"
3. Select "Deploy from GitHub repo"
4. Choose your `AI-Resume-Parser` repository
5. Railway will automatically detect the configuration

### 3. Add PostgreSQL Database

1. In your Railway project dashboard, click "New"
2. Select "Database" → "PostgreSQL"
3. Railway will automatically create a PostgreSQL database
4. The `DATABASE_URL` environment variable will be automatically set

### 4. Configure Environment Variables

In your Railway project settings, add the following environment variables:

| Variable | Value | Description |
|----------|-------|-------------|
| `GEMINI_API_KEY` | `your_api_key_here` | Your Google Gemini API key |
| `PORT` | (auto-set by Railway) | Application port |
| `DATABASE_URL` | (auto-set by Railway) | PostgreSQL connection string |

**To add environment variables:**
1. Click on your service in Railway
2. Go to "Variables" tab
3. Click "New Variable"
4. Add `GEMINI_API_KEY` with your actual API key

### 5. Deploy

Railway will automatically deploy your application. The deployment process:

1. **Build Phase**:
   - Installs Python dependencies from `requirements.txt`
   - Downloads spaCy language model (`en_core_web_sm`)

2. **Deploy Phase**:
   - Starts the application using the `Procfile`
   - Creates database tables automatically
   - Serves frontend from root URL

### 6. Access Your Application

Once deployed, Railway will provide you with a URL like:
```
https://your-app-name.up.railway.app
```

Visit this URL to access your ResumeHub application!

## Configuration Files

### `Procfile`
```
web: uvicorn main:app --host 0.0.0.0 --port $PORT
```

### `railway.json`
```json
{
  "$schema": "https://railway.app/railway.schema.json",
  "build": {
    "builder": "NIXPACKS",
    "buildCommand": "pip install -r requirements.txt && python -m spacy download en_core_web_sm"
  },
  "deploy": {
    "startCommand": "uvicorn main:app --host 0.0.0.0 --port $PORT",
    "restartPolicyType": "ON_FAILURE",
    "restartPolicyMaxRetries": 10
  }
}
```

## Database Configuration

The application automatically detects the environment:

- **Production (Railway)**: Uses PostgreSQL via `DATABASE_URL`
- **Local Development**: Uses SQLite (`resume_parser.db`)

No manual configuration needed!

## Frontend Configuration

The frontend automatically detects the environment:

- **Production**: Uses `window.location.origin` as API base URL
- **Local**: Uses `http://localhost:8000` as API base URL

## Troubleshooting

### Build Fails

**Issue**: spaCy model download fails
**Solution**: Check the build logs. Railway should automatically download the model. If it fails, you can add it to the build command in `railway.json`.

### Database Connection Error

**Issue**: Cannot connect to PostgreSQL
**Solution**: 
1. Ensure PostgreSQL service is added to your project
2. Check that `DATABASE_URL` is set in environment variables
3. Restart the deployment

### API Key Error

**Issue**: "GEMINI_API_KEY not found"
**Solution**: 
1. Go to Railway project settings
2. Add `GEMINI_API_KEY` environment variable
3. Redeploy the application

### Frontend Not Loading

**Issue**: Getting JSON response instead of HTML
**Solution**: 
1. Ensure the `resumehub-frontend` folder is in your repository
2. Check that the path in `main.py` is correct
3. Redeploy

## Monitoring

Railway provides built-in monitoring:

1. **Logs**: View real-time application logs
2. **Metrics**: CPU, memory, and network usage
3. **Deployments**: History of all deployments

Access these from your Railway project dashboard.

## Updating Your Application

To deploy updates:

```bash
# Make your changes
git add .
git commit -m "Your update message"
git push origin main
```

Railway will automatically detect the push and redeploy!

## Cost

Railway offers:
- **Free Tier**: $5 of usage per month (sufficient for testing)
- **Pro Plan**: $20/month for production use

PostgreSQL database is included in your usage.

## Security Recommendations

1. **Never commit `.env` file** - It's already in `.gitignore`
2. **Use Railway environment variables** for sensitive data
3. **Enable HTTPS** - Railway provides this automatically
4. **Restrict CORS** in production (optional):
   - Set `ALLOWED_ORIGINS` environment variable
   - Example: `https://your-app.up.railway.app`

## Next Steps

After deployment:

1. ✅ Test resume upload
2. ✅ Test AI analysis
3. ✅ Test AI suggestions
4. ✅ Verify database persistence
5. ✅ Share your app URL!

## Support

- Railway Documentation: https://docs.railway.app
- Railway Discord: https://discord.gg/railway
- Project Issues: GitHub repository issues

---

**Your ResumeHub application is now live on Railway! 🚀**
