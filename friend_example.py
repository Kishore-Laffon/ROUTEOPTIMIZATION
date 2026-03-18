"""
Route Optimization API - Friend Integration Template
Simple example to get started with the API

Install: pip install websockets
Run: python friend_example.py
"""

import asyncio
import json
import websockets
import time

# ============================================================================
# CONFIGURATION
# ============================================================================

API_URL = "wss://route-optimization-api.onrender.com/ws/optimize?token=demo"

# Example delivery stops (lat, lng)
SAMPLE_LOCATIONS = [
    {"lat": 13.0827, "lng": 80.2707, "name": "Depot (Start)"},
    {"lat": 13.0860, "lng": 80.2850, "name": "Stop 1: Office A"},
    {"lat": 13.0950, "lng": 80.2900, "name": "Stop 2: Office B"},
    {"lat": 13.1000, "lng": 80.2950, "name": "Stop 3: Warehouse"},
    {"lat": 13.0900, "lng": 80.2750, "name": "Stop 4: Store"},
    {"lat": 13.1050, "lng": 80.2800, "name": "Stop 5: Hub"},
]

# ============================================================================
# MAIN FUNCTION
# ============================================================================

async def optimize_delivery_routes(locations, job_id="friend_demo_001"):
    """
    Connect to route optimization API and optimize delivery routes.
    
    Args:
        locations: List of dicts with 'lat' and 'lng' keys
        job_id: Unique identifier for this optimization job
    """
    
    print("\n" + "="*70)
    print("🚀 ROUTE OPTIMIZATION API - FRIEND DEMO")
    print("="*70)
    print(f"\nConnecting to: {API_URL}")
    print(f"Optimizing {len(locations)} delivery stops...\n")
    
    try:
        async with websockets.connect(API_URL) as ws:
            print("✓ Connected to API\n")
            
            # Send optimization request
            request = {
                "type": "start_optimization",
                "locations": locations,
                "client_job_id": job_id
            }
            
            print(f"📤 Sending {len(locations)} delivery stops...")
            await ws.send(json.dumps(request))
            
            # Listen for responses
            start_time = time.time()
            while True:
                message = await ws.recv()
                data = json.loads(message)
                
                # Handle different message types
                if data["type"] == "ready":
                    print("✓ API is ready\n")
                
                elif data["type"] == "progress":
                    progress = (data["elapsed"] / data["total"]) * 100
                    print(f"⏳ Optimizing... {progress:.0f}% complete", end="\r")
                
                elif data["type"] == "complete":
                    elapsed = time.time() - start_time
                    print(f"\n\n✓ OPTIMIZATION COMPLETE in {elapsed:.2f}s!\n")
                    print_routes(data)
                    break
                
                elif data["type"] == "error":
                    print(f"\n✗ Error: {data['message']}")
                    break
    
    except Exception as e:
        print(f"✗ Connection Error: {e}")
        print("💡 Tip: Make sure the API is deployed on Render first!")

# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def print_routes(response):
    """Pretty print the optimized routes"""
    
    print("="*70)
    print("OPTIMIZATION RESULTS")
    print("="*70)
    
    # Summary
    print(f"\n📊 Summary:")
    print(f"   Total Routes: {len(response['routes'])}")
    print(f"   Vehicles Used: {response['vehicles_used']}")
    print(f"   Total Distance: {response['total_distance_km']} km\n")
    
    # Detailed routes
    print("📍 ROUTES:\n")
    colors = ["🔴", "🟢", "🔵", "🟡", "🟣"]
    
    for i, route in enumerate(response['routes']):
        color = colors[i % len(colors)]
        print(f"{color} Vehicle {route['vehicle_id']}:")
        print(f"   Stops: {route['stops']}")
        print(f"   Distance: {route['distance']} km")
        
        # Show waypoints
        if route.get('waypoints'):
            waypoint_count = len(route['waypoints'])
            print(f"   Path Points: {waypoint_count}")
            print(f"   Coordinates:")
            for j, wp in enumerate(route['waypoints'][:3]):  # Show first 3
                print(f"      {j+1}. [{wp[0]:.4f}, {wp[1]:.4f}]")
            if waypoint_count > 3:
                print(f"      ... ({waypoint_count - 3} more)")
        print()

def print_locations(locations):
    """Pretty print the input locations"""
    print("\n📌 INPUT LOCATIONS:")
    for i, loc in enumerate(locations):
        name = loc.get('name', f'Location {i}')
        print(f"   {i}. {name}: [{loc['lat']:.4f}, {loc['lng']:.4f}]")
    print()

# ============================================================================
# EXAMPLE USAGE
# ============================================================================

async def main():
    """Run the optimization demo"""
    
    print_locations(SAMPLE_LOCATIONS)
    
    # Optimize routes
    await optimize_delivery_routes(SAMPLE_LOCATIONS)
    
    print("\n" + "="*70)
    print("💡 NEXT STEPS:")
    print("="*70)
    print("""
1. Paste your own delivery locations in SAMPLE_LOCATIONS
2. Run this script again with your data
3. The API will return optimized routes for your delivery network
4. Use the routes in your own application!

Need help?
- Read: API_DOCUMENTATION.md for detailed API reference
- Read: DEPLOYMENT.md for deployment instructions
- Check: Your routes on interactive map
""")

if __name__ == "__main__":
    asyncio.run(main())
