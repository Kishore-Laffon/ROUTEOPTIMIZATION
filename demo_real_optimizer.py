"""
SupplySense Real Optimizer Demo - Integrated with OR-Tools
Accepts multiple delivery locations and returns optimized vehicle routes
"""
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import json
import uuid
import os
import math
import asyncio
from ortools.constraint_solver import routing_enums_pb2, pywrapcp
import requests

app = FastAPI(title="SupplySense Real Optimizer", version="2.0")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static files
if os.path.exists("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")

class LoginRequest(BaseModel):
    username: str
    password: str

# Simple credentials
USERS = {
    "admin": "admin123",
    "user": "user123"
}

def haversine_minutes(lat1: float, lng1: float, lat2: float, lng2: float, speed_kmh: int = 40) -> int:
    """Calculate travel time in minutes between two coordinates using haversine formula"""
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlng/2)**2
    dist_km = 2 * 6371 * math.asin(math.sqrt(a))
    return math.ceil((dist_km / speed_kmh) * 60)

def build_distance_matrix(locations: list[dict]) -> list[list[int]]:
    """Build distance matrix from locations using haversine"""
    n = len(locations)
    matrix = [[0] * n for _ in range(n)]
    
    for i in range(n):
        for j in range(n):
            if i != j:
                matrix[i][j] = haversine_minutes(
                    locations[i]["lat"], locations[i]["lng"],
                    locations[j]["lat"], locations[j]["lng"]
                )
    
    return matrix

def get_route_geometry(waypoints: list[list[float]]) -> list[list[float]]:
    """
    Get actual routing geometry from coordinates using OSRM or simple interpolation.
    Returns: [[lat, lng], [lat, lng], ...] with intermediate points along the route
    """
    if len(waypoints) < 2:
        return waypoints
    
    # Try to use OSRM if available, otherwise use simple interpolation
    try:
        # Format: lng,lat;lng,lat (OSRM uses lng,lat)
        coords_str = ";".join([f"{w[1]},{w[0]}" for w in waypoints])
        url = f"http://router.project-osrm.org/route/v1/driving/{coords_str}?geometries=geojson&overview=full"
        
        response = requests.get(url, timeout=5)
        if response.status_code == 200:
            data = response.json()
            if data.get("routes") and len(data["routes"]) > 0:
                coords = data["routes"][0]["geometry"]["coordinates"]
                # Convert from [lng, lat] to [lat, lng]
                return [[c[1], c[0]] for c in coords]
    except:
        pass
    
    # Fallback: simple linear interpolation between waypoints
    result = [waypoints[0]]
    for i in range(len(waypoints) - 1):
        start = waypoints[i]
        end = waypoints[i + 1]
        
        # Add 5 intermediate points between each pair
        for step in range(1, 6):
            t = step / 6.0
            lat = start[0] + (end[0] - start[0]) * t
            lng = start[1] + (end[1] - start[1]) * t
            result.append([lat, lng])
    
    return result

