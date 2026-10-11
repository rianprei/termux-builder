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

Para cada ferramenta sem caminho explícito em `bins`, o builder procura primeiro no `PATH` e depois em `sdk-path/build-tools/<versão>` (ou no SDK resolvido). Assim, ferramentas nativas do Termux no `PATH` têm prioridade sobre as cópias do SDK.

## Quick Start

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

### Jetpack Compose (Experimental)

```yaml
android:
  compose: true
```

Requer `compose-compiler.jar` em `.libs/` ou `.cache/`. O builder passa `-Xplugin` automaticamente pro kotlinc.

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

O download do bundletool usa a versão 1.18.3 e exige o SHA-256 fixado pelo projeto antes de publicar ou reutilizar o JAR do cache. Redirecionamentos são verificados antes de cada conexão: no máximo cinco, somente HTTPS em `github.com`, `release-assets.githubusercontent.com` ou `objects.githubusercontent.com`, sem credenciais, fragmentos ou portas alternativas. O conteúdo baixado tem limite de 64 MiB; falhas preservam o cache anterior e removem staging. Erros de rede não reproduzem URLs assinadas. Um executável `bundletool` instalado no PATH continua tendo precedência sobre o JAR do cache.

| Fluxo ou recurso | Estado | Escopo verificado / limite |
|------------------|--------|----------------------------|
| `project.yml` nativo, Java + AndroidX → APK assinado | VALIDATED | Build E2E em Linux x86_64, OpenJDK 25.0.4.1, Android API 36 e Build Tools 37.0.0 com `androidx.lifecycle:lifecycle-runtime:2.6.1`; manifesto e DEX presentes, `apksigner verify` aprovado; APK de 1.230.021 bytes. |
| `project.yml` nativo, Java + AndroidX → AAB | VALIDATED | Mesmo projeto e toolchain, módulo `base`; manifesto e DEX presentes, `jarsigner -verify` aprovado e `bundletool build-apks --mode=universal` gerou APK universal assinado; AAB de 1.225.589 bytes. |
| APK V4 com sidecar `.idsig` | VALIDATED | Scaffold local com `min-sdk: 30`; `apksigner verify -v4-signature-file` confirmou V4. |
| `bundletool build-apks --mode=universal` | VALIDATED | Executado sobre o AAB AndroidX acima; o APK universal passou `apksigner verify`. |
| Instalação e abertura no Android | VALIDATED | `termux-builder init <caminho-absoluto>` + `build --install` geraram e instalaram o APK pela CLI; `adb shell am start -W -n com.example.termuxbuildervalidation1011/.MainActivity` retornou `LaunchState: COLD` e `pidof` confirmou o processo em Android 16/API 36 `arm64-v8a`. O build foi feito no host Linux x86_64 e o pacote temporário foi removido. |
| Build Java → APK executado em Android/Termux/Bionic arm64 | VALIDATED | Fixture nativa em Android 16/API 36, Python 3.14.6, JDK 21.0.12, ferramentas Termux e android.jar oficial API 36: build frio e rebuild pela CLI; assinatura, CRC, DEX e identidade do pacote verificados. Processo no UID/contexto SELinux do Termux, sem capacidades Linux; acionamento automatizado via MagiskSU. Kotlin/JNI nativos e inicialização pelo terminal interativo ainda não verificados. |
| Build Java → AAB executado em Android/Termux/Bionic arm64 | VALIDATED | Mesmo ambiente nativo, JAR bundletool 1.18.3 com SHA-256 verificado: CLI build/rebuild, assinatura JAR, validacao bundletool, identidade do pacote, CRC, DEX e metadados do modulo base. Modulos dinamicos e APK derivado do AAB no dispositivo nao verificados. |
| JUnit 4 e JaCoCo 0.8.12 na JVM do Termux ARM64 | VALIDATED | Android 16/API 36, JDK 21.0.12, UID/contexto SELinux do Termux e capacidades Linux zeradas: assertion negativa, remoção de testes, invalidação do bytecode, cobertura independente por execução e falha explícita do relatório. JARs oficiais fornecidos em cache e hashes verificados; não comprova download no dispositivo nem instrumentação Android. |
| Bibliotecas JNI/native em APK e AAB | UNVERIFIED | Há descoberta de bibliotecas e código de empacotamento, mas nenhum build E2E com bibliotecas `.so` reais foi executado nesta rodada. |
| Kotlin 1.9.24 com KAPT → APK/AAB pela CLI | VALIDATED | Fixture real no host, JDK 21/API 36/Build Tools 37.0.0: projeto misto Java/Kotlin, classes e recurso gerados, bytecode direto, execução JVM, assinatura e rebuild sem clean. Não comprova compatibilidade com todos os processadores. |
| Kotlin 1.9.24/KSP 1.9.24-1.0.20 → APK/AAB pela CLI | VALIDATED | Provider real no host, mesma toolchain Android/JDK: geração Java/Kotlin, recurso, execução JVM, assinatura e rebuild sem clean. |
| Flavors e Compose | UNVERIFIED | Existem caminhos de implementação, mas não foram incluídos no build ponta a ponta desta matriz. Compose continua experimental. |
| Projetos Gradle/AGP, Kotlin DSL, Capacitor e plugins Gradle | NOT IMPLEMENTED | O pipeline consome `project.yml`; não há adaptador para esses modelos de projeto. |
| Maven: herança remota, propriedades, BOM imports, gestão de versão/escopo/exclusão, scopes compile/runtime, optional, mediação nearest, tipos jar/aar, exclusões por caminho e cache com hash SHA-256 | PARTIAL | Suíte unitária e build real de APK/AAB com `androidx.lifecycle:lifecycle-runtime:2.6.1`, incluindo DEX de bibliotecas. Parent `relativePath`, profiles, classifiers, tipos além de jar/aar e outras regras Maven/Gradle não estão implementados. |
| Merge nativo de manifests, placeholders e diretivas selecionadas | PARTIAL | Testes unitários cobrem prioridade, conflitos, placeholders, `tools:*` suportado e `uses-sdk`; o pipeline também foi exercitado com AAR real. Não há equivalência total com AGP. |
| Módulos de feature/dynamic delivery em AAB | NOT IMPLEMENTED | O AAB validado contém somente o módulo `base`. |

