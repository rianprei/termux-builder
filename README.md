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

Declare coordenadas `group:artifact:versao` em `dependencies`. O resolvedor baixa somente de Maven Central e Google Maven por HTTPS, recusa redirecionamentos e interrompe o build quando uma coordenada ou artefato nao pode ser obtido. Downloads usam arquivo temporario exclusivo e so passam ao cache quando concluidos. O digest `.sha1` publicado junto do artefato e conferido quando disponivel; se o repositorio responde 404, o builder avisa que a verificacao foi pulada, mas uma falha de rede encerra a resolucao. O cache guarda SHA-256, coordenada e URL de origem, e confere os hashes do artefato e dos arquivos extraidos antes de reutiliza-los.

O resolvedor le dependencias diretas e herdadas, expande propriedades locais e herdadas e valores basicos de `project.*`, ignora dependencias `test`, `provided` e `optional`, e inclui `compile` e `runtime`. Entradas locais de `dependencyManagement` e BOMs importados podem fornecer versao, escopo e exclusoes. Exclusoes sao aplicadas por caminho e preservadas no cache; conflitos usam a versao no caminho mais curto, com desempate pela ordem de `dependencies` e depois pela ordem declarada no POM. Artefatos de grupos diferentes usam diretorios de cache separados. JARs Maven antigos reconhecidos no cache deixam de entrar no classpath quando uma versao diferente foi selecionada, sem remover esses arquivos do projeto.

Heranca resolve o POM pai remoto pelas coordenadas Maven; `relativePath` local, profiles, ranges abertos, escopos `system`/`import` fora de BOMs, classifiers, packaging alem de `jar`/`aar` e tipos nao suportados falham explicitamente. Dependencias com type `jar` e `aar` selecionam a extensao declarada; dependencias sem type usam o `packaging` do POM. A notacao de versao exata `[1.2.3]` e aceita. A implementacao Maven continua parcial e nao equivale ao Maven/Gradle; confira a matriz de compatibilidade antes de depender dessas construcoes. SHA-1 remoto detecta corrupcao de transferencia quando publicado; SHA-256 local detecta alteracoes posteriores no cache. Nenhum deles comprova autenticidade do artefato; sem sidecar SHA-1 o builder avisa que a verificacao de transferencia foi omitida.

### Merge de Manifest

O builder expande `android.manifest-placeholders` em atributos XML antes de mesclar manifestos. `${applicationId}` usa o ID final do app, incluindo o sufixo da flavor. Uma flavor pode sobrescrever valores em `flavors.<nome>.manifest-placeholders`.

O manifesto do app tem prioridade sobre bibliotecas. Bibliotecas diretas seguem a ordem de `dependencies`; bibliotecas sem correspondencia nessa lista seguem ordem lexica por caminho. A mesclagem combina atributos sem conflito, interrompe builds em conflitos e aceita `tools:replace`, `tools:remove`, `tools:strict`, `tools:selector` e `tools:node` com `merge`, `mergeOnlyAttributes`, `replace`, `remove`, `removeAll` ou `strict`. Tambem verifica incompatibilidade numerica de `minSdkVersion`, com suporte a `tools:overrideLibrary`, e os valores de SDK em `project.yml` prevalecem sobre os do XML.

Esse caminho nativo ainda nao implementa todas as regras do Manifest Merger do Android Gradle Plugin. Sobreposicoes de manifestos de variantes, injecao de permissoes implicitas por `targetSdkVersion` e precedencia Maven transitiva equivalente ao Gradle permanecem fora da cobertura. Diretivas `tools:*` desconhecidas falham explicitamente. Consulte [Manage manifest files](https://developer.android.com/build/manage-manifests) para as regras completas do AGP.

## Estrutura do Projeto

```
myapp/
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

| Fluxo ou recurso | Estado | Escopo verificado / limite |
|------------------|--------|----------------------------|
| `project.yml` nativo, Java + AndroidX → APK assinado | VALIDATED | Build local em Linux x86_64 com plataforma Android API 34, Build Tools 37.0.0 e `androidx.lifecycle:lifecycle-runtime:2.6.1`; `apksigner verify` aprovado e 15 entradas DEX no APK. |
| `project.yml` nativo, Java + AndroidX → AAB | VALIDATED | Build local de módulo base com 15 entradas DEX; `jarsigner` e `bundletool validate` aprovados. |
| APK V4 com sidecar `.idsig` | VALIDATED | Scaffold local com `min-sdk: 30`; `apksigner verify -v4-signature-file` confirmou V4. |
| `bundletool build-apks --mode=universal` | VALIDATED | Executado sobre o AAB AndroidX acima; o APK universal passou `apksigner verify`. |
| Instalação e abertura no Android | UNVERIFIED | Não instalamos nesta rodada os artefatos gerados pelo código atual; o E2E foi executado em Linux x86_64. |
| Build executado dentro do Termux/Bionic arm64 | UNVERIFIED | O build desta rodada foi executado em Linux x86_64; compatibilidade do builder no sandbox Termux não foi exercitada. |
| Bibliotecas JNI/native em APK e AAB | UNVERIFIED | Há descoberta de bibliotecas e código de empacotamento, mas nenhum build E2E com bibliotecas `.so` reais foi executado nesta rodada. |
| Kotlin, flavors e Compose | UNVERIFIED | Existem caminhos de implementação, mas não foram incluídos no build ponta a ponta desta matriz. Compose continua experimental. |
| Projetos Gradle/AGP, Kotlin DSL, Capacitor e plugins Gradle | NOT IMPLEMENTED | O pipeline consome `project.yml`; não há adaptador para esses modelos de projeto. |
| Maven: herança remota, propriedades, BOM imports, gestão de versão/escopo/exclusão, scopes compile/runtime, optional, mediação nearest, tipos jar/aar, exclusões por caminho e cache com hash SHA-256 | PARTIAL | Suíte unitária e build real de APK/AAB com `androidx.lifecycle:lifecycle-runtime:2.6.1`, incluindo DEX de bibliotecas. Parent `relativePath`, profiles, classifiers, tipos além de jar/aar e outras regras Maven/Gradle não estão implementados. |
| Merge nativo de manifests, placeholders e diretivas selecionadas | PARTIAL | Testes unitários cobrem prioridade, conflitos, placeholders, `tools:*` suportado e `uses-sdk`; o pipeline também foi exercitado com AAR real. Não há equivalência total com AGP. |
| Módulos de feature/dynamic delivery em AAB | NOT IMPLEMENTED | O AAB validado contém somente o módulo `base`. |

`VALIDATED` descreve apenas as combinações e comandos listados acima. O teste em Linux não comprova execução nativa em Termux/Bionic; a assinatura de debug comprova integridade, não confiança ou identidade de publicação.

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
