"""
client.py - Implementação do Remetente/Cliente do protocolo UDP confiável
"""

import socket
import time
import logging
import os
import sys
from collections import deque
import math
import matplotlib.pyplot as plt 
from protocol import ReliableUDP, Packet, PacketType, MAX_PAYLOAD_SIZE, INITIAL_WINDOW_SIZE

# Configuração do logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger('ReliableUDP-Client')

class ReliableUDPClient(ReliableUDP):
    """Implementação do Cliente do Protocolo UDP Confiável"""
    
    def __init__(self, server_ip, server_port):
        """Inicializa o cliente com o endereço do servidor"""
        # Cria socket UDP
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(('0.0.0.0', 0))
        server_addr = (server_ip, server_port)
        
        super().__init__(self.sock, server_addr)
        
         # Adicione estas listas
        self.time_history = []
        self.throughput_history = []
        self.cwnd_history = []
        self.rtt_history = []
        self.rto_history = []
        self.packets_in_flight_history = []
        
        # Buffer de envio para armazenar pacotes aguardando ACK
        self.send_buffer = {}  # seq_num -> (packet, retries)
        self.next_seq_to_send = self.sequence_number  # Próximo número de sequência a enviar
        self.base = self.sequence_number  # Base da janela (pacote mais antigo não confirmado)
        self.receiver_window = INITIAL_WINDOW_SIZE  # Controle de fluxo - tamanho da janela do receptor
        self.initial_sequence = self.sequence_number
        
        # Tamanho da janela anunciada pelo cliente (fixo em um valor razoável)
        self.window_size = 64  # Usa um tamanho fixo razoável para a janela
        
        # Tamanho do buffer da aplicação (apenas para fins de rastreamento)
        self.application_buffer_size = 1024 * 1024  # Buffer de aplicação de 1MB
        self.application_buffer_used = 0
        
        # Estatísticas para logging
        self.retransmissions = 0
        self.total_packets_sent = 0
        self.start_time = None
        self.last_log_time = 0
        self.log_interval = 2.0  # Log a cada 2 segundos
    
    def establish_connection(self):
        """Estabelece a conexão com o three-way handshake"""
        logger.info("Iniciando conexão com %s", self.remote_addr)
        
        # Envia SYN com o tamanho inicial da janela
        syn_packet = self.send_packet(PacketType.SYN, payload=b'', window=self.window_size)
        
        # Aguarda SYN-ACK
        syn_ack, _ = self.receive_packet(timeout=5.0)
        if not syn_ack or syn_ack.flags != PacketType.SYN:
            raise ConnectionError("Falha ao estabelecer conexão: Nenhum SYN-ACK recebido")
        
        # Atualiza o número de sequência esperado
        self.expected_seq_num = syn_ack.seq_num + 1
        
        # Salva o tamanho inicial da janela do receptor
        self.receiver_window = syn_ack.window
        logger.info("Tamanho inicial da janela recebido do servidor: %d", self.receiver_window)
        
        # Envia ACK com o tamanho da nossa janela
        self.send_packet(PacketType.ACK, ack_num=self.expected_seq_num, payload=b'', window=self.window_size)
        
        # Incrementa o número de sequência para o pacote SYN
        self.sequence_number += 1
        
        # Define a sequência inicial para rastrear bytes enviados
        self.initial_sequence = self.sequence_number
        
        # Atualiza base e next_seq_to_send
        self.next_seq_to_send = self.sequence_number
        self.base = self.sequence_number
        
        logger.info("Conexão estabelecida com %s", self.remote_addr)
        logger.info("Número de sequência após handshake: %d", self.sequence_number)
        
        # Inicializa estatísticas
        self.start_time = time.time()
        self.last_log_time = self.start_time
        
        return True
    
    def close_connection(self):
        """Fecha a conexão com pacotes FIN"""
        logger.info("Iniciando fechamento da conexão")
        
        # Log das estatísticas finais
        self._log_connection_stats(final=True)
        
        # Envia FIN com o tamanho atual da janela
        fin_packet = self.send_packet(PacketType.FIN, window=self.window_size)
        
        # Aguarda FIN-ACK
        fin_ack, _ = self.receive_packet(timeout=5.0)
        if not fin_ack or fin_ack.flags != PacketType.FIN:
            logger.warning("Nenhum FIN-ACK recebido, fechando mesmo assim")
        
        # Fecha o socket
        self.sock.close()
        logger.info("Conexão fechada")
    
    def generate_graphs(self):
    
        # Gráfico de Throughput
        plt.figure(figsize=(12, 6))
        plt.plot(self.time_history, self.throughput_history, label='Throughput (KB/s)')
        plt.title("Throughput ao Longo do Tempo")
        plt.xlabel("Tempo (s)")
        plt.ylabel("KB/s")
        plt.grid(True)
        plt.legend()
        plt.savefig("throughput.png")
        
        # Gráfico de Janela de Congestionamento
        plt.figure(figsize=(12, 6))
        plt.plot(self.time_history, self.cwnd_history, label='Janela de Congestionamento (cwnd)')
        plt.title("Janela de Congestionamento")
        plt.xlabel("Tempo (s)")
        plt.ylabel("Tamanho da Janela")
        plt.grid(True)
        plt.legend()
        plt.savefig("cwnd.png")
        
        # Gráfico de RTT e RTO
        plt.figure(figsize=(12, 6))
        plt.plot(self.time_history, self.rtt_history, label='RTT (s)')
        plt.plot(self.time_history, self.rto_history, label='RTO (s)')
        plt.title("RTT e RTO ao Longo do Tempo")
        plt.xlabel("Tempo (s)")
        plt.ylabel("Tempo (s)")
        plt.grid(True)
        plt.legend()
        plt.savefig("rtt_rto.png")
    
    def send_file(self, file_path):
        """Envia um arquivo usando o protocolo confiável"""
        if not self.establish_connection():
            return False
        
        try:
            logger.info("Número de sequência antes do primeiro dado: %d", self.sequence_number)

            file_size = os.path.getsize(file_path)
            num_packets = math.ceil(file_size / MAX_PAYLOAD_SIZE)
            
            logger.info("Enviando arquivo: %s", file_path)
            logger.info("Tamanho do arquivo: %d bytes, Pacotes estimados: %d", file_size, num_packets)
            
            with open(file_path, 'rb') as file:
                bytes_sent = 0
                start_time = time.time()
                self.start_time = start_time
                
                # Começa a enviar dados
                while bytes_sent < file_size:
                    self._send_available_data(file)
                    self._handle_acknowledgments()
                    
                    # Atualiza o progresso
                    bytes_sent = self.sequence_number - self.initial_sequence
                    progress = (bytes_sent / file_size) * 100
                    
                    # Log periódico de estatísticas detalhadas
                    self._log_periodic_stats(bytes_sent, file_size)
                
                # Aguarda todos os pacotes serem confirmados
                while self.base < self.next_seq_to_send:
                    self._handle_acknowledgments()
                    # Log da janela final enquanto aguarda ACKs
                    self._log_periodic_stats(bytes_sent, file_size, force=True)
                
                duration = time.time() - start_time
                throughput = file_size / duration / 1024  # KB/s
                
                logger.info("Arquivo enviado com sucesso em %.2f segundos", duration)
                logger.info("Throughput: %.2f KB/s", throughput)
                
                self.generate_graphs()
                return True
                
        except Exception as e:
            logger.error("Erro ao enviar arquivo: %s", e)
            return False
        finally:
            self.close_connection()
    
    def send_synthetic_data(self, total_bytes):
        """Envia dados sintéticos usando o protocolo confiável"""
        if not self.establish_connection():
            return False
        
        try:
            logger.info("Número de sequência antes do primeiro dado: %d", self.sequence_number)

            num_packets = math.ceil(total_bytes / MAX_PAYLOAD_SIZE)
            
            logger.info("Enviando dados sintéticos: %d bytes", total_bytes)
            logger.info("Pacotes estimados: %d", num_packets)
            
            bytes_sent = 0
            start_time = time.time()
            self.start_time = start_time
            
            # Gera um padrão de dados (apenas um padrão simples para testes)
            data_pattern = b''.join([bytes([i % 256]) for i in range(min(MAX_PAYLOAD_SIZE, total_bytes))])
            
            # Começa a enviar dados
            while bytes_sent < total_bytes:
                remaining = total_bytes - bytes_sent
                chunk_size = min(MAX_PAYLOAD_SIZE, remaining)
                
                # Usa o data_pattern completo ou um chunk do tamanho certo
                if chunk_size < len(data_pattern):
                    chunk = data_pattern[:chunk_size]
                else:
                    chunk = data_pattern
                
                self._send_data_chunk(chunk)
                self._handle_acknowledgments()
                
                # Atualiza o progresso
                bytes_sent = self.sequence_number - self.initial_sequence
                
                # Log periódico de estatísticas detalhadas
                self._log_periodic_stats(bytes_sent, total_bytes)
            
            # Aguarda todos os pacotes serem confirmados
            while self.base < self.next_seq_to_send:
                self._handle_acknowledgments()
                # Log da janela final enquanto aguarda ACKs
                self._log_periodic_stats(bytes_sent, total_bytes, force=True)
            
            duration = time.time() - start_time
            throughput = total_bytes / duration / 1024  # KB/s
            
            logger.info("Dados enviados com sucesso em %.2f segundos", duration)
            logger.info("Throughput: %.2f KB/s", throughput)
            
            return True
                
        except Exception as e:
            logger.error("Erro ao enviar dados: %s", e)
            return False
        finally:
            self.close_connection()
    
    def _log_periodic_stats(self, bytes_sent, total_bytes, force=False):
        """Log de estatísticas detalhadas periodicamente"""
        current_time = time.time()
        
        if force or (current_time - self.last_log_time >= self.log_interval):
            progress = (bytes_sent / total_bytes) * 100 if total_bytes > 0 else 0
            
            # Calcula a janela efetiva atual
            packets_in_flight = (self.next_seq_to_send - self.base) // MAX_PAYLOAD_SIZE
            effective_window = self.congestion.get_window_size(self.receiver_window)
            
            # Calcula o throughput instantâneo
            elapsed = current_time - self.start_time
            throughput = bytes_sent / elapsed / 1024 if elapsed > 0 else 0
            
            self.time_history.append(elapsed)
            self.throughput_history.append(bytes_sent / elapsed / 1024 if elapsed > 0 else 0)
            self.cwnd_history.append(self.congestion.cwnd)
            self.rtt_history.append(self.rtt_estimator.srtt)
            self.rto_history.append(self.rtt_estimator.rto)
            self.packets_in_flight_history.append(
            (self.next_seq_to_send - self.base) // MAX_PAYLOAD_SIZE)
            
            logger.info("Progresso: %.2f%% (%d/%d bytes)", progress, bytes_sent, total_bytes)
            logger.info("Estatísticas da Janela: cwnd=%.2f, rwnd=%d, efetiva=%d, in_flight=%d, ssthresh=%.2f", 
                       self.congestion.cwnd, self.receiver_window, effective_window, 
                       packets_in_flight, self.congestion.ssthresh)
            logger.info("Desempenho: %.2f KB/s, RTT=%.3fs, RTO=%.3fs, Retransmissões=%d", 
                       throughput, self.rtt_estimator.srtt, self.rtt_estimator.rto, self.retransmissions)
            
            # Log do estado de congestionamento
            if self.congestion.in_fast_recovery:
                state = "RECUPERAÇÃO RÁPIDA"
            elif self.congestion.cwnd < self.congestion.ssthresh:
                state = "SLOW START"
            else:
                state = "PREVENÇÃO DE CONGESTIONAMENTO"
            logger.info("Estado de congestionamento: %s", state)
            
            self.last_log_time = current_time
    
    def _log_connection_stats(self, final=False):
        """Log das estatísticas gerais da conexão"""
        if not final:
            return
            
        # Apenas log no fechamento da conexão
        packets_sent = self.total_packets_sent
        retransmission_rate = (self.retransmissions / packets_sent * 100) if packets_sent > 0 else 0
        
        logger.info("Estatísticas da Conexão:")
        logger.info("  Total de pacotes enviados: %d", packets_sent)
        logger.info("  Retransmissões: %d (%.2f%%)", self.retransmissions, retransmission_rate)
        logger.info("  Janela de congestionamento final: %.2f pacotes", self.congestion.cwnd)
        logger.info("  Limiar de slow start final: %.2f pacotes", self.congestion.ssthresh)
        logger.info("  Estimativa final de RTT: %.3f segundos", self.rtt_estimator.srtt)
    
    def _update_client_window_size(self):
        """Atualiza o tamanho da janela anunciada pelo cliente (simplificado)"""
        # Mantém o tamanho da janela fixo em um valor razoável
        # Isso é separado da janela de controle de congestionamento
        self.application_buffer_used = sum(len(packet.payload) for packet, _ in self.send_buffer.values())
        
        # Apenas para depuração
        logger.debug("Uso atual do buffer da aplicação: %d bytes", self.application_buffer_used)
    
    def _send_available_data(self, file):
        """Envia chunks de dados do arquivo que cabem na janela"""
        # Calcula o tamanho efetivo da janela (baseado no controle de congestionamento)
        effective_window = self.congestion.get_window_size(self.receiver_window)
        
        # Calcula quantos pacotes podem ser enviados na janela atual
        packets_in_flight = (self.next_seq_to_send - self.base) // MAX_PAYLOAD_SIZE
        available_slots = max(0, effective_window - packets_in_flight)
        
        logger.debug("Informações da janela: efetiva=%d, in_flight=%d, disponíveis=%d, receptor=%d", 
                     effective_window, packets_in_flight, available_slots, self.receiver_window)
        
        for _ in range(available_slots):
            # Lê o próximo chunk de dados
            chunk = file.read(MAX_PAYLOAD_SIZE)
            if not chunk:  # Fim do arquivo
                break
            
            self._send_data_chunk(chunk)
    
    def _send_data_chunk(self, chunk):
        """Envia um único chunk de dados e o armazena para possível retransmissão"""
        curr_seq = self.sequence_number  # Salva o número de sequência atual
        
        logger.debug("Enviando pacote DATA: seq=%d, tamanho=%d bytes", curr_seq, len(chunk))
        
        # Cria e envia o pacote com o tamanho atual da janela
        packet = self.send_packet(PacketType.DATA, payload=chunk, 
                                ack_num=self.expected_seq_num, 
                                window=self.window_size)
        
        # Armazena no buffer de envio para retransmissão, se necessário
        self.send_buffer[curr_seq] = (packet, 0)
        self.total_packets_sent += 1
        
        # Atualiza o próximo número de sequência a enviar
        self.next_seq_to_send = self.sequence_number
        
        # Inicia o timer para este pacote se for o primeiro pacote na janela
        if self.base == curr_seq:
            self.set_timer()
    
    def _handle_acknowledgments(self):
        """Lida com ACKs recebidos, timeouts e retransmissões"""
        timeout = self.rtt_estimator.get_timeout()
        packet, _ = self.receive_packet(timeout=timeout)
        
        if packet:
            if packet.flags == PacketType.ACK:
                self._process_ack(packet)
            
            # Atualiza o número de sequência esperado para pacotes de dados
            if packet.flags == PacketType.DATA and packet.seq_num == self.expected_seq_num:
                self.expected_seq_num += len(packet.payload)
                self.last_ack_sent = self.expected_seq_num
                
                # Envia ACK cumulativo com o tamanho da nossa janela
                self.send_packet(PacketType.ACK, ack_num=self.expected_seq_num, window=self.window_size)
            
            # Atualiza o tamanho da janela do receptor para controle de fluxo
            if hasattr(packet, 'window'):
                old_window = self.receiver_window
                self.receiver_window = packet.window
                if old_window != self.receiver_window:
                    logger.debug("Atualização da janela recebida do servidor: %d -> %d", old_window, self.receiver_window)
            
        else:
            # Ocorreu timeout
            self._handle_timeout()
    
    def _process_ack(self, ack_packet):
        """Processa um pacote ACK"""
        # Atualiza o controle de fluxo - salva o tamanho da janela anunciada pelo receptor
        if hasattr(ack_packet, 'window'):
            old_window = self.receiver_window
            self.receiver_window = ack_packet.window
            if old_window != self.receiver_window:
                logger.debug("Atualização da janela do receptor: %d -> %d", old_window, self.receiver_window)
        
        old_cwnd = self.congestion.cwnd
        old_ssthresh = self.congestion.ssthresh
        
        # Atualiza o controle de congestionamento
        self.congestion.on_ack_received(ack_packet.ack_num)
        
        # Log se a janela de congestionamento mudou significativamente
        if abs(old_cwnd - self.congestion.cwnd) > 1 or old_ssthresh != self.congestion.ssthresh:
            logger.debug("Atualização da janela de congestionamento: %.2f -> %.2f (ssthresh=%.2f)", 
                        old_cwnd, self.congestion.cwnd, self.congestion.ssthresh)
        
        # ACK cumulativo - todos os pacotes até ack_num são confirmados
        if ack_packet.ack_num > self.base:
            # Conta os pacotes confirmados
            acked_bytes = ack_packet.ack_num - self.base
            acked_packets = math.ceil(acked_bytes / MAX_PAYLOAD_SIZE)
            logger.debug("ACK recebido: %d, confirmando %d bytes (%d pacotes)", 
                        ack_packet.ack_num, acked_bytes, acked_packets)
            
            # Remove os pacotes confirmados do buffer de envio
            keys_to_remove = [seq for seq in self.send_buffer if seq < ack_packet.ack_num]
            for seq in keys_to_remove:
                # Atualiza o estimador de RTT se este for o pacote mais antigo
                if seq == self.base:
                    packet, _ = self.send_buffer[seq]
                    rtt = time.time() - packet.timestamp
                    old_rto = self.rtt_estimator.rto
                    new_rto = self.rtt_estimator.update(rtt)
                    
                    if abs(old_rto - new_rto) > 0.1:  # Apenas log de mudanças significativas
                        logger.debug("Atualização do RTT: medido=%.3fs, srtt=%.3fs, rto=%.3fs", 
                                    rtt, self.rtt_estimator.srtt, new_rto)
                
                del self.send_buffer[seq]
            
            # Atualiza a base
            self.base = ack_packet.ack_num
            
            # Se todos os pacotes forem confirmados, para o timer
            if self.base == self.next_seq_to_send:
                self.stop_timer()
                logger.debug("Todos os pacotes confirmados, janela limpa")
            else:
                # Reinicia o timer para o próximo pacote não confirmado
                self.set_timer()
                # Log dos pacotes ainda em trânsito
                packets_in_flight = (self.next_seq_to_send - self.base) // MAX_PAYLOAD_SIZE
                logger.debug("Pacotes ainda em trânsito: %d", packets_in_flight)
    
    def _handle_timeout(self):
        """Lida com timeouts e realiza retransmissões"""
        # Atualiza o controle de congestionamento no timeout
        old_cwnd = self.congestion.cwnd
        old_ssthresh = self.congestion.ssthresh
        
        self.congestion.on_timeout()
        
        logger.warning("Timeout detectado. Janela de congestionamento: %.2f -> %.2f, ssthresh: %.2f -> %.2f", 
                      old_cwnd, self.congestion.cwnd, old_ssthresh, self.congestion.ssthresh)
        
        # Encontra o pacote mais antigo não confirmado
        if self.base in self.send_buffer:
            packet, retries = self.send_buffer[self.base]
            
            # Se o número máximo de retransmissões for atingido, considera a conexão quebrada
            if retries >= 10:
                logger.error("Número máximo de tentativas de retransmissão atingido. Conexão parece estar quebrada.")
                return
            
            # Cria um novo pacote com o tamanho atual da janela 
            # mas preserva o número de sequência original
            updated_packet = Packet(
                seq_num=packet.seq_num,
                ack_num=packet.ack_num,
                flags=packet.flags,
                window=self.window_size,  # Usa o tamanho atual da janela
                payload=packet.payload
            )
            
            # Retransmite o pacote com a janela atualizada
            self.sock.sendto(updated_packet.to_bytes(), self.remote_addr)
            self.retransmissions += 1
            logger.warning("Retransmitindo pacote: seq=%d, tamanho=%d bytes, tentativa=%d", 
                          packet.seq_num, len(packet.payload), retries+1)
            
            # Atualiza o pacote no buffer de envio com o novo
            self.send_buffer[self.base] = (updated_packet, retries + 1)
            
            # Reinicia o timer
            self.set_timer()
    
    def set_timer(self):
        """Define um timer para o pacote mais antigo não confirmado (não bloqueante)"""
        # Em uma implementação real, isso configuraria um callback de timer
        # Para simplificar, usaremos o timeout em receive_packet
        pass
    
    def stop_timer(self):
        """Para o timer de retransmissão"""
        # Em uma implementação real, isso cancelaria o timer
        pass


def main():
    """Função principal para executar o cliente"""
    try:
        if len(sys.argv) < 4:
            print(f"Uso: {sys.argv[0]} <server_ip> <server_port> <file_path>")
            print(f"   ou: {sys.argv[0]} <server_ip> <server_port> --synthetic <bytes>")
            sys.exit(1)
        
        server_ip = sys.argv[1]
        server_port = int(sys.argv[2])
        
        client = ReliableUDPClient(server_ip, server_port)
        
        if sys.argv[3] == "--synthetic":
            if len(sys.argv) < 5:
                print("Erro: Falta o número de bytes para dados sintéticos")
                sys.exit(1)
            
            bytes_to_send = int(sys.argv[4])
            client.send_synthetic_data(bytes_to_send)
        else:
            file_path = sys.argv[3]
            client.send_file(file_path)
    except KeyboardInterrupt:
        logger.info("Cliente interrompido pelo usuário. Fechando conexão.")
        client.close_connection()


if __name__ == "__main__":
    main()