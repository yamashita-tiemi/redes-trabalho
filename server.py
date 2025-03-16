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
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
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
        
        # Statistics
        self.received_packets = 0
        self.dropped_packets = 0
        self.out_of_order_packets = 0
        self.total_bytes = 0
    
    def wait_for_connection(self):
        """Wait for a client to connect"""
        logger.info("Waiting for client connection on %s", self.sock.getsockname())

        logger.info(f"Expected sequence after SYN: {self.expected_seq_num}")
        
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
                logger.info(f"Expected sequence after SYN: {self.expected_seq_num}")
                
                # Send SYN-ACK
                self.send_packet(PacketType.SYN, ack_num=self.expected_seq_num)
                
                # Wait for ACK to complete three-way handshake
                ack_packet, _ = self.receive_packet(timeout=5.0)
                if not ack_packet or ack_packet.flags != PacketType.ACK:
                    logger.warning("No ACK received, resetting connection state")
                    self.remote_addr = None
                    continue
                
                logger.info("Connection established with %s", addr)
                return True
            
            else:
                logger.warning("Received non-SYN packet during connection setup, ignoring")
    
    def receive_data(self, output_file=None):
        """Receive data from a client"""
        # Initialize output file if provided
        file_obj = None
        if output_file:
            file_path = os.path.join(self.output_dir, output_file)
            file_obj = open(file_path, 'wb')
            logger.info(f"Writing received data to {file_path}")
        
        try:
            data_buffer = bytearray()
            last_delivered_seq = self.expected_seq_num - 1
            
            # Start receiving data
            start_time = time.time()
            connection_active = True
            
            while connection_active:
                packet, addr = self.receive_packet(timeout=10.0)

                # if packet:
                #     logger.info(f"Received raw packet with seq={packet.seq_num}, ack={packet.ack_num}, flags={packet.flags}")
                
                if not packet:
                    logger.info("No packet received within timeout, assuming connection closed")
                    break
                
                # Check if this is from our connected client
                if addr != self.remote_addr:
                    continue
                
                # Handle packet based on type
                if packet.flags == PacketType.DATA:
                    connection_active = self._handle_data_packet(packet, file_obj, data_buffer, last_delivered_seq)
                    
                elif packet.flags == PacketType.FIN:
                    logger.info("Received FIN packet, connection closing")
                    self.send_packet(PacketType.FIN, ack_num=packet.seq_num + 1)
                    connection_active = False
            
            # Calculate statistics
            duration = time.time() - start_time
            if duration > 0:
                throughput = self.total_bytes / duration / 1024  # KB/s
                logger.info(f"Transfer complete in {duration:.2f} seconds")
                logger.info(f"Throughput: {throughput:.2f} KB/s")
                logger.info(f"Total packets received: {self.received_packets}")
                logger.info(f"Packets dropped (simulated loss): {self.dropped_packets}")
                logger.info(f"Out-of-order packets: {self.out_of_order_packets}")
            
            # Return the received data if no file was specified
            if not file_obj:
                return bytes(data_buffer)
            return True
            
        except Exception as e:
            logger.error(f"Error receiving data: {e}")
            return False
        finally:
            if file_obj:
                file_obj.close()
    
    def _handle_data_packet(self, packet, file_obj, data_buffer, last_delivered_seq):
        """Process a received data packet"""
        # logger.info(f"Received packet: seq={packet.seq_num}, payload size={len(packet.payload)}")

        # # In _handle_data_packet, add this logging:
        # if file_obj:
        #     logger.info(f"Writing {len(packet.payload)} bytes to file at position {file_obj.tell()}")
        #     file_obj.write(packet.payload)
        #     logger.info(f"After write, file position is {file_obj.tell()}")

        # if file_obj:
        #     file_obj.write(packet.payload)
        #     file_obj.flush()  # Force flush to disk

        # Simulate packet loss
        if random.random() < self.packet_loss_rate:
            self.dropped_packets += 1
            logger.debug(f"Simulating packet loss for seq={packet.seq_num}")
            # Still send ACK for the last correctly received packet to trigger fast retransmit
            self.send_packet(PacketType.ACK, ack_num=self.expected_seq_num)
            return True
        
        self.received_packets += 1
        
        # Check if this is the expected packet
        if packet.seq_num == self.expected_seq_num:
            # Process this packet
            if file_obj:
                file_obj.write(packet.payload)
            else:
                data_buffer.extend(packet.payload)
            
            self.total_bytes += len(packet.payload)
            last_delivered_seq = packet.seq_num
            self.expected_seq_num += len(packet.payload)
            
            # Check if we have any buffered packets that can now be processed
            while self.expected_seq_num in self.receive_buffer:
                buffered_packet = self.receive_buffer.pop(self.expected_seq_num)
                if file_obj:
                    file_obj.write(buffered_packet.payload)
                else:
                    data_buffer.extend(buffered_packet.payload)
                
                self.total_bytes += len(buffered_packet.payload)
                last_delivered_seq = buffered_packet.seq_num
                self.expected_seq_num += len(buffered_packet.payload)
        
        elif packet.seq_num > self.expected_seq_num:
            # Out of order packet - buffer it
            self.out_of_order_packets += 1
            self.receive_buffer[packet.seq_num] = packet
            logger.debug(f"Out-of-order packet: expected={self.expected_seq_num}, received={packet.seq_num}")
        
        # Adjust flow control window based on buffer usage
        buffer_usage = sum(len(p.payload) for p in self.receive_buffer.values())
        available_space = self.buffer_capacity - buffer_usage
        self.window_size = max(1, available_space // MAX_PAYLOAD_SIZE)
        
        # Send cumulative ACK
        self.send_packet(PacketType.ACK, ack_num=self.expected_seq_num)
        
        return True


def main():
    """Main function to run the server"""
    if len(sys.argv) < 3:
        print(f"Usage: {sys.argv[0]} <listen_port> <output_file> [packet_loss_rate]")
        sys.exit(1)
    
    listen_port = int(sys.argv[1])
    output_file = sys.argv[2]
    
    # Optional packet loss rate
    packet_loss_rate = 0.0
    if len(sys.argv) > 3:
        packet_loss_rate = float(sys.argv[3])
        logger.info(f"Simulating packet loss rate of {packet_loss_rate:.1%}")
    
    server = ReliableUDPServer('0.0.0.0', listen_port, packet_loss_rate=packet_loss_rate)
    
    while True:
        if server.wait_for_connection():
            server.receive_data(output_file)
            logger.info("Ready for new connections")


if __name__ == "__main__":
    main()