def solve_vrp(locations: list[dict], num_vehicles: int = 3) -> dict:
    """
    Solve Vehicle Routing Problem using OR-Tools.
    Returns: {routes: [{vehicle_id, stops: [stop indices], stop_coords: [[lat,lng],...]}], ...}
    """
    n = len(locations)
    
    if n < 2:
        return {"status": "INFEASIBLE", "routes": [], "message": "Need at least 2 locations"}
    
    # Limit vehicles to reasonable number
    num_vehicles = min(num_vehicles, n - 1)
    
    # Build distance matrix
    distance_matrix = build_distance_matrix(locations)
    
    # Create OR-Tools manager and routing
    manager = pywrapcp.RoutingIndexManager(n, num_vehicles, 0)  # 0 = depot (first location)
    routing = pywrapcp.RoutingModel(manager)
    
    # Distance callback
    def distance_callback(from_index, to_index):
        from_node = manager.IndexToNode(from_index)
        to_node = manager.IndexToNode(to_index)
        return distance_matrix[from_node][to_node]
    
    transit_callback_index = routing.RegisterTransitCallback(distance_callback)
    routing.SetArcCostEvaluatorOfAllVehicles(transit_callback_index)
    
    # Add distance dimension (constraint on max distance per vehicle)
    dimension_name = 'Distance'
    routing.AddDimension(
        transit_callback_index,
        slack_max=0,
        capacity=500,  # Max 500 minutes (~8 hours) per vehicle
        fix_start_cumul_to_zero=True,
        name=dimension_name,
    )
    
    # Set search parameters
    search_parameters = pywrapcp.DefaultRoutingSearchParameters()
    search_parameters.first_solution_strategy = (
        routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
    )
    search_parameters.local_search_metaheuristic = (
        routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    )
    search_parameters.time_limit.seconds = 5
    
    # Solve
    solution = routing.SolveWithParameters(search_parameters)
    
    if not solution:
        return {
            "status": "INFEASIBLE",
            "routes": [],
            "message": f"Could not find solution with {num_vehicles} vehicles"
        }
    
    # Parse solution
    routes = []
    total_distance = 0
    
    for vehicle_id in range(num_vehicles):
        index = routing.Start(vehicle_id)
        stops = []
        stop_coords = []
        route_distance = 0
        
        # Build route by following the solution path
        while True:
            node_index = manager.IndexToNode(index)
            stops.append(node_index)
            stop_coords.append([locations[node_index]["lat"], locations[node_index]["lng"]])
            
            # Check if this is the end of the route
            if routing.IsEnd(index):
                break
            
            # Get next index from solution using the correct OR-Tools API
            next_index = solution.Value(routing.NextVar(index))
            next_node = manager.IndexToNode(next_index)
            route_distance += distance_matrix[node_index][next_node]
            index = next_index
        
        # Only add route if it has stops (besides depot)
        if len(stops) > 2:  # depot -> stops -> depot
            total_distance += route_distance
            
            # Get full routing geometry (actual path, not just straight lines)
            full_geometry = get_route_geometry(stop_coords)
            
            routes.append({
                "vehicle_id": vehicle_id,
                "vehicle_name": f"Vehicle {vehicle_id + 1}",
                "stops": stops,
                "waypoints": full_geometry,  # Full path with intermediate points
                "distance_minutes": route_distance,
                "distance_km": round(route_distance * 0.667, 2),  # Rough estimate
            })
    
    return {
        "status": "OPTIMAL",
        "routes": routes,
        "num_vehicles_used": len(routes),
        "total_distance_minutes": total_distance,
        "message": f"Optimized {n} stops into {len(routes)} routes using {num_vehicles} vehicles"
    }

@app.get("/")
async def root():
    return {"status": "ok", "message": "SupplySense Real Optimizer Running"}

@app.get("/health")
async def health():
    """Health check endpoint for deployment monitoring"""
    return {"status": "healthy", "service": "route-optimization-api"}

@app.post("/token")
async def login(request: LoginRequest):
    """Login endpoint"""
    if request.username not in USERS:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    if USERS[request.username] != request.password:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    token = f"real_optimizer_{request.username}_{uuid.uuid4().hex[:8]}"
    
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": {
            "username": request.username,
            "full_name": request.username.title(),
            "role": "admin"
        }
    }

