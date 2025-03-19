# Reliable UDP Protocol

Este projeto é uma implementação de um protocolo de transporte confiável sobre o protocolo UDP, desenvolvido como parte da disciplina de Redes de Computadores da UFJF. A implementação adapta o UDP para torná-lo mais confiável, aplicando conceitos como entrega ordenada, confirmação acumulativa, controle de fluxo e controle de congestionamento.

### Funcionalidades Implementadas

- Entrega Ordenada: Cada pacote possui um número de sequência para garantir a ordem correta na recepção.

- Confirmação Acumulativa: O destinatário envia ACKs acumulativos para confirmar o recebimento de múltiplos pacotes.

- Controle de Fluxo: O remetente ajusta o envio de pacotes com base no tamanho da janela do destinatário.

- Controle de Congestionamento: Implementação baseada nos conceitos de Slow Start e Congestion Avoidance do TCP para reduzir o fluxo de envio em caso de perdas excessivas.

### Estrutura do Código

O projeto é composto pelos seguintes arquivos:

- protocol.py - Implementação central do protocolo.

- client.py - Implementação do remetente.

- server.py - Implementação do destinatário.


#### Execução Manual

Inicie o servidor: ```python server.py 5000 received_file.dat 0.05```

Isso inicia um servidor na porta 5000, salvando os dados recebidos no arquivo received_file.dat e simulando uma perda de pacotes de 5%.

Em outra aba do terminal, inicie o cliente: ```python client.py 127.0.0.1 5000 bigfile.bin```

Para enviar dados sintéticos, utilize: ```python client.py 127.0.0.1 5000 --synthetic 4096```

Ao rodar o cógico do cliente, os pngs dos gráficos são gerados automaticamente.

Para rodar os testes, basta rodar o servidor primeiro e então ```python .\testes.py```

### Relatório

Para mais detalhes sobre a implementação e os testes realizados, consulte o relatório disponível em: [Relatório](https://www.overleaf.com/read/tqfssgbfwdhb#768510)
