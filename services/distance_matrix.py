# SupplySense AI Module - services/distance_matrix.py

import math
import httpx
from config import settings, logger, ORTOOLS_CONFIG
from services.osrm_service import get_osrm_service

def haversine_minutes(lat1: float, lng1: float, lat2: float, lng2: float, speed_kmh: int = 30) -> int:
    """
    Calculate travel time in minutes between two GPS coordinates.
    Uses great-circle (straight-line) distance divided by road speed estimate.
    Pure function — no side effects, no imports beyond math.
    Returns integer minutes (always round up with math.ceil).
    Earth radius = 6371 km.
    """
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlng/2)**2
    dist_km = 2 * 6371 * math.asin(math.sqrt(a))
    return math.ceil((dist_km / speed_kmh) * 60)

def get_cache_key(lat1: float, lng1: float, lat2: float, lng2: float) -> str:
    """
    Generate Redis cache key for a location pair.
    Use 4 decimal places = ~11 metre precision, sufficient for vehicle routing.
    """
    return f"dist:{lat1:.4f},{lng1:.4f}:{lat2:.4f},{lng2:.4f}"

async def build_distance_matrix(
    locations: list[dict],
    redis_client,
) -> tuple[list[list[int]], str]:
    """
    Build a 2D travel-time matrix for OR-Tools.

    Args:
        locations: list of dicts, each with keys: lat (float), lng (float), label (str)
                   Index 0 MUST be the depot. Index 1..N are delivery stops.
        redis_client: aioredis client for caching

    Returns:
        (matrix, note)
        matrix: 2D list of ints where matrix[i][j] = minutes from location i to location j
                matrix[i][i] = 0 always (same location)
        note: "osrm", "google_maps", "haversine_fallback" etc indicating source
    """
    n = len(locations)
    matrix = [[0] * n for _ in range(n)]
    
    # Determine which provider to use
    maps_provider = getattr(settings, "MAPS_PROVIDER", "osrm").lower()
    
    if maps_provider == "osrm":
        return await _build_matrix_osrm(locations, redis_client, matrix)
    elif maps_provider == "google_maps":
        return await _build_matrix_google_maps(locations, redis_client, matrix)
    else:
        logger.warning(f"Unknown MAPS_PROVIDER: {maps_provider}, using OSRM")
        return await _build_matrix_osrm(locations, redis_client, matrix)


async def _build_matrix_osrm(
    locations: list[dict],
    redis_client,
    matrix: list[list[int]]
) -> tuple[list[list[int]], str]:
    """Build distance matrix using OSRM."""
    n = len(locations)
    osrm = get_osrm_service()
    note = "osrm"
    
    # Build list of all locations
    coords = [(loc["lat"], loc["lng"]) for loc in locations]
    
    try:
        # Use OSRM batch distance matrix
        for i in range(n):
            if i == 0:
                # Query from origin to all other locations
                origin_lat, origin_lng = coords[0]
                destinations = coords[1:]
                
                results = await osrm.batch_distance_matrix(
                    origin_lat, origin_lng, destinations, redis_client
                )
                
                for j, result in enumerate(results.items()):
                    dest_idx, data = result
                    matrix[0][dest_idx + 1] = data["travel_minutes"]
            else:
                # Query from this location to all others
                origin_lat, origin_lng = coords[i]
                # Build destinations list excluding self
                destinations = [(coords[j][0], coords[j][1]) for j in range(n) if j != i]
                
                try:
                    results = await osrm.batch_distance_matrix(
                        origin_lat, origin_lng, destinations, redis_client
                    )
                    
                    # Map results back to matrix indices
                    result_idx = 0
                    for j in range(n):
                        if i == j:
                            matrix[i][j] = 0  # Same location
                        elif j < i:
                            # Already queried from j -> i, use that value
                            pass
                        else:
                            if result_idx in results:
                                matrix[i][j] = results[result_idx]["travel_minutes"]
                            result_idx += 1
                except Exception as e:
                    logger.warning(f"OSRM batch query for location {i} failed: {e}")
                    # Fallback to Haversine for this origin
                    for j in range(n):
                        if i != j:
                            mins = haversine_minutes(
                                coords[i][0], coords[i][1],
                                coords[j][0], coords[j][1]
                            )
                            matrix[i][j] = mins
                            note = "osrm_with_haversine_fallback"
    except Exception as e:
        logger.warning(f"OSRM error: {e}, falling back to Haversine")
        note = "haversine_fallback"
        for i in range(n):
            for j in range(n):
                if i != j:
                    mins = haversine_minutes(
                        coords[i][0], coords[i][1],
                        coords[j][0], coords[j][1]
                    )
                    matrix[i][j] = mins
    
    return matrix, note