@app.websocket("/ws/optimize")
async def websocket_optimize(websocket: WebSocket):
    """WebSocket endpoint with real OR-Tools optimization"""
    await websocket.accept()
    print(f"[WS] Client connected")
    
    try:
        # Send ready
        await websocket.send_json({
            "type": "ready",
            "message": "Connected - Real Optimizer Ready",
            "user": "Demo User",
            "optimizer": "OR-Tools 9.8"
        })
        print(f"[WS] Sent ready message")
        
        while True:
            try:
                data = await websocket.receive_json()
                print(f"[WS] Received: {data.get('type')}")
                msg_type = data.get("type")
                
                if msg_type == "start_optimization":
                    client_job_id = data.get("client_job_id")
                    locations = data.get("locations", [])
                    
                    print(f"[OPT] Optimization request: {len(locations)} locations, job_id={client_job_id}")
                    
                    # Validate
                    if not locations or len(locations) < 2:
                        await websocket.send_json({
                            "type": "error",
                            "message": "Need 2+ locations",
                            "client_job_id": client_job_id
                        })
                        print(f"[OPT] Validation failed: {len(locations)} locations")
                        continue
                    
                    # Generate route ID
                    route_id = f"OPTIMAL-{uuid.uuid4().hex[:8].upper()}"
                    
                    # Send progress
                    await websocket.send_json({
                        "type": "progress",
                        "elapsed": 0.25,
                        "total": 1,
                        "status": "building_distance_matrix",
                        "message": "Building distance matrix...",
                        "job_id": route_id,
                        "client_job_id": client_job_id
                    })
                    print(f"[OPT] Sent progress 25%")
                    
                    # Run optimization
                    try:
                        optimization_result = solve_vrp(locations, num_vehicles=3)
                        print(f"[OPT] Optimization complete: {optimization_result['status']}")
                    except Exception as e:
                        print(f"[OPT] Error during optimization: {e}")
                        await websocket.send_json({
                            "type": "error",
                            "message": f"Optimization error: {str(e)}",
                            "client_job_id": client_job_id
                        })
                        continue
                    
                    await websocket.send_json({
                        "type": "progress",
                        "elapsed": 0.75,
                        "total": 1,
                        "status": "optimizing",
                        "message": "Running OR-Tools solver...",
                        "job_id": route_id,
                        "client_job_id": client_job_id
                    })
                    print(f"[OPT] Sent progress 75%")
                    
                    if optimization_result["status"] == "INFEASIBLE":
                        await websocket.send_json({
                            "type": "error",
                            "message": optimization_result["message"],
                            "client_job_id": client_job_id
                        })
                        print(f"[OPT] Optimization infeasible: {optimization_result['message']}")
                        continue
                    
                    # Prepare routes
                    routes_data = []
                    for route in optimization_result["routes"]:
                        routes_data.append({
                            "vehicle_id": route["vehicle_id"],
                            "vehicle_name": route["vehicle_name"],
                            "waypoints": route["waypoints"],
                            "geometry": route["waypoints"],
                            "distance_km": route["distance_km"],
                            "estimated_time_min": route["distance_minutes"]
                        })
                    
                    # Send complete
                    await websocket.send_json({
                        "type": "complete",
                        "job_id": route_id,
                        "client_job_id": client_job_id,
                        "routes": routes_data,
                        "num_vehicles_used": optimization_result["num_vehicles_used"],
                        "total_distance_km": round(optimization_result["total_distance_minutes"] * 0.667, 2),
                        "total_stops": len(locations),
                        "status": "completed",
                        "message": optimization_result["message"]
                    })
                    print(f"[OPT] Sent complete message with {len(routes_data)} routes")
                
                elif msg_type == "ping":
                    await websocket.send_json({"type": "pong"})
                    print(f"[WS] Sent pong")
                else:
                    print(f"[WS] Unknown message type: {msg_type}")
                    
            except asyncio.CancelledError:
                print(f"[WS] Cancelled")
                break
            except Exception as e:
                print(f"[WS] Error in message loop: {e}")
                await websocket.send_json({
                    "type": "error",
                    "message": f"Server error: {str(e)}"
                })
                break
    
    except WebSocketDisconnect:
        print(f"[WS] Client disconnected")
    except Exception as e:
        print(f"[WS] Fatal error: {e}")
        try:
            await websocket.send_json({
                "type": "error",
                "message": str(e)
            })
        except:
            pass
