# Custo do CRC no ZIP AAB

Comando: `python benchmarks/aab_crc.py --samples 9`.

Fixtures sintéticas com estrutura de nomes AAB e payload pseudoaleatório determinístico. Não são bundles protobuf válidos. Medição com cache de filesystem aquecido, ordem alternada, nove amostras por modo; geração e validadores externos excluídos. Python 3.14.7; Linux-7.2.9-2-cachyos-x86_64-with-glibc2.44.

| Payload | Metadados, mediana | Metadados + CRC, mediana | Pico de alocações Python no CRC |
|---|---:|---:|---:|
| 1 MiB | 0.047 ms | 1.205 ms | 3.17 MiB |
| 16 MiB | 0.075 ms | 18.690 ms | 3.17 MiB |
| 64 MiB | 0.077 ms | 73.977 ms | 3.17 MiB |

Resultados brutos, hashes e todas as amostras: [aab_crc_host.json](aab_crc_host.json).

Este resultado mede o custo adicionado da leitura/CRC, sem alegar aceleração. Não mede build frio, desempenho Termux, validação de assinatura/bundletool ou consumo nativo de memória. O pico tracemalloc foi medido em chamada separada e não contaminou os tempos. O RSS de processo inclui preparação/startup e não permite atribuição ao CRC; não é usado como memória da etapa. A biblioteca padrão lê as entradas em blocos de 1 MiB.
