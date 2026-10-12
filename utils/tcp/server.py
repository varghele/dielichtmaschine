# utils/tcp/server.py
# TCP server for sending configuration to Visualizer

import socket
import threading
import time
from typing import Dict, List, Optional, Set, Tuple
from PyQt6.QtCore import QObject, pyqtSignal
from config.models import Configuration
from utils import user_warnings
from .protocol import VisualizerProtocol


class VisualizerTCPServer(QObject):
    """
    TCP server for sending configuration data to Visualizer clients.

    Runs in a background thread and manages multiple client connections.
    Emits signals when clients connect/disconnect.
    """

    # Signals
    client_connected = pyqtSignal(str)  # client address
    client_disconnected = pyqtSignal(str)  # client address
    error_occurred = pyqtSignal(str)  # error message

    def __init__(self, config: Configuration, port: int = 9000):
        """
        Initialize TCP server.

        Args:
            config: Configuration to send to clients
            port: TCP port to listen on (default: 9000)
        """
        super().__init__()

        self.config = config
        self.port = port
        self.host = "0.0.0.0"  # Listen on all interfaces

        # Server state
        self.server_socket: Optional[socket.socket] = None
        self.running = False
        self.server_thread: Optional[threading.Thread] = None

        # Connected clients. Every write to a client socket holds that
        # client's send lock: the client's own thread (initial config,
        # heartbeat) and the UI thread (send_update, update_config) both
        # write, and two sendall() calls on one socket can interleave
        # their bytes mid-message.
        self.clients: Set[socket.socket] = set()
        self._send_locks: Dict[socket.socket, threading.Lock] = {}
        self.clients_lock = threading.Lock()

        print(f"TCP Server initialized on port {port}")

    def start(self):
        """Start the TCP server in a background thread."""
        if self.running:
            print("TCP Server already running")
            return

        # Bind HERE, on the caller's thread: a port that cannot be
        # opened (taken by another program or a second Lichtmaschine)
        # must leave is_running() False BEFORE start() returns. The
        # VISUALIZER toggle reads it right after the call to decide
        # whether to launch the viewer, and the status chip reads it
        # too; a stale True also made the next press "stop" a server
        # that never existed instead of retrying.
        server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server_socket.bind((self.host, self.port))
            server_socket.listen(5)
            server_socket.settimeout(1.0)  # Timeout for accept()
        except Exception as e:
            try:
                server_socket.close()
            except Exception:
                pass
            print(f"Server error: {e}")
            user_warnings.warn(
                f"Visualizer feed could not listen on port {self.port}: {e}",
                category="output")
            self.error_occurred.emit(str(e))
            return

        print(f"TCP Server listening on {self.host}:{self.port}")
        self.server_socket = server_socket
        self.running = True
        self.server_thread = threading.Thread(
            target=self._run_server, args=(server_socket,), daemon=True)
        self.server_thread.start()
        print(f"TCP Server started on {self.host}:{self.port}")

    def stop(self):
        """Stop the TCP server and disconnect all clients."""
        if not self.running:
            return

        print("Stopping TCP Server...")
        self.running = False

        # Close all client connections
        with self.clients_lock:
            for client_socket in list(self.clients):
                try:
                    client_socket.close()
                except Exception:
                    pass
            self.clients.clear()
            self._send_locks.clear()

        # Close server socket
        if self.server_socket:
            try:
                self.server_socket.close()
            except Exception:
                pass
            self.server_socket = None

        # Wait for server thread to finish
        if self.server_thread and self.server_thread.is_alive():
            self.server_thread.join(timeout=2.0)

        print("TCP Server stopped")

    def _run_server(self, server_socket: socket.socket):
        """Main server loop (runs in background thread)."""
        # The listening socket is passed in, not read from the
        # attribute: after a stop() + start() the attribute belongs to
        # the NEXT server thread, and this one must neither close that
        # socket nor keep looping on it.
        me = threading.current_thread()
        try:
            while self.running and self.server_thread is me:
                try:
                    # Accept client connection (with timeout)
                    client_socket, client_address = server_socket.accept()
                    client_addr_str = f"{client_address[0]}:{client_address[1]}"

                    print(f"Client connected: {client_addr_str}")

                    # The client joins self.clients in _handle_client,
                    # under its send lock, so no update can reach it
                    # before its initial config.

                    # Emit signal
                    self.client_connected.emit(client_addr_str)

                    # Handle client in separate thread
                    client_thread = threading.Thread(
                        target=self._handle_client,
                        args=(client_socket, client_addr_str),
                        daemon=True
                    )
                    client_thread.start()

                except socket.timeout:
                    # Normal timeout, continue loop
                    continue
                except Exception as e:
                    if self.running and self.server_thread is me:
                        print(f"Error accepting connection: {e}")
                        self.error_occurred.emit(str(e))

        except Exception as e:
            print(f"Server error: {e}")
            self.error_occurred.emit(str(e))
        finally:
            try:
                server_socket.close()
            except Exception:
                pass

    def _handle_client(self, client_socket: socket.socket, client_addr: str):
        """
        Handle a connected client (runs in separate thread per client).

        Args:
            client_socket: Client socket
            client_addr: Client address string
        """
        try:
            # Register and send the initial configuration under the
            # client's send lock: a send_update() from the UI thread
            # finds the client only once the lock is taken, waits for
            # the config, and lands after it.
            send_lock = threading.Lock()
            with send_lock:
                with self.clients_lock:
                    if not self.running:
                        # stop() ran between accept() and here and has
                        # already swept the client set.
                        return
                    self.clients.add(client_socket)
                    self._send_locks[client_socket] = send_lock
                self._write_config(client_socket)

            # Keep connection alive and handle incoming data
            while self.running:
                try:
                    # Receive data (with timeout)
                    client_socket.settimeout(5.0)
                    data = client_socket.recv(1024)

                    if not data:
                        # Client disconnected
                        break

                    # Parse message (currently just for ACK/heartbeat)
                    try:
                        message = VisualizerProtocol.parse_message(data.decode('utf-8'))
                        # Handle incoming messages if needed
                        # (Currently clients just receive, not send)
                    except Exception as e:
                        print(f"Error parsing message from {client_addr}: {e}")

                except socket.timeout:
                    # Send heartbeat to keep connection alive
                    try:
                        heartbeat = VisualizerProtocol.create_heartbeat_message()
                        with send_lock:
                            client_socket.sendall(heartbeat.encode('utf-8'))
                    except Exception:
                        break
                except Exception as e:
                    print(f"Error receiving from {client_addr}: {e}")
                    break

        except Exception as e:
            print(f"Error handling client {client_addr}: {e}")
        finally:
            # Remove from clients set
            with self.clients_lock:
                self.clients.discard(client_socket)
                self._send_locks.pop(client_socket, None)

            # Close socket
            try:
                client_socket.close()
            except Exception:
                pass

            print(f"Client disconnected: {client_addr}")
            self.client_disconnected.emit(client_addr)

    def _client_snapshot(self) -> List[Tuple[socket.socket, threading.Lock]]:
        """The connected clients with their send locks. Writes happen
        outside clients_lock, so one slow client does not hold up
        registration, disconnects or the other clients."""
        with self.clients_lock:
            return [(s, self._send_locks[s]) for s in self.clients]

    def _write_config(self, client_socket: socket.socket):
        """
        Send complete configuration to a client. The caller holds the
        client's send lock.

        Args:
            client_socket: Client socket to send to
        """
        try:
            # Serialize configuration
            messages = VisualizerProtocol.serialize_full_config(self.config)

            # Send all messages
            for message in messages:
                client_socket.sendall(message.encode('utf-8'))
                time.sleep(0.01)  # Small delay between messages

            print(f"Sent configuration to client ({len(messages)} messages)")

        except Exception as e:
            print(f"Error sending config to client: {e}")
            raise

    def send_update(self, update_type: str, data: dict):
        """
        Send update message to all connected clients.

        Args:
            update_type: Type of update
            data: Update data
        """
        if not self.clients:
            return

        payload = VisualizerProtocol.create_update_message(
            update_type, data).encode('utf-8')

        for client_socket, send_lock in self._client_snapshot():
            try:
                with send_lock:
                    client_socket.sendall(payload)
            except Exception as e:
                print(f"Error sending update to client: {e}")

    def update_config(self, config: Configuration):
        """
        Update configuration and send to all clients.

        Args:
            config: New configuration
        """
        self.config = config

        # Send full config to all connected clients
        for client_socket, send_lock in self._client_snapshot():
            try:
                with send_lock:
                    self._write_config(client_socket)
            except Exception as e:
                print(f"Error updating client config: {e}")

    def get_client_count(self) -> int:
        """
        Get number of connected clients.

        Returns:
            Number of connected clients
        """
        with self.clients_lock:
            return len(self.clients)

    def is_running(self) -> bool:
        """
        Check if server is running.

        Returns:
            True if server is running
        """
        return self.running
