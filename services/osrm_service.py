# SupplySense AI Module - services/osrm_service.py
"""
OSRM (Open Source Routing Machine) Distance Matrix API integration.

OSRM provides free, unlimited distance and routing data from OpenStreetMap.
No API key required. Uses the public OSRM server.

URL: https://router.project-osrm.org
Docs: http://project-osrm.org/docs/v5.5.1/api/overview

Features:
- Unlimited free requests (no quota)
- No registration required
- Excellent routing for all regions
- Based on OpenStreetMap data
- ~11 meter precision for coordinates

Coordinates must be: longitude, latitude (opposite of Google Maps!)
Example: OSRM expects (79.1599, 12.9716) not (12.9716, 79.1599)
"""

import math
import httpx
from typing import Optional, List, Tuple, Dict
from config import settings, logger


class OSRMService:
    """
    OSRM Distance Matrix and Routing Service.
    100% free, no API key required, unlimited requests.
    """
    
    BASE_URL = "https://router.project-osrm.org/table/v1/driving"
    CACHE_TTL_SECONDS = 21600  # 6 hours
    MAX_LOCATIONS_PER_REQUEST = 100  # OSRM limit
    
    def __init__(self):
        """Initialize OSRM service (no config needed)."""
        self.available = True  # Always available since it's a public server
        logger.info("OSRMService: Initialized (public server, unlimited free requests)")
    
    @staticmethod
    def haversine_distance(lat1: float, lng1: float, lat2: float, lng2: float) -> Tuple[float, int]:
        """
        Fallback great-circle distance calculation.
        
        Args:
            lat1, lng1: Origin coordinates
            lat2, lng2: Destination coordinates
            
        Returns:
            Tuple of (distance_km, travel_time_minutes)
        """
        dlat = math.radians(lat2 - lat1)
        dlng = math.radians(lng2 - lng1)
        a = (math.sin(dlat/2)**2 + 
             math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * 
             math.sin(dlng/2)**2)
        distance_km = 2 * 6371 * math.asin(math.sqrt(a))
        
        # Estimate travel time at 30 km/h average road speed
        travel_minutes = math.ceil((distance_km / 30) * 60)
        
        return distance_km, travel_minutes
    
    async def distance_between(
        self,
        lat1: float,
        lng1: float,
        lat2: float,
        lng2: float,
        redis_client=None
    ) -> Dict[str, any]:
        """
        Get distance and travel time between two points using OSRM.
        
        Args:
            lat1, lng1: Origin coordinates
            lat2, lng2: Destination coordinates
            redis_client: Optional Redis client for caching
            
        Returns:
            Dict with keys:
            - distance_km: Distance in kilometers
            - distance_m: Distance in meters
            - travel_minutes: Estimated travel time in minutes
            - travel_seconds: Travel time in seconds
            - source: "osrm" or "osrm_cached" or "haversine_fallback"
        """
        # Check cache first
        if redis_client:
            cache_key = f"supplysense:dist:{lat1:.4f},{lng1:.4f}:{lat2:.4f},{lng2:.4f}"
            try:
                cached_val = await redis_client.get(cache_key)
                if cached_val:
                    return {
                        "distance_km": float(cached_val),
                        "distance_m": float(cached_val) * 1000,
                        "travel_minutes": math.ceil(float(cached_val) / 30 * 60),
                        "travel_seconds": math.ceil(float(cached_val) / 30 * 3600),
                        "source": "osrm_cached"
                    }
            except Exception as e:
                logger.debug(f"Cache check failed: {e}")
        
        # Query OSRM
        try:
            result = await self.query_distance(lat1, lng1, lat2, lng2)
            
            # Cache result
            if redis_client and "distance_km" in result:
                cache_key = f"supplysense:dist:{lat1:.4f},{lng1:.4f}:{lat2:.4f},{lng2:.4f}"
                try:
                    await redis_client.set(
                        cache_key,
                        str(result["distance_km"]),
                        ex=self.CACHE_TTL_SECONDS
                    )
                except Exception:
                    pass
            
            return result
        except Exception as e:
            logger.warning(f"OSRM lookup failed: {e} — using Haversine fallback")
            # Fallback to Haversine
            distance_km, travel_minutes = self.haversine_distance(lat1, lng1, lat2, lng2)
            return {
                "distance_km": distance_km,
                "distance_m": distance_km * 1000,
                "travel_minutes": travel_minutes,
                "travel_seconds": travel_minutes * 60,
                "source": "haversine_fallback"
            }
    
    async def query_distance(
        self,
        lat1: float,
        lng1: float,
        lat2: float,
        lng2: float
    ) -> Dict[str, any]:
        """
        Query OSRM for distance between two points.
        
        IMPORTANT: OSRM expects longitude,latitude (opposite of Google Maps!)
        
        Args:
            lat1, lng1: Origin coordinates
            lat2, lng2: Destination coordinates
            
        Returns:
            Dict with distance_km, distance_m, travel_minutes, travel_seconds
        """
        # OSRM uses longitude,latitude order (not latitude,longitude)
        coords = f"{lng1},{lat1};{lng2},{lat2}"
        
        params = {
            "coordinates": coords,
            "overview": "false",
        }
        
        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                url = f"{self.BASE_URL}/{coords}"
                response = await client.get(url, params=params)
                response.raise_for_status()
                data = response.json()
                
                if data.get("code") != "Ok":
                    raise Exception(f"OSRM error: {data.get('code')} - {data.get('message', '')}")
                
                # Extract first (and only) distance/duration pair
                distances = data.get("distances", [[]])[0]
                durations = data.get("durations", [[]])[0]
                
                if not distances or not durations or len(distances) < 2 or len(durations) < 2:
                    raise Exception("Invalid OSRM response: missing distance/duration data")
                
                distance_m = distances[1]  # Index 1 because [0] is self-distance (0)
                duration_sec = durations[1]
                
                return {
                    "distance_km": distance_m / 1000,
                    "distance_m": distance_m,
                    "travel_minutes": math.ceil(duration_sec / 60),
                    "travel_seconds": duration_sec,
                    "source": "osrm"
                }
            except Exception as e:
                logger.error(f"OSRM API error: {e}")
                raise
    
    async def batch_distance_matrix(
        self,
        origin_lat: float,
        origin_lng: float,
        destinations: List[Tuple[float, float]],
        redis_client=None
    ) -> Dict[int, Dict[str, any]]:
        """
        Get distances from one origin to multiple destinations.
        
        Args:
            origin_lat, origin_lng: Origin coordinates
            destinations: List of (lat, lng) tuples
            redis_client: Optional Redis client for caching
            
        Returns:
            Dict mapping destination index to distance info
        """
        results = {}
        
        # Process in batches (OSRM limit: 100 locations per request)
        for batch_start in range(0, len(destinations), self.MAX_LOCATIONS_PER_REQUEST - 1):
            batch_end = min(batch_start + self.MAX_LOCATIONS_PER_REQUEST - 1, len(destinations))
            batch_indices = list(range(batch_start, batch_end))
            batch_destinations = [destinations[i] for i in batch_indices]
            
            try:
                batch_results = await self._batch_query(
                    origin_lat, origin_lng, batch_destinations, redis_client
                )
                for local_idx, idx in enumerate(batch_indices):
                    results[idx] = batch_results[local_idx]
            except Exception as e:
                logger.warning(f"Batch query failed: {e} — using Haversine for this batch")
                for local_idx, idx in enumerate(batch_indices):
                    lat2, lng2 = batch_destinations[local_idx]
                    distance_km, travel_minutes = self.haversine_distance(
                        origin_lat, origin_lng, lat2, lng2
                    )
                    results[idx] = {
                        "distance_km": distance_km,
                        "distance_m": distance_km * 1000,
                        "travel_minutes": travel_minutes,
                        "travel_seconds": travel_minutes * 60,
                        "source": "haversine_fallback"
                    }
        
        return results

    async def route_geometry(self, waypoints: List[Tuple[float, float]]):
        """
        Get full road geometry, distance, and duration for an ordered list of waypoints.

        Args:
            waypoints: list of (lat, lng) tuples in travel order (including start/end)

        Returns:
            dict with geometry (list of [lat, lng]), distance_km, duration_min
        """
        if len(waypoints) < 2:
            raise ValueError("At least two waypoints are required")

        # ===== DEBUG LOGGING =====
        logger.info(f"[OSRM] route_geometry called with {len(waypoints)} waypoints:")
        for idx, (lat, lng) in enumerate(waypoints):
            logger.info(f"[OSRM]   Waypoint {idx}: ({lat:.4f}, {lng:.4f})")

        # OSRM expects lng,lat order
        coord_str = ";".join([f"{lng},{lat}" for lat, lng in waypoints])
        url = f"https://router.project-osrm.org/route/v1/driving/{coord_str}"
        params = {"overview": "full", "geometries": "geojson"}
        
        logger.info(f"[OSRM] Request URL: {url}")
        logger.info(f"[OSRM] Parameters: {params}")

        async with httpx.AsyncClient(timeout=15.0) as client:
            try:
                response = await client.get(url, params=params)
                response.raise_for_status()
                data = response.json()
            except Exception as e:
                logger.error(f"[OSRM] HTTP request failed: {e}")
                raise

        logger.info(f"[OSRM] Response code: {data.get('code')}")
        
        if data.get("code") != "Ok" or not data.get("routes"):
            logger.error(f"[OSRM] Route error: {data.get('code')} - {data.get('message', 'No message')}")
            raise Exception(f"OSRM route error: {data.get('code')}")

        route = data["routes"][0]
        
        # Extract geometry and swap back to [lat, lng] format
        geometry = [[lat, lng] for lng, lat in route["geometry"]["coordinates"]]
        distance_km = (route.get("distance", 0) or 0) / 1000
        duration_min = (route.get("duration", 0) or 0) / 60
        
        logger.info(f"[OSRM] ✓ Route calculated: {distance_km:.2f} km, {duration_min:.1f} min")
        logger.info(f"[OSRM] Geometry points: {len(geometry)}")
        logger.info(f"[OSRM] First point: {geometry[0]}")
        logger.info(f"[OSRM] Last point: {geometry[-1]}")

        return {
            "geometry": geometry,
            "distance_km": distance_km,
            "duration_min": duration_min,
            "source": "osrm"
        }
    
    async def _batch_query(
        self,
        origin_lat: float,
        origin_lng: float,
        destinations: List[Tuple[float, float]],
        redis_client=None
    ) -> List[Dict]:
        """Internal method to execute batch distance query."""
        # OSRM coordinate format: origin;dest1;dest2;...
        # Format: longitude,latitude (opposite of usual)
        coords_list = [f"{origin_lng},{origin_lat}"]
        coords_list.extend(f"{lng},{lat}" for lat, lng in destinations)
        coords_str = ";".join(coords_list)
        
        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                url = f"{self.BASE_URL}/{coords_str}"
                response = await client.get(url)
                response.raise_for_status()
                data = response.json()
                
                if data.get("code") != "Ok":
                    raise Exception(f"OSRM error: {data.get('code')}")
                
                # Extract distances from origin (index 0) to all destinations
                distances = data.get("distances", [[]])[0]
                durations = data.get("durations", [[]])[0]
                
                results = []
                for i in range(1, len(distances)):  # Skip index 0 (origin to self)
                    distance_m = distances[i]
                    duration_sec = durations[i]
                    
                    results.append({
                        "distance_km": distance_m / 1000,
                        "distance_m": distance_m,
                        "travel_minutes": math.ceil(duration_sec / 60),
                        "travel_seconds": duration_sec,
                        "source": "osrm"
                    })
                
                return results
            except Exception as e:
                logger.error(f"OSRM batch query error: {e}")
                raise


# Global instance
_instance: Optional[OSRMService] = None


def get_osrm_service() -> OSRMService:
    """Get or create global OSRMService instance."""
    global _instance
    if _instance is None:
        _instance = OSRMService()
    return _instance
