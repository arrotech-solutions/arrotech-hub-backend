import logging
import httpx
import math
import os
from typing import Dict, Any, List, Optional
from ..config import settings

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════
# DATA SOURCE ADAPTER LAYER
# ═══════════════════════════════════════════════════════════════

class DataSourceAdapter:
    """Interface for fetching dynamic data (locations, riders) statelessly."""
    async def fetch_data(self, source_config: dict) -> dict:
        raise NotImplementedError

class RestApiAdapter(DataSourceAdapter):
    async def fetch_data(self, source_config: dict) -> dict:
        url = source_config.get("url")
        method = source_config.get("method", "GET").upper()
        headers = source_config.get("headers", {})
        payload = source_config.get("payload", None)
        
        if not url:
            return {"success": False, "error": "URL is required for RestApiAdapter"}

        async with httpx.AsyncClient() as client:
            try:
                response = await client.request(method, url, headers=headers, json=payload, timeout=10.0)
                response.raise_for_status()
                return {"success": True, "data": response.json()}
            except Exception as e:
                logger.error(f"[RestApiAdapter] Error fetching data: {e}")
                return {"success": False, "error": str(e)}

class AirtableAdapter(DataSourceAdapter):
    async def fetch_data(self, source_config: dict) -> dict:
        # Mock Airtable fetch logic
        # Expects base_id, table_name, api_key in config
        logger.info(f"[AirtableAdapter] Fetching from {source_config.get('table_name')}")
        # In a real implementation, we would query the Airtable API.
        # For now, return a successful mock response.
        return {
            "success": True, 
            "data": {
                "records": [
                    {"fields": {"lat": -1.2921, "lng": 36.8219, "id": "rider_1"}}
                ]
            }
        }

# ═══════════════════════════════════════════════════════════════
# MAPS PROVIDER LAYER
# ═══════════════════════════════════════════════════════════════

class BaseMapsProvider:
    """Abstract interface for Maps functionality to allow vendor swapping."""
    async def geocode(self, address: str) -> dict: raise NotImplementedError
    async def reverse_geocode(self, lat: float, lng: float) -> dict: raise NotImplementedError
    async def distance_matrix(self, origin: dict, destinations: List[dict]) -> dict: raise NotImplementedError
    async def route(self, origin: dict, destination: dict) -> dict: raise NotImplementedError
    async def static_map(self, markers: List[dict]) -> str: raise NotImplementedError

class GoogleMapsProvider(BaseMapsProvider):
    def __init__(self, api_key: str = None):
        # Fallback to MOCK_KEY to ensure safe execution without a real key
        self.api_key = api_key or getattr(settings, "GOOGLE_MAPS_API_KEY", "MOCK_KEY")
        
    async def geocode(self, address: str) -> dict:
        if self.api_key == "MOCK_KEY":
            return {
                "lat": -1.2921, "lng": 36.8219,
                "formatted_address": f"{address} (Mocked)",
                "confidence": 0.95
            }
            
        url = "https://maps.googleapis.com/maps/api/geocode/json"
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, params={"address": address, "key": self.api_key})
            if resp.status_code == 200 and resp.json().get("status") == "OK":
                res = resp.json()["results"][0]
                loc = res["geometry"]["location"]
                return {
                    "lat": loc["lat"], "lng": loc["lng"],
                    "formatted_address": res["formatted_address"],
                    "confidence": 1.0 if res["geometry"]["location_type"] == "ROOFTOP" else 0.7
                }
            return {"error": "Geocode failed", "details": resp.json()}

    async def reverse_geocode(self, lat: float, lng: float) -> dict:
        if self.api_key == "MOCK_KEY":
            return {
                "formatted_address": f"Nairobi CBD (Mocked {lat}, {lng})",
                "area": "Nairobi",
                "landmark": "KICC"
            }
            
        url = "https://maps.googleapis.com/maps/api/geocode/json"
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, params={"latlng": f"{lat},{lng}", "key": self.api_key})
            if resp.status_code == 200 and resp.json().get("status") == "OK":
                res = resp.json()["results"][0]
                return {
                    "formatted_address": res["formatted_address"],
                    "area": "Mapped Area",
                    "landmark": ""
                }
            return {"error": "Reverse geocode failed"}

    async def distance_matrix(self, origin: dict, destinations: List[dict]) -> dict:
        if self.api_key == "MOCK_KEY":
            # Return mocked distances based on coordinate differences
            results = []
            for dest in destinations:
                dist = math.hypot(origin["lat"] - dest["lat"], origin["lng"] - dest["lng"]) * 111 # rough km
                results.append({
                    "distance_km": round(dist, 2),
                    "duration_minutes": round(dist * 3, 0), # assume 20km/h
                    "traffic_level": "medium" if dist > 5 else "low"
                })
            return {"results": results}
            
        return {"error": "Not implemented for real API yet"}

    async def route(self, origin: dict, destination: dict) -> dict:
        if self.api_key == "MOCK_KEY":
            dist = math.hypot(origin["lat"] - destination["lat"], origin["lng"] - destination["lng"]) * 111
            return {
                "polyline": "encoded_polyline_mock",
                "distance_km": round(dist, 2),
                "duration_minutes": round(dist * 3, 0),
                "steps": ["Head North", "Turn left", "Arrive at destination"]
            }
        return {"error": "Not implemented for real API yet"}

    async def static_map(self, markers: List[dict]) -> str:
        if self.api_key == "MOCK_KEY":
            return "https://maps.googleapis.com/maps/api/staticmap?mock=true&size=600x400"
        return "https://maps.googleapis.com/maps/api/staticmap"

