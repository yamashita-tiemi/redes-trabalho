"""
test.py - Test script to evaluate the reliable UDP protocol
"""

import os
import sys
import subprocess
import time
import random
import argparse
import logging
import threading
import shutil

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger('ReliableUDP-Test')

def create_test_file(filename, size_mb):
    """Create a test file of the specified size in megabytes"""
    size_bytes = size_mb * 1024 * 1024
    
    logger.info(f"Creating test file {filename} of {size_mb} MB")
    
    with open(filename, 'wb') as f:
        # Write in chunks to avoid memory issues with large files
        chunk_size = 1024 * 1024  # 1MB chunks
        remaining = size_bytes
        
        while remaining > 0:
            # Generate random data
            chunk = bytearray(random.getrandbits(8) for _ in range(min(chunk_size, remaining)))
            f.write(chunk)
            remaining -= len(chunk)
            
    logger.info(f"Created test file: {filename} ({os.path.getsize(filename)} bytes)")
    return filename

def start_server(port, output_file, packet_loss_rate):
    """Start the server in a separate process"""
    cmd = [sys.executable, 'server.py', str(port), output_file, str(packet_loss_rate)]
    logger.info(f"Starting server: {' '.join(cmd)}")
    
    server_process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1
    )
    
    # Wait a moment for server to initialize
    time.sleep(1)
    
    if server_process.poll() is not None:
        logger.error("Server failed to start")
        stdout, stderr = server_process.communicate()
        logger.error(f"Server stdout: {stdout}")
        logger.error(f"Server stderr: {stderr}")
        return None
    
    logger.info("Server started successfully")
    return server_process

def start_client(server_ip, server_port, mode, data_size):
    """Start the client process to send data"""
    if mode == 'synthetic':
        cmd = [sys.executable, 'client.py', server_ip, str(server_port), '--synthetic', str(data_size)]
    else:
        cmd = [sys.executable, 'client.py', server_ip, str(server_port), data_size]
    
    logger.info(f"Starting client: {' '.join(cmd)}")
    
    client_process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1
    )
    
    return client_process

def monitor_process(process, name):
    """Monitor process output and log it"""
    for line in process.stdout:
        logger.info(f"{name}: {line.strip()}")
    
    for line in process.stderr:
        logger.error(f"{name} error: {line.strip()}")

def verify_transfer(original_file, received_file):
    """Verify that files match after transfer"""
    if not os.path.exists(received_file):
        logger.error(f"Received file {received_file} does not exist")
        return False
    
    if os.path.getsize(original_file) != os.path.getsize(received_file):
        logger.error(f"File size mismatch: original={os.path.getsize(original_file)}, received={os.path.getsize(received_file)}")
        return False
    
    # Compare files
    with open(original_file, 'rb') as f1, open(received_file, 'rb') as f2:
        while True:
            chunk1 = f1.read(8192)
            chunk2 = f2.read(8192)
            
            if chunk1 != chunk2:
                logger.error("File content mismatch")
                return False
                
            if not chunk1:
                break
    
    logger.info("File transfer verified successfully")
    return True

def run_test(test_type, packet_loss_rate, data_size, verify=True):
    """Run a complete test scenario"""
    server_port = random.randint(10000, 65000)
    server_ip = '127.0.0.1'
    out_dir = 'test_output'
    
    # Ensure output directory exists
    os.makedirs(out_dir, exist_ok=True)
    
    # Clean up any previous files
    for f in os.listdir(out_dir):
        os.remove(os.path.join(out_dir, f))
    
    # Setup test parameters
    if test_type == 'file':
        test_file = os.path.join(out_dir, 'test_input.dat')
        received_file = os.path.join(out_dir, 'received.dat')
        
        # Create test file
        create_test_file(test_file, data_size // (1024 * 1024))  # Convert bytes to MB
    else:
        # Synthetic data
        test_file = str(data_size)  # Just pass the byte count
        received_file = os.path.join(out_dir, 'received.dat')
    
    # Start server
    server_process = start_server(server_port, received_file, packet_loss_rate)
    if not server_process:
        return False
    
    # Start server output monitoring
    server_thread = threading.Thread(target=monitor_process, args=(server_process, "Server"))
    server_thread.daemon = True
    server_thread.start()
    
    try:
        # Start client
        time.sleep(2)  # Give server time to start
        client_process = start_client(server_ip, server_port, 
                                     'file' if test_type == 'file' else 'synthetic', 
                                     test_file)
        
        # Monitor client output
        client_thread = threading.Thread(target=monitor_process, args=(client_process, "Client"))
        client_thread.daemon = True
        client_thread.start()
        
        # Wait for client to finish
        client_process.wait()
        logger.info(f"Client exited with code {client_process.returncode}")
        
        # Wait a bit for server to process everything
        time.sleep(5)
        
        # Verify transfer if needed
        if verify and test_type == 'file':
            if not verify_transfer(test_file, received_file):
                return False
        
        return True
    
    except KeyboardInterrupt:
        logger.info("Test interrupted by user")
        return False
    
    finally:
        # Terminate server
        if server_process:
            server_process.terminate()
            try:
                server_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                server_process.kill()

def main():
    """Main function to run tests"""
    parser = argparse.ArgumentParser(description='Test reliable UDP protocol')
    parser.add_argument('--test-type', choices=['file', 'synthetic'], default='synthetic',
                      help='Type of test to run (file or synthetic data)')
    parser.add_argument('--loss-rate', type=float, default=0.05,
                      help='Packet loss rate (0.0-1.0)')
    parser.add_argument('--data-size', type=int, default=10 * 1024 * 1024,
                      help='Data size in bytes (default 10MB)')
    
    args = parser.parse_args()
    
    if args.test_type == 'file' and args.data_size < 1024:
        logger.warning("File size is very small, increasing to 1KB")
        args.data_size = 1024
    
    # Make sure we have enough packets to test properly
    min_packets = 10000
    packet_data_size = 1024 - 12  # MAX_PAYLOAD_SIZE
    min_data_size = min_packets * packet_data_size
    
    if args.data_size < min_data_size:
        logger.warning(f"Data size too small for proper testing, increasing to {min_data_size} bytes")
        args.data_size = min_data_size
    
    logger.info(f"Running {args.test_type} test with {args.loss_rate:.1%} packet loss rate and {args.data_size} bytes")
    success = run_test(args.test_type, args.loss_rate, args.data_size)
    
    if success:
        logger.info("Test completed successfully")
        return 0
    else:
        logger.error("Test failed")
        return 1

if __name__ == "__main__":
    sys.exit(main())