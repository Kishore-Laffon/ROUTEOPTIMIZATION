# 🚀 DEPLOYMENT GUIDE - RENDER

## Step 1: Prepare Your Repository (DONE ✅)
Your code is already pushed to GitHub:
- https://github.com/Kishore-Laffon/ROUTEOPTIMIZATION

## Step 2: Deploy on Render (Free)

### Option A: Using Render Dashboard (Easiest)

1. **Go to Render:** https://render.com

2. **Create Account** (sign up with GitHub for easier auth)

3. **Create New Web Service:**
   - Click "+ New" → "Web Service"
   - Connect GitHub repository: `Kishore-Laffon/ROUTEOPTIMIZATION`
   - Select `master` branch

4. **Configure Service:**
   ```
   Name: route-optimization-api
   Environment: Python 3
   Build Command: pip install -r requirements.txt
   Start Command: uvicorn demo_real_optimizer:app --host 0.0.0.0 --port 8000
   Plan: Free
   ```

5. **Add Environment Variables** (in Render dashboard):
   ```
   SECRET_KEY=your-random-secret-key-here
   SUPABASE_URL=https://your-project.supabase.co
   SUPABASE_KEY=sb_secret_YOUR_actual_key_from_supabase
   DEBUG=false
   ```

6. **Deploy:**
   - Click "Create Web Service"
   - Wait 2-3 minutes for deployment
   - Get your URL: `https://route-optimization-api.onrender.com`

### Option B: Using render.yaml (Advanced)

1. Push `render.yaml` to your repo (already created)
2. Go to https://render.com/dashboard
3. Click "New" → "Blueprint"
4. Connect your GitHub repo
5. Render automatically reads `render.yaml` and deploys

---

## Step 3: Share API with Friends

### Base URL
```
https://route-optimization-api.onrender.com
```

### API Documentation

#### 1. **Health Check** (Verify API is running)
```bash
GET https://route-optimization-api.onrender.com/health

Response:
{
  "status": "healthy",
  "service": "route-optimization-api"
}
```

#### 2. **Login** (Get token - optional)
```bash
POST https://route-optimization-api.onrender.com/token

Body:
{
  "username": "admin",
  "password": "admin123"
}

Response:
{
  "access_token": "eyJ0eXAiOiJKV1QiLCJhbGc...",
  "token_type": "bearer"
}
```

#### 3. **WebSocket Optimization** (Real-time route optimization)
```javascript
// Connect to WebSocket
const ws = new WebSocket('wss://route-optimization-api.onrender.com/ws/optimize?token=demo');

// Send locations
ws.send(JSON.stringify({
  type: "start_optimization",
  locations: [
    {"lat": 13.0827, "lng": 80.2707},  // Deposit
    {"lat": 13.0860, "lng": 80.2850},  // Stop 1
    {"lat": 13.0950, "lng": 80.2900}   // Stop 2
  ],
  client_job_id: "job_123"
}));

// Receive progress & results
ws.onmessage = (event) => {
  const data = JSON.parse(event.data);
  console.log(data.type); // "ready", "progress", "complete", "error"
};
```

#### 4. **Frontend Map Interface**
```
https://route-optimization-api.onrender.com/static/index_multi_route.html
```
- Click map to add delivery stops
- Click "Optimize Routes"
- View optimized routes with vehicle colors

---

## Step 4: Give Instructions to Your Friend

### For Integration (Developer)

Create a simple client script:

```python
import asyncio
import websockets
import json

async def optimize_routes(locations):
    """Optimize delivery routes via API"""
    uri = "wss://route-optimization-api.onrender.com/ws/optimize?token=demo"
    
    async with websockets.connect(uri) as websocket:
        # Send locations
        await websocket.send(json.dumps({
            "type": "start_optimization",
            "locations": locations,
            "client_job_id": "job_001"
        }))
        
        # Receive updates
        while True:
            response = await websocket.recv()
            data = json.parse(response)
            print(f"Event: {data['type']}")
            
            if data['type'] == 'complete':
                print(f"Routes: {data['routes']}")
                break
            elif data['type'] == 'error':
                print(f"Error: {data['message']}")
                break

# Test
locations = [
    {"lat": 13.0827, "lng": 80.2707},
    {"lat": 13.0860, "lng": 80.2850},
    {"lat": 13.0950, "lng": 80.2900},
]
asyncio.run(optimize_routes(locations))
```

### For Testing (No Code)

Use **curl** or **Postman**:

```bash
# Test health
curl https://route-optimization-api.onrender.com/health

# Login
curl -X POST https://route-optimization-api.onrender.com/token \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"admin123"}'
```

---

## Step 5: Troubleshooting

### Deployment Failed?

1. **Check Render logs:** Dashboard → Your Service → Logs
2. **Common issues:**
   - ❌ `ModuleNotFoundError` → Missing package in requirements.txt
   - ❌ `Port already in use` → Change port in start command
   - ❌ `Timeout` → Increase health check timeout

### API Not Responding?

1. Verify deployment status in Render dashboard
2. Check if free tier quota is exceeded (they have resource limits)
3. Test with curl: `curl https://your-app.onrender.com/health`

### WebSocket Connection Failed?

1. Ensure you're using `wss://` (secure WebSocket)
2. Check browser console for errors (F12)
3. Verify API is running: `https://your-app.onrender.com/health`

---

## Step 6: Production Checklist

- [ ] Change `SECRET_KEY` to random secure string
- [ ] Set `DEBUG=false` in environment
- [ ] Store sensitive keys in Render secrets, not code
- [ ] Test all API endpoints before sharing
- [ ] Monitor Render dashboard for resource usage
- [ ] Set up alerts for downtime (optional)
- [ ] Document API rate limits for users

---

## Costs

**Render Free Tier:**
- ✅ 0.5 GB RAM
- ✅ 1 shared CPU
- ✅ Automatic scaling
- ✅ HTTPS included
- ⚠️ Spins down after 15 min of inactivity (wake-up takes ~1 min)

**Paid tier ($7/month):** No spin-down, better performance

---

## Support Links

- Render Docs: https://render.com/docs
- FastAPI Deployment: https://fastapi.tiangolo.com/deployment/
- OR-Tools API: https://developers.google.com/optimization-js-reference/reference/google.maps.optimization_v1

Your API is now ready for friends to integrate! 🎉
