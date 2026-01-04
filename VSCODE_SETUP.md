# How to Run ResumeHub in VS Code

## Quick Start

### Method 1: Using VS Code Integrated Terminal (Recommended)

1. **Open the project in VS Code**
   - Open VS Code
   - File → Open Folder
   - Select `AI-Resume-Parser` folder

2. **Open two terminals** (Terminal → New Terminal)

3. **Terminal 1: Start Backend**
   ```bash
   python -m uvicorn main:app --reload --port 8000
   ```

4. **Terminal 2: Start Frontend** (Optional - see note below)
   ```bash
   python -m http.server 3000 --directory "resumehub-frontend/public"
   ```

5. **Access the application**
   - Open browser: `http://localhost:3000/index.html`
   - Or directly from backend: `http://localhost:8000/`

> **Note**: After the recent updates, you can access the frontend directly from `http://localhost:8000/` without running the separate frontend server!

---

## Method 2: Using VS Code Tasks (One-Click Start)

Create a `.vscode/tasks.json` file in your project:

```json
{
    "version": "2.0.0",
    "tasks": [
        {
            "label": "Start Backend",
            "type": "shell",
            "command": "python -m uvicorn main:app --reload --port 8000",
            "isBackground": true,
            "problemMatcher": [],
            "presentation": {
                "reveal": "always",
                "panel": "new"
            }
        },
        {
            "label": "Start Frontend",
            "type": "shell",
            "command": "python -m http.server 3000 --directory resumehub-frontend/public",
            "isBackground": true,
            "problemMatcher": [],
            "presentation": {
                "reveal": "always",
                "panel": "new"
            }
        },
        {
            "label": "Start ResumeHub",
            "dependsOn": ["Start Backend", "Start Frontend"],
            "problemMatcher": []
        }
    ]
}
```

**To use:**
1. Press `Ctrl+Shift+P` (or `Cmd+Shift+P` on Mac)
2. Type "Tasks: Run Task"
3. Select "Start ResumeHub"

---

## Method 3: Using VS Code Launch Configuration

Create a `.vscode/launch.json` file:

```json
{
    "version": "0.2.0",
    "configurations": [
        {
            "name": "Python: FastAPI",
            "type": "debugpy",
            "request": "launch",
            "module": "uvicorn",
            "args": [
                "main:app",
                "--reload",
                "--port",
                "8000"
            ],
            "jinja": true,
            "justMyCode": false
        }
    ]
}
```

**To use:**
1. Press `F5` or click the "Run and Debug" icon
2. Select "Python: FastAPI"
3. Backend will start with debugging enabled

---

## Simplified Setup (Backend Only)

Since the backend now serves the frontend, you only need:

```bash
python -m uvicorn main:app --reload --port 8000
```

Then open: `http://localhost:8000/`

---

## Troubleshooting

### Port Already in Use
```bash
# Windows - Kill process on port 8000
netstat -ano | findstr :8000
taskkill /PID <PID> /F

# Or use PowerShell
Stop-Process -Id (Get-NetTCPConnection -LocalPort 8000).OwningProcess -Force
```

### Module Not Found
```bash
pip install -r requirements.txt
python -m spacy download en_core_web_sm
```

### Environment Variables
Make sure `.env` file exists with:
```
GEMINI_API_KEY=your_api_key_here
```

---

## VS Code Extensions (Recommended)

- **Python** (Microsoft)
- **Pylance** (Microsoft)
- **Thunder Client** (for API testing)
- **Live Server** (alternative for frontend)

---

## Keyboard Shortcuts

- **New Terminal**: `` Ctrl+` ``
- **Split Terminal**: `Ctrl+Shift+5`
- **Run Task**: `Ctrl+Shift+P` → "Tasks: Run Task"
- **Start Debugging**: `F5`
- **Stop Debugging**: `Shift+F5`

---

## Current Status

✅ Backend is running on port 8000
✅ Frontend server on port 3000 (optional)
✅ Application accessible at `http://localhost:3000/` or `http://localhost:8000/`

**You're all set!** Just run the backend and access the app in your browser.
