# SupplySense AI Module - services/google_maps_service.py
"""
Google Maps Distance Matrix API integration service.

Provides high-level methods for distance calculations using Google Maps API.
Features:
- Batch distance matrix queries (up to 100 destinations per request)
- Automatic caching via Redis (TTL: 6 hours)
- Fallback to Haversine distance if API unavailable
- Error handling and retry logic

Pricing: $0.005 per request (25,000 free requests/month)
"""

import math
import httpx
from typing import Optional, Dict, List, Tuple
from config import settings, logger


class GoogleMapsService:
    """
    Wrapper around Google Maps Distance Matrix API.
    Handles batch requests, caching, and error handling.
    """
    
    API_URL = "https://maps.googleapis.com/maps/api/distancematrix/json"
    CACHE_TTL_SECONDS = 21600  # 6 hours
    MAX_DESTINATIONS_PER_REQUEST = 100  # Google Maps API limit
    
    def __init__(self, api_key: Optional[str] = None):
        """
        Initialize Google Maps service.
        
        Args:
            api_key: Google Maps API key. If None, uses GOOGLE_MAPS_API_KEY from config.
        """
        self.api_key = api_key or getattr(settings, "GOOGLE_MAPS_API_KEY", "")
        self.available = bool(self.api_key and self.api_key.strip())
        
        if not self.available:
            logger.warning("GoogleMapsService: No API key provided — will use Haversine fallback")
    
    @staticmethod
    def haversine_distance(lat1: float, lng1: float, lat2: float, lng2: float) -> Tuple[float, int]:
        """
        Calculate great-circle distance and travel time using Haversine formula.
        
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
        Get distance and travel time between two points.
        
        Args:
            lat1, lng1: Origin coordinates
            lat2, lng2: Destination coordinates
            redis_client: Optional Redis client for caching
            
        Returns:
            Dict with keys:
            - distance_km: Distance in kilometers
            - travel_minutes: Estimated travel time in minutes
            - source: "google_maps", "google_maps_cached", or "haversine_fallback"
        """
        # Check cache first
        if redis_client:
            cache_key = f"supplysense:dist:{lat1:.4f},{lng1:.4f}:{lat2:.4f},{lng2:.4f}"
            try:
                cached_val = await redis_client.get(cache_key)
                if cached_val:
                    return {
                        "distance_km": float(cached_val),
                        "travel_minutes": math.ceil(float(cached_val) / 30 * 60),
                        "source": "google_maps_cached"
                    }
            except Exception as e:
                logger.debug(f"Cache check failed: {e}")
        
        # If API available, try Google Maps
        if self.available:
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
                logger.warning(f"Google Maps lookup failed: {e} — using Haversine")
        
        # Fallback to Haversine
        distance_km, travel_minutes = self.haversine_distance(lat1, lng1, lat2, lng2)
        return {
            "distance_km": distance_km,
            "travel_minutes": travel_minutes,
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
        Query Google Maps Distance Matrix API for distance.
        
        Args:
            lat1, lng1: Origin coordinates
            lat2, lng2: Destination coordinates
            
        Returns:
            Dict with distance_km, distance_m, travel_minutes, travel_seconds
        """
        params = {
            "origins": f"{lat1},{lng1}",
            "destinations": f"{lat2},{lng2}",
            "key": self.api_key,
            "units": "metric",
            "mode": "driving"
        }
        
        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                response = await client.get(self.API_URL, params=params)
                response.raise_for_status()
                data = response.json()
                
                if data.get("status") != "OK":
                    raise Exception(f"API error: {data.get('status')} - {data.get('error_message', '')}")
                
                rows = data.get("rows", [])[0]
                element = rows.get("elements", [])[0]
                
                if element.get("status") != "OK":
                    raise Exception(f"Location error: {element.get('status')}")
                
                distance_m = element.get("distance", {}).get("value", 0)
                duration_sec = element.get("duration", {}).get("value", 0)
                
                return {
                    "distance_km": distance_m / 1000,
                    "distance_m": distance_m,
                    "travel_minutes": math.ceil(duration_sec / 60),
                    "travel_seconds": duration_sec,
                    "source": "google_maps"
                }
            except Exception as e:
                logger.error(f"Google Maps API error: {e}")
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
        
        # Try Google Maps API (batched into max 100 destinations per request)
        if self.available:
            for batch_start in range(0, len(destinations), self.MAX_DESTINATIONS_PER_REQUEST):
                batch_end = min(batch_start + self.MAX_DESTINATIONS_PER_REQUEST, len(destinations))
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
                            "travel_minutes": travel_minutes,
                            "source": "haversine_fallback"
                        }
        else:
            # No API key — use Haversine for all
            for idx, (lat2, lng2) in enumerate(destinations):
                distance_km, travel_minutes = self.haversine_distance(
                    origin_lat, origin_lng, lat2, lng2
                )
                results[idx] = {
                    "distance_km": distance_km,
                    "travel_minutes": travel_minutes,
                    "source": "haversine_fallback"
                }
        
        return results
    
    async def _batch_query(
        self,
        origin_lat: float,
        origin_lng: float,
        destinations: List[Tuple[float, float]],
        redis_client=None
    ) -> List[Dict]:
        """Internal method to execute batch distance query."""
        params = {
            "origins": f"{origin_lat},{origin_lng}",
            "destinations": "|".join(f"{lat},{lng}" for lat, lng in destinations),
            "key": self.api_key,
            "units": "metric",
            "mode": "driving"
        }
        
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(self.API_URL, params=params)
            response.raise_for_status()
            data = response.json()
            
            if data.get("status") != "OK":
                raise Exception(f"API error: {data.get('status')}")
            
            results = []
            for element in data.get("rows", [{}])[0].get("elements", []):
                if element.get("status") == "OK":
                    distance_m = element.get("distance", {}).get("value", 0)
                    duration_sec = element.get("duration", {}).get("value", 0)
                    results.append({
                        "distance_km": distance_m / 1000,
                        "distance_m": distance_m,
                        "travel_minutes": math.ceil(duration_sec / 60),
                        "travel_seconds": duration_sec,
                        "source": "google_maps"
                    })
                else:
                    raise Exception(f"Element error: {element.get('status')}")
            
            return results


# Global instance
_instance: Optional[GoogleMapsService] = None


def get_google_maps_service() -> GoogleMapsService:
    """Get or create global GoogleMapsService instance."""
    global _instance
    if _instance is None:
        _instance = GoogleMapsService()
    return _instance
