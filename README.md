Running the Code
Your implementation consists of three main components:
    protocol.py - Core protocol implementation
    client.py - Sender implementation
    server.py - Receiver implementation
    test.py - Test script to evaluate the protocol

TEST
The easiest way to test is using the test.py script, which automates the process of:
    Creating test data
    Starting a server
    Starting a client to send data to the server
    Verifying the transfer

How to Run the Test
Open a terminal and run: `python test.py`
By default, this will:
    Run a test with synthetic data (10MB)
    Simulate a 5% packet loss rate
    Create and verify the transfer
You can customize the test with these options: `python test.py --test-type file --loss-rate 0.1 --data-size 20971520`
This would:
    Use an actual file instead of synthetic data
    Set packet loss rate to 10%
    Use a 20MB file size

MANUAL
Start the server: `python server.py 5000 received_file.dat 0.05`
This starts a server on port 5000, saving received data to received_file.dat with 5% packet loss.
Start the client in another terminal: `python client.py 127.0.0.1 5000 test_file.dat`
Or to send synthetic data: `python client.py 127.0.0.1 5000 --synthetic 4096`