"""
protocol.py - Implementação do núcleo do protocolo de transporte confiável sobre UDP
"""

import time
import random
from enum import Enum
from collections import deque
import struct

# Constantes do protocolo
MAX_PACKET_SIZE = 1024  # Tamanho máximo do pacote em bytes
HEADER_SIZE = 14  # Tamanho do cabeçalho em bytes (seq, ack, flags, window)
MAX_PAYLOAD_SIZE = MAX_PACKET_SIZE - HEADER_SIZE
DEFAULT_TIMEOUT = 1.0  # Timeout em segundos
MAX_RETRIES = 10  # Número máximo de tentativas de retransmissão
INITIAL_WINDOW_SIZE = 4  # Tamanho inicial da janela (pacotes) - aumentado de 1
INITIAL_SSTHRESH = 64  # Limiar inicial de slow start
MAX_WINDOW_SIZE = 128  # Tamanho máximo da janela

class PacketType(Enum):
    DATA = 0
    ACK = 1
    SYN = 2
    FIN = 3

class Packet:
    """Representa um pacote no nosso protocolo confiável"""
    
    def __init__(self, seq_num=0, ack_num=0, flags=PacketType.DATA, window=0, payload=b''):
        self.seq_num = seq_num
        self.ack_num = ack_num
        self.flags = flags
        self.window = window
        self.payload = payload
        self.timestamp = time.time()
    
    def to_bytes(self):
        """Converte o pacote em bytes para transmissão"""
        header = struct.pack('!IIIH', 
                            self.seq_num, 
                            self.ack_num, 
                            self.flags.value,
                            self.window)
        return header + self.payload
    
    @staticmethod
    def from_bytes(data):
        """Converte bytes recebidos em um objeto Packet"""
        if len(data) < HEADER_SIZE:
            return None
        
        header = data[:HEADER_SIZE]
        payload = data[HEADER_SIZE:]
        
        seq_num, ack_num, flags_value, window = struct.unpack('!IIIH', header)
        
        # Converte flags_value para o enum PacketType apropriado
        flags = PacketType(flags_value)
        
        return Packet(seq_num, ack_num, flags, window, payload)
    
    def __str__(self):
        return f"Packet(seq={self.seq_num}, ack={self.ack_num}, flags={self.flags.name}, window={self.window}, payload_size={len(self.payload)})"


class CongestionControl:
    """Implementa controle de congestionamento semelhante ao TCP"""
    
    def __init__(self):
        self.cwnd = INITIAL_WINDOW_SIZE  # Tamanho da janela de congestionamento
        self.ssthresh = INITIAL_SSTHRESH  # Limiar de slow start
        self.duplicate_acks = 0  # Contagem de ACKs duplicados
        self.last_ack = 0  # Último ACK recebido
        self.in_fast_recovery = False  # Indica se estamos no modo de recuperação rápida
    
    def on_ack_received(self, ack_num):
        """Atualiza a janela de congestionamento com base no ACK recebido"""
        if ack_num > self.last_ack:
            # Novo ACK
            self.duplicate_acks = 0
            self.in_fast_recovery = False
            
            # Aumenta a janela com base na fase atual
            if self.cwnd < self.ssthresh:
                # Fase de slow start - crescimento exponencial
                self.cwnd += 1
            else:
                # Fase de congestion avoidance - aumento aditivo
                self.cwnd += 1 / self.cwnd
            
            self.last_ack = ack_num
        else:
            # ACK duplicado
            self.duplicate_acks += 1
            
            # Retransmissão rápida / Recuperação rápida
            if self.duplicate_acks == 3 and not self.in_fast_recovery:
                # Entra em recuperação rápida
                self.ssthresh = max(self.cwnd / 2, 2)
                self.cwnd = self.ssthresh + 3
                self.in_fast_recovery = True
            elif self.in_fast_recovery:
                # Aumenta cwnd durante a recuperação rápida
                self.cwnd += 1
    
    def on_timeout(self):
        """Lida com timeout - congestionamento severo"""
        self.ssthresh = max(self.cwnd / 2, 2)
        self.cwnd = INITIAL_WINDOW_SIZE
        self.duplicate_acks = 0
        self.in_fast_recovery = False
    
    def get_window_size(self, receiver_window):
        """Retorna o tamanho efetivo da janela (mínimo entre cwnd e a janela do receptor)"""
        return min(int(self.cwnd), receiver_window, MAX_WINDOW_SIZE)


class ReliableUDP:
    """Classe base para a implementação do protocolo UDP confiável"""
    
    def __init__(self, sock, remote_addr):
        self.sock = sock
        self.remote_addr = remote_addr
        self.buffer_size = MAX_PACKET_SIZE
        self.sequence_number = random.randint(0, 100000)  # Número de sequência inicial
        self.expected_seq_num = 0  # Próximo número de sequência esperado
        self.last_ack_sent = 0  # Último acknowledgment enviado
        self.window_size = INITIAL_WINDOW_SIZE  # Janela inicial de controle de fluxo
        self.congestion = CongestionControl()  # Controle de congestionamento
        self.rtt_estimator = RTTEstimator()  # Para timeout adaptativo
    
    def send_packet(self, packet_type, payload=b'', ack_num=0, window=0):
        """Cria e envia um pacote"""
        packet = Packet(
            seq_num=self.sequence_number,
            ack_num=ack_num,
            flags=packet_type,
            window=window,
            payload=payload
        )
        
        data = packet.to_bytes()
        self.sock.sendto(data, self.remote_addr)
        
        if packet_type == PacketType.DATA:
            self.sequence_number += len(payload)
        
        return packet
    
    def receive_packet(self, timeout=None):
        """Recebe um pacote com timeout"""
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
            self.sock.settimeout(None)  # Reseta o timeout


class RTTEstimator:
    """Estima o tempo de ida e volta (RTT) usando média móvel ponderada exponencial"""
    
    def __init__(self):
        self.srtt = 0  # RTT suavizado
        self.rttvar = 0.75  # Variação do RTT
        self.alpha = 0.125  # Peso para cálculo do SRTT
        self.beta = 0.25  # Peso para cálculo do RTTVAR
        self.rto = DEFAULT_TIMEOUT  # Timeout de retransmissão
        self.measurements = 0  # Número de medições realizadas
    
    def update(self, rtt):
        """Atualiza a estimativa de RTT com base em uma nova medição"""
        if self.measurements == 0:
            # Primeira medição
            self.srtt = rtt
            self.rttvar = rtt / 2
        else:
            # Atualiza as estimativas
            self.rttvar = (1 - self.beta) * self.rttvar + self.beta * abs(self.srtt - rtt)
            self.srtt = (1 - self.alpha) * self.srtt + self.alpha * rtt
        
        # Atualiza o RTO com um valor mínimo
        self.rto = self.srtt + max(0.01, 4 * self.rttvar)
        self.measurements += 1
        
        # Limita o RTO entre valores razoáveis
        self.rto = max(0.1, min(self.rto, 10.0))
        
        return self.rto
    
    def get_timeout(self):
        """Retorna o valor atual do timeout"""
        return self.rto if self.measurements > 0 else DEFAULT_TIMEOUT