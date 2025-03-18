"""
server.py - Receiver/Server implementation of the reliable UDP protocol
"""

import socket
import time
import logging
import os
import sys
import random
from collections import defaultdict, deque
from protocol import ReliableUDP, Packet, PacketType, MAX_PAYLOAD_SIZE

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger('ReliableUDP-Server')

class ReliableUDPServer(ReliableUDP):
    """Server implementation of Reliable UDP Protocol"""
    
    def __init__(self, listen_ip, listen_port, output_dir=None, packet_loss_rate=0.0):
        """Initialize server to listen on specified address"""
        # Create UDP socket
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind((listen_ip, listen_port))
        
        # Initialize with a placeholder remote address (will be set on connection)
        self.remote_addr = None
        super().__init__(self.sock, self.remote_addr)
        
        # Receive buffer for ordering packets
        self.receive_buffer = {}  # seq_num -> packet
        self.packet_loss_rate = packet_loss_rate
        self.output_dir = output_dir or os.getcwd()
        
        # Flow control
        self.max_window_size = 64  # Maximum receiver window size
        self.window_size = self.max_window_size
        self.buffer_capacity = self.max_window_size * MAX_PAYLOAD_SIZE  # Buffer capacity in bytes
        self.client_window = 0  # Window size advertised by client
        
        # Bytes currently being processed
        self.processing_bytes = 0
        
        # Statistics
        self.received_packets = 0
        self.dropped_packets = 0
        self.out_of_order_packets = 0
        self.total_bytes = 0
    
    def wait_for_connection(self):
        """Wait for a client to connect"""
        logger.info("Waiting for client connection on %s", self.sock.getsockname())

        while True:
            # Wait for SYN packet
            packet, addr = self.receive_packet()
            if not packet:
                continue
            
            if packet.flags == PacketType.SYN:
                # Save client address
                self.remote_addr = addr
                logger.info("Client connecting from %s", addr)
                
                # Update expected sequence number
                self.expected_seq_num = packet.seq_num + 1
                logger.info("Expected sequence after SYN: %d", self.expected_seq_num)
                
                # Save client's window size if available
                if hasattr(packet, 'window'):
                    self.client_window = packet.window
                    logger.info("Client advertised window size: %d", self.client_window)
                
                # Update our window before sending SYN-ACK
                self._update_window_size()
                
                # Send SYN-ACK with our window size
                self.send_packet(PacketType.SYN, ack_num=self.expected_seq_num, window=self.window_size)
                
                # Wait for ACK to complete three-way handshake
                ack_packet, _ = self.receive_packet(timeout=5.0)
                if not ack_packet or ack_packet.flags != PacketType.ACK:
                    logger.warning("No ACK received, resetting connection state")
                    self.remote_addr = None
                    continue
                
                # Update client window size if provided in ACK
                if hasattr(ack_packet, 'window'):
                    self.client_window = ack_packet.window
                    logger.info("Client advertised window size in ACK: %d", self.client_window)
                
                logger.info("Connection established with %s", addr)
                return True
            
            else:
                logger.warning("Received non-SYN packet during connection setup, ignoring")
    
    def _update_window_size(self):
        """Update the receiver's window size based on buffer usage"""
        # Calculate bytes in buffer (not processed)
        buffer_usage = sum(len(p.payload) for p in self.receive_buffer.values())
        
        # Add bytes being processed
        total_buffer_usage = buffer_usage + self.processing_bytes
        
        # Calculate available space
        available_space = max(0, self.buffer_capacity - total_buffer_usage)
        
        # Convert to packet slots
        self.window_size = max(1, available_space // MAX_PAYLOAD_SIZE)
        
        logger.debug("Server window size: %d (buffer usage: %d/%d)", 
                     self.window_size, total_buffer_usage, self.buffer_capacity)
    
    def receive_data(self, output_file=None):
        """Receive data from a client"""
        # Initialize output file if provided
        file_obj = None
        if output_file:
            file_path = os.path.join(self.output_dir, output_file)
            file_obj = open(file_path, 'wb')
            logger.info("Writing received data to %s", file_path)
        
        try:
            data_buffer = bytearray()
            last_delivered_seq = self.expected_seq_num - 1
            
            # Start receiving data
            start_time = time.time()
            connection_active = True
            
            while connection_active:
                # Update window size before potentially receiving a packet
                self._update_window_size()
                
                packet, addr = self.receive_packet(timeout=30.0)
                
                if not packet:
                    logger.info("No packet received within timeout, assuming connection closed")
                    break
                
                # Check if this is from our connected client
                if addr != self.remote_addr:
                    continue
                
                # Update client window size if available in packet
                if hasattr(packet, 'window'):
                    self.client_window = packet.window
                    logger.debug("Client window size updated: %d", self.client_window)
                
                # Handle packet based on type
                if packet.flags == PacketType.DATA:
                    connection_active = self._handle_data_packet(packet, file_obj, data_buffer, last_delivered_seq)
                    
                elif packet.flags == PacketType.FIN:
                    logger.info("Received FIN packet, connection closing")
                    # Send FIN with our current window
                    self._update_window_size()
                    self.send_packet(PacketType.FIN, ack_num=packet.seq_num + 1, window=self.window_size)
                    connection_active = False
            
            # Calculate statistics
            duration = time.time() - start_time
            if duration > 0:
                throughput = self.total_bytes / duration / 1024  # KB/s
                logger.info("Transfer complete in %.2f seconds", duration)
                logger.info("Throughput: %.2f KB/s", throughput)
                logger.info("Total packets received: %d", self.received_packets)
                logger.info("Packets dropped (simulated loss): %d", self.dropped_packets)
                logger.info("Out-of-order packets: %d", self.out_of_order_packets)
            
            # Return the received data if no file was specified
            if not file_obj:
                return bytes(data_buffer)
            return True
            
        except Exception as e:
            logger.error("Error receiving data: %s", e)
            return False
        finally:
            if file_obj:
                file_obj.close()
    
    def _handle_data_packet(self, packet, file_obj, data_buffer, last_delivered_seq):
        """Process a received data packet"""
        logger.debug("Packet received: seq=%d, expected=%d", packet.seq_num, self.expected_seq_num)

        # Simulate packet loss
        if random.random() < self.packet_loss_rate:
            self.dropped_packets += 1
            logger.debug("Simulating packet loss for seq=%d", packet.seq_num)
            # Still send ACK for the last correctly received packet to trigger fast retransmit
            self._update_window_size()
            self.send_packet(PacketType.ACK, ack_num=self.expected_seq_num, window=self.window_size)
            return True
        
        self.received_packets += 1
        
        # Check if this is the expected packet
        if packet.seq_num == self.expected_seq_num:
            # Mark bytes as "processing" before writing to file/buffer
            payload_size = len(packet.payload)
            self.processing_bytes += payload_size
            
            # Process this packet
            if file_obj:
                file_obj.write(packet.payload)
                file_obj.flush()  # Ensure data is written to disk
            else:
                data_buffer.extend(packet.payload)
            
            # After processing, bytes are no longer "processing"
            self.processing_bytes -= payload_size
            
            self.total_bytes += payload_size
            last_delivered_seq = packet.seq_num
            self.expected_seq_num += payload_size
            
            # Check if we have any buffered packets that can now be processed
            # First sort the keys to process in order
            ordered_keys = sorted([k for k in self.receive_buffer.keys() if k == self.expected_seq_num])
            
            for seq in ordered_keys:
                buffered_packet = self.receive_buffer.pop(seq)
                payload_size = len(buffered_packet.payload)
                
                # Mark as processing
                self.processing_bytes += payload_size
                
                if file_obj:
                    file_obj.write(buffered_packet.payload)
                    file_obj.flush()  # Ensure data is written to disk
                else:
                    data_buffer.extend(buffered_packet.payload)
                
                # Processing complete
                self.processing_bytes -= payload_size
                
                self.total_bytes += payload_size
                last_delivered_seq = buffered_packet.seq_num
                self.expected_seq_num += payload_size
        
        elif packet.seq_num > self.expected_seq_num:
            # Out of order packet - buffer it
            self.out_of_order_packets += 1
            self.receive_buffer[packet.seq_num] = packet
            logger.debug("Out-of-order packet: expected=%d, received=%d", 
                         self.expected_seq_num, packet.seq_num)
        
        # Adjust window size after processing the packet
        self._update_window_size()
        
        # Send cumulative ACK with current window size
        self.send_packet(PacketType.ACK, ack_num=self.expected_seq_num, window=self.window_size)
        
        return True


def main():
    """Main function to run the server"""
    if len(sys.argv) < 3:
        print(f"Usage: {sys.argv[0]} <listen_port> <output_file> [packet_loss_rate]")
        sys.exit(1)
    
    listen_port = int(sys.argv[1])
    output_file = sys.argv[2]
    
    # Optional packet loss rate
    packet_loss_rate = 0.1
    if len(sys.argv) > 3:
        packet_loss_rate = float(sys.argv[3])
        logger.info("Simulating packet loss rate of %.1f%%", packet_loss_rate * 100)
    
    server = ReliableUDPServer('0.0.0.0', listen_port, packet_loss_rate=packet_loss_rate)
    
    while True:
        if server.wait_for_connection():
            server.receive_data(output_file)
            logger.info("Ready for new connections")


if __name__ == "__main__":
    main()