`VALIDATED` descreve apenas as combinações e comandos listados acima. O teste em Linux não comprova execução nativa em Termux/Bionic; a assinatura de debug comprova integridade, não confiança ou identidade de publicação.

A assinatura AAB usa o algoritmo escolhido pelo `jarsigner` para o tipo e tamanho da chave, mantendo SHA-256 nos digests do JAR. Chaves RSA e EC foram verificadas com ferramentas reais no host e no Termux. `bundletool validate` também aceita bundles sem assinatura: o pipeline verifica a assinatura JAR separadamente; validação estrutural não comprova assinatura nem confiança no certificado.

### Testes JUnit do projeto

`termux-builder test <dir>` compila as fontes encontradas e executa JUnit 4 na JVM, usando as classes do app já compiladas e as dependências locais. O diretório gerado `.build/test-classes` (ou o equivalente em `build-path`) é removido antes de cada execução, inclusive quando todas as fontes foram excluídas; symlinks ou arquivos nesse destino são recusados. Isso impede executar classes de testes removidos. Sem fontes, a CLI informa explicitamente que não executou testes. Embora descubra também `src/androidTest`, esse comando não fornece um runner de instrumentação no dispositivo.

A fixture `tests/integration/verify_testing.py` exige JDK, JUnit 4.13.2, Hamcrest Core 1.3 e um SDK local. Ela executa a CLI real, exige uma falha de assertion JUnit, remove a fonte que falhava e exige sucesso com exatamente um teste, depois remove todas as fontes e verifica a invalidação do bytecode. Reproduza com `PYTHONPATH=. python tests/integration/verify_testing.py --android-jar /caminho/SDK/platforms/android-36/android.jar --junit-jar /caminho/junit-4.13.2.jar --hamcrest-jar /caminho/hamcrest-core-1.3.jar`. O fluxo passou no host Linux com JDK 21 e JDK 25.0.4.1; a CI configura JDK 17 e baixa essas dependências do Maven Central. A fixture também passou no Termux ARM64, Android 16/API 36 e JDK 21.0.12, sob o UID/contexto SELinux do aplicativo e sem capacidades Linux, acionada por automação via MagiskSU. Execução remota da CI e acionamento pelo terminal interativo permanecem não verificados. A recusa de `test` concorrente pelo lock foi verificada no Termux.

### Segurança de `build-path` e limpeza

`build-path` exige uma string não vazia sem NUL. A configuração recusa a raiz do projeto e seus ancestrais, sobreposição com `src`, fontes/recursos/assets/JNI/bibliotecas, SDK e cache configurados, e saídas que contenham configuração, manifesto, chave de assinatura, android.jar, regras R8 ou processadores declarados. Os caminhos reais são comparados, incluindo aliases symlink. Isso impede apagar entradas conhecidas e misturar saídas com diretórios de descoberta de fontes.

