"""
server.py - Implementação do Receptor/Servidor do protocolo UDP confiável
"""

import socket
import time
import logging
import os
import sys
import random
from collections import defaultdict, deque
from protocol import ReliableUDP, Packet, PacketType, MAX_PAYLOAD_SIZE


logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger('ReliableUDP-Server')

class ReliableUDPServer(ReliableUDP):
    """Implementação do Servidor do Protocolo UDP Confiável"""
    
    def __init__(self, listen_ip, listen_port, output_dir=None, packet_loss_rate=0.0):
        """Inicializa o servidor para escutar no endereço especificado"""
        # Cria socket UDP
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind((listen_ip, listen_port))
        
        
        self.remote_addr = None
        super().__init__(self.sock, self.remote_addr)
        
        # Buffer de recebimento para ordenar pacotes
        self.receive_buffer = {}  # seq_num -> pacote
        self.packet_loss_rate = packet_loss_rate
        self.output_dir = output_dir or os.getcwd()
        
        # Controle de Fluxo
        self.max_window_size = 64  # Tamanho máximo da janela do receptor
        self.window_size = self.max_window_size
        self.buffer_capacity = self.max_window_size * MAX_PAYLOAD_SIZE  # Capacidade do buffer em bytes
        self.client_window = 0  # Tamanho da janela informada pelo cliente
        
        # Bytes sendo processados
        self.processing_bytes = 0
        
        # Estatísticas
        self.received_packets = 0
        self.dropped_packets = 0
        self.out_of_order_packets = 0
        self.total_bytes = 0
    
    def wait_for_connection(self):
        """Aguarda um cliente se conectar"""
        logger.info("Aguardando conexão do cliente em %s", self.sock.getsockname())

        while True:
            # Espera pelo pacote SYN
            packet, addr = self.receive_packet()
            if not packet:
                continue
            
            if packet.flags == PacketType.SYN:
                # Salva o endereço do cliente
                self.remote_addr = addr
                logger.info("Cliente conectando de %s", addr)
                
                # Atualiza o número de sequência esperado
                self.expected_seq_num = packet.seq_num + 1
                logger.info("Número de sequência esperado após SYN: %d", self.expected_seq_num)
                
                # Salva o tamanho da janela do cliente, se disponível
                if hasattr(packet, 'window'):
                    self.client_window = packet.window
                    logger.info("Tamanho da janela anunciado pelo cliente: %d", self.client_window)
                
                # Atualiza o tamanho da janela antes de enviar o SYN-ACK
                self._update_window_size()
                
                # Envia SYN-ACK com o tamanho da nossa janela
                self.send_packet(PacketType.SYN, ack_num=self.expected_seq_num, window=self.window_size)
                
                # Aguarda o ACK para completar o three-way handshake
                ack_packet, _ = self.receive_packet(timeout=5.0)
                if not ack_packet or ack_packet.flags != PacketType.ACK:
                    logger.warning("Nenhum ACK recebido, redefinindo estado da conexão")
                    self.remote_addr = None
                    continue
                
                # Atualiza o tamanho da janela do cliente se fornecido no ACK
                if hasattr(ack_packet, 'window'):
                    self.client_window = ack_packet.window
                    logger.info("Tamanho da janela anunciado pelo cliente no ACK: %d", self.client_window)
                
                logger.info("Conexão estabelecida com %s", addr)
                return True
            
            else:
                logger.warning("Pacote não-SYN recebido durante a configuração da conexão, ignorando")
    
    def _update_window_size(self):
        """Atualiza o tamanho da janela do receptor com base no uso do buffer"""
        # Calcula os bytes no buffer (não processados)
        buffer_usage = sum(len(p.payload) for p in self.receive_buffer.values())
        
        # Adiciona os bytes sendo processados
        total_buffer_usage = buffer_usage + self.processing_bytes
        
        # Calcula o espaço disponível
        available_space = max(0, self.buffer_capacity - total_buffer_usage)
        
        # Converte para slots de pacotes
        self.window_size = max(1, available_space // MAX_PAYLOAD_SIZE)
        
        logger.debug("Tamanho da janela do servidor: %d (uso do buffer: %d/%d)", 
                     self.window_size, total_buffer_usage, self.buffer_capacity)
    
    def receive_data(self, output_file=None):
        """Recebe dados de um cliente"""
        # Inicializa o arquivo de saída, se fornecido
        file_obj = None
        if output_file:
            file_path = os.path.join(self.output_dir, output_file)
            file_obj = open(file_path, 'wb')
            logger.info("Escrevendo dados recebidos em %s", file_path)
        
        try:
            data_buffer = bytearray()
            last_delivered_seq = self.expected_seq_num - 1
            
            # Começa a receber os dados
            start_time = time.time()
            connection_active = True
            
            while connection_active:
                # Atualiza o tamanho da janela antes de potencialmente receber um pacote
                self._update_window_size()
                
                packet, addr = self.receive_packet(timeout=30.0)
                
                if not packet:
                    logger.info("Nenhum pacote recebido dentro do timeout, assumindo que a conexão foi fechada")
                    break
                
                # Verifica se é do nosso cliente conectado
                if addr != self.remote_addr:
                    continue
                
                # Atualiza o tamanho da janela do cliente se disponível no pacote
                if hasattr(packet, 'window'):
                    self.client_window = packet.window
                    logger.debug("Tamanho da janela do cliente atualizado: %d", self.client_window)
                
                # Manipula o pacote com base no tipo
                if packet.flags == PacketType.DATA:
                    connection_active = self._handle_data_packet(packet, file_obj, data_buffer, last_delivered_seq)
                    
                elif packet.flags == PacketType.FIN:
                    logger.info("Pacote FIN recebido, conexão sendo fechada")
                    # Envia FIN com o tamanho da nossa janela atual
                    self._update_window_size()
                    self.send_packet(PacketType.FIN, ack_num=packet.seq_num + 1, window=self.window_size)
                    connection_active = False
            
            # Calcula estatísticas
            duration = time.time() - start_time
            if duration > 0:
                throughput = self.total_bytes / duration / 1024  # KB/s
                logger.info("Transferência concluída em %.2f segundos", duration)
                logger.info("Taxa de transferência: %.2f KB/s", throughput)
                logger.info("Total de pacotes recebidos: %d", self.received_packets)
                logger.info("Pacotes perdidos (simulação de perda): %d", self.dropped_packets)
                logger.info("Pacotes fora de ordem: %d", self.out_of_order_packets)
            
            # Retorna os dados recebidos se nenhum arquivo foi especificado
            if not file_obj:
                return bytes(data_buffer)
            return True
            
        except Exception as e:
            logger.error("Erro ao receber dados: %s", e)
            return False
        finally:
            if file_obj:
                file_obj.close()
    
    def _handle_data_packet(self, packet, file_obj, data_buffer, last_delivered_seq):
        """Processa um pacote de dados recebido"""
        logger.debug("Pacote recebido: seq=%d, esperado=%d", packet.seq_num, self.expected_seq_num)

        # Simula perda de pacote
        if random.random() < self.packet_loss_rate:
            self.dropped_packets += 1
            logger.debug("Simulando perda de pacote para seq=%d", packet.seq_num)
            # Ainda envia ACK para o último pacote recebido corretamente para acionar retransmissão rápida
            self._update_window_size()
            self.send_packet(PacketType.ACK, ack_num=self.expected_seq_num, window=self.window_size)
            return True
        
        self.received_packets += 1
        
        # Verifica se este é o pacote esperado
        if packet.seq_num == self.expected_seq_num:
            # Marca os bytes como "processando" antes de escrever no arquivo/buffer
            payload_size = len(packet.payload)
            self.processing_bytes += payload_size
            
            # Processa este pacote
            if file_obj:
                file_obj.write(packet.payload)
                file_obj.flush()  # Garante que os dados sejam escritos no disco
            else:
                data_buffer.extend(packet.payload)
            
            # Após o processamento, os bytes não estão mais "processando"
            self.processing_bytes -= payload_size
            
            self.total_bytes += payload_size
            last_delivered_seq = packet.seq_num
            self.expected_seq_num += payload_size
            
            # Verifica se temos pacotes em buffer que podem ser processados agora
            # Primeiro ordena as chaves para processar em ordem
            ordered_keys = sorted([k for k in self.receive_buffer.keys() if k == self.expected_seq_num])
            
            for seq in ordered_keys:
                buffered_packet = self.receive_buffer.pop(seq)
                payload_size = len(buffered_packet.payload)
                
                # Marca como processando
                self.processing_bytes += payload_size
                
                if file_obj:
                    file_obj.write(buffered_packet.payload)
                    file_obj.flush()  # Garante que os dados sejam escritos no disco
                else:
                    data_buffer.extend(buffered_packet.payload)
                
                # Processamento concluído
                self.processing_bytes -= payload_size
                
                self.total_bytes += payload_size
                last_delivered_seq = buffered_packet.seq_num
                self.expected_seq_num += payload_size
        
        elif packet.seq_num > self.expected_seq_num:
            # Pacote fora de ordem - armazena no buffer
            self.out_of_order_packets += 1
            self.receive_buffer[packet.seq_num] = packet
            logger.debug("Pacote fora de ordem: esperado=%d, recebido=%d", 
                         self.expected_seq_num, packet.seq_num)
        
        # Ajusta o tamanho da janela após processar o pacote
        self._update_window_size()
        
        # Envia ACK cumulativo com o tamanho atual da janela
        self.send_packet(PacketType.ACK, ack_num=self.expected_seq_num, window=self.window_size)
        
        return True


def main():
    """Função principal para executar o servidor"""
    if len(sys.argv) < 3:
        print(f"Uso: {sys.argv[0]} <listen_port> <output_file> [packet_loss_rate]")
        sys.exit(1)
    
    listen_port = int(sys.argv[1])
    output_file = sys.argv[2]
    
    # Taxa de perda de pacote opcional
    packet_loss_rate = 0.1
    if len(sys.argv) > 3:
        packet_loss_rate = float(sys.argv[3])
        logger.info("Simulando taxa de perda de pacote de %.1f%%", packet_loss_rate * 100)
    
    server = ReliableUDPServer('0.0.0.0', listen_port, packet_loss_rate=packet_loss_rate)
    
    while True:
        if server.wait_for_connection():
            server.receive_data(output_file)
            logger.info("Pronto para novas conexões")


if __name__ == "__main__":
    main()