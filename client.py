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
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
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
        
        # Client's advertised window size (fixed at a reasonable value)
        self.window_size = 64  # Use a reasonable fixed window size
        
        # Application buffer size (for tracking purposes only)
        self.application_buffer_size = 1024 * 1024  # 1MB application buffer
        self.application_buffer_used = 0
        
        # Stats for logging
        self.retransmissions = 0
        self.total_packets_sent = 0
        self.start_time = None
        self.last_log_time = 0
        self.log_interval = 2.0  # Log every 2 seconds
    
    def establish_connection(self):
        """Establish connection with three-way handshake"""
        logger.info("Initiating connection to %s", self.remote_addr)
        
        # Send SYN with initial window size
        syn_packet = self.send_packet(PacketType.SYN, payload=b'', window=self.window_size)
        
        # Wait for SYN-ACK
        syn_ack, _ = self.receive_packet(timeout=5.0)
        if not syn_ack or syn_ack.flags != PacketType.SYN:
            raise ConnectionError("Failed to establish connection: No SYN-ACK received")
        
        # Update expected sequence number
        self.expected_seq_num = syn_ack.seq_num + 1
        
        # Save receiver's initial window size
        self.receiver_window = syn_ack.window
        logger.info("Received initial window size from server: %d", self.receiver_window)
        
        # Send ACK with our window size
        self.send_packet(PacketType.ACK, ack_num=self.expected_seq_num, payload=b'', window=self.window_size)
        
        # Increment sequence number for the SYN packet
        self.sequence_number += 1
        
        # Set initial sequence for tracking bytes sent
        self.initial_sequence = self.sequence_number
        
        # Update base and next_seq_to_send
        self.next_seq_to_send = self.sequence_number
        self.base = self.sequence_number
        
        logger.info("Connection established with %s", self.remote_addr)
        logger.info("Sequence number after handshake: %d", self.sequence_number)
        
        # Initialize stats
        self.start_time = time.time()
        self.last_log_time = self.start_time
        
        return True
    
    def close_connection(self):
        """Close the connection with FIN packets"""
        logger.info("Initiating connection close")
        
        # Log final stats
        self._log_connection_stats(final=True)
        
        # Send FIN with current window size
        fin_packet = self.send_packet(PacketType.FIN, window=self.window_size)
        
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
            logger.info("Sequence number before first data: %d", self.sequence_number)

            file_size = os.path.getsize(file_path)
            num_packets = math.ceil(file_size / MAX_PAYLOAD_SIZE)
            
            logger.info("Sending file: %s", file_path)
            logger.info("File size: %d bytes, Estimated packets: %d", file_size, num_packets)
            
            with open(file_path, 'rb') as file:
                bytes_sent = 0
                start_time = time.time()
                self.start_time = start_time
                
                # Start sending data
                while bytes_sent < file_size:
                    self._send_available_data(file)
                    self._handle_acknowledgments()
                    
                    # Update progress
                    bytes_sent = self.sequence_number - self.initial_sequence
                    progress = (bytes_sent / file_size) * 100
                    
                    # Periodically log detailed stats
                    self._log_periodic_stats(bytes_sent, file_size)
                
                # Wait for all packets to be acknowledged
                while self.base < self.next_seq_to_send:
                    self._handle_acknowledgments()
                    # Log final window while waiting for ACKs
                    self._log_periodic_stats(bytes_sent, file_size, force=True)
                
                duration = time.time() - start_time
                throughput = file_size / duration / 1024  # KB/s
                
                logger.info("File sent successfully in %.2f seconds", duration)
                logger.info("Throughput: %.2f KB/s", throughput)
                
                return True
                
        except Exception as e:
            logger.error("Error sending file: %s", e)
            return False
        finally:
            self.close_connection()
    
    def send_synthetic_data(self, total_bytes):
        """Send synthetic data using the reliable protocol"""
        if not self.establish_connection():
            return False
        
        try:
            logger.info("Sequence number before first data: %d", self.sequence_number)

            num_packets = math.ceil(total_bytes / MAX_PAYLOAD_SIZE)
            
            logger.info("Sending synthetic data: %d bytes", total_bytes)
            logger.info("Estimated packets: %d", num_packets)
            
            bytes_sent = 0
            start_time = time.time()
            self.start_time = start_time
            
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
                
                # Periodically log detailed stats
                self._log_periodic_stats(bytes_sent, total_bytes)
            
            # Wait for all packets to be acknowledged
            while self.base < self.next_seq_to_send:
                self._handle_acknowledgments()
                # Log final window while waiting for ACKs
                self._log_periodic_stats(bytes_sent, total_bytes, force=True)
            
            duration = time.time() - start_time
            throughput = total_bytes / duration / 1024  # KB/s
            
            logger.info("Data sent successfully in %.2f seconds", duration)
            logger.info("Throughput: %.2f KB/s", throughput)
            
            return True
                
        except Exception as e:
            logger.error("Error sending data: %s", e)
            return False
        finally:
            self.close_connection()
    
    def _log_periodic_stats(self, bytes_sent, total_bytes, force=False):
        """Log detailed stats periodically"""
        current_time = time.time()
        if force or (current_time - self.last_log_time >= self.log_interval):
            progress = (bytes_sent / total_bytes) * 100 if total_bytes > 0 else 0
            
            # Calculate current effective window
            packets_in_flight = (self.next_seq_to_send - self.base) // MAX_PAYLOAD_SIZE
            effective_window = self.congestion.get_window_size(self.receiver_window)
            
            # Calculate instantaneous throughput
            elapsed = current_time - self.start_time
            throughput = bytes_sent / elapsed / 1024 if elapsed > 0 else 0
            
            logger.info("Progress: %.2f%% (%d/%d bytes)", progress, bytes_sent, total_bytes)
            logger.info("Window Stats: cwnd=%.2f, rwnd=%d, effective=%d, in_flight=%d, ssthresh=%.2f", 
                       self.congestion.cwnd, self.receiver_window, effective_window, 
                       packets_in_flight, self.congestion.ssthresh)
            logger.info("Performance: %.2f KB/s, RTT=%.3fs, RTO=%.3fs, Retransmissions=%d", 
                       throughput, self.rtt_estimator.srtt, self.rtt_estimator.rto, self.retransmissions)
            
            # Log congestion state
            if self.congestion.in_fast_recovery:
                state = "FAST RECOVERY"
            elif self.congestion.cwnd < self.congestion.ssthresh:
                state = "SLOW START"
            else:
                state = "CONGESTION AVOIDANCE"
            logger.info("Congestion state: %s", state)
            
            self.last_log_time = current_time
    
    def _log_connection_stats(self, final=False):
        """Log overall connection statistics"""
        if not final:
            return
            
        # Only log at connection close
        packets_sent = self.total_packets_sent
        retransmission_rate = (self.retransmissions / packets_sent * 100) if packets_sent > 0 else 0
        
        logger.info("Connection Statistics:")
        logger.info("  Total packets sent: %d", packets_sent)
        logger.info("  Retransmissions: %d (%.2f%%)", self.retransmissions, retransmission_rate)
        logger.info("  Final congestion window: %.2f packets", self.congestion.cwnd)
        logger.info("  Final slow start threshold: %.2f packets", self.congestion.ssthresh)
        logger.info("  Final RTT estimate: %.3f seconds", self.rtt_estimator.srtt)
    
    def _update_client_window_size(self):
        """Update client's advertised window size (simplified)"""
        # Keep the window size fixed at a reasonable value
        # This is separate from congestion control window
        self.application_buffer_used = sum(len(packet.payload) for packet, _ in self.send_buffer.values())
        
        # For debugging only
        logger.debug("Current application buffer usage: %d bytes", self.application_buffer_used)
    
    def _send_available_data(self, file):
        """Send data chunks from file that fit within the window"""
        # Calculate effective window size (based on congestion control)
        effective_window = self.congestion.get_window_size(self.receiver_window)
        
        # Calculate how many more packets can be sent in the current window
        packets_in_flight = (self.next_seq_to_send - self.base) // MAX_PAYLOAD_SIZE
        available_slots = max(0, effective_window - packets_in_flight)
        
        logger.debug("Window info: effective=%d, in_flight=%d, available=%d, receiver=%d", 
                     effective_window, packets_in_flight, available_slots, self.receiver_window)
        
        for _ in range(available_slots):
            # Read the next chunk of data
            chunk = file.read(MAX_PAYLOAD_SIZE)
            if not chunk:  # End of file
                break
            
            self._send_data_chunk(chunk)
    
    def _send_data_chunk(self, chunk):
        """Send a single data chunk and store it for possible retransmission"""
        curr_seq = self.sequence_number  # Save current sequence number
        
        logger.debug("Sending DATA packet: seq=%d, size=%d bytes", curr_seq, len(chunk))
        
        # Create and send the packet with current window size
        packet = self.send_packet(PacketType.DATA, payload=chunk, 
                                ack_num=self.expected_seq_num, 
                                window=self.window_size)
        
        # Store in send buffer for retransmission if needed
        self.send_buffer[curr_seq] = (packet, 0)
        self.total_packets_sent += 1
        
        # Update next sequence number to send
        self.next_seq_to_send = self.sequence_number
        
        # Start timer for this packet if it's the first packet in the window
        if self.base == curr_seq:
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
                
                # Send cumulative ACK with our window size
                self.send_packet(PacketType.ACK, ack_num=self.expected_seq_num, window=self.window_size)
            
            # Update receiver's window size for flow control
            if hasattr(packet, 'window'):
                old_window = self.receiver_window
                self.receiver_window = packet.window
                if old_window != self.receiver_window:
                    logger.debug("Received window update from server: %d -> %d", old_window, self.receiver_window)
            
        else:
            # Timeout occurred
            self._handle_timeout()
    
    def _process_ack(self, ack_packet):
        """Process an ACK packet"""
        # Update flow control - save the receiver's advertised window
        if hasattr(ack_packet, 'window'):
            old_window = self.receiver_window
            self.receiver_window = ack_packet.window
            if old_window != self.receiver_window:
                logger.debug("Receiver window update: %d -> %d", old_window, self.receiver_window)
        
        old_cwnd = self.congestion.cwnd
        old_ssthresh = self.congestion.ssthresh
        
        # Update congestion control
        self.congestion.on_ack_received(ack_packet.ack_num)
        
        # Log if congestion window changed significantly
        if abs(old_cwnd - self.congestion.cwnd) > 1 or old_ssthresh != self.congestion.ssthresh:
            logger.debug("Congestion window update: %.2f -> %.2f (ssthresh=%.2f)", 
                        old_cwnd, self.congestion.cwnd, self.congestion.ssthresh)
        
        # Cumulative ACK - all packets up to ack_num are acknowledged
        if ack_packet.ack_num > self.base:
            # Count acknowledged packets
            acked_bytes = ack_packet.ack_num - self.base
            acked_packets = math.ceil(acked_bytes / MAX_PAYLOAD_SIZE)
            logger.debug("ACK received: %d, acknowledging %d bytes (%d packets)", 
                        ack_packet.ack_num, acked_bytes, acked_packets)
            
            # Remove acknowledged packets from the send buffer
            keys_to_remove = [seq for seq in self.send_buffer if seq < ack_packet.ack_num]
            for seq in keys_to_remove:
                # Update RTT estimator if this is the oldest packet
                if seq == self.base:
                    packet, _ = self.send_buffer[seq]
                    rtt = time.time() - packet.timestamp
                    old_rto = self.rtt_estimator.rto
                    new_rto = self.rtt_estimator.update(rtt)
                    
                    if abs(old_rto - new_rto) > 0.1:  # Only log significant changes
                        logger.debug("RTT update: measured=%.3fs, srtt=%.3fs, rto=%.3fs", 
                                    rtt, self.rtt_estimator.srtt, new_rto)
                
                del self.send_buffer[seq]
            
            # Update base
            self.base = ack_packet.ack_num
            
            # If all packets are acknowledged, stop the timer
            if self.base == self.next_seq_to_send:
                self.stop_timer()
                logger.debug("All packets acknowledged, window clear")
            else:
                # Restart the timer for the next unacknowledged packet
                self.set_timer()
                # Log packets still in flight
                packets_in_flight = (self.next_seq_to_send - self.base) // MAX_PAYLOAD_SIZE
                logger.debug("Packets still in flight: %d", packets_in_flight)
    
    def _handle_timeout(self):
        """Handle timeouts and perform retransmissions"""
        # Update congestion control on timeout
        old_cwnd = self.congestion.cwnd
        old_ssthresh = self.congestion.ssthresh
        
        self.congestion.on_timeout()
        
        logger.warning("Timeout detected. Congestion window: %.2f -> %.2f, ssthresh: %.2f -> %.2f", 
                      old_cwnd, self.congestion.cwnd, old_ssthresh, self.congestion.ssthresh)
        
        # Find the oldest unacknowledged packet
        if self.base in self.send_buffer:
            packet, retries = self.send_buffer[self.base]
            
            # If max retries reached, consider the connection broken
            if retries >= 10:
                logger.error("Max retransmission attempts reached. Connection seems broken.")
                return
            
            # Create a new packet with the current window size 
            # but preserve the original sequence number
            updated_packet = Packet(
                seq_num=packet.seq_num,
                ack_num=packet.ack_num,
                flags=packet.flags,
                window=self.window_size,  # Use current window size
                payload=packet.payload
            )
            
            # Retransmit the packet with updated window
            self.sock.sendto(updated_packet.to_bytes(), self.remote_addr)
            self.retransmissions += 1
            logger.warning("Retransmitting packet: seq=%d, size=%d bytes, attempt=%d", 
                          packet.seq_num, len(packet.payload), retries+1)
            
            # Update packet in send buffer with the new one
            self.send_buffer[self.base] = (updated_packet, retries + 1)
            
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