"""
protocol.py - Core reliable transport protocol implementation over UDP
"""

import time
import random
from enum import Enum
from collections import deque
import struct

# Protocol constants
MAX_PACKET_SIZE = 1024  # Maximum packet size in bytes
HEADER_SIZE = 14  # Size of the header in bytes (seq, ack, flags, window)
MAX_PAYLOAD_SIZE = MAX_PACKET_SIZE - HEADER_SIZE
DEFAULT_TIMEOUT = 0.5  # Timeout in seconds
MAX_RETRIES = 10  # Maximum number of retransmission attempts
INITIAL_WINDOW_SIZE = 1  # Initial window size (packets)
INITIAL_SSTHRESH = 64  # Initial slow start threshold
MAX_WINDOW_SIZE = 128  # Maximum window size

class PacketType(Enum):
    DATA = 0
    ACK = 1
    SYN = 2
    FIN = 3

class Packet:
    """Represents a packet in our reliable protocol"""
    
    def __init__(self, seq_num=0, ack_num=0, flags=PacketType.DATA, window=0, payload=b''):
        self.seq_num = seq_num
        self.ack_num = ack_num
        self.flags = flags
        self.window = window
        self.payload = payload
        self.timestamp = time.time()
    
    def to_bytes(self):
        """Convert packet to bytes for transmission"""
        header = struct.pack('!IIIH', 
                            self.seq_num, 
                            self.ack_num, 
                            self.flags.value,
                            self.window)
        return header + self.payload
    
    @staticmethod
    def from_bytes(data):
        """Convert received bytes to a Packet object"""
        if len(data) < HEADER_SIZE:
            return None
        
        header = data[:HEADER_SIZE]
        payload = data[HEADER_SIZE:]
        
        seq_num, ack_num, flags_value, window = struct.unpack('!IIIH', header)
        flags = PacketType(flags_value)
        
        return Packet(seq_num, ack_num, flags, window, payload)
    
    def __str__(self):
        return f"Packet(seq={self.seq_num}, ack={self.ack_num}, flags={self.flags.name}, window={self.window}, payload_size={len(self.payload)})"


class CongestionControl:
    """Implements TCP-like congestion control"""
    
    def __init__(self):
        self.cwnd = INITIAL_WINDOW_SIZE  # Congestion window size
        self.ssthresh = INITIAL_SSTHRESH  # Slow start threshold
        self.duplicate_acks = 0  # Count of duplicate ACKs
        self.last_ack = 0  # Last ACK received
        self.in_fast_recovery = False  # Whether we're in fast recovery mode
    
    def on_ack_received(self, ack_num):
        """Update congestion window based on received ACK"""
        if ack_num > self.last_ack:
            # New ACK
            self.duplicate_acks = 0
            self.in_fast_recovery = False
            
            # Increase window based on current phase
            if self.cwnd < self.ssthresh:
                # Slow start phase - exponential growth
                self.cwnd += 1
            else:
                # Congestion avoidance phase - additive increase
                self.cwnd += 1 / self.cwnd
            
            self.last_ack = ack_num
        else:
            # Duplicate ACK
            self.duplicate_acks += 1
            
            # Fast retransmit / Fast recovery
            if self.duplicate_acks == 3 and not self.in_fast_recovery:
                # Enter fast recovery
                self.ssthresh = max(self.cwnd / 2, 2)
                self.cwnd = self.ssthresh + 3
                self.in_fast_recovery = True
            elif self.in_fast_recovery:
                # Increase cwnd during fast recovery
                self.cwnd += 1
    
    def on_timeout(self):
        """Handle timeout - severe congestion"""
        self.ssthresh = max(self.cwnd / 2, 2)
        self.cwnd = INITIAL_WINDOW_SIZE
        self.duplicate_acks = 0
        self.in_fast_recovery = False
    
    def get_window_size(self, receiver_window):
        """Return the effective window size (min of cwnd and receiver window)"""
        return min(int(self.cwnd), receiver_window, MAX_WINDOW_SIZE)


class ReliableUDP:
    """Base class for reliable UDP protocol implementation"""
    
    def __init__(self, sock, remote_addr):
        self.sock = sock
        self.remote_addr = remote_addr
        self.buffer_size = MAX_PACKET_SIZE
        self.sequence_number = random.randint(0, 100000)  # Initial sequence number
        self.expected_seq_num = 0  # Next expected sequence number
        self.last_ack_sent = 0  # Last acknowledgment sent
        self.window_size = INITIAL_WINDOW_SIZE  # Initial flow control window
        self.congestion = CongestionControl()  # Congestion control
        self.rtt_estimator = RTTEstimator()  # For adaptive timeout
    
    def send_packet(self, packet_type, payload=b'', ack_num=0):
        """Create and send a packet"""
        packet = Packet(
            seq_num=self.sequence_number,
            ack_num=ack_num,
            flags=packet_type,
            window=self.window_size,
            payload=payload
        )
        
        data = packet.to_bytes()
        self.sock.sendto(data, self.remote_addr)
        
        if packet_type == PacketType.DATA:
            self.sequence_number += len(payload)
        
        return packet
    
    def receive_packet(self, timeout=None):
        """Receive a packet with timeout"""
        self.sock.settimeout(timeout)
        try:
            data, addr = self.sock.recvfrom(self.buffer_size)
            packet = Packet.from_bytes(data)
            if packet:
                packet.timestamp = time.time()
            return packet, addr
        except (TimeoutError, ConnectionResetError) as e:
            return None, None
        finally:
            self.sock.settimeout(None)  # Reset timeout


class RTTEstimator:
    """Estimates round-trip time using exponential weighted moving average"""
    
    def __init__(self):
        self.srtt = 0  # Smoothed round-trip time
        self.rttvar = 0.75  # Round-trip time variation
        self.alpha = 0.125  # Weight for SRTT calculation
        self.beta = 0.25  # Weight for RTTVAR calculation
        self.rto = DEFAULT_TIMEOUT  # Retransmission timeout
        self.measurements = 0  # Number of measurements taken
    
    def update(self, rtt):
        """Update RTT estimate based on new measurement"""
        if self.measurements == 0:
            # First measurement
            self.srtt = rtt
            self.rttvar = rtt / 2
        else:
            # Update estimates
            self.rttvar = (1 - self.beta) * self.rttvar + self.beta * abs(self.srtt - rtt)
            self.srtt = (1 - self.alpha) * self.srtt + self.alpha * rtt
        
        # Update RTO with a minimum value
        self.rto = self.srtt + max(0.01, 4 * self.rttvar)
        self.measurements += 1
        
        # Clamp RTO between reasonable values
        self.rto = max(0.1, min(self.rto, 10.0))
        
        return self.rto
    
    def get_timeout(self):
        """Get current timeout value"""
        return self.rto if self.measurements > 0 else DEFAULT_TIMEOUT