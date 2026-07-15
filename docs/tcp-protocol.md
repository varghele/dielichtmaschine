# TCP Protocol (Visualizer Config Sync)

Die Lichtmaschine runs a TCP server that sends stage and fixture configuration to connected Visualizer clients. This lets the Visualizer set up its 3D scene without manual configuration.

## Components

### Protocol (`utils/tcp/protocol.py`)

JSON messages delimited by newlines. Each line is a complete JSON object.

### Server (`utils/tcp/server.py`)

Multi-threaded TCP server:
- Listens on port 9000 (configurable)
- Accepts multiple simultaneous clients
- Sends full configuration on client connect
- Sends updates when configuration changes
- Heartbeat every 5 seconds for keep-alive
- Qt signals: `client_connected`, `client_disconnected`, `error_occurred`

## Message Types

### Stage

```json
{"type": "stage", "width": 10.0, "height": 8.0, "grid_size": 0.5}
```

### Fixtures

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
      "position": {"x": -2.0, "y": 3.0, "z": 0.0},
      "orientation": {"mounting": "hanging", "yaw": 0.0, "pitch": 90.0, "roll": 0.0},
      "channels": { ... },
      "color_wheel": [ ... ],
      "gobo_wheel": [ ... ]
    }
  ]
}
```

### Groups

```json
{
  "type": "groups",
  "groups": [
    {
      "name": "Front Wash",
      "color": "#FF5722",
      "fixtures": ["LED Bar 1", "LED Bar 2"]
    }
  ]
}
```

### Update

```json
{"type": "update", "update_type": "config_changed", "data": {}}
```

### Heartbeat

```json
{"type": "heartbeat", "timestamp": null}
```

## Connection Flow

1. Client connects to `host:9000`
2. Server sends: Stage message, Fixtures message, Groups message
3. Server sends heartbeat every 5 seconds
4. Server sends full config again when show/configuration changes
5. Client disconnects or connection drops

## GUI Integration

The Shows tab toolbar includes:
- **Visualizer Server** checkbox to enable/disable
- **Status LED** indicator:
  - Gray: server not running
  - Blue: running, no clients connected
  - Green: client(s) connected (tooltip shows count)

Configuration is automatically sent when a show is loaded or the configuration changes.

## Usage

```python
from utils.tcp import VisualizerTCPServer

server = VisualizerTCPServer(config, port=9000)
server.client_connected.connect(lambda addr: print(f"Connected: {addr}"))
server.start()

# When config changes:
server.update_config(new_config)

server.stop()
```

## Network

- **Host**: `0.0.0.0` (all interfaces)
- **Port**: 9000
- **Protocol**: TCP
- **Format**: JSON, newline-delimited (`\n`)
- **Security**: No authentication or encryption. Intended for trusted local networks only.

### Firewall

```bash
# Windows
netsh advfirewall firewall add rule name="Show Creator TCP" dir=in action=allow protocol=TCP localport=9000

# Linux
sudo ufw allow 9000/tcp
```

## Troubleshooting

| Problem | Solution |
|---------|----------|
| Server won't start | Check if port 9000 is in use (`netstat -ano \| findstr :9000`) |
| Client can't connect | Verify checkbox is enabled, LED is blue/green, firewall allows port |
| No messages received | Ensure a configuration with fixtures is loaded |
| JSON parse errors | Buffer data until `\n` delimiter, parse each line separately |