async def _build_matrix_google_maps(
    locations: list[dict],
    redis_client,
    matrix: list[list[int]]
) -> tuple[list[list[int]], str]:
    """Build distance matrix using Google Maps API."""
    n = len(locations)
    note = "google_maps"
    
    cache_misses = []

    # Check cache first
    for i in range(n):
        for j in range(n):
            if i == j:
                matrix[i][j] = 0
                continue
                
            lat1, lng1 = locations[i]["lat"], locations[i]["lng"]
            lat2, lng2 = locations[j]["lat"], locations[j]["lng"]
            
            key = f"supplysense:{get_cache_key(lat1, lng1, lat2, lng2)}"
            try:
                val = await redis_client.get(key)
                if val is not None:
                    matrix[i][j] = int(val)
                else:
                    cache_misses.append((i, j, lat1, lng1, lat2, lng2, key))
            except Exception as e:
                logger.warning(f"Redis cache error: {e}")
                cache_misses.append((i, j, lat1, lng1, lat2, lng2, key))

    if not cache_misses:
        return matrix, note

    # Check if API key is available
    api_key = getattr(settings, "GOOGLE_MAPS_API_KEY", None)
    if not api_key:
        logger.warning("Google Maps API key unavailable — using Haversine distance fallback")
        note = "haversine_fallback"
        for i, j, lat1, lng1, lat2, lng2, key in cache_misses:
            mins = haversine_minutes(lat1, lng1, lat2, lng2)
            matrix[i][j] = mins
            try:
                await redis_client.set(key, str(mins), ex=21600)
            except Exception:
                pass
        return matrix, note

    # API is available - batch requests
    misses_by_origin = {}
    for i, j, lat1, lng1, lat2, lng2, key in cache_misses:
        if i not in misses_by_origin:
            misses_by_origin[i] = []
        misses_by_origin[i].append((j, lat1, lng1, lat2, lng2, key))

    api_calls_made = 0
    api_calls_failed = 0
    url = "https://maps.googleapis.com/maps/api/distancematrix/json"

    async with httpx.AsyncClient(timeout=10.0) as client:
        for i, dests in misses_by_origin.items():
            for start_idx in range(0, len(dests), 100):
                chunk = dests[start_idx:start_idx+100]
                lat1, lng1 = chunk[0][1], chunk[0][2]
                
                origin_str = f"{lat1},{lng1}"
                dest_str = "|".join(f"{lat2},{lng2}" for _, _, _, lat2, lng2, _ in chunk)
                
                params = {
                    "origins": origin_str,
                    "destinations": dest_str,
                    "key": api_key,
                    "units": "metric",
                    "mode": "driving"
                }

                api_calls_made += 1
                try:
                    resp = await client.get(url, params=params)
                    resp.raise_for_status()
                    data = resp.json()
                    
                    if data.get("status") != "OK":
                        raise Exception(f"API status: {data.get('status')} - {data.get('error_message', '')}")
                        
                    rows = data.get("rows", [])
                    if not rows:
                        raise Exception("Empty rows in API response")
                        
                    elements = rows[0].get("elements", [])
                    
                    for idx, element in enumerate(elements):
                        j, _, _, lat2, lng2, key = chunk[idx]
                        if element.get("status") == "OK":
                            duration_sec = element.get("duration", {}).get("value", 0)
                            mins = math.ceil(duration_sec / 60)
                        else:
                            mins = haversine_minutes(lat1, lng1, lat2, lng2)
                            
                        matrix[i][j] = mins
                        try:
                            await redis_client.set(key, str(mins), ex=21600)
                        except Exception:
                            pass
                            
                except Exception as e:
                    logger.warning(f"Google Maps request failed ({e}) — using Haversine fallback for batch")
                    api_calls_failed += 1
                    for j, _, _, lat2, lng2, key in chunk:
                        mins = haversine_minutes(lat1, lng1, lat2, lng2)
                        matrix[i][j] = mins
                        try:
                            await redis_client.set(key, str(mins), ex=21600)
                        except Exception:
                            pass

    if api_calls_made > 0 and api_calls_failed == api_calls_made:
        logger.warning("Google Maps unavailable — using Haversine distance fallback")
        note = "haversine_fallback"

    return matrix, note
