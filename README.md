# termux-builder

Android Studio no Termux — build APK **sem root, sem PC**. Java, Kotlin, ViewBinding, dependencias Maven, R8, BuildConfig, debug keystore, install via adb. Tudo em um comando.

## Instalacao

Instale [Termux](https://f-droid.org/packages/com.termux/) pelo F-Droid, depois:

```
curl -s https://raw.githubusercontent.com/rianprei/termux-builder/main/install.sh | bash
```

O installer:
- Instala todas as dependencias automaticamente (openjdk-17, aapt2, dx (d8 fallback via doctor/setup), apksigner, kotlin, python)
- Baixa `android.jar` (API 34) do GitHub
- Configura `ANDROID_SDK` nos shell RCs
- Verifica que tudo funciona no final

Para cada ferramenta sem caminho explícito em `bins`, o builder procura primeiro no `PATH` e depois em `build-tools/<versão>` do SDK resolvido. Assim, ferramentas nativas do Termux no `PATH` têm prioridade sobre as cópias do SDK.

Configure o SDK em `android.sdk-path`. Caminhos relativos são resolvidos contra o diretório do projeto, independentemente do diretório de execução da CLI; caminhos absolutos preservam sua raiz. Omitir o campo ou usar `null` mantém a seleção automática por ambiente/fallback. Strings vazias, NUL e valores de outros tipos são recusados. Um `sdk-path` na raiz de `project.yml` agora gera erro com ação corretiva, inclusive quando existe também o campo correto: mova a opção para `android.sdk-path` e remova a chave da raiz. A versão anterior ignorava essa chave e resolvia caminhos relativos a partir do diretório de execução; projetos que dependiam desse comportamento devem ajustar o caminho. A configuração inválida retorna código 1 antes de `--clean`, sem alterar o YAML ou a saída anterior.

A CLI verifica o `android.jar` resolvido antes de `build --clean`, dependências ou ferramentas de recursos, em APK e AAB. Ausência ou corrupção retorna código 1 e preserva a saída anterior. A validação limita o diretório antes de construir os metadados ZIP, recusa duplicatas, nomes ambíguos ou com NUL, criptografia e compressões além de STORED/DEFLATED, exige `android/app/Activity.class` não vazio e verifica tamanho descomprimido real, término do fluxo e CRC em blocos limitados. Limites: 128 MiB de arquivo, 60.000 entradas, 16 MiB de diretório e 1 GiB expandido; arquivos com diretório ZIP64/multipartes são recusados. O fallback nativo continua disponível. Esses controles não certificam origem, autenticidade, bytecode Java, nível de API ou recursos de framework; a toolchain real ainda pode recusá-lo. Restaure o JAR da plataforma selecionada a partir de sua fonte confiável quando o diagnóstico indicar corrupção. A fixture `tests/integration/verify_aab_preflight.py` cobre ausência/corrupção no host, além de ferramentas AAB e R8 ausentes.

## Quick Start

Antes de limpar saídas ou resolver dependências, o build APK exige o AAPT2 configurado executável ou `aapt` executável no PATH. A seleção de AAPT2 usa `bins.aapt2` resolvido: um arquivo sem permissão de execução ou outro AAPT2 no PATH não torna esse caminho válido. Quando ele está indisponível e `aapt` existe, o APK registra e utiliza o fallback AAPT1. AAB continua exigindo AAPT2 para recursos protobuf. A checagem de presença/permissão não certifica arquitetura, versão, bibliotecas dinâmicas ou compatibilidade de recursos; falhas posteriores da ferramenta continuam explícitas.

`android.density-splits: true` integra também o fallback AAPT1 ao assinador e ao conjunto de instalação: APK base e seis splits `ldpi` a `xxxhdpi`. Os destinos emitidos pelo AAPT1 são validados antes da execução, incluindo recusa de symlinks. APK com `abi-splits` e `density-splits` simultâneos é recusado antes de `--clean`; escolha um modo. Essa combinação era ignorada parcialmente e ainda não tem implementação correta.

O [AAPT1 exige que cada recurso variável por densidade tenha definição no split ou no base](https://android.googlesource.com/platform/frameworks/base/+/refs/tags/android-16.0.0_r2/tools/aapt/Resource.cpp); sem isso, o build falha explicitamente. Forneça recursos padrão compatíveis ou use AAPT2. O mesmo código AOSP gera manifesto de split com pacote e `versionCode`, sem `versionName`; a fixture exige pacote/versionCode e certificado iguais ao base e aceita a ausência desse campo opcional. Não altera os recursos do projeto para contornar essas regras.

```bash
# Criar projeto novo
termux-builder init myapp --package com.example.myapp

# Entrar no projeto
cd myapp

# Buildar APK
termux-builder build .

# Buildar e instalar via adb
termux-builder build . --install

# Build limpo
termux-builder build . --clean
```

## Comandos

| Comando | Descricao |
|---------|-----------|
| `termux-builder init <nome>` | Cria projeto novo com template |
| `termux-builder build <dir>` | Compila e gera APK |
| `termux-builder build <dir> --aab` | Compila e gera um Android App Bundle assinado |
| `termux-builder build <dir> --install` | Compila e instala via adb |
| `termux-builder build <dir> --clean` | Build limpo (remove artifacts) |
| `termux-builder gradle-build <dir>` | Adaptador experimental: Gradle 9.7.1/AGP 9.4.1 reais, APK verificado |
| `termux-builder gradle-build <dir> --aab --bundletool-jar <jar>` | AAB produzido pelo AGP e verificado com bundletool local |
| `termux-builder clean <dir>` | Remove .build/ |
| `termux-builder deps <dir>` | Baixa dependencias Maven |
| `termux-builder test <dir>` | Roda testes JUnit |
| `termux-builder test <dir> --coverage` | Roda testes com cobertura JaCoCo (HTML+XML) |
| `termux-builder lint <dir>` | Verifica problemas no codigo |
| `termux-builder lint <dir> --report r.xml\|.html` | Escreve relatorio de lint |
| `termux-builder lint <dir> --baseline b.txt` | Suprime issues ja conhecidas |
| `termux-builder lint <dir> --write-baseline b.txt` | Snapshota issues atuais como baseline |
| `termux-builder decompile <apk>` | Descompila APK com apktool |
| `termux-builder recompile <dir>` | Recompila APK descompilado |
| `termux-builder doctor` | Diagnostico do ambiente |
| `termux-builder setup --api 34` | Instala android.jar |
| `termux-builder analyze <apk>` | Tamanho por dex/res/assets/native libs (APK analyzer CLI) |
| `termux-builder recon <apk> --html` | Engenharia reversa: manifest (permissoes, componentes exportados, sdk) + scan de padroes (secrets, URLs, WebView JS, exec, SQL, crypto fraca) + libs nativas, com JSON/HTML |
| `termux-builder db pull <pkg> <db>` | Puxa SQLite do app via adb + dump de schema (Database Inspector CLI) |
| `termux-builder logcat [pkg]` | Stream de logcat, filtrado por pacote se informado |
| `termux-builder deps-tree <dir>` | Arvore de dependencias transitivas resolvidas |
| `termux-builder applinks <dominio> <pkg>` | Verifica assetlinks.json (App Links Assistant CLI) |
| `termux-builder emulator list` / `start <avd>` | Lista/inicia AVD headless (sem GUI) |

## Projetos Gradle (experimental)

`gradle-build` delega o modelo do projeto ao Gradle/AGP real. Não converte scripts para YAML: usa as APIs públicas `SingleArtifact.APK`, `BuiltArtifactsLoader` e `SingleArtifact.BUNDLE` para construir e selecionar os artefatos da variante exata. O caminho direto `build` continua usando `project.yml`.

O adaptador aceita somente o par exercitado **Gradle 9.7.1 / AGP 9.4.1**, um módulo `com.android.application` e um launcher Gradle já instalado. Outras versões e launchers Wrapper são recusados explicitamente; não há bootstrap de distribuição. Exige JDK, SDK configurado pelo projeto e ferramentas de verificação locais. No Termux, usa `aapt2` nativo como override do AGP. Desativa serviços nativos do Gradle e file watching e usa daemon de uma execução. Essa combinação foi exercitada com OpenJDK HotSpot 21 no host e Android 16/ARM64/Bionic com JDK 21.0.12; outras JVMs e outros ambientes não foram certificados.

Java e Kotlin foram exercitados juntos nesse par, com referências Java↔Kotlin e remoção de fontes dos dois idiomas sem clean. A fixture usa o [Kotlin integrado do AGP 9](https://developer.android.com/build/migrate-to-built-in-kotlin), sem adicionar outro adaptador de compilação ou o plugin `org.jetbrains.kotlin.android`. Essa prova não certifica configurações Kotlin adicionais, KMP ou plugins de processamento no caminho Gradle.

A desativação também é aplicada à inicialização das JVMs dos comandos do adaptador: acrescenta `-Dorg.gradle.native=false` ao `_JAVA_OPTIONS` do subprocesso, preservando as opções existentes e o ambiente do controlador. A flag apenas na CLI foi insuficiente no teste real do daemon; no [HotSpot 21, `_JAVA_OPTIONS` é processado após as opções da linha de comando](https://github.com/openjdk/jdk21u/blob/master/src/hotspot/share/runtime/arguments.cpp). O stderr permanece descartado, inclusive o aviso da JVM que pode conter opções privadas. Não altera arquivos do projeto ou o ambiente global.

A tarefa temporária de exportação ainda é incompatível com o cache de configuração do Gradle. O comando usa `--no-configuration-cache`, inclusive quando o projeto o habilita, sem editar `gradle.properties`. A execução incremental das tarefas e o cache de dependências continuam sob controle do Gradle; isso não comprova aceleração nem reprodutibilidade do build completo.

```bash
termux-builder gradle-build /caminho/projeto \
  --gradle /caminho/gradle-9.7.1/bin/gradle \
  --module :app --variant demoDebug --offline \
  --aapt2 /caminho/aapt2 --apksigner /caminho/apksigner

termux-builder gradle-build /caminho/projeto \
  --gradle /caminho/gradle-9.7.1/bin/gradle \
  --module :app --variant demoDebug --offline --aab \
  --bundletool-jar /caminho/bundletool-all-1.18.3.jar
```

`--offline` exige dependências e plugins já no cache Gradle, além do SDK e bundletool locais. O JAR bundletool 1.18.3 precisa corresponder ao SHA-256 fixado pelo projeto. APK exige `apksigner verify`, CRC, manifesto e pacote da variante; AAB exige bundletool, estrutura, CRC, pacote e cobertura da assinatura JAR. A verificação ocorre em cópia privada, e o hash da saída original precisa corresponder aos bytes verificados antes do sucesso. Certificado confiável, instalação e execução Android não são certificados por esses controles. Release sem assinatura retorna código 1, mesmo quando AGP produziu o arquivo.

O comando não aplica reparos nem altera scripts/configuração do projeto. Gradle executa os plugins e escreve suas saídas/caches habituais; use projetos confiáveis. O lock coordena invocações termux-builder no mesmo projeto, sem isolar outros processos. Logs brutos dos plugins são descartados para evitar reproduzir credenciais; erros de seleção têm diagnóstico específico. Para outras falhas, o código de saída é informado: execute o Gradle diretamente no projeto para investigar sua causa. Não forneça senhas por argumentos; configure a assinatura no próprio projeto por meios que não as exponham.

Os comandos síncronos executados pelo helper `run`, incluindo o adaptador, usam uma sessão/grupo de processos próprios. Ao terminar, inclusive com sucesso, o helper encerra com SIGKILL os remanescentes desse grupo e espera o launcher antes de restaurar o handler de SIGINT. Filhos deixados deliberadamente no mesmo grupo deixam de sobreviver ao retorno; processos que criaram uma sessão independente são preservados. Essa mudança de contrato impede escritas posteriores à liberação do lock. Regressões com processos reais cobrem Ctrl+C na inicialização, durante execução, repetição durante cleanup e transições do handler; também verificam handlers personalizados e preservação de sessões independentes. Não há isolamento de plugins, encerramento de sessões arbitrárias ou recuperação após SIGTERM/SIGKILL/force-stop do controlador.

Reprodução: `PYTHONPATH=. python tests/integration/verify_gradle.py --gradle /caminho/gradle --sdk /caminho/SDK --aapt2 /caminho/aapt2 --apksigner /caminho/apksigner --dexdump /caminho/dexdump --bundletool-jar /caminho/bundletool-all-1.18.3.jar --offline`. A fixture usa fontes Java/Kotlin, Kotlin DSL e flavor em módulo `:mobile`: cinco APKs e três AABs verificados, definições DEX dos dois idiomas, alteração de recursos, remoção de quatro classes sem clean, erros de seleção, recusa de release realmente produzido sem assinatura e falha/recuperação com cache offline vazio. O fluxo completo passou no host, por wheel instalado fora do checkout e no Termux ARM64/Bionic sob UID/contexto do aplicativo e CapEff=0. O negativo de cache vazio remove também `GRADLE_RO_DEP_CACHE`, impedindo que um cache compartilhado o faça passar indevidamente. A CI configura esse par e executa o fluxo online e offline; sua execução remota permanece não verificada. Splits, módulos dinâmicos, Capacitor e plugins adicionais precisam de validações próprias.

No teste nativo misto, SDK, distribuição Gradle e dependências AGP já estavam locais. A primeira tentativa offline diagnosticou a ausência de `kotlin-build-tools-impl:2.2.10`. O fluxo completo passou após fornecer um [cache de dependências somente leitura do Gradle](https://docs.gradle.org/current/userguide/dependency_caching.html#sec:shared-readonly-cache), produzido pelo Gradle 9.7.1 no host e com SHA-256 conferido no aparelho. Foram transferidos somente arquivos de dependências e metadados compatíveis, sem locks ou executáveis do host. Isso comprova operação offline com cache disponível; não comprova bootstrap completo de uma instalação vazia no aparelho.

Uma preparação separada resolveu `kotlin-build-tools-impl:2.2.10` e suas dependências pelo Gradle 9.7.1 no próprio aparelho, usando Maven Central e os grupos suplementares normais do Termux. Uma tentativa anterior de resolução falhou com erro de DNS quando o harness retirava esses grupos, incluindo o grupo de rede; preservar os grupos permitiu a resolução online. A correção pertence à automação de laboratório. O fluxo completo acima usou o cache somente leitura e permissões mais restritas. Não houve uma nova repetição completa após essa resolução online, nem download do SDK/distribuição Gradle no aparelho. A saída bruta do Gradle foi descartada: não se quantificaram downloads novos nessa preparação.

A regressão adicional de cancelamento da fixture interrompe uma tarefa AGP `preBuild` que iniciou um filho escritor, exige código 130, ausência de escrita após liberação do lock e recuperação com APK/AAB verificados. Passou no host, por wheel e no Termux para `:mobile/demoDebug` com fontes mistas. Um harness separado passou no Termux para `:app/debug`, junto dos nove testes de processos reais. Nesse dispositivo, daemon e filho permaneceram no grupo gerenciado e não sobreviveram ao Ctrl+C. A configuração da fixture inclui `org.gradle.native=true` nas opções da JVM para exigir que o override de inicialização prevaleça. Não é um teste de cancelamento durante a execução do compilador Kotlin.

Um APK Java separado, produzido pelo mesmo adaptador no Termux e verificado com `apksigner`, foi instalado e aberto no Android 16: `am start -W` retornou `Status: ok`, e `pidof` confirmou o processo. O pacote de teste foi removido após a validação; instalação e execução do novo aplicativo misto Java/Kotlin e de APKs derivados de AAB no dispositivo permanecem não verificadas.

### Baseline local do adaptador

Revisões `4279730` e `4b6d88a`, Linux x86_64, JDK 21.0.12.1, API 36/Build Tools 37.0.0: três pares alternados de build com saídas limpas e rebuild por formato em cada revisão, totalizando 24 execuções. Mesmos comandos, projeto, entradas e toolchain, sem alteração de fontes da fixture. `:app:clean` removeu `app/build` antes de cada primeiro build; limpeza ficou fora do tempo medido. Dependências, compilação de scripts e cache do sistema de arquivos já estavam quentes. As validações dos artefatos estão incluídas no tempo total.

| Formato / fase | Tempo antes | Tempo após correção | Pico RSS antes / depois | Tamanho |
|----------------|------------:|--------------------:|-----------------------:|--------:|
| APK, saídas limpas | 11,6473 s | 10,5186 s | 848,0 / 865,1 MiB | 872.390 bytes |
| APK, rebuild | 8,7105 s | 7,7306 s | 668,1 / 674,3 MiB | 872.390 bytes |
| AAB, saídas limpas | 13,4336 s | 11,8879 s | 893,2 / 875,9 MiB | 778.067 bytes |
| AAB, rebuild | 9,9543 s | 8,8863 s | 667,7 / 671,9 MiB | 778.067 bytes |

Os valores são medianas de três amostras por célula. RSS foi amostrado a cada 20 ms com psutil, somando controlador e descendentes: páginas compartilhadas podem ser contadas mais de uma vez e picos breves podem passar despercebidos. CRC, payload e hashes completos de APK/AAB permaneceram iguais entre as revisões nessa fixture, com a mesma chave/cache. Dados, comandos, versões, hashes e fontes estão na [baseline](benchmarks/gradle-baseline-2026-10-11.json) e na [repetição após a correção de cancelamento](benchmarks/gradle-after-cancellation-2026-10-11.json). O harness foi temporário; não mediu tempos internos das tarefas nem caches totalmente frias. Carga ambiente e estado do cache de filesystem não foram controlados; a baseline anterior tinha um controlador ADB ativo para teste em outro dispositivo. Essa comparação descritiva não estabelece aceleração causal ou desempenho no Termux.

## Configuracao (project.yml)

```yaml
name: myapp
build-path: .build
libs-path: .libs
cache-path: .cache

dependencies:
  - "androidx.core:core:1.12.0"
  - "androidx.appcompat:appcompat:1.6.1"
  - "com.google.android.material:material:1.11.0"

android:
  target-sdk: 34
  min-sdk: 21
  version-code: 1
  version-name: "1.0.0"
  manifest-placeholders:
    appLinkHost: "example.com"

  manifest-path: AndroidManifest.xml
  sources-path: src/java
  res-path: src/res
  assets-path: src/assets
  jni-path: src/jniLibs

  build-type: release     # debug ou release
  java-version: 17
  aab: false              # true gera AAB; tambem pode usar build --aab
  view-binding: true      # gera classes de binding
  compose: false          # Jetpack Compose (experimental)
  r8: true                # minificacao R8 (release only)
  r8-rules: proguard-rules.pro

  keystore-path: my.keystore
  keystore-alias: mykey
  keystore-store-pass: "env:ANDROID_KEYSTORE_PASSWORD"
  keystore-key-pass: "env:ANDROID_KEY_PASSWORD"

  signing:              # todos opcionais, defaults abaixo
    v1: true
    v2: true
    v3: true
    v4: false           # true automatico se min-sdk >= 30
```

Defina as variaveis de ambiente antes de um build de release. Valores sem o prefixo `env:` continuam aceitos para compatibilidade; mantenha senhas de release fora do `project.yml` e do Git. Builds AAB verificam a estrutura e a assinatura do arquivo e nao podem ser combinados com `--install`.

Quando V4 esta ativo, o build valida o APK e seu arquivo `<apk>.idsig` com `apksigner` antes de publicar o par. A build falha se o assinador nao gerar o sidecar ou se a verificacao V4 falhar; uma falha ao publicar APK ou sidecar tenta restaurar os artefatos anteriores e informa onde recuperar backups se o rollback tambem falhar.

### Dependencias Maven

Declare coordenadas `group:artifact:versao` em `dependencies`. O resolvedor baixa somente de Maven Central e Google Maven por HTTPS, recusa redirecionamentos e interrompe o build quando uma coordenada ou artefato nao pode ser obtido. POMs sao lidos em blocos e limitados a 16 MiB para conter o uso de memoria durante a resolucao. Downloads usam arquivo temporario exclusivo e so passam ao cache quando concluidos. O digest `.sha1` publicado junto do artefato e conferido quando disponivel; se o repositorio responde 404, o builder avisa que a verificacao foi pulada, mas uma falha de rede encerra a resolucao. O cache guarda SHA-256, coordenada e URL de origem, e confere os hashes do artefato e dos arquivos extraidos antes de reutiliza-los.

O resolvedor le dependencias diretas e herdadas, expande propriedades locais e herdadas e valores basicos de `project.*`, ignora dependencias `test`, `provided` e `optional`, e inclui `compile` e `runtime`. Entradas locais de `dependencyManagement` e BOMs importados podem fornecer versao, escopo e exclusoes. Exclusoes sao aplicadas por caminho e preservadas no cache; conflitos usam a versao no caminho mais curto, com desempate pela ordem de `dependencies` e depois pela ordem declarada no POM. Artefatos de grupos diferentes usam diretorios de cache separados. JARs Maven antigos reconhecidos no cache deixam de entrar no classpath quando uma versao diferente foi selecionada, sem remover esses arquivos do projeto.

Heranca resolve o POM pai remoto pelas coordenadas Maven; `relativePath` local, profiles, ranges abertos, escopos `system`/`import` fora de BOMs, classifiers, packaging alem de `jar`/`aar` e tipos nao suportados falham explicitamente. Dependencias com type `jar` e `aar` selecionam a extensao declarada; dependencias sem type usam o `packaging` do POM. A notacao de versao exata `[1.2.3]` e aceita. A implementacao Maven continua parcial e nao equivale ao Maven/Gradle; confira a matriz de compatibilidade antes de depender dessas construcoes. SHA-1 remoto detecta corrupcao de transferencia quando publicado; SHA-256 local detecta alteracoes posteriores no cache. Nenhum deles comprova autenticidade do artefato; sem sidecar SHA-1 o builder avisa que a verificacao de transferencia foi omitida.

### Merge de Manifest

O builder expande `android.manifest-placeholders` em atributos XML antes de mesclar manifestos. `${applicationId}` usa o ID final do app, incluindo o sufixo da flavor. Uma flavor pode sobrescrever valores em `flavors.<nome>.manifest-placeholders`.

O manifesto do app tem prioridade sobre bibliotecas. Bibliotecas diretas seguem a ordem de `dependencies`; bibliotecas sem correspondencia nessa lista seguem ordem lexica por caminho. A mesclagem combina atributos sem conflito, interrompe builds em conflitos e aceita `tools:replace`, `tools:remove`, `tools:strict`, `tools:selector` e `tools:node` com `merge`, `mergeOnlyAttributes`, `replace`, `remove`, `removeAll` ou `strict`. Tambem verifica incompatibilidade numerica de `minSdkVersion`, com suporte a `tools:overrideLibrary`, e os valores de SDK em `project.yml` prevalecem sobre os do XML.

Esse caminho nativo ainda nao implementa todas as regras do Manifest Merger do Android Gradle Plugin. Sobreposicoes de manifestos de variantes, injecao de permissoes implicitas por `targetSdkVersion` e precedencia Maven transitiva equivalente ao Gradle permanecem fora da cobertura. Diretivas `tools:*` desconhecidas falham explicitamente. Consulte [Manage manifest files](https://developer.android.com/build/manage-manifests) para as regras completas do AGP.

## Estrutura do Projeto

```
myapp/
├── .gitignore               # Saidas de build, chaves locais e arquivos de ambiente
├── project.yml              # Configuracao do build
├── AndroidManifest.xml
├── debug.keystore           # Gerado automaticamente
├── src/
│   ├── java/                # Codigo Java e Kotlin
│   │   └── com/example/app/
│   │       └── MainActivity.java
│   ├── res/
│   │   ├── layout/
│   │   ├── values/
│   │   └── drawable/
│   └── assets/
```

## Recursos

### ViewBinding

```yaml
android:
  view-binding: true
```

Gera classes de binding para todos os layouts em `src/res/layout/`.

### R8 / ProGuard

```yaml
android:
  r8: true
  r8-rules: proguard-rules.pro
```

Minifica e otimiza codigo no build release.

Com `android.r8: true` e `android.build-type: release`, `r8` precisa estar executável no PATH. A CLI recusa sua ausência antes de `--clean`, dependências ou recursos, preservando saídas anteriores. O diagnóstico mantém a orientação `pkg install r8` para Termux; esse teste de presença não comprova compatibilidade da versão instalada. `verify_aab_preflight.py` também cobre essa falha release pela CLI.

### Jetpack Compose (Experimental)

```yaml
android:
  compose: true
```

Requer `compose-compiler.jar` nos diretórios configurados por `libs-path` ou `cache-path` (padrão `.libs/` e `.cache/`), compatível com o compilador Kotlin usado. O builder passa `-Xplugin` automaticamente para kotlinc. Com `compose: true`, a ausência do JAR encerra APK/AAB com código 1 antes de `--clean`, dependências ou recursos, preservando artefatos anteriores. A fixture real verifica a falha em ambos os formatos e recupera o build comum após desabilitar Compose. A presença do JAR não comprova compatibilidade; Compose positivo continua experimental e não verificado ponta a ponta nesta matriz.

### Debug Keystore

O `termux-builder init` gera um debug keystore automaticamente. Para release, crie seu proprio:

```bash
keytool -genkeypair -keystore release.keystore -alias mykey \
  -keyalg RSA -keysize 2048 -validity 10000
```

### JNI / Native Libs

Coloque `.so` em `src/jniLibs/<abi>/`:

```
src/jniLibs/
├── arm64-v8a/
│   └── libfoo.so
├── armeabi-v7a/
│   └── libfoo.so
└── x86_64/
    └── libfoo.so
```

## Matriz de compatibilidade verificada

AAB exige cobertura de todos os arquivos de payload e presença das entradas nomeadas pelo manifesto JAR assinado. `jarsigner -verify -strict` recusa entradas sem assinatura; o verificador Java, usando APIs públicas do JDK, autentica os pares SF/bloco, exige digest do manifesto inteiro e recusa metadados órfãos, dados anexados e diretórios com payload. Assinaturas que protegem somente seções do manifesto, metadados `SIG-*` não verificáveis e arquivos SF embutidos no bloco (`jarsigner -internalsf`) são recusados explicitamente. Metadados são lidos sem ativar a verificação JAR, com limite real de 16 MiB por entrada e 64 MiB no total; diretórios precisam estar efetivamente vazios. Esses controles precedem o parsing autenticado, bundletool e jarsigner. Doze regressões criptográficas com RSA passaram no host com JDK 17/21 e no Termux ARM64 com JDK 21, incluindo assinaturas válidas e adulterações de payload/metadados. Um teste separado verifica assinaturas RSA/EC válidas no host JDK 17/21 e no Termux JDK 21, sob UID/contexto do aplicativo e CapEff=0. A fixture criptográfica isola assinaturas JAR; APK/AAB reais têm fixtures separadas. Confiança/validade da cadeia do certificado não são certificadas. A [documentação jarsigner](https://docs.oracle.com/en/java/javase/24/docs/specs/man/jarsigner.html) distingue cobertura, falhas e avisos de certificado; verificar apenas a mensagem `jar verified` era insuficiente.

O download do bundletool usa a versão 1.18.3 e exige o SHA-256 fixado pelo projeto antes de publicar ou reutilizar o JAR do cache. Redirecionamentos são verificados antes de cada conexão: no máximo cinco, somente HTTPS em `github.com`, `release-assets.githubusercontent.com` ou `objects.githubusercontent.com`, sem credenciais, fragmentos ou portas alternativas. O conteúdo baixado tem limite de 64 MiB; falhas preservam o cache anterior e removem staging. Erros de rede não reproduzem URLs assinadas. Um executável `bundletool` instalado no PATH continua tendo precedência sobre o JAR do cache.

| Fluxo ou recurso | Estado | Escopo verificado / limite |
|------------------|--------|----------------------------|
| `project.yml` nativo, Java + AndroidX → APK assinado | VALIDATED | Build E2E em Linux x86_64, OpenJDK 25.0.4.1, Android API 36 e Build Tools 37.0.0 com `androidx.lifecycle:lifecycle-runtime:2.6.1`; manifesto e DEX presentes, `apksigner verify` aprovado; APK de 1.230.021 bytes. |
| `project.yml` nativo, Java + AndroidX → AAB | VALIDATED | Mesmo projeto e toolchain, módulo `base`; manifesto e DEX presentes, `jarsigner -verify` aprovado e `bundletool build-apks --mode=universal` gerou APK universal assinado; AAB de 1.225.589 bytes. |
| APK V4 com sidecar `.idsig` | VALIDATED | Scaffold local com `min-sdk: 30`; `apksigner verify -v4-signature-file` confirmou V4. |
| `bundletool build-apks --mode=universal` | VALIDATED | Executado sobre o AAB AndroidX acima; o APK universal passou `apksigner verify`. |
| Instalação e abertura no Android | VALIDATED | `termux-builder init <caminho-absoluto>` + `build --install` geraram e instalaram o APK pela CLI; `adb shell am start -W -n com.example.termuxbuildervalidation1011/.MainActivity` retornou `LaunchState: COLD` e `pidof` confirmou o processo em Android 16/API 36 `arm64-v8a`. O build foi feito no host Linux x86_64 e o pacote temporário foi removido. |
| Build Java → APK executado em Android/Termux/Bionic arm64 | VALIDATED | Fixture nativa em Android 16/API 36, Python 3.14.6, JDK 21.0.12, ferramentas Termux e android.jar oficial API 36: build frio e rebuild pela CLI; assinatura, CRC, DEX e identidade do pacote verificados. Processo no UID/contexto SELinux do Termux, sem capacidades Linux; acionamento automatizado via MagiskSU. JNI e inicialização pelo terminal interativo ainda não verificados; Kotlin/KSP tem validação própria abaixo. |
| Build Java → AAB executado em Android/Termux/Bionic arm64 | VALIDATED | Mesmo ambiente nativo, JAR bundletool 1.18.3 com SHA-256 verificado: CLI build/rebuild, assinatura JAR, validacao bundletool, identidade do pacote, CRC, DEX e metadados do modulo base. Modulos dinamicos e APK derivado do AAB no dispositivo nao verificados. |
| Integridade ZIP do SDK antes de `--clean` | VALIDATED | Host: 338 testes, 18 cenários de CLI e revalidação KAPT/KSP com APK/AAB reais. Termux ARM64/Android 16/JDK 21.0.12, UID/contexto do aplicativo e CapEff=0: cinco testes de ZIP, 12 falhas de corrupção pela CLI com saída preservada, JAR de sistema aceito e APK/AAB Java produzidos com SDK oficial API 36, CRC/assinatura e presença de DEX/manifesto verificados. Wheel instalado fora do checkout passou o mesmo gate. Não certifica autenticidade, bytecode ou recursos de framework. |
| JUnit 4 e JaCoCo 0.8.12 na JVM do Termux ARM64 | VALIDATED | Android 16/API 36, JDK 21.0.12, UID/contexto SELinux do Termux e capacidades Linux zeradas: assertion negativa, remoção de testes, invalidação do bytecode, cobertura independente por execução e falha explícita do relatório. JARs oficiais fornecidos em cache e hashes verificados; não comprova download no dispositivo nem instrumentação Android. |
| Testes JVM mistos Java/Kotlin no Termux ARM64 | VALIDATED | Kotlin 1.9.24 em JARs portáveis, JDK nativo 21.0.12, Android 16/API 36, UID/contexto do Termux e capacidades Linux zeradas: referências Java↔Kotlin, dois testes JUnit, bytecode Java 8 e falha explícita após remover a dependência Kotlin. Não valida APK/AAB Kotlin, KAPT/KSP ou instrumentação Android. |
| Bibliotecas JNI/native em APK e AAB | UNVERIFIED | Há descoberta de bibliotecas e código de empacotamento, mas nenhum build E2E com bibliotecas `.so` reais foi executado nesta rodada. |
| Projeto misto Java/Kotlin 1.9.24 sem processadores → APK/AAB | VALIDATED | Host JDK 21/API 36/Build Tools 37.0.0: referências Java↔Kotlin, classes no DEX, assinatura APK/AAB, bundletool, chamada JVM com resultado 7, recuperação e rejeição de dependências removidas sem clean. Execução Android do aplicativo e esta fixture mista sem processadores no dispositivo não verificados. |
| Kotlin 1.9.24 com KAPT → APK/AAB pela CLI | VALIDATED | Fixture real no host, JDK 21/API 36/Build Tools 37.0.0: projeto misto Java/Kotlin, classes e recurso gerados, bytecode direto, execução JVM, assinatura e rebuild sem clean. Não comprova compatibilidade com todos os processadores. |
| Kotlin 1.9.24 com KAPT → APK/AAB no Termux ARM64/Bionic | VALIDATED | Fixture completa em Android 16/API 36, Python 3.14.6/JDK 21.0.12: fontes mistas, anotação Java original, Java/Kotlin/bytecode e recursos gerados, valor JVM 28, DEX, assinatura, bundletool e remoção sem clean. Dois APKs/dois AABs pela CLI, UID/contexto do Termux e capacidades Linux zeradas. JARs/android.jar fornecidos localmente, acionamento por ADB/MagiskSU; instalação, bootstrap de rede e outros processadores não verificados. |
| Kotlin 1.9.24/KSP 1.9.24-1.0.20 → APK/AAB pela CLI | VALIDATED | Provider real no host, mesma toolchain Android/JDK: anotação em Java original dispara geração; Kotlin chama Java que usa classes Java/Kotlin geradas, com resultado 17 na JVM. Recurso, classes no DEX, assinatura e rebuild sem clean verificados. |
| Kotlin 1.9.24/KSP 1.9.24-1.0.20 → APK/AAB no Termux ARM64/Bionic | VALIDATED | Fixture completa em Android 16/API 36, Python 3.14.6/JDK 21.0.12: projeto misto e entradas somente Java, saídas Java/Kotlin ou somente Java, resultados JVM 17/10, DEX, recurso, assinatura, bundletool e remoção sem clean. UID/contexto do Termux, capacidades Linux zeradas; JARs e android.jar fornecidos localmente, acionamento via ADB/MagiskSU. Instalação e bootstrap pela rede não verificados. |
| Flavors do pipeline `project.yml` e Compose | UNVERIFIED | Existem caminhos de implementação, mas não foram incluídos no build ponta a ponta desta matriz. Compose continua experimental. |
| `android.density-splits` no fallback AAPT1 | VALIDATED | Host API 34/36/Build Tools 37, wheel externo e Termux ARM64/Bionic/Android 16/JDK 21.0.12: base e seis splits reais, CRC, DEX no base, pacote/versionCode/certificado compatíveis, recusa de ABI+density antes de clean e de recursos sem fallback, preservação e recuperação sem HDPI obsoleto. Nativo: 62 testes, fluxo completo com 15 APKs, hashes coincidentes, UID/contexto do aplicativo, grupos normais e CapEff=0. AAPT1 exige recursos completos ou fallback no base; instalação desse conjunto e CI remota não verificadas. |
| ABI+density simultâneos no pipeline APK direto | NOT IMPLEMENTED | A CLI recusa a combinação antes de clean/dependências; não gera silenciosamente apenas uma das modalidades. Os modos separados permanecem disponíveis. |
| Gradle 9.7.1/AGP 9.4.1, fontes Java/Kotlin e Kotlin DSL → APK/AAB | VALIDATED | CLI real no host JDK 21/API 36/Build Tools 37.0.0 e por wheel instalado fora do checkout; módulo :mobile/demoDebug, referências Java↔Kotlin, cinco APKs/três AABs, assinatura/CRC/pacote/definições DEX/recursos, remoção de quatro classes Java/Kotlin sem clean, release sem assinatura, seleção inválida, cache offline vazio e cancelamento com recuperação. Plugins Kotlin adicionais não foram exercitados. |
| Gradle 9.7.1/AGP 9.4.1, fontes Java/Kotlin → APK/AAB no Termux ARM64/Bionic | VALIDATED | Android 16/API 36, JDK nativo 21.0.12, UID/contexto do aplicativo e CapEff=0: mesma fixture mista completa :mobile/demoDebug, oito artefatos, assinatura/CRC/pacote/definições DEX/recursos, remoção Java/Kotlin sem clean, release produzido sem assinatura e recusado, seleção inválida, cache offline vazio e cancelamento com recuperação. Fontes críticas/fixture com hashes coincidentes; SDK/Gradle/cache AGP locais, dependências Kotlin em cache somente leitura verificado; aapt2 nativo e executáveis SDK do host sem execução. APK Java separado :app/debug instalado e aberto. Instalação do APK misto, bootstrap completo e outros pares não verificados. |
| Capacitor, outras configurações Kotlin, splits/módulos dinâmicos no adaptador e outros plugins Gradle | UNVERIFIED | O adaptador executa o Gradle real, mas essas combinações ainda não têm fixtures E2E e não são anunciadas como suportadas. |
| Maven: herança remota, propriedades, BOM imports, gestão de versão/escopo/exclusão, scopes compile/runtime, optional, mediação nearest, tipos jar/aar, exclusões por caminho e cache com hash SHA-256 | PARTIAL | Suíte unitária e build real de APK/AAB com `androidx.lifecycle:lifecycle-runtime:2.6.1`, incluindo DEX de bibliotecas. Parent `relativePath`, profiles, classifiers, tipos além de jar/aar e outras regras Maven/Gradle não estão implementados. |
| Merge nativo de manifests, placeholders e diretivas selecionadas | PARTIAL | Testes unitários cobrem prioridade, conflitos, placeholders, `tools:*` suportado e `uses-sdk`; o pipeline também foi exercitado com AAR real. Não há equivalência total com AGP. |
| Módulos de feature/dynamic delivery em AAB | NOT IMPLEMENTED | O AAB validado contém somente o módulo `base`. |

`VALIDATED` descreve apenas as combinações e comandos listados acima. O teste em Linux não comprova execução nativa em Termux/Bionic; a assinatura de debug comprova integridade, não confiança ou identidade de publicação.

A verificação AAB recusa entradas ZIP duplicadas, caminhos absolutos ou com traversal/componentes vazios, barras invertidas e symlinks antes de invocar bundletool/jarsigner. Todas as entradas passam por verificação de CRC do ZIP antes das ferramentas externas; CRC não comprova autenticidade. O manifesto base também precisa ter conteúdo; a fixture negativa verifica sua substituição por bytes vazios em uma cópia do AAB real. Essas verificações não substituem a validação do formato protobuf nem a assinatura JAR. O gate passou em AAB real pela CLI no host JDK 21/API 36/Build Tools 37.0.0. Após um build validado, execute `PYTHONPATH=. python tests/integration/verify_aab_archive.py /caminho/app.aab`: a fixture modifica apenas cópias temporárias e exige rejeição de entradas duplicadas ou inseguras. Está conectada ao AAB produzido na CI; execução remota e revalidação nativa deste gate permanecem não verificadas.

A assinatura APK exige staging não vazio após o assinador e verificação `apksigner verify` antes de publicar. Retorno zero sem escrita no staging gera erro, preserva o APK anterior e remove a saída temporária; existência do arquivo não basta.

A assinatura AAB usa o algoritmo escolhido pelo `jarsigner` para o tipo e tamanho da chave, mantendo SHA-256 nos digests do JAR. Chaves RSA e EC foram verificadas com ferramentas reais no host e no Termux. `bundletool validate` também aceita bundles sem assinatura: o pipeline verifica a assinatura JAR separadamente; validação estrutural não comprova assinatura nem confiança no certificado.

### Testes JUnit do projeto

`termux-builder test <dir>` compila as fontes encontradas e executa JUnit 4 na JVM, usando as classes do app já compiladas e as dependências locais. O runtime JUnit 4 é identificado pelas entradas `org/junit/runner/JUnitCore.class` e `org/junit/Test.class` nos JARs locais ou no cache, incluindo JARs renomeados. Arquivos ilegíveis, ZIPs inválidos, symlinks e arquivos especiais são ignorados; ausência de runtime compatível gera diagnóstico explícito. Essa inspeção não verifica autenticidade nem bytecode: falhas de carregamento continuam sendo erros da execução JVM. O diretório gerado `.build/test-classes` (ou o equivalente em `build-path`) é removido antes de cada execução, inclusive quando todas as fontes foram excluídas; symlinks ou arquivos nesse destino são recusados. Isso impede executar classes de testes removidos. A descoberta preserva o nome completo do pacote e seleciona classes de topo cujo nome começa ou termina com `Test`; classes auxiliares com outros nomes e classes internas são excluídas. Sem fontes, a CLI informa explicitamente que não executou testes. Embora descubra também `src/androidTest`, esse comando não fornece um runner de instrumentação no dispositivo.

A fixture `tests/integration/verify_testing.py` exige JDK, JUnit 4.13.2, Hamcrest Core 1.3 e um SDK local. Ela fornece o runtime real renomeado e um JAR decoy sem JUnit, exige diagnóstico/código 1 após retirar o runtime e sucesso após restaurá-lo. Executa a CLI real, exige uma falha de assertion JUnit, remove a fonte que falhava e exige sucesso com exatamente um teste, depois remove todas as fontes e verifica a invalidação do bytecode. Reproduza com `PYTHONPATH=. python tests/integration/verify_testing.py --android-jar /caminho/SDK/platforms/android-36/android.jar --junit-jar /caminho/junit-4.13.2.jar --hamcrest-jar /caminho/hamcrest-core-1.3.jar`. O fluxo passou no host Linux com JDK 21 e JDK 25.0.4.1; a CI configura JDK 17 e baixa essas dependências do Maven Central. A fixture também passou no Termux ARM64, Android 16/API 36 e JDK 21.0.12, sob o UID/contexto SELinux do aplicativo e sem capacidades Linux, acionada por automação via MagiskSU. Execução remota da CI e acionamento pelo terminal interativo permanecem não verificados. A recusa de `test` concorrente pelo lock foi verificada no Termux.

A fixture também aceita `--kotlinc /caminho/kotlinc --kotlin-stdlib /caminho/kotlin-stdlib.jar` em conjunto. Com Kotlin 1.9.24 e JDK 21 no host, passou a compilação e execução de testes mistos Java/Kotlin com referências nos dois sentidos, verificação do bytecode Java 8 (major 52) e remoção das classes após excluir as fontes. Kotlin compila primeiro usando fontes Java para resolver símbolos; javac compila depois com as classes Kotlin no classpath. Remover a dependência Kotlin faz o teste Java falhar explicitamente, sem reutilizar seu bytecode anterior. O comando usa `1.8` como alvo Kotlin quando `java-version` é 8; outros níveis preservam sua grafia numérica. Esse cenário também passou no Termux ARM64, Android 16/API 36, com JDK nativo 21.0.12 e os JARs portáveis oficiais Kotlin 1.9.24 fornecidos localmente. A execução usou o UID/contexto SELinux do aplicativo, sem capacidades Linux, acionada via MagiskSU. Não valida bootstrap Kotlin pela rede no dispositivo, build Kotlin de APK/AAB, KAPT/KSP ou instrumentação Android. O cenário está conectado à CI, cuja execução remota permanece não verificada.

### Segurança de `build-path` e limpeza

`build-path` exige uma string não vazia sem NUL. A configuração recusa a raiz do projeto e seus ancestrais, sobreposição com `src`, fontes/recursos/assets/JNI/bibliotecas, SDK e cache configurados, e saídas que contenham configuração, manifesto, chave de assinatura, android.jar, regras R8 ou processadores declarados. Os caminhos reais são comparados, incluindo aliases symlink. Isso impede apagar entradas conhecidas e misturar saídas com diretórios de descoberta de fontes.

`clean` e `build --clean` revalidam os caminhos antes de excluir arquivos. A limpeza recusa um symlink na raiz da saída, inclusive com barra final ou `/.`, e caminhos cujo `..` através de symlink tenha significado diferente após normalização. Diretórios de saída dedicados fora do projeto continuam permitidos. Configurações sobrepostas precisam mover a saída, as entradas ou o cache para diretórios separados; nenhum caminho é alterado automaticamente.

Essas verificações protegem as entradas declaradas e os diretórios convencionais; não identificam arquivos pessoais desconhecidos colocados numa saída nem isolam o projeto de alterações externas simultâneas. `clean` continua removendo todo o diretório de saída dedicado. Testes temporários verificam preservação de fontes, configuração, dependências, chaves, cache e aliases; a fixture Termux também recusa saídas `.`/`src` e verifica build com `--clean`.

### Cobertura JaCoCo

O bootstrap JaCoCo 0.8.12 verifica SHA-256 fixado do agente e CLI antes de executar ou reutilizar seus JARs. O download exige HTTPS no Maven Central (`repo.maven.apache.org`), resposta 200 direta sem redirects e no máximo 8 MiB; usa staging exclusivo e publica somente após verificação. Cache ausente precisa de rede; cache válido funciona offline. A raiz do cache e seu diretório `deps` não podem ser symlinks, inclusive com barra final; paths ambíguos com symlink/`..` são recusados. Cache corrompido, symlink ou arquivo especial gera erro sem download ou reparo automático: remova somente o JAR indicado e obtenha novamente os bytes oficiais. Erros de rede não reproduzem detalhes da exceção que possam conter credenciais de proxy.

Origem dos bytes pinados: [agente 0.8.12](https://repo.maven.apache.org/maven2/org/jacoco/org.jacoco.agent/0.8.12/org.jacoco.agent-0.8.12-runtime.jar) e [CLI 0.8.12](https://repo.maven.apache.org/maven2/org/jacoco/org.jacoco.cli/0.8.12/org.jacoco.cli-0.8.12-nodeps.jar). Os hashes estão em `builder/testing.py`. Ambos foram baixados pelo bootstrap real e reutilizados com rede desabilitada por instrumentação de teste no host. O pin identifica os bytes aprovados pelo projeto; não verifica uma assinatura criptográfica do fornecedor. Interrupções tratáveis removem staging; limpeza de arquivos órfãos após SIGKILL não foi implementada.

`test --coverage` substitui os dados de execução em `jacoco.exec` a cada execução (`append=false`); não acumula cobertura de testes anteriores. Um destino existente precisa ser arquivo regular com um único hard link; symlinks, diretórios e FIFOs são recusados antes da compilação. Se o gerador JaCoCo falhar, a CLI retorna código 1 e não anuncia um relatório bem-sucedido. O destino do relatório recusa symlinks no caminho, traversal ambíguo, arquivos especiais e hard links existentes na árvore de saída, antes de obter a ferramenta ou executar Java. Diretórios que não possam ser inspecionados falham explicitamente. Isso não isola alterações externas simultâneas. O gerador escreve em staging exclusivo; antes de publicar, a CLI exige XML parseável com raiz `report` e um `index.html` contendo a estrutura HTML. Falha de geração ou validação preserva os relatórios anteriores e limpa o staging. A publicação copia os arquivos verificados sobre a saída existente, preservando arquivos não substituídos; não é uma transação atômica, e falha durante a cópia pode deixar publicação parcial. Arquivos de relatórios antigos podem permanecer: só trate o relatório como resultado atual após sucesso do comando.

A fixture JUnit aceita `--jacoco-agent /caminho/org.jacoco.agent-0.8.12-runtime.jar --jacoco-cli /caminho/org.jacoco.cli-0.8.12-nodeps.jar`. Com as ferramentas reais, executa separadamente os dois ramos da mesma classe, exige um ramo coberto e um não coberto em cada XML, e exige erro quando um bytecode truncado impede gerar o relatório. Também verifica HTML publicado, preservação de todos os bytes do relatório após falha do gerador e remoção do staging. O fluxo completo passou no host JDK 21 e no Termux ARM64/Android 16/API 36, com JDK 21.0.12, UID/contexto SELinux do aplicativo e capacidades Linux zeradas; a indisponibilidade anterior do ambiente Termux foi superada. Os JARs oficiais foram fornecidos em cache e verificados pelos hashes de produção; download pela rede no dispositivo permanece não verificado. O fluxo está conectado à CI, cuja execução remota permanece não verificada. A verificação de caminhos não isola o projeto de alterações simultâneas por processos externos.

### Concorrência no projeto

A CLI protege `build` (APK/AAB, incluindo `--clean`), `gradle-build`, `test`, `clean` e `deps` com um `flock` exclusivo no diretório do projeto. Uma operação concorrente no mesmo diretório é recusada imediatamente com código 1 e orientação para tentar novamente após a primeira terminar. Caminhos symlink para o mesmo diretório compartilham o lock; projetos diferentes continuam independentes. Não há arquivo de lock a apagar: o kernel libera o descritor quando o processo termina, inclusive após SIGKILL. Testes com processo independente verificam a recusa antes de alterações e a recuperação após interrupção. A liberação pelo kernel após SIGKILL não encerra os subprocessos; o cleanup do helper trata interrupções SIGINT com o controlador ainda ativo.

Essa proteção coordena os comandos da CLI. Não bloqueia editores, chamadas diretas aos módulos Python ou projetos distintos configurados para gravar nos mesmos diretórios de saída; use diretórios de build separados nesses casos. Não constitui grafo de tarefas ou cache incremental de todas as etapas. A liberação do lock após SIGKILL não comprova encerramento de subprocessos de toolchain que tenham sobrevivido ao controlador; recuperação de toda a árvore de processos ainda não foi implementada.

### Validação nativa no Termux

Use `--key-algorithm EC` para repetir a fixture com chave EC; o padrão é RSA. No fluxo AAB, a fixture compara SHA-256 de cada entrada entre build e rebuild e falha se o conteúdo fora das entradas de assinatura JAR mudar. Também registra diferenças de metadados ZIP.

Execute na raiz do checkout, com Python/PyYAML, JDK, aapt2, D8 e apksigner nativos instalados:

```sh
PYTHONPATH=. python tests/integration/verify_termux.py --android-jar /caminho/android-sdk/platforms/android-36/android.jar
```

A fixture cria um projeto e certificado temporários, executa build/rebuild pela CLI e verifica o APK, removendo seus arquivos ao terminar. Também mantém o lock do projeto e exige que outras CLIs para build --clean, test, clean e deps retornem código 1 sem alterar o APK; essa checagem passou no Termux ARM64. Para incluir AAB, acrescente `--aab` e tenha `jarsigner` no PATH. Acrescente também `--bundletool-jar /caminho/bundletool-all-1.18.3.jar` para semear o cache e dispensar o download: o fixture verifica o SHA-256 e exige que o comando resolvido use esse JAR, recusando um executável `bundletool` que o substitua no PATH. Sem o JAR, o fluxo AAB pode precisar de rede ou de bundletool instalado. O AAB é verificado quanto a assinatura, estrutura, DEX, metadados e identidade do pacote via manifesto protobuf. Ela exige Android ARM64 e recusa execução como root. Sem `--android-jar`, usa a descoberta normal de SDK do projeto. O android.jar de `/data/data/com.termux/files/usr/share/java/` instalado neste dispositivo não contém os recursos de framework exigidos pelo template: o primeiro teste falhou com `Theme.Material.Light not found`. Com o JAR oficial da plataforma API 36, o template intacto compilou usando somente executáveis nativos do Termux, sem proot/glibc/Gradle.

Na validação automatizada, ADB/MagiskSU transferiu o código/JAR e iniciou o processo com UID/GID 10357, contexto `untrusted_app_27` do Termux e capacidades Linux removidas. Isso verifica o build nativo nessa configuração; não comprova inicialização pelo terminal interativo, instalação do APK produzido ou processadores Kotlin no dispositivo. Uma amostra observou 20,468 s no build frio e 19,528 s no rebuild, ambos com APK de 12.689 bytes; não é uma comparação de desempenho antes/depois. Em outra execução com `--aab`, o primeiro AAB levou 23,976 s e o rebuild 24,499 s, com 5.512 e 5.514 bytes respectivamente (uma amostra por fase, após os builds APK). Isso não estabelece reprodutibilidade dos artefatos assinados. Em novas execuções completas com RSA e EC, APK/AAB e rebuild passaram; os hashes de todas as entradas fora da assinatura permaneceram iguais. Houve diferenças no conteúdo do bloco de assinatura e nos metadados ZIP das entradas de assinatura; portanto, o AAB assinado completo não foi idêntico byte a byte.

## Benchmark do cache DEX de bibliotecas

Java e Kotlin recompilam as fontes em diretórios de classes limpos, para que classes removidas não permaneçam no DEX. Isso também vale quando não restam fontes de uma linguagem. O cache de DEX das bibliotecas é separado dessa limpeza; não há cache incremental da compilação das fontes da aplicação.

As fontes Java geradas por AIDL também são invalidadas quando interfaces são removidas. Projetos com arquivos `.aidl` exigem o compilador `aidl` no `PATH`; sua ausência encerra o build com erro. A geração e a remoção foram verificadas com o compilador real do SDK Build Tools 37.0.0 no host Linux; isso não comprova execução nativa no Termux.

ViewBinding regenera suas fontes em um diretório limpo e falha em XML malformado. Um rebuild de APK no host Linux confirmou que o binding de um layout removido desaparece do DEX, com CRC e assinatura válidos. Essa validação não demonstra paridade completa com o ViewBinding do AGP.

Os campos `android.min-sdk`, `android.target-sdk` , `android.java-version` e o `version-code` efetivo (incluindo flavors) exigem inteiros positivos; strings, booleanos, valores fracionários e `null` são recusados. Isso valida formato, sem comprovar compatibilidade da toolchain com cada nível de SDK ou alvo Java. O fallback existente para compatibilidade DEX/dx reduz alvos Java acima de 8 para Java 8 e agora emite aviso explícito; configure um D8 disponível para preservar o alvo solicitado.

A seção `bins` exige um mapa de nomes de ferramentas para strings de executáveis não vazias, sem NUL. Nomes de comandos e caminhos explícitos continuam aceitos; argumentos adicionais não fazem parte desse campo.

A busca compartilhada de arquivos retorna caminhos em ordem determinística e encerra a operação quando não consegue percorrer um diretório, em vez de omitir entradas silenciosamente. Diretórios opcionais inexistentes continuam aceitos.

A raiz de `project.yml` e a seção `android` exigem mapas YAML. Erros de sintaxe indicam linha/coluna sem reproduzir o conteúdo do arquivo, para evitar expor credenciais nos logs.

A seção `android.signing` exige um mapa; `v1`, `v2`, `v3` e `v4` exigem booleanos YAML sem aspas. Valores inválidos são recusados na leitura da configuração.

As opções Android `kapt`, `ksp`, `aab`, `desugar`, `r8`, `view-binding`, `compose`, `abi-splits` e `density-splits` exigem booleanos YAML (`true`/`false` sem aspas). `annotation-processors` exige uma lista de caminhos não vazios; uma string isolada, `null` ou entradas com NUL são recusados antes da preparação do build.

As saídas de processadores (`gen-apt`, `kapt` e `ksp`) são limpas antes da recompilação, inclusive quando não restam fontes. Um processador javac real confirmou que remover uma anotação elimina seu fonte e sua classe gerados. Em projetos com KAPT e fontes Kotlin, o processamento pertence ao KAPT: a compilação Java é adiada, os fontes Java originais e gerados por recursos/ViewBinding entram na fase KAPT e na resolução Kotlin, e javac compila Java depois de Kotlin com `-proc:none`. Isso evita executar o mesmo processador duas vezes e permite que Java use classes geradas. Sem fontes Kotlin, o processamento javac continua disponível. Classes emitidas diretamente em `kapt/classes` entram no classpath e no DEX; symlinks e arquivos especiais são recusados antes do DEX.

Com KSP e fontes Kotlin, Java também aguarda a geração: suas fontes originais e as fontes R/BuildConfig/ViewBinding entram na análise KSP e na resolução Kotlin. Java compila depois de Kotlin, sem passar os providers KSP a javac como processadores APT. A fixture real exige geração condicionada a uma anotação Java, executa o bytecode misto e verifica as classes no APK/AAB; ao desabilitar KSP e remover o consumidor Java, exige ausência das classes e recursos anteriores no rebuild sem clean.

KSP também processa aplicativos sem fontes Kotlin originais. A fase de análise usa `-Xallow-no-source-files` do compilador 1.9.24; se o provider gerar Kotlin, essas fontes compilam antes de Java. Se produzir somente Java, a compilação Kotlin final é omitida. A fixture remove a última fonte Kotlin sem clean, exige APK/AAB válidos e executa o consumidor Java com resultado 17; em seguida, restringe o provider a saídas Java e verifica resultado 10, ausência das classes Kotlin removidas, recurso e assinatura em ambos os formatos. Validado no host JDK 21/API 36/Build Tools 37.0.0; compatibilidade com outros providers continua não verificada.

Recursos KAPT de `CLASS_OUTPUT` e KSP de `.build/ksp/resources` entram no APK e em `root/` do módulo base AAB. Caminhos reservados, metadados de assinatura, symlinks, arquivos especiais e conflitos são recusados. Erros de leitura encerram o empacotamento e preservam o APK anterior; `.class` segue somente pelo DEX. Os testes comparam bytes do APK unsigned e do ZIP do módulo base após alterar apenas os mtimes de recursos e DEX, mantendo o APK de recursos e demais entradas fixos. Isso não comprova reprodutibilidade do build completo ou das assinaturas.

As fixtures `tests/integration/verify_kapt.py` e `verify_ksp.py` usam processadores e compiladores reais para gerar Java/Kotlin e executar as classes na JVM. Com SDK, executam D8/aapt2 e builds pela CLI, verificam as definições de classe com `dexdump`, recursos, CRC e assinatura de APK/AAB. O AAB também passa pela validação do bundletool no pipeline público. Ambas desabilitam o processador em `project.yml` e reconstroem sem `clean`, verificando a remoção de classes/recursos e a nova assinatura. KAPT também cobre `Filer.createClassFile` e um projeto misto em que Kotlin chama Java, que usa classes geradas em Java/Kotlin e bytecode direto. Uma anotação na fonte Java dispara a geração condicional de outra classe e recurso; a fixture exige ambos nos artefatos e verifica sua remoção no rebuild, inclusive a remoção da classe Java original.

Esses fluxos passaram no host com JDK 21, Android 36 e Build Tools 37.0.0. Reproduza com `PYTHONPATH=. python tests/integration/verify_kapt.py --android-jar /caminho/SDK/platforms/android-36/android.jar --d8 /caminho/d8 --dexdump /caminho/dexdump --aapt2 /caminho/aapt2 --apksigner /caminho/apksigner`, com JDK compatível e `keytool`/`jarsigner` no PATH. Para KSP, troque o nome do script por `verify_ksp.py`. Sem os argumentos de SDK, as fixtures verificam apenas compilação/execução JVM. A CI configura JDK 17/Android 34/Build Tools 35.0.0; a execução remota ainda não foi confirmada. O certificado temporário é autoassinado: verificar a assinatura não comprova confiança no certificado. Instalação desses artefatos, execução conjunta de KAPT/KSP e compatibilidade com todos os processadores permanecem não verificados; as fixtures KAPT e KSP passaram separadamente no Termux, conforme os escopos abaixo.

A sondagem `kotlinc -version` usada pelo KAPT exige código de saída zero e tem limite de 30 segundos. Falhas ao iniciar o executável ou detectar a versão encerram a preparação com orientação corretiva, sem copiar a saída bruta do processo para o erro.

`verify_kapt.py` e `verify_ksp.py` aceitam `--toolchain-cache /caminho/cache` para reutilizar Kotlin, o plugin correspondente e bundletool disponíveis localmente. As fixtures aplicam os validadores normais ao cache, criam projetos temporários e usam o caminho do Python atual no shebang do wrapper, inclusive no Termux sem `/usr/bin/env`. Para inspecionar DEX no Android, podem receber `--dexdump /apex/com.android.art/bin/dexdump` quando esse executável estiver disponível. A opção de cache passou pelo fluxo completo de ambas no host; fornecer JARs localmente não comprova bootstrap pela rede no dispositivo.

A fixture completa também passou no Termux ARM64/Bionic, Android 16/API 36, com Python 3.14.6 e JDK nativo 21.0.12. Usou aapt2 `2.20-android-16.0.0_r4`, D8 `9.2.4-dev`, apksigner `0.9` e ART dexdump de `/apex/com.android.art/bin/dexdump`, além de bundletool 1.18.3 em cache validado. Python, Java e aapt2 foram confirmados como ELF aarch64 com interpretador `/system/bin/linker64`. A automação transferiu fontes/JARs/android.jar locais via ADB/MagiskSU e executou no UID 10357, contexto SELinux `untrusted_app_27`, com `CapEff=0`; não usou proot, glibc ou distribuição externa.

Foram verificados geração e execução JVM, seis builds de APK e quatro de AAB, incluindo CLI, entradas somente Java, saídas somente Java e remoção de classes/recursos após desabilitar KSP sem clean. São verificações de assinatura e estrutura, sem comprovar confiança no certificado autoassinado. Download no dispositivo, execução pelo terminal interativo, instalação/abertura desses APKs e outros providers continuam não verificados.

Para reproduzir no Termux com dependências locais, use `PYTHONPATH=. python tests/integration/verify_ksp.py --toolchain-cache /caminho/cache --android-jar /caminho/sdk/platforms/android-36/android.jar --d8 d8 --dexdump /apex/com.android.art/bin/dexdump --aapt2 aapt2 --apksigner apksigner` com as ferramentas no PATH.

A fixture KAPT completa também passou nesse ambiente nativo, com Kotlin/plugin 1.9.24 e bundletool 1.18.3 locais. O processador gera Java/Kotlin, bytecode direto e recursos; uma anotação Java original aciona outra classe e recurso. A CLI produz APK/AAB assinados, exige valor JVM 28 e definições de classe no DEX e, após desabilitar KAPT/remover a fonte Java, exige valor 0 e ausência das saídas antigas em ambos os formatos, sem clean. CRC, `apksigner verify`, `jarsigner -verify` e validação bundletool passaram com ferramentas nativas. O primeiro wrapper falhou por `/usr/bin/env` ausente; a fixture agora usa o Python atual. Uma execução USB foi interrompida por perda do transporte; a repetição completa por Wi-Fi no mesmo número de série terminou com código 0. Para repetir, use o comando anterior com `verify_kapt.py` e um cache que inclua Kotlin/KAPT/bundletool. Não comprova instalação, bootstrap pela rede, fallback de K2, execução conjunta com KSP ou outros processadores.

O bootstrap do compilador Kotlin K1 usa staging exclusivo, rejeita caminhos ZIP inseguros e verifica os JARs antes de publicar ou reutilizar o cache. Caches inválidos geram erro; remova somente `.cache/kapt/kotlinc-1.9.24` (ou o equivalente no cache configurado) e tente novamente. ZIP64 e arquivos multipartes são recusados explicitamente. A distribuição oficial Kotlin 1.9.24 compilou uma classe real com JDK 21 neste host; com JDK 25, falhou em `JavaVersion.parse`. A validação de CRC e estrutura não comprova autenticidade nem detecta substituições que preservem um ZIP válido. O plugin KAPT também valida versão, destino, limites, CRC e classe registradora antes da publicação e da reutilização offline; o JAR oficial 1.9.24 passou nessas verificações no host. Isso não comprova autenticidade nem compatibilidade com todos os processadores KAPT. O bootstrap KSP também valida seu compilador embeddable, API e plugin, com staging exclusivo e rejeição de caches corrompidos. Os artefatos oficiais da combinação Kotlin 1.9.24/KSP 1.9.24-1.0.20 passaram nas verificações, e o compilador embeddable iniciou com JDK 21 no host. Downloads Maven de KAPT/KSP exigem resposta HTTP 200 direta e recusam redirecionamentos. Para reproduzir o APK KSP real, use `PYTHONPATH=. python tests/integration/verify_ksp.py --android-jar /caminho/android.jar --d8 /caminho/d8 --dexdump /caminho/dexdump --aapt2 /caminho/aapt2 --apksigner /caminho/apksigner`, com JDK compatível e `keytool` no PATH. A CI configura esse fluxo com JDK 17/Android 34/Build Tools 35.0.0; a execução remota ainda não foi confirmada. A fixture KSP valida um provider local real e a geração em um diretório de recursos separado das fontes; o empacotamento desses recursos tem testes para APK e módulo base AAB, incluindo entradas inseguras. A fixture não comprova compatibilidade com todos os processadores ou com Kotlin 2.x; sua execução no Termux com JARs locais está validada nesta seção. A distribuição K1 segue no máximo cinco redirecionamentos, somente por HTTPS entre `github.com` e `release-assets.githubusercontent.com`, sem credenciais na URL ou portas alternativas. O download oficial passou com essa política; erros de rede não propagam URLs assinadas na causa da exceção.

A validação ZIP compartilhada de Kotlin K1/KAPT/KSP lê o payload comprimido em blocos de até 64 KiB, verifica o tamanho expandido real e o CRC e exige término completo do DEFLATE, sem dados excedentes. Isso substitui `testzip()`, que aceitou tamanho/CRC forjados para um prefixo de classe. Recusa entradas duplicadas, nomes com NUL ou normalização ambígua, criptografia e compressões além de STORED/DEFLATED. O diretório é limitado antes do parsing; o mesmo arquivo permanece aberto durante a validação. Os limites de expansão são 256 MiB para cada JAR KAPT/KSP e 512 MiB para a distribuição K1 e cada um de seus JARs; a distribuição tem até 10.000 entradas e o diretório ZIP até 16 MiB. A verificação ocorre antes da extração/publicação e em toda reutilização offline; falhas não removem nem reparam silenciosamente o cache existente. Ela certifica integridade estrutural do ZIP, sem garantir autenticidade ou validade completa do bytecode; a inspeção da classe exigida continua limitada ao cabeçalho.

Reproduza as regressões com `PYTHONPATH=. python -m unittest tests.test_kapt_cache tests.test_ksp_cache -v` e `PYTHONPATH=. python tests/integration/verify_toolchain_cache.py`, com `javac`/`javap` no PATH. A segunda fixture compila uma classe Java real: aceita dois JARs legítimos e recusa quatro mutações STORED/DEFLATED que passam em `testzip()`, incluindo duas classes truncadas rejeitadas também por `javap`. Passou no host JDK 17/21 e no Termux ARM64/Android 16/JDK 21.0.12, UID/contexto do aplicativo e `CapEff=0`; os 49 testes de cache também passaram no dispositivo. O fluxo não valida bootstrap pela rede nem confiança na origem dos JARs. A CI inclui essa regressão JDK, sem confirmação de execução remota.

Na revisão `1b4f59e`, as fixtures KAPT/KSP completas foram repetidas separadamente no Termux com o novo validador de payload. Geração, execução JVM, APK/AAB, definições DEX, recursos, assinaturas e remoção sem clean passaram; hashes das fontes críticas coincidiram com o checkout. Foram usadas ferramentas ARM64/Bionic e JARs/SDK locais, no UID/contexto do aplicativo e `CapEff=0`. Isso não valida bootstrap remoto, instalação desses APKs ou execução conjunta dos processadores.

Comparação local entre `15e09c4` e `9ea1e8b`, em Linux x86_64, OpenJDK 25.0.4.1, Build Tools 37.0.0 e plataforma `android-36`. Foram executadas 9 amostras intercaladas por revisão. Cada amostra usa um JAR Java pequeno, chama `builder.dexer._dex_libraries(config, use_d8=True)` uma vez sem cache e uma vez com cache; o harness cronometra com `time.perf_counter`, compara o SHA-256 do DEX e lê o pico de memória dos processos filhos.

| Medida | `15e09c4` | `9ea1e8b` |
|--------|----------:|---------:|
| Build DEX frio, mediana | 0,6197 s | 0,7001 s |
| Rebuild DEX quente, mediana | 0,0888 s | 0,0885 s |
| Pico de RSS dos processos filhos, mediana | 124.412 KiB | 123.792 KiB |

O SHA-256 do DEX foi idêntico nas duas revisões. O caminho frio na revisão atual ficou 0,0804 s (13%) mais lento; esta medição não isolou qual etapa responde pela diferença. No caminho quente, a diferença observada foi inferior a 1%. O harness foi temporário e mediu apenas DEX de uma biblioteca pequena, não o tempo completo de um build Android.

Para repetir o smoke test em um dispositivo ADB autorizado, configure `ANDROID_SDK` no host e `DEVICE_SERIAL` com o serial do dispositivo:

```sh
set -e
workspace=$(mktemp -d)
python -m builder init "$workspace/app" --package com.example.termuxbuildervalidation1011
python -m builder build "$workspace/app" --install --device "$DEVICE_SERIAL"
adb -s "$DEVICE_SERIAL" shell am start -W -n com.example.termuxbuildervalidation1011/.MainActivity
adb -s "$DEVICE_SERIAL" shell pidof com.example.termuxbuildervalidation1011
adb -s "$DEVICE_SERIAL" uninstall com.example.termuxbuildervalidation1011
rm -rf "$workspace"
```

## Diagnostico

```bash
termux-builder doctor
```

Verifica: javac, ecj+dalvikvm, kotlinc, aapt2, d8/dx, apksigner, android.jar, Python deps, adb, apktool. Output verde/vermelho por item.

## Desinstalar

```bash
pip uninstall termux-builder
rm -rf ~/.termux-builder
```

## Casos de Uso

1. **Desenvolvimento Android sem PC** — celular + teclado bluetooth
2. **Hotfix em campo** — corrigir bug urgente sem laptop
3. **Educacao** — alunos aprendem Android dev no celular
4. **CI/CD ARM** — servidor ARM buildando APKs
5. **Prototipagem rapida** — testar ideias sem IDE de 8GB RAM
6. **Automacao** — scripts que geram variantes de APK

## Requisitos

- Termux (F-Droid)
- ~200MB espaco (tools + SDK)
- Android 7.0+
- Python 3.9+

## Creditos

Projeto independente inspirado por:
- **[silvadev13/ApkBuilder](https://github.com/silvadev13/ApkBuilder)** — conceito de build CLI lightweight
- **[Reginer/aosp-android-jar](https://github.com/Reginer/aosp-android-jar)** — android.jar pre-compilado

## Licenca

[MIT](LICENSE)

### Diagnóstico do SDK

`doctor` não considera a mera pasta do SDK ou de uma plataforma como presença de `android.jar`: exige um arquivo na plataforma ou o fallback de sistema. A ausência gera problema e código 1 pela CLI. Essa checagem constata presença; não valida o conteúdo do JAR nem comprova que a API selecionada pelo projeto está disponível. `doctor --aab` acrescenta a presença de Java, jarsigner e aapt2 aos requisitos padrão, retornando código 1 quando faltam. Não baixa ferramentas nem valida cache/versão do bundletool; esse gate continua no build. O próprio build AAB também exige Java/jarsigner e aapt2 executável (incluindo `bins.aapt2` configurado) antes de `--clean`, criação de saídas e resolução de dependências; aplica-se ao flag `--aab` e à configuração AAB. Essa checagem não baixa nada. A presença de executáveis não comprova versões compatíveis, APIs específicas do projeto ou build bem-sucedido.

A fixture `PYTHONPATH=. python tests/integration/verify_aab_preflight.py` exige Java/jarsigner reais disponíveis e isola o PATH em projetos temporários para retirar uma ferramenta por vez. Seus 18 cenários cobrem Java/jarsigner/aapt2 e R8 ausentes, SDK ausente em APK/AAB, JAR não ZIP, truncamento, CRC, classe de framework ausente, nomes com NUL e payload deflate oculto por tamanho/CRC falsificados. Confirma `android.sdk-path` e o JAR efetivamente selecionado, código 1 e preservação dos bytes anteriores com `--clean`. Não executa compilação nem substitui os builds reais; está conectada à CI. Os cenários de SDK ausente são específicos do host sem fallback de sistema.

`PYTHONPATH=. python tests/integration/verify_sdk_selection.py` cobre 18 erros de localização/tipo de `sdk-path` em APK/AAB, chamando a CLI de um diretório separado e exigindo preservação de YAML e artefatos. Para acrescentar builds reais com SDK relativo, forneça `--sdk /caminho/SDK --target-sdk 36 --aapt2 /caminho/aapt2 --d8 /caminho/d8 --apksigner /caminho/apksigner --dexdump /caminho/dexdump --bundletool-jar /caminho/bundletool-all-1.18.3.jar`. A fixture copia apenas `android.jar` e bundletool para um projeto temporário, usa ferramentas explícitas e exige APK/AAB, definição de `MainActivity` no DEX e assinaturas válidas, além do gate AAB público. Os 20 cenários passaram no host Linux/JDK 21/API 36/Build Tools 37.0.0. A CI executa com API 34/Build Tools 35.0.0 e reutiliza o bundletool do build anterior; execução remota não confirmada.

`PYTHONPATH=. python tests/integration/verify_resource_tools.py --sdk /caminho/SDK --target-sdk 36 --aapt /caminho/aapt --aapt2 /caminho/aapt2 --d8 /caminho/d8 --apksigner /caminho/apksigner --dexdump /caminho/dexdump` reproduz quatro falhas de ferramentas pela CLI real: caminho configurado ausente, arquivo sem execução, diretório e AAPT2 não configurado presente no PATH. Exige código 1, diagnóstico e preservação de YAML/artefatos com `--clean`; produz também APK AAPT1 real mesmo com AAPT2 não configurado disponível.

A fixture habilita density-splits e verifica base e seis splits, recursos, CRC, definição DEX, pacote/versionCode e certificado do conjunto. Recusa ABI+density com clean preservando os APKs; remover a definição HDPI sem fallback falha explicitamente sem publicar saídas novas. Acrescentar o recurso padrão recupera o build sem clean e remove o payload HDPI obsoleto. São 15 APKs verificados no fluxo completo.

O fluxo passou no host API 34/36 com Build Tools 37, por wheel externo e no Termux ARM64/Bionic/Android 16/JDK 21.0.12. Nativo: 62 testes focados, oito hashes das fontes conferidos, UID/contexto do aplicativo, grupos suplementares normais e CapEff=0. Suíte completa: 361 testes no host. Instalação/execução desse conjunto permanece não verificada. A CI conecta a mesma fixture à API 34/Build Tools 35; execução remota não confirmada.

Os mesmos 20 cenários e quatro testes de configuração passaram no Termux ARM64/Android 16/JDK 21.0.12, no UID/contexto do aplicativo e `CapEff=0`, com ferramentas nativas e JARs locais. Hashes de configuração, validador e fixture corresponderam às fontes do checkout. A repetição no host por wheel instalado fora do checkout também passou, com definição de classe DEX exigida pela linha `Class descriptor` do `dexdump`. Esses builds não incluem instalação ou execução dos APKs.

### Compilação mista sem processadores

Quando existem fontes Kotlin e nenhum processador foi declarado, a compilação Java aguarda Kotlin. O compilador Kotlin recebe as fontes Java para resolver símbolos, incluindo R/BuildConfig/ViewBinding; javac/ECJ compila Java depois contra as classes Kotlin. O caminho KAPT conserva seu processamento antes da compilação final. Este caso comum não comprova todas as combinações de APT Java, KSP e KAPT.

Reproduza a fixture real com `PYTHONPATH=. python tests/integration/verify_mixed_compile.py --android-jar /caminho/android.jar --aapt2 /caminho/aapt2 --d8 /caminho/d8 --apksigner /caminho/apksigner`, em JDK compatível. A fixture cria somente projetos temporários, exige APK/AAB assinados e verifica falhas após remover dependências de cada linguagem. Está conectada à CI; execução remota permanece não verificada.
