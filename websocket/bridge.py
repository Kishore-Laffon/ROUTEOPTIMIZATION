# SupplySense AI Module - websocket/bridge.py

from config import logger
import asyncio

class ConnectionManager:
    """
    Manages all active WebSocket connections for SupplySense.
    Keyed by channel name. One channel can have multiple connected clients.
    Example: "route_updates:1" has the dispatch dashboard connected.
             "stop_updates:3" has TRK-203's driver connected.
    """

    def __init__(self):
        self.active_connections: dict[str, list] = {}

    async def connect(self, websocket, channel: str) -> None:
        await websocket.accept()
        if channel not in self.active_connections:
            self.active_connections[channel] = []
        self.active_connections[channel].append(websocket)
        logger.info("SupplySense WS connected", extra={"channel": channel})

    def disconnect(self, websocket, channel: str) -> None:
        if channel in self.active_connections:
            try:
                self.active_connections[channel].remove(websocket)
            except ValueError:
                pass

    async def broadcast_to_channel(self, channel: str, data: str) -> None:
        """Send message to all clients on a specific channel. Remove dead connections."""
        if channel not in self.active_connections:
            return
        dead = []
        for ws in self.active_connections[channel]:
            try:
                await ws.send_text(data)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws, channel)

    async def broadcast_to_pattern(self, pattern_prefix: str, data: str) -> None:
        """
        Broadcast to all channels matching a prefix.
        e.g. prefix "route_updates:" matches "route_updates:1", "route_updates:2"
        """
        for ch in list(self.active_connections.keys()):
            if ch.startswith(pattern_prefix):
                await self.broadcast_to_channel(ch, data)


# Module-level singleton — imported by routers/routes.py
manager = ConnectionManager()

async def redis_pubsub_listener(redis_client) -> None:
    """
    Subscribe to all SupplySense Redis pub/sub channels.
    Forward every message to connected WebSocket clients.

    Runs FOREVER as a background asyncio task started at FastAPI startup.
    Automatically restarts if it crashes (while True + asyncio.sleep(5)).

    SupplySense pub/sub channels:
      route_updates:{depot_id}   → full route solution (from Celery routing task)
      alert_updates:{user_id}    → alert for a specific user (from alert engine)
      location_updates           → GPS ping (from POST /routes/vehicles/location)
      stop_updates:{vehicle_id}  → stop status change (from delivery confirmation)
    """
    while True:
        try:
            pubsub = redis_client.pubsub()
            await pubsub.psubscribe(
                "route_updates:*",
                "alert_updates:*",
                "location_updates",
                "stop_updates:*",
            )
            logger.info("SupplySense pub/sub bridge active — all channels subscribed")

            async for message in pubsub.listen():
                if message["type"] not in ("message", "pmessage"):
                    continue

                channel = message["channel"]
                if isinstance(channel, bytes):
                    channel = channel.decode("utf-8")

                data = message["data"]
                if isinstance(data, bytes):
                    data = data.decode("utf-8")

                # Route to correct WebSocket clients
                if channel.startswith("route_updates:"):
                    await manager.broadcast_to_channel(channel, data)
                elif channel.startswith("alert_updates:"):
                    await manager.broadcast_to_channel(channel, data)
                elif channel == "location_updates":
                    await manager.broadcast_to_channel("location_updates", data)
                elif channel.startswith("stop_updates:"):
                    await manager.broadcast_to_channel(channel, data)

        except Exception as e:
            logger.error(
                "SupplySense pub/sub bridge crashed — restarting in 5 seconds",
                extra={"error": str(e), "type": type(e).__name__},
            )
            await asyncio.sleep(5)
            # The while True loop restarts automatically.
            # This means the bridge NEVER dies permanently.
            # Even if Redis restarts, the bridge reconnects within 5 seconds.
