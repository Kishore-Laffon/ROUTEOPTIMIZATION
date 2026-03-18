# Vehicle Animation Integration Guide

## Problem
You have two UIs now:
1. **index.html** - Route calculation and display (polyline on map)
2. **animation.html** - Vehicle animation with live stats

## Solution: Unified System

### Option 1: Use Animation in New Tab (Quickest)
Share the animation URL with waypoints:
```javascript
// After route calculation, redirect to:
const waypoints = data.waypoints; // From websocket complete event
const encoded = btoa(JSON.stringify(waypoints)); // Base64 encode
window.open(`/animation.html?route=${encoded}`, '_blank');
```

### Option 2: Merge Animations (Recommended)
Add vehicle animation capabilities to **index.html** using the VehicleAnimationEngine.

#### Step 1: Add Animation Controls to Sidebar
After the route is drawn, show animation controls:

```html
<!-- Add to index.html sidebar after route info section -->
<div class="section">
    <div class="section-title">Vehicle Animation</div>
    <div class="controls">
        <button id="animateVehicleBtn" onclick="startVehicleAnimation()" disabled>
            🎬 Animate Vehicle
        </button>
    </div>
    <div id="animationStats" style="display: none;">
        <div class="stat">
            <span class="stat-label">Animation Speed</span>
            <span class="stat-value" id="animSpeed">60 km/h</span>
        </div>
        <div class="stat">
            <span class="stat-label">Distance Covered</span>
            <span class="stat-value" id="animDistance">0 km</span>
        </div>
    </div>
</div>
```

#### Step 2: Add Animation Engine to index.html
Replace the WebSocket handling with integrated animation:

```javascript
// Global animation object (add to index.html)
let vehicleAnimator = null;

// When route calculation completes:
function handleWebSocketMessage(data) {
    if (data.type === 'complete') {
        // Draw route polyline (existing code)
        drawRoute(data);
        
        // Initialize vehicle animator if not already done
        if (!vehicleAnimator) {
            vehicleAnimator = new VehicleAnimationEngine(map, data.waypoints);
        } else {
            vehicleAnimator.loadRoute(data.waypoints);
        }
        
        // Enable animation button
        document.getElementById('animateVehicleBtn').disabled = false;
    }
}

// Start animation when user clicks button
function startVehicleAnimation() {
    if (vehicleAnimator) {
        vehicleAnimator.startAnimation();
        document.getElementById('animationStats').style.display = 'block';
    }
}
```

### Option 3: Replace index.html with animation.html
If you only want the animation interface:
```bash
cp animation.html index.html
```

---

## WebSocket Integration

To send **live vehicle positions** from backend to animate in real-time:

### Backend (demo_simple.py or your route handler)
```python
# Send vehicle position updates during optimization
async def optimization_loop():
    for waypoint in optimized_waypoints:
        # ... optimization logic ...
        
        # Send current vehicle position
        await websocket.send_json({
            "type": "vehicle_location",
            "latitude": vehicle_lat,
            "longitude": vehicle_lng,
            "bearing": vehicle_bearing,
            "speed": vehicle_speed_kmh,
            "job_id": job_id
        })
        
        await asyncio.sleep(0.5)  # Update every 500ms
```

### Frontend (animation.html)
```javascript
// Add to WebSocket message handler
if (data.type === 'vehicle_location') {
    vehicleAnimator.updateFromLiveData({
        lat: data.latitude,
        lng: data.longitude,
        bearing: data.bearing,
        speed: data.speed
    });
}
```

---

## Customization

### Change Vehicle Icon
Edit in **animation.html** around line 350:
```html
<!-- Change emoji or use image -->
<img src="/assets/truck-icon.png" style="width: 100%; height: 100%;" />
<!-- Or change emoji -->
🚗, 🚙, 🏎️, 🚛, ...
```

### Change Default Animation Speed
In animation.html, line 125:
```javascript
this.speedKmh = 80;  // Change from 60 to 80 km/h
```

### Adjust Colors
Change gradient in animation.html styles:
```css
background: linear-gradient(135deg, #ff6b6b 0%, #ee5a6f 100%);
```

### Disable Follow Mode by Default
In animation.html, line 127:
```javascript
this.followMode = false;  // Don't center map on vehicle
```

---

## Testing Checklist

- [ ] Load animation.html and see example route
- [ ] Click Play - vehicle should move smoothly
- [ ] Adjust speed multiplier slider
- [ ] Watch bearing rotate with direction
- [ ] ETA should count down
- [ ] Distance covered should increase
- [ ] Follow mode centers on vehicle
- [ ] Pause/Resume works correctly
- [ ] Reset returns to start

---

## Performance Notes

- Uses `requestAnimationFrame` for smooth 60fps animation
- Only updates marker position, not full map re-render
- Haversine distance calculation is O(n) on route load only
- Interpolation is O(1) per frame - very efficient

---

## Troubleshooting

**Vehicle not moving?**
- Check console for [ANIMATION] logs
- Verify route has at least 2 points
- Ensure Play button isn't disabled

**Map not following?**
- Toggle follow mode off/on with 📍 button
- Check console for panTo errors

**ETA showing wrong time?**
- Verify speed multiplier matches your expectation
- ETA is calculated as: remaining_km / (speed_kmh * multiplier)

---

## Next Steps

1. **Try animation.html** as standalone tool
2. **Integrate with index.html** for unified experience
3. **Connect live GPS** from backend via WebSocket
4. **Customize styling** to match your branding
5. **Deploy to production** on your server
