"""
testes.py - Ambiente de testes para comparar o protocolo UDP confiável com o UDP padrão
"""

import socket
import time
import random
import matplotlib.pyplot as plt
from client import ReliableUDPClient
from protocol import MAX_PAYLOAD_SIZE

# Configurações do teste
SERVER_IP = '127.0.0.1'
SERVER_PORT = 12345
TEST_DURATION = 30  # Duração de cada teste em segundos
PACKET_LOSS_RATES = [0.0, 0.1, 0.2, 0.3]  # Taxas de perda de pacotes para teste
DATA_SIZE = 10 * 1024 * 1024  # 10 MB de dados para envio

def run_udp_test(packet_loss_rate=0.0):
    """Teste de envio de pacotes usando UDP padrão"""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(('0.0.0.0', 0))
    
    start_time = time.time()
    bytes_sent = 0
    throughput_history = []
    time_history = []
    
    while time.time() - start_time < TEST_DURATION:
        # Simula perda de pacotes
        if random.random() < packet_loss_rate:
            continue
        
        # Envia dados
        data = b'x' * MAX_PAYLOAD_SIZE
        sock.sendto(data, (SERVER_IP, SERVER_PORT))
        bytes_sent += len(data)
        
        # Registra a vazão
        elapsed = time.time() - start_time
        throughput_history.append(bytes_sent / elapsed / 1024)  # KB/s
        time_history.append(elapsed)
    
    sock.close()
    return time_history, throughput_history

def run_reliable_udp_test(packet_loss_rate=0.0):
    """Teste de envio de pacotes usando o protocolo UDP confiável"""
    client = ReliableUDPClient(SERVER_IP, SERVER_PORT)
    client.packet_loss_rate = packet_loss_rate
    
    start_time = time.time()
    bytes_sent = 0
    throughput_history = []
    time_history = []
    
    while time.time() - start_time < TEST_DURATION:
        # Envia dados
        data = b'x' * MAX_PAYLOAD_SIZE
        client._send_data_chunk(data)
        bytes_sent += len(data)
        
        # Registra a vazão
        elapsed = time.time() - start_time
        throughput_history.append(bytes_sent / elapsed / 1024)  # KB/s
        time_history.append(elapsed)
    
    client.close_connection()
    return time_history, throughput_history

def plot_comparison(udp_data, reliable_udp_data, title):
    """Gera gráficos comparando UDP padrão e UDP confiável"""
    plt.figure(figsize=(12, 6))
    plt.plot(udp_data[0], udp_data[1], label='UDP Padrão', linestyle='--')
    plt.plot(reliable_udp_data[0], reliable_udp_data[1], label='UDP Confiável', linestyle='-')
    plt.title(title)
    plt.xlabel("Tempo (s)")
    plt.ylabel("Vazão (KB/s)")
    plt.grid(True)
    plt.legend()
    plt.savefig(f"{title.replace(' ', '_')}.png")
    plt.show()

def test_no_packet_loss():
    """Teste sem perda de pacotes"""
    print("Executando teste sem perda de pacotes...")
    udp_data = run_udp_test(packet_loss_rate=0.0)
    reliable_udp_data = run_reliable_udp_test(packet_loss_rate=0.0)
    plot_comparison(udp_data, reliable_udp_data, "Vazão sem Perda de Pacotes")

def test_packet_loss_without_congestion_control():
    """Teste com perda de pacotes e sem controle de congestionamento"""
    print("Executando teste com perda de pacotes e sem controle de congestionamento...")
    udp_data = run_udp_test(packet_loss_rate=0.1)
    reliable_udp_data = run_reliable_udp_test(packet_loss_rate=0.1)
    plot_comparison(udp_data, reliable_udp_data, "Vazão com Perda de Pacotes (Sem Controle de Congestionamento)")

def test_packet_loss_with_congestion_control():
    """Teste com perda de pacotes e controle de congestionamento"""
    print("Executando teste com perda de pacotes e controle de congestionamento...")
    reliable_udp_data = run_reliable_udp_test(packet_loss_rate=0.1)
    plt.figure(figsize=(12, 6))
    plt.plot(reliable_udp_data[0], reliable_udp_data[1], label='UDP Confiável', linestyle='-')
    plt.title("Vazão com Perda de Pacotes (Com Controle de Congestionamento)")
    plt.xlabel("Tempo (s)")
    plt.ylabel("Vazão (KB/s)")
    plt.grid(True)
    plt.legend()
    plt.savefig("Vazão_com_Perda_de_Pacotes_Com_Controle_de_Congestionamento.png")
    plt.show()

def general_comparison():
    """Comparação geral entre os cenários"""
    print("Executando comparação geral...")
    throughput_results = {}
    
    for loss_rate in PACKET_LOSS_RATES:
        print(f"Testando com taxa de perda de {loss_rate * 100}%...")
        udp_data = run_udp_test(packet_loss_rate=loss_rate)
        reliable_udp_data = run_reliable_udp_test(packet_loss_rate=loss_rate)
        throughput_results[loss_rate] = {
            'udp': udp_data[1][-1],  # Vazão final do UDP padrão
            'reliable_udp': reliable_udp_data[1][-1]  # Vazão final do UDP confiável
        }
    
    # Plotando a comparação geral
    loss_rates = list(throughput_results.keys())
    udp_throughputs = [throughput_results[rate]['udp'] for rate in loss_rates]
    reliable_udp_throughputs = [throughput_results[rate]['reliable_udp'] for rate in loss_rates]
    
    plt.figure(figsize=(12, 6))
    plt.plot(loss_rates, udp_throughputs, label='UDP Padrão', marker='o')
    plt.plot(loss_rates, reliable_udp_throughputs, label='UDP Confiável', marker='s')
    plt.title("Comparação Geral da Vazão")
    plt.xlabel("Taxa de Perda de Pacotes")
    plt.ylabel("Vazão Final (KB/s)")
    plt.grid(True)
    plt.legend()
    plt.savefig("Comparação_Geral_da_Vazão.png")
    plt.show()

def main():
    """Função principal para executar os testes"""
    print("Iniciando testes...")
    
    # Teste sem perda de pacotes
    test_no_packet_loss()
    
    # Teste com perda de pacotes e sem controle de congestionamento
    test_packet_loss_without_congestion_control()
    
    # Teste com perda de pacotes e controle de congestionamento
    test_packet_loss_with_congestion_control()
    
    # Comparação geral entre os cenários
    general_comparison()
    
    print("Testes concluídos!")

if __name__ == "__main__":
    main()