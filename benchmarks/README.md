# Medições locais

## Adaptador Gradle/AGP

[gradle-baseline-2026-10-11.json](gradle-baseline-2026-10-11.json) registra 12 execuções verificadas de `gradle-build` na revisão `4279730`: três pares de saídas limpas/rebuild por formato, com dependências, compilação de scripts e cache de filesystem aquecidos. O cache de configuração do Gradle estava desativado. Inclui comandos, versões, fontes da fixture, hashes e amostras de tempo/RSS/tamanho. `:app:clean` e a ausência de `app/build` foram verificados antes de cada primeiro build; limpeza não foi cronometrada. O payload fora de `META-INF/` permaneceu igual nas seis execuções de cada formato.

[gradle-after-cancellation-2026-10-11.json](gradle-after-cancellation-2026-10-11.json) repete as 12 execuções na revisão `4b6d88a`, com comandos, entradas e toolchain iguais. CRC/payload e hashes completos permaneceram iguais nessa fixture, com a mesma chave/cache. Os dados comparados totalizam 24 execuções; as medianas estão no [README principal](../README.md#baseline-local-do-adaptador).

O RSS foi amostrado a cada 20 ms pela soma dos processos observados: páginas compartilhadas podem ser contadas várias vezes e picos breves podem ser perdidos. O harness foi temporário; não houve medição de cache totalmente frio ou tempos internos das tarefas. Carga ambiente/cache de filesystem não foram controlados, e a primeira baseline tinha um controlador ADB ativo para testes em outro dispositivo. Três amostras por célula não estabelecem aceleração causal no host ou desempenho no Termux.

## Custo do CRC no ZIP AAB

Comando: `python benchmarks/aab_crc.py --samples 9`.

Fixtures sintéticas com estrutura de nomes AAB e payload pseudoaleatório determinístico. Não são bundles protobuf válidos. Medição com cache de filesystem aquecido, ordem alternada, nove amostras por modo; geração e validadores externos excluídos. Python 3.14.7; Linux-7.2.9-2-cachyos-x86_64-with-glibc2.44.

| Payload | Metadados, mediana | Metadados + CRC, mediana | Pico de alocações Python no CRC |
|---|---:|---:|---:|
| 1 MiB | 0.047 ms | 1.205 ms | 3.17 MiB |
| 16 MiB | 0.075 ms | 18.690 ms | 3.17 MiB |
| 64 MiB | 0.077 ms | 73.977 ms | 3.17 MiB |

Resultados brutos, hashes e todas as amostras: [aab_crc_host.json](aab_crc_host.json).

Este resultado mede o custo adicionado da leitura/CRC, sem alegar aceleração. Não mede build frio, desempenho Termux, validação de assinatura/bundletool ou consumo nativo de memória. O pico tracemalloc foi medido em chamada separada e não contaminou os tempos. O RSS de processo inclui preparação/startup e não permite atribuição ao CRC; não é usado como memória da etapa. A biblioteca padrão lê as entradas em blocos de 1 MiB.
