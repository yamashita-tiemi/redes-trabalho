"""
client.py - Sender/Client implementation of the reliable UDP protocol
"""

import socket
import time
import logging
import os
import sys
from collections import deque
import math
from protocol import ReliableUDP, Packet, PacketType, MAX_PAYLOAD_SIZE, INITIAL_WINDOW_SIZE

# Configure logging
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger('ReliableUDP-Client')

class ReliableUDPClient(ReliableUDP):
    """Client implementation of Reliable UDP Protocol"""
    
    def __init__(self, server_ip, server_port):
        """Initialize client with server address"""
        # Create UDP socket
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(('0.0.0.0', 0))
        server_addr = (server_ip, server_port)
        
        super().__init__(self.sock, server_addr)
        
        # Send buffer for storing packets waiting for ACK
        self.send_buffer = {}  # seq_num -> (packet, retries)
        self.next_seq_to_send = self.sequence_number  # Next sequence number to send
        self.base = self.sequence_number  # Base of the window (oldest unacknowledged packet)
        self.receiver_window = INITIAL_WINDOW_SIZE  # Flow control - receiver's window size
        self.initial_sequence = self.sequence_number
    
    def establish_connection(self):
        """Establish connection with three-way handshake"""
        logger.info("Initiating connection to %s", self.remote_addr)

        logger.info(f"Initial sequence number: {self.sequence_number}")
        
        # Send SYN
        syn_packet = self.send_packet(PacketType.SYN, payload=b'')
        
        # Wait for SYN-ACK
        syn_ack, _ = self.receive_packet(timeout=5.0)
        if not syn_ack or syn_ack.flags != PacketType.SYN:
            raise ConnectionError("Failed to establish connection: No SYN-ACK received")
        
        # Update sequence number and expected sequence number
        self.expected_seq_num = syn_ack.seq_num + 1
        
        # Send ACK
        self.send_packet(PacketType.ACK, ack_num=self.expected_seq_num, payload=b'')
        
        # Save receiver's initial window size
        self.receiver_window = syn_ack.window

        # Manually increment sequence number by 1 for the SYN packet
        # This is needed because send_packet() only increments for DATA packets
        self.sequence_number += 1
        
        # Update base and next_seq_to_send to match the new sequence number
        self.next_seq_to_send = self.sequence_number
        self.base = self.sequence_number

        self.initial_sequence = self.sequence_number

        logger.info(f"Sequence number after handshake: {self.sequence_number}")
        
        logger.info("Connection established with %s", self.remote_addr)
        return True
    
    def close_connection(self):
        """Close the connection with FIN packets"""
        logger.info("Initiating connection close")
        
        # Send FIN
        fin_packet = self.send_packet(PacketType.FIN)
        
        # Wait for FIN-ACK
        fin_ack, _ = self.receive_packet(timeout=5.0)
        if not fin_ack or fin_ack.flags != PacketType.FIN:
            logger.warning("No FIN-ACK received, closing anyway")
        
        # Close socket
        self.sock.close()
        logger.info("Connection closed")
    
    def send_file(self, file_path):
        """Send a file using the reliable protocol"""
        if not self.establish_connection():
            return False
        
        try:
            logger.info(f"Sequence number before first data: {self.sequence_number}")

            file_size = os.path.getsize(file_path)
            num_packets = math.ceil(file_size / MAX_PAYLOAD_SIZE)
            
            logger.info(f"Sending file: {file_path}")
            logger.info(f"File size: {file_size} bytes, Estimated packets: {num_packets}")
            
            with open(file_path, 'rb') as file:
                bytes_sent = 0
                start_time = time.time()
                
                # Start sending data
                while bytes_sent < file_size:
                    self._send_available_data(file)
                    self._handle_acknowledgments()
                    
                    # Update progress
                    bytes_sent = self.sequence_number - self.initial_sequence
                    progress = (bytes_sent / file_size) * 100
                    if bytes_sent % (MAX_PAYLOAD_SIZE * 100) == 0:
                        logger.info(f"Progress: {progress:.2f}% ({bytes_sent}/{file_size} bytes)")
                
                # Wait for all packets to be acknowledged
                while self.base < self.next_seq_to_send:
                    self._handle_acknowledgments()
                
                duration = time.time() - start_time
                throughput = file_size / duration / 1024  # KB/s
                
                logger.info(f"File sent successfully in {duration:.2f} seconds")
                logger.info(f"Throughput: {throughput:.2f} KB/s")
                
                return True
                
        except Exception as e:
            logger.error(f"Error sending file: {e}")
            return False
        finally:
            self.close_connection()
    
    def send_synthetic_data(self, total_bytes):
        """Send synthetic data using the reliable protocol"""
        if not self.establish_connection():
            return False
        
        try:
            logger.info(f"Sequence number before first data: {self.sequence_number}")

            num_packets = math.ceil(total_bytes / MAX_PAYLOAD_SIZE)
            
            logger.info(f"Sending synthetic data: {total_bytes} bytes")
            logger.info(f"Estimated packets: {num_packets}")
            
            bytes_sent = 0
            start_time = time.time()
            
            # Generate data pattern (just a simple pattern for testing)
            data_pattern = b''.join([bytes([i % 256]) for i in range(min(MAX_PAYLOAD_SIZE, total_bytes))])
            
            # Start sending data
            while bytes_sent < total_bytes:
                remaining = total_bytes - bytes_sent
                chunk_size = min(MAX_PAYLOAD_SIZE, remaining)
                
                # Use either a full data_pattern or the right sized chunk
                if chunk_size < len(data_pattern):
                    chunk = data_pattern[:chunk_size]
                else:
                    chunk = data_pattern
                
                self._send_data_chunk(chunk)
                self._handle_acknowledgments()
                
                # Update progress
                bytes_sent = self.sequence_number - self.initial_sequence
                progress = (bytes_sent / total_bytes) * 100
                if bytes_sent % (MAX_PAYLOAD_SIZE * 100) == 0:
                    logger.info(f"Progress: {progress:.2f}% ({bytes_sent}/{total_bytes} bytes)")
            
            # Wait for all packets to be acknowledged
            while self.base < self.next_seq_to_send:
                self._handle_acknowledgments()
            
            duration = time.time() - start_time
            throughput = total_bytes / duration / 1024  # KB/s
            
            logger.info(f"Data sent successfully in {duration:.2f} seconds")
            logger.info(f"Throughput: {throughput:.2f} KB/s")
            
            return True
                
        except Exception as e:
            logger.error(f"Error sending data: {e}")
            return False
        finally:
            self.close_connection()
    
    def _send_available_data(self, file):
        """Send data chunks from file that fit within the window"""
        # Calculate effective window size (minimum of congestion window and flow control window)
        effective_window = min(
        self.congestion.get_window_size(self.receiver_window),  # Janela de congestionamento
        self.receiver_window  # Janela do receptor
        )

        # Calculate how many more packets can be sent in the current window
        packets_in_flight = (self.next_seq_to_send - self.base) // MAX_PAYLOAD_SIZE
        available_slots = effective_window - packets_in_flight
        
        for _ in range(max(0, available_slots)):
            # Read the next chunk of data
            chunk = file.read(MAX_PAYLOAD_SIZE)
            if not chunk:  # End of file
                break
            
            self._send_data_chunk(chunk)
    
    def _send_data_chunk(self, chunk):
        """Send a single data chunk and store it for possible retransmission"""
        # Create and send the packet
        packet = self.send_packet(PacketType.DATA, payload=chunk, ack_num=self.expected_seq_num)
        
        # Store in send buffer for retransmission if needed
        self.send_buffer[self.sequence_number - len(chunk)] = (packet, 0)  # (packet, retry_count)
        
        # Update next sequence number to send
        self.next_seq_to_send = self.sequence_number
        
        # Start timer for this packet if it's the first packet in the window
        if self.base == self.sequence_number - len(chunk):
            self.set_timer()
    
    def _handle_acknowledgments(self):
        """Handle incoming ACKs, timeouts, and retransmissions"""
        timeout = self.rtt_estimator.get_timeout()
        packet, _ = self.receive_packet(timeout=timeout)
        
        if packet:
            if packet.flags == PacketType.ACK:
                self._process_ack(packet)
            
            # Update expected sequence number for data packets
            if packet.flags == PacketType.DATA and packet.seq_num == self.expected_seq_num:
                self.expected_seq_num += len(packet.payload)
                self.last_ack_sent = self.expected_seq_num
                # Send cumulative ACK
                self.send_packet(PacketType.ACK, ack_num=self.expected_seq_num)
            
            # Update receiver's window size for flow control
            self.receiver_window = packet.window
            
        else:
            # Timeout occurred
            self._handle_timeout()
    
    def _process_ack(self, ack_packet):
        """Process an ACK packet"""
        # Update congestion control
        self.receiver_window = ack_packet.window
        self.congestion.on_ack_received(ack_packet.ack_num)
        
        # Cumulative ACK - all packets up to ack_num are acknowledged
        if ack_packet.ack_num > self.base:
            # Remove acknowledged packets from the send buffer
            keys_to_remove = [seq for seq in self.send_buffer if seq < ack_packet.ack_num]
            for seq in keys_to_remove:
                # Update RTT estimator if this is the oldest packet
                if seq == self.base:
                    packet, _ = self.send_buffer[seq]
                    rtt = time.time() - packet.timestamp
                    self.rtt_estimator.update(rtt)
                
                del self.send_buffer[seq]
            
            # Update base
            self.base = ack_packet.ack_num
            
            # If all packets are acknowledged, stop the timer
            if self.base == self.next_seq_to_send:
                self.stop_timer()
            else:
                # Restart the timer for the next unacknowledged packet
                self.set_timer()
    
    def _handle_timeout(self):
        """Handle timeouts and perform retransmissions"""
        # Update congestion control on timeout
        self.congestion.on_timeout()
        
        # Find the oldest unacknowledged packet
        if self.base in self.send_buffer:
            packet, retries = self.send_buffer[self.base]
            
            # If max retries reached, consider the connection broken
            if retries >= 10:
                logger.error("Max retransmission attempts reached. Connection seems broken.")
                return
            
            # Retransmit the packet
            self.sock.sendto(packet.to_bytes(), self.remote_addr)
            logger.debug(f"Retransmitting packet: seq={packet.seq_num}, attempt={retries+1}")
            
            # Update retries count
            self.send_buffer[self.base] = (packet, retries + 1)
            
            # Reset the timer
            self.set_timer()
    
    def set_timer(self):
        """Set a timer for the oldest unacknowledged packet (non-blocking)"""
        # In a real implementation, this would set a timer callback
        # For simplicity, we'll use the timeout in receive_packet instead
        pass
    
    def stop_timer(self):
        """Stop the retransmission timer"""
        # In a real implementation, this would cancel the timer
        pass


def main():
    """Main function to run the client"""

    try:
        # Código atual do main
        if len(sys.argv) < 4:
            print(f"Usage: {sys.argv[0]} <server_ip> <server_port> <file_path>")
            print(f"   or: {sys.argv[0]} <server_ip> <server_port> --synthetic <bytes>")
            sys.exit(1)
        
        server_ip = sys.argv[1]
        server_port = int(sys.argv[2])
        
        client = ReliableUDPClient(server_ip, server_port)
        
        if sys.argv[3] == "--synthetic":
            if len(sys.argv) < 5:
                print("Error: Missing byte count for synthetic data")
                sys.exit(1)
            
            bytes_to_send = int(sys.argv[4])
            client.send_synthetic_data(bytes_to_send)
        else:
            file_path = sys.argv[3]
            client.send_file(file_path)
    except KeyboardInterrupt:
        logger.info("Client interrupted by user. Closing connection.")
        client.close_connection()


if __name__ == "__main__":
    main()