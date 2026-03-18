# 📡 Route Optimization API - Integration Guide

**Base URL:** `https://route-optimization-api.onrender.com`

---

## 🔌 Endpoints

### 1. Health Check
Check if API is running.

**Request:**
```bash
GET /health
```

**Response:**
```json
{
  "status": "healthy",
  "service": "route-optimization-api"
}
```

---

### 2. Login (Optional)
Get authentication token for secure access.

**Request:**
```bash
POST /token

Content-Type: application/json
{
  "username": "admin",
  "password": "admin123"
}
```

**Response:**
```json
{
  "access_token": "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9...",
  "token_type": "bearer"
}
```

---

### 3. WebSocket - Real-time Route Optimization ⭐
Connect via WebSocket for real-time optimization with progress tracking.

**Connection:**
```
wss://route-optimization-api.onrender.com/ws/optimize?token=demo
```

**Message Format - Start Optimization:**
```json
{
  "type": "start_optimization",
  "locations": [
    {"lat": 13.0827, "lng": 80.2707},
    {"lat": 13.0860, "lng": 80.2850},
    {"lat": 13.0950, "lng": 80.2900},
    {"lat": 13.1000, "lng": 80.2950}
  ],
  "client_job_id": "unique_job_id_123"
}
```

**Response Messages:**

#### Ready (Connection established)
```json
{
  "type": "ready",
  "message": "Connected and ready to optimize"
}
```

#### Progress (During optimization)
```json
{
  "type": "progress",
  "elapsed": 2.5,
  "total": 10
}
```

#### Complete (Routes calculated)
```json
{
  "type": "complete",
  "routes": [
    {
      "vehicle_id": 0,
      "stops": [0, 1, 3],
      "waypoints": [
        [13.0827, 80.2707],
        [13.0860, 80.2850],
        [13.0950, 80.2900]
      ],
      "distance": 15.7
    },
    {
      "vehicle_id": 1,
      "stops": [0, 2],
      "waypoints": [
        [13.0827, 80.2707],
        [13.1000, 80.2950]
      ],
      "distance": 12.3
    }
  ],
  "vehicles_used": 2,
  "total_distance_km": 28.0,
  "job_id": "unique_job_id_123"
}
```

#### Error
```json
{
  "type": "error",
  "message": "Error message here",
  "job_id": "unique_job_id_123"
}
```

---

## 💻 Integration Examples

### Python (Sync - requests)
```python
import requests
import json

# Health check
response = requests.get("https://route-optimization-api.onrender.com/health")
print(response.json())

# Login
response = requests.post(
    "https://route-optimization-api.onrender.com/token",
    json={"username": "admin", "password": "admin123"}
)
token = response.json()["access_token"]
```

### Python (Async - websockets)
```python
import asyncio
import json
import websockets

async def optimize_delivery_routes():
    """Optimize routes via WebSocket"""
    uri = "wss://route-optimization-api.onrender.com/ws/optimize?token=demo"
    
    locations = [
        {"lat": 13.0827, "lng": 80.2707},  # Depot
        {"lat": 13.0860, "lng": 80.2850},  # Stop 1
        {"lat": 13.0950, "lng": 80.2900},  # Stop 2
        {"lat": 13.1000, "lng": 80.2950},  # Stop 3
    ]
    
    async with websockets.connect(uri) as websocket:
        # Send optimization request
        await websocket.send(json.dumps({
            "type": "start_optimization",
            "locations": locations,
            "client_job_id": "job_001"
        }))
        
        # Listen for responses
        while True:
            message = await websocket.recv()
            data = json.loads(message)
            
            if data["type"] == "ready":
                print("✓ Connected and ready")
            
            elif data["type"] == "progress":
                progress = (data["elapsed"] / data["total"]) * 100
                print(f"Progress: {progress:.0f}%")
            
            elif data["type"] == "complete":
                print(f"\n✓ Optimization Complete!")
                print(f"Routes: {len(data['routes'])}")
                print(f"Total Distance: {data['total_distance_km']} km")
                print(f"Vehicles Used: {data['vehicles_used']}")
                
                # Print each route
                for route in data["routes"]:
                    print(f"\nVehicle {route['vehicle_id']}:")
                    print(f"  Stops: {route['stops']}")
                    print(f"  Distance: {route['distance']} km")
                break
            
            elif data["type"] == "error":
                print(f"✗ Error: {data['message']}")
                break

# Run
asyncio.run(optimize_delivery_routes())
```

