# 🚀 Route Optimization API - Share with Your Friend

**Your API is ready to use!** Share this document with your friend to integrate.

---

## ⚡ Quick Start (2 minutes)

### 1. Test the API
```bash
# Check if API is running
curl https://route-optimization-api.onrender.com/health

# Response:
# {"status": "healthy", "service": "route-optimization-api"}
```

### 2. Run the Example
```bash
# Install
pip install websockets

# Download and run example
python friend_example.py
```

### 3. Integrate into Your Code

**Python:**
```python
import asyncio, json, websockets

async def get_optimized_routes(locations):
    uri = "wss://route-optimization-api.onrender.com/ws/optimize?token=demo"
    async with websockets.connect(uri) as ws:
        await ws.send(json.dumps({
            "type": "start_optimization",
            "locations": locations,
            "client_job_id": "my_job_001"
        }))
        async for msg in ws:
            data = json.loads(msg)
            if data["type"] == "complete":
                return data["routes"]

# Use it
locations = [
    {"lat": 13.0827, "lng": 80.2707},  # Start point
    {"lat": 13.0860, "lng": 80.2850},  # Delivery 1
    {"lat": 13.0950, "lng": 80.2900},  # Delivery 2
]
routes = asyncio.run(get_optimized_routes(locations))
print(routes)
```

**JavaScript (Node.js):**
```javascript
const WebSocket = require('ws');

const ws = new WebSocket('wss://route-optimization-api.onrender.com/ws/optimize?token=demo');

ws.on('open', () => {
  ws.send(JSON.stringify({
    type: 'start_optimization',
    locations: [
      { lat: 13.0827, lng: 80.2707 },
      { lat: 13.0860, lng: 80.2850 },
      { lat: 13.0950, lng: 80.2900 }
    ],
    client_job_id: 'job_123'
  }));
});

ws.on('message', (message) => {
  const data = JSON.parse(message);
  if (data.type === 'complete') {
    console.log('Routes:', data.routes);
    console.log('Total Distance:', data.total_distance_km, 'km');
  }
});
```

---

## 📡 API Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/health` | GET | Check API status |
| `/token` | POST | Get authentication token |
| `/ws/optimize` | WebSocket | Real-time route optimization |
| `/static/index_multi_route.html` | GET | Interactive map interface |

---

## 🔌 WebSocket Connection

**URL:** `wss://route-optimization-api.onrender.com/ws/optimize?token=demo`

**Send:** Location list for optimization
```json
{
  "type": "start_optimization",
  "locations": [
    {"lat": 13.0827, "lng": 80.2707},
    {"lat": 13.0860, "lng": 80.2850}
  ],
  "client_job_id": "unique_id"
}
```

**Receive:** Routes, distance, vehicle assignments
```json
{
  "type": "complete",
  "routes": [
    {
      "vehicle_id": 0,
      "stops": [0, 1],
      "distance": 15.5,
      "waypoints": [[13.0827, 80.2707], [13.0860, 80.2850]]
    }
  ],
  "total_distance_km": 15.5,
  "vehicles_used": 1
}
```

---

## 💡 Use Cases

- **Delivery optimization** - Minimize distance, reduce fuel costs
- **Fleet routing** - Assign stops to vehicles
- **Real-time tracking** - Monitor multiple vehicles
- **Logistics planning** - Plan daily delivery schedules
- **Route planning** - Get actual street routing (not straight lines)

---

## 📝 Sample Response

```python
{
  "type": "complete",
  "routes": [
    {
      "vehicle_id": 0,
      "stops": [0, 1, 3],           # Indices of delivery stops
      "distance": 28.5,              # Total distance in km
      "waypoints": [                 # Full path with intermediate points
        [13.0827, 80.2707],          # Start
        [13.0835, 80.2720],          # Route point 1
        [13.0860, 80.2850],          # Delivery 1
        [13.0950, 80.2900]           # Delivery 2
      ]
    },
    {
      "vehicle_id": 1,
      "stops": [0, 2],
      "distance": 22.3,
      "waypoints": [[13.0827, 80.2707], [13.1000, 80.2950]]
    }
  ],
  "total_distance_km": 50.8,          # Sum of all routes
  "vehicles_used": 2,                 # Total vehicles needed
  "job_id": "unique_id"
}
```

---

## 🎯 Step-by-Step Integration

### Step 1: Parse Input
Get your delivery locations (lat/lng pairs)

### Step 2: Connect
Create WebSocket connection to API

### Step 3: Send Locations
Send locations list for optimization

### Step 4: Listen for Updates
- `ready` → API connected
- `progress` → Optimization in progress
- `complete` → Routes calculated
- `error` → Something went wrong

### Step 5: Use the Routes
Extract `routes` array and use for delivery sequencing

---

## ⚙️ Configuration

No configuration needed! The API works with:
- ✓ Any number of stops (tested with 100+)
- ✓ Any coordinates (lat/lng format)
- ✓ Any vehicle count
- ✓ Automatic distance calculation
- ✓ Real street routing (via OSRM)

---

## 🐛 Troubleshooting

| Problem | Solution |
|---------|----------|
| Connection refused | Check if API is deployed (see status below) |
| Timeout | Increase timeout, API takes up to 85s to optimize |
| No routes returned | Check coordinates are realistic (valid lat/lng) |
| WebSocket error | Use `wss://` not `ws://`, must be over HTTPS |

---

## 📊 Performance

- **Max stops**: 100+ (tested with OR-Tools)
- **Max time**: 85 seconds per optimization
- **Max vehicles**: Unlimited
- **Average optimization**: 2-10 seconds for 10-20 stops

---

## 🔗 Resources

- **Full Docs:** `API_DOCUMENTATION.md`
- **Deployment:** `DEPLOYMENT.md`
- **Example Code:** `friend_example.py`
- **Repository:** https://github.com/Kishore-Laffon/ROUTEOPTIMIZATION

---

## 🆘 Need Help?

1. **Check API Status:** https://route-optimization-api.onrender.com/health
2. **Review Examples:** Look at `friend_example.py`
3. **Read Docs:** Check `API_DOCUMENTATION.md` for detailed specs
4. **Test in Browser:** Open `/static/index_multi_route.html` for interactive demo

---

## ✅ What You Can Do

With this API, you can:
1. ✓ Optimize delivery routes
2. ✓ Calculate distances between coordinates
3. ✓ Assign stops to vehicles
4. ✓ Get real street paths (not straight lines)
5. ✓ Track progress in real-time
6. ✓ Scale to 100+ stops
7. ✓ Use with any programming language
8. ✓ Integrate into your own system

---

## 🎉 Start Building!

Ready to optimize your delivery routes? Here's the next step:

```python
# Copy this and start building!
import asyncio, json, websockets

async def optimize(locations):
    uri = "wss://route-optimization-api.onrender.com/ws/optimize?token=demo"
    async with websockets.connect(uri) as ws:
        await ws.send(json.dumps({
            "type": "start_optimization",
            "locations": locations,
            "client_job_id": "my_first_job"
        }))
        async for msg in ws:
            data = json.loads(msg)
            if data["type"] == "complete":
                # You got the optimized routes!
                for route in data["routes"]:
                    print(f"Vehicle {route['vehicle_id']}: {route['stops']}")

asyncio.run(optimize([
    {"lat": 13.0827, "lng": 80.2707},
    {"lat": 13.0860, "lng": 80.2850},
]))
```

That's it! Your API is live and ready to integrate. 🚀