# ═══════════════════════════════════════════════════════════════
# MAPS ORCHESTRATOR SERVICE
# ═══════════════════════════════════════════════════════════════

class MapsService:
    """Core Map Operations for MCP tools."""
    
    def __init__(self, provider: BaseMapsProvider = None):
        self.provider = provider or GoogleMapsProvider()
        self.adapters: Dict[str, DataSourceAdapter] = {
            "api": RestApiAdapter(),
            "rest_api": RestApiAdapter(),
            "webhook": RestApiAdapter(),
            "airtable": AirtableAdapter()
        }

    async def geocode(self, address: str) -> dict:
        return await self.provider.geocode(address)
        
    async def reverse_geocode(self, lat: float, lng: float) -> dict:
        return await self.provider.reverse_geocode(lat, lng)
        
    async def distance_matrix(self, origin: dict, destinations: List[dict]) -> dict:
        return await self.provider.distance_matrix(origin, destinations)
        
    async def route(self, origin: dict, destination: dict) -> dict:
        return await self.provider.route(origin, destination)

    async def static_map(self, markers: List[dict]) -> dict:
        url = await self.provider.static_map(markers)
        return {"image_url": url}

    async def track_location(self, entity_id: str, source: dict) -> dict:
        """Fetch live location via adapter."""
        adapter = self.adapters.get(source.get("type", "api"))
        if not adapter:
            return {"error": f"Unknown source type: {source.get('type')}"}
        
        data = await adapter.fetch_data(source.get("config", {}))
        if not data.get("success"):
            return {"error": data.get("error")}
            
        # Extract lat/lng dynamically
        # In a real scenario, the adapter config would map fields
        lat = data.get("data", {}).get("lat", -1.2921)
        lng = data.get("data", {}).get("lng", 36.8219)
        
        import datetime
        return {
            "lat": lat, 
            "lng": lng, 
            "timestamp": datetime.datetime.utcnow().isoformat()
        }

    async def geofence_check(self, point: dict, zone: dict) -> dict:
        """Check if a point is within a circular or polygon geofence."""
        lat, lng = point.get("lat"), point.get("lng")
        zone_type = zone.get("type", "circle")
        
        if zone_type == "circle":
            center = zone.get("center", {})
            radius_km = zone.get("radius_km", 5.0)
            
            # Haversine distance
            R = 6371
            dlat = math.radians(center.get("lat", lat) - lat)
            dlon = math.radians(center.get("lng", lng) - lng)
            a = math.sin(dlat/2) * math.sin(dlat/2) + math.cos(math.radians(lat)) \
                * math.cos(math.radians(center.get("lat", lat))) * math.sin(dlon/2) * math.sin(dlon/2)
            dist = R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
            
            return {
                "inside": dist <= radius_km, 
                "distance_from_center_km": round(dist, 2)
            }
        else:
            # Polygon check logic (Ray casting) mocked for now
            return {"inside": True, "note": "Polygon mock check"}