### JavaScript (Browser)
```javascript
async function optimizeRoutes() {
  const locations = [
    { lat: 13.0827, lng: 80.2707 },  // Depot
    { lat: 13.0860, lng: 80.2850 },  // Stop 1
    { lat: 13.0950, lng: 80.2900 },  // Stop 2
    { lat: 13.1000, lng: 80.2950 },  // Stop 3
  ];

  const ws = new WebSocket('wss://route-optimization-api.onrender.com/ws/optimize?token=demo');

  ws.onopen = () => {
    console.log('Connected');
    ws.send(JSON.stringify({
      type: 'start_optimization',
      locations: locations,
      client_job_id: 'job_001'
    }));
  };

  ws.onmessage = (event) => {
    const data = JSON.parse(event.data);
    
    switch (data.type) {
      case 'ready':
        console.log('✓ Ready to optimize');
        break;
      
      case 'progress':
        const progress = (data.elapsed / data.total) * 100;
        console.log(`Progress: ${progress.toFixed(0)}%`);
        break;
      
      case 'complete':
        console.log('✓ Routes optimized!');
        console.log(`Routes: ${data.routes.length}`);
        console.log(`Total Distance: ${data.total_distance_km} km`);
        
        // Draw routes on map
        data.routes.forEach(route => {
          console.log(`Vehicle ${route.vehicle_id}: ${route.stops.join(' → ')}`);
        });
        ws.close();
        break;
      
      case 'error':
        console.error(`Error: ${data.message}`);
        ws.close();
        break;
    }
  };

  ws.onerror = (error) => {
    console.error('WebSocket error:', error);
  };
}

optimizeRoutes();
```

### JavaScript (Node.js)
```javascript
const WebSocket = require('ws');

async function optimizeRoutes() {
  const uri = 'wss://route-optimization-api.onrender.com/ws/optimize?token=demo';
  const ws = new WebSocket(uri);

  const locations = [
    { lat: 13.0827, lng: 80.2707 },
    { lat: 13.0860, lng: 80.2850 },
    { lat: 13.0950, lng: 80.2900 },
  ];

  ws.on('open', () => {
    console.log('✓ Connected');
    ws.send(JSON.stringify({
      type: 'start_optimization',
      locations: locations,
      client_job_id: 'job_001'
    }));
  });

  ws.on('message', (message) => {
    const data = JSON.parse(message);
    
    if (data.type === 'complete') {
      console.log('✓ Routes:', data.routes);
      ws.close();
    } else if (data.type === 'error') {
      console.error('Error:', data.message);
      ws.close();
    }
  });
}

optimizeRoutes();
```

### cURL
```bash
# Health check
curl https://route-optimization-api.onrender.com/health

# Login
curl -X POST https://route-optimization-api.onrender.com/token \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"admin123"}'
```

### Postman Collection
```json
{
  "info": {
    "name": "Route Optimization API",
    "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json"
  },
  "item": [
    {
      "name": "Health Check",
      "request": {
        "method": "GET",
        "url": "https://route-optimization-api.onrender.com/health"
      }
    },
    {
      "name": "Login",
      "request": {
        "method": "POST",
        "url": "https://route-optimization-api.onrender.com/token",
        "body": {
          "mode": "raw",
          "raw": "{\"username\":\"admin\",\"password\":\"admin123\"}"
        }
      }
    }
  ]
}
```

---

## 📊 Example: Delivery Scenario

**Problem:** 10 stops to deliver, optimize routes for 3 vehicles

**Locations (Lat, Lng):**
```
Depot:     13.0827, 80.2707 (Starting point)
Stop 1:    13.0860, 80.2850
Stop 2:    13.0950, 80.2900
Stop 3:    13.1000, 80.2950
... 
Stop 10:   13.1200, 80.3050
```

**API Response:**
```json
{
  "routes": [
    {
      "vehicle_id": 0,
      "stops": [0, 1, 4, 7],
      "distance": 45.3,
      "waypoints": [[13.0827, 80.2707], ...]
    },
    {
      "vehicle_id": 1,
      "stops": [0, 2, 5, 8],
      "distance": 52.1,
      "waypoints": [[13.0827, 80.2707], ...]
    },
    {
      "vehicle_id": 2,
      "stops": [0, 3, 6, 9, 10],
      "distance": 61.8,
      "waypoints": [[13.0827, 80.2707], ...]
    }
  ],
  "total_distance_km": 159.2,
  "vehicles_used": 3
}
```

---

## ⚠️ Limits & Considerations

| Feature | Limit |
|---------|-------|
| Max stops per optimization | 100+ |
| Max optimization time | 85 seconds |
| Max vehicles | Unlimited |
| API timeout | 30 seconds |
| Concurrent connections | 10 (free tier) |

---

## 🔐 Authentication

- Default token: `demo` (no password needed)
- Or login to get JWT token
- Token is optional for demo endpoints

---

## 📞 Support

For issues:
1. Check health endpoint: `/health`
2. Review browser console (F12) for WebSocket errors
3. Check Render dashboard logs
4. Verify network connectivity (may need VPN in some regions)

---

**Ready to integrate?** Start with the Python async example above! 🚀