`clean` e `build --clean` revalidam os caminhos antes de excluir arquivos. A limpeza recusa um symlink na raiz da saída, inclusive com barra final ou `/.`, e caminhos cujo `..` através de symlink tenha significado diferente após normalização. Diretórios de saída dedicados fora do projeto continuam permitidos. Configurações sobrepostas precisam mover a saída, as entradas ou o cache para diretórios separados; nenhum caminho é alterado automaticamente.

Essas verificações protegem as entradas declaradas e os diretórios convencionais; não identificam arquivos pessoais desconhecidos colocados numa saída nem isolam o projeto de alterações externas simultâneas. `clean` continua removendo todo o diretório de saída dedicado. Testes temporários verificam preservação de fontes, configuração, dependências, chaves, cache e aliases; a fixture Termux também recusa saídas `.`/`src` e verifica build com `--clean`.

### Cobertura JaCoCo

O bootstrap JaCoCo 0.8.12 verifica SHA-256 fixado do agente e CLI antes de executar ou reutilizar seus JARs. O download exige HTTPS no Maven Central (`repo.maven.apache.org`), resposta 200 direta sem redirects e no máximo 8 MiB; usa staging exclusivo e publica somente após verificação. Cache ausente precisa de rede; cache válido funciona offline. A raiz do cache e seu diretório `deps` não podem ser symlinks, inclusive com barra final; paths ambíguos com symlink/`..` são recusados. Cache corrompido, symlink ou arquivo especial gera erro sem download ou reparo automático: remova somente o JAR indicado e obtenha novamente os bytes oficiais. Erros de rede não reproduzem detalhes da exceção que possam conter credenciais de proxy.

