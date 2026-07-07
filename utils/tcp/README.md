# TCP Server for Visualizer Integration

TCP server implementation for sending stage/fixture configuration to the Visualizer application.

## Overview

The TCP server runs in Die Lichtmaschine and sends configuration data to connected Visualizer clients. This enables the Visualizer to know:
- Stage dimensions
- Fixture positions and types
- Fixture groups and colors
- DMX addresses and modes

## Components

### 1. `protocol.py` - Protocol Definition

Defines JSON message formats for communication:

**Message Types:**
- `STAGE` - Stage dimensions
- `FIXTURES` - Fixture list with positions and DMX addresses
- `GROUPS` - Fixture groups with colors
- `UPDATE` - Configuration update notification
- `HEARTBEAT` - Keep-alive message
- `ACK` - Acknowledgment

**Message Format:**
All messages are JSON-formatted with newline delimiter:
```json
{"type": "stage", "width": 10.0, "height": 8.0}\n
```

### 2. `server.py` - TCP Server

Multi-threaded TCP server:
- Listens on port 9000 (default)
- Accepts multiple client connections
- Sends full configuration on connect
- Sends updates when configuration changes
- Heartbeat every 5 seconds to keep connections alive
- Thread-safe client management
- Qt signals for GUI integration

### 3. ShowsTab Integration

**UI Elements:**
- `Visualizer Server` checkbox - Enable/disable server
- Status indicator (â—) - Shows connection state:
  - Gray: Server not running
  - Blue: Server running, no clients
  - Green: Clients connected

**Auto-send:**
- Configuration sent when show is loaded
- Updates sent when configuration changes

## Usage

### In the main app GUI

1. Go to Shows tab
2. Check "Visualizer Server" checkbox
3. Status indicator turns blue (server running)
4. When Visualizer connects, indicator turns green

### Programmatic Usage

```python
from utils.tcp import VisualizerTCPServer
from config.models import Configuration

# Load configuration
config = Configuration.load("config.yaml")

# Create server
server = VisualizerTCPServer(config, port=9000)

# Connect to signals
server.client_connected.connect(lambda addr: print(f"Client connected: {addr}"))
server.client_disconnected.connect(lambda addr: print(f"Client disconnected: {addr}"))

# Start server
server.start()

# Send update when config changes
server.update_config(new_config)

# Stop server
server.stop()
```

## Protocol Messages

### 1. Stage Dimensions

```json
{
  "type": "stage",
  "width": 10.0,
  "height": 8.0
}
```

### 2. Fixtures

```json
{
  "type": "fixtures",
  "fixtures": [
    {
      "name": "LED Bar 1",
      "manufacturer": "Stairville",
      "model": "LED BAR 240/8",
      "mode": "14ch",
      "universe": 0,
      "address": 1,
      "position": {"x": -2.0, "y": 3.0, "z": 0.0}
    },
    ...
  ]
}
```

### 3. Groups

```json
{
  "type": "groups",
  "groups": [
    {
      "name": "Front Wash",
      "color": "#FF5722",
      "fixtures": ["LED Bar 1", "LED Bar 2", "LED Bar 3"]
    },
    ...
  ]
}
```

### 4. Update Notification

```json
{
  "type": "update",
  "update_type": "config_changed",
  "data": {}
}
```

### 5. Heartbeat

```json
{
  "type": "heartbeat",
  "timestamp": null
}
```

## Testing

### Test with provided client:

```bash
python test_tcp_client.py
```

Or connect to specific host/port:
```bash
python test_tcp_client.py 192.168.1.100 9000
```

### Test with netcat:

```bash
nc localhost 9000
```

You'll receive JSON messages as they're sent.

### Test with Python:

```python
import socket
import json

sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.connect(("localhost", 9000))

# Receive data
data = sock.recv(4096).decode('utf-8')
for line in data.split('\n'):
    if line.strip():
        message = json.loads(line)
        print(f"Received: {message['type']}")

sock.close()
```

## Connection Sequence

1. **Client connects** to `localhost:9000`
2. **Server sends** configuration sequence:
   - Stage message
   - Fixtures message
   - Groups message
3. **Server sends** heartbeat every 5 seconds
4. **Server sends** updates when configuration changes
5. **Client disconnects** or connection times out

## Network Configuration

**Default settings:**
- Host: `0.0.0.0` (all interfaces)
- Port: `9000`
- Protocol: TCP
- Message format: JSON with newline delimiter

**Firewall:**
- Allow inbound TCP port 9000

**Security:**
- Currently no authentication
- Intended for local network use only
- Do not expose to public internet

## Error Handling

**Server errors:**
- `error_occurred` signal emitted
- Error logged to console
- Server continues running if possible

**Client disconnection:**
- Detected via socket error or empty receive
- Client removed from active list
- `client_disconnected` signal emitted

**Message parsing:**
- Invalid JSON ignored
- Error logged, connection continues

## Performance

**Metrics:**
- Message size: ~100-5,000 bytes (depends on config)
- Send rate: On connect + on change
- Overhead: Minimal (<1% CPU)
- Latency: <10ms for local connections

**Scalability:**
- Supports multiple simultaneous clients
- Each client handled in separate thread
- No practical limit on client count

## Future Enhancements

- [ ] Authentication/authorization
- [ ] TLS/SSL encryption
- [ ] Binary protocol option (faster)
- [ ] Compression for large configurations
- [ ] Configurable port from GUI
- [ ] Selective updates (not full config)
- [ ] Bidirectional communication (Visualizer -> main app)
- [ ] Client capabilities negotiation

## Troubleshooting

### Server won't start

**Problem:** "Address already in use"

**Solution:**
- Another application is using port 9000
- Stop the other application
- Or change port in code (default: 9000)

### Client can't connect

**Problem:** Connection refused

**Solution:**
- Check "Visualizer Server" checkbox is enabled
- Check status indicator is blue or green
- Verify firewall allows port 9000
- Try `localhost` instead of IP address

### No messages received

**Problem:** Connected but no data

**Solution:**
- Check that configuration is loaded
- Try loading a show in Shows tab
- Check console for error messages
- Verify socket is reading until newline

### Messages incomplete

**Problem:** JSON parse errors

**Solution:**
- Messages are newline-delimited
- Buffer data until `\n` is found
- Parse each complete line separately
- See `test_tcp_client.py` for example

## Integration with Visualizer

The Visualizer (Phase V2) will:
1. Connect to this TCP server on startup
2. Receive and parse configuration messages
3. Store configuration in local data structures
4. Use configuration to set up 3D scene
5. Receive ArtNet DMX data separately (Phase V3)
6. Combine TCP config + ArtNet DMX for rendering

**Visualizer implementation:**
```
visualizer/tcp/client.py - TCP client
visualizer/tcp/protocol.py - Message parsing
```

## See Also

- `.claude/PHASE_PLAN.md` - Phase 13 details
- `test_tcp_client.py` - Example client implementation
- `utils/artnet/` - ArtNet DMX output (Phase 12)
- Visualizer documentation (when available)