Origem dos bytes pinados: [agente 0.8.12](https://repo.maven.apache.org/maven2/org/jacoco/org.jacoco.agent/0.8.12/org.jacoco.agent-0.8.12-runtime.jar) e [CLI 0.8.12](https://repo.maven.apache.org/maven2/org/jacoco/org.jacoco.cli/0.8.12/org.jacoco.cli-0.8.12-nodeps.jar). Os hashes estão em `builder/testing.py`. Ambos foram baixados pelo bootstrap real e reutilizados com rede desabilitada por instrumentação de teste no host. O pin identifica os bytes aprovados pelo projeto; não verifica uma assinatura criptográfica do fornecedor. Interrupções tratáveis removem staging; limpeza de arquivos órfãos após SIGKILL não foi implementada.

`test --coverage` substitui os dados de execução em `jacoco.exec` a cada execução (`append=false`); não acumula cobertura de testes anteriores. Um destino existente precisa ser arquivo regular com um único hard link; symlinks, diretórios e FIFOs são recusados antes da compilação. Se o gerador JaCoCo falhar, a CLI retorna código 1 e não anuncia um relatório bem-sucedido. Arquivos de relatórios antigos podem permanecer: só trate o relatório como resultado atual após sucesso do comando.

A fixture JUnit aceita `--jacoco-agent /caminho/org.jacoco.agent-0.8.12-runtime.jar --jacoco-cli /caminho/org.jacoco.cli-0.8.12-nodeps.jar`. Com as ferramentas reais, executa separadamente os dois ramos da mesma classe, exige um ramo coberto e um não coberto em cada relatório XML, e exige erro quando um bytecode truncado impede gerar o relatório. Esse fluxo passou no host com JDK 21 e no Termux ARM64 com Android 16/API 36 e JDK 21.0.12, sob o UID/contexto SELinux do aplicativo e sem capacidades Linux. Os JARs oficiais foram fornecidos em cache e verificados pelos hashes de produção; download pela rede no dispositivo permanece não verificado. O fluxo está conectado à CI, cuja execução remota permanece não verificada. A verificação de caminhos não isola o projeto de alterações simultâneas por processos externos.

### Concorrência no projeto

A CLI protege `build` (APK/AAB, incluindo `--clean`), `test`, `clean` e `deps` com um `flock` exclusivo no diretório do projeto. Uma operação concorrente no mesmo diretório é recusada imediatamente com código 1 e orientação para tentar novamente após a primeira terminar. Caminhos symlink para o mesmo diretório compartilham o lock; projetos diferentes continuam independentes. Não há arquivo de lock a apagar: o kernel libera o descritor quando o processo termina, inclusive após SIGKILL. Testes com processo independente verificam a recusa antes de alterações e a recuperação após interrupção.

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

Recursos KAPT de `CLASS_OUTPUT` e KSP de `.build/ksp/resources` entram no APK e em `root/` do módulo base AAB. Caminhos reservados, metadados de assinatura, symlinks, arquivos especiais e conflitos são recusados. Erros de leitura encerram o empacotamento e preservam o APK anterior; `.class` segue somente pelo DEX. Os testes comparam bytes do APK unsigned e do ZIP do módulo base após alterar apenas os mtimes de recursos e DEX, mantendo o APK de recursos e demais entradas fixos. Isso não comprova reprodutibilidade do build completo ou das assinaturas.

As fixtures `tests/integration/verify_kapt.py` e `verify_ksp.py` usam processadores e compiladores reais para gerar Java/Kotlin e executar as classes na JVM. Com SDK, executam D8/aapt2 e builds pela CLI, verificam as definições de classe com `dexdump`, recursos, CRC e assinatura de APK/AAB. O AAB também passa pela validação do bundletool no pipeline público. Ambas desabilitam o processador em `project.yml` e reconstroem sem `clean`, verificando a remoção de classes/recursos e a nova assinatura. KAPT também cobre `Filer.createClassFile` e um projeto misto em que Kotlin chama Java, que usa classes geradas em Java/Kotlin e bytecode direto. Uma anotação na fonte Java dispara a geração condicional de outra classe e recurso; a fixture exige ambos nos artefatos e verifica sua remoção no rebuild, inclusive a remoção da classe Java original.

Esses fluxos passaram no host com JDK 21, Android 36 e Build Tools 37.0.0. Reproduza com `PYTHONPATH=. python tests/integration/verify_kapt.py --android-jar /caminho/SDK/platforms/android-36/android.jar --d8 /caminho/d8 --dexdump /caminho/dexdump --aapt2 /caminho/aapt2 --apksigner /caminho/apksigner`, com JDK compatível e `keytool`/`jarsigner` no PATH. Para KSP, troque o nome do script por `verify_ksp.py`. Sem os argumentos de SDK, as fixtures verificam apenas compilação/execução JVM. A CI configura JDK 17/Android 34/Build Tools 35.0.0; a execução remota ainda não foi confirmada. O certificado temporário é autoassinado: verificar a assinatura não comprova confiança no certificado. Instalação desses artefatos, build nativo desses fluxos KAPT/KSP no Termux, execução conjunta de KAPT/KSP e compatibilidade com todos os processadores permanecem não verificados.

A sondagem `kotlinc -version` usada pelo KAPT exige código de saída zero e tem limite de 30 segundos. Falhas ao iniciar o executável ou detectar a versão encerram a preparação com orientação corretiva, sem copiar a saída bruta do processo para o erro.

O bootstrap do compilador Kotlin K1 usa staging exclusivo, rejeita caminhos ZIP inseguros e verifica os JARs antes de publicar ou reutilizar o cache. Caches inválidos geram erro; remova somente `.cache/kapt/kotlinc-1.9.24` (ou o equivalente no cache configurado) e tente novamente. ZIP64 e arquivos multipartes são recusados explicitamente. A distribuição oficial Kotlin 1.9.24 compilou uma classe real com JDK 21 neste host; com JDK 25, falhou em `JavaVersion.parse`. A validação de CRC e estrutura não comprova autenticidade nem detecta substituições que preservem um ZIP válido. O plugin KAPT também valida versão, destino, limites, CRC e classe registradora antes da publicação e da reutilização offline; o JAR oficial 1.9.24 passou nessas verificações no host. Isso não comprova autenticidade nem compatibilidade com todos os processadores KAPT. O bootstrap KSP também valida seu compilador embeddable, API e plugin, com staging exclusivo e rejeição de caches corrompidos. Os artefatos oficiais da combinação Kotlin 1.9.24/KSP 1.9.24-1.0.20 passaram nas verificações, e o compilador embeddable iniciou com JDK 21 no host. Downloads Maven de KAPT/KSP exigem resposta HTTP 200 direta e recusam redirecionamentos. Para reproduzir o APK KSP real, use `PYTHONPATH=. python tests/integration/verify_ksp.py --android-jar /caminho/android.jar --d8 /caminho/d8 --dexdump /caminho/dexdump --aapt2 /caminho/aapt2 --apksigner /caminho/apksigner`, com JDK compatível e `keytool` no PATH. A CI configura esse fluxo com JDK 17/Android 34/Build Tools 35.0.0; a execução remota ainda não foi confirmada. A fixture KSP valida um provider local real e a geração em um diretório de recursos separado das fontes; o empacotamento desses recursos tem testes para APK e módulo base AAB, incluindo entradas inseguras. A fixture mas não comprova compatibilidade com todos os processadores, com Kotlin 2.x ou execução no Termux. A distribuição K1 segue no máximo cinco redirecionamentos, somente por HTTPS entre `github.com` e `release-assets.githubusercontent.com`, sem credenciais na URL ou portas alternativas. O download oficial passou com essa política; erros de rede não propagam URLs assinadas na causa da exceção.

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
