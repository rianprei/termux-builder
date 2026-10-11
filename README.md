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
| `project.yml` nativo, Java → APK assinado | VALIDATED | Build local em Linux x86_64 com Android API 34 e Build Tools 35.0.0; `apksigner verify` aprovado. |
| `project.yml` nativo, Java → AAB | VALIDATED | Bundle de módulo base; `jarsigner`, `bundletool validate` e geração de APK universal aprovados. |
| Instalação e abertura no Android | VALIDATED | APK direto e APK universal do AAB instalados e abertos em Android 16/API 36, arm64. Assinatura de debug; não é validação de publicação. |
| Build executado dentro do Termux/Bionic arm64 | UNVERIFIED | A validação no dispositivo cobriu instalação e execução do app, não a execução do builder dentro do sandbox do Termux. |
| Kotlin, flavors e Compose | UNVERIFIED | Existem caminhos de implementação, mas não foram incluídos no build ponta a ponta desta matriz. Compose continua experimental. |
| Projetos Gradle/AGP, Kotlin DSL, Capacitor e plugins Gradle | NOT IMPLEMENTED | O pipeline consome `project.yml`; não há adaptador para esses modelos de projeto. |
| Herança Maven, BOM, `dependencyManagement` e exclusões avançadas | NOT IMPLEMENTED | O resolvedor atual não implementa toda a semântica do Maven. |
| Placeholders e diretivas `tools:*` no merge de manifests | NOT IMPLEMENTED | O merge atual não equivale ao merger do AGP. |
| Módulos de feature/dynamic delivery em AAB | NOT IMPLEMENTED | O AAB validado contém somente o módulo `base`. |

`VALIDATED` descreve apenas as combinações e comandos listados acima. O teste em Linux não comprova execução nativa em Termux/Bionic; a assinatura de debug comprova integridade, não confiança ou identidade de publicação.

## Comparacao

| Feature | Android Studio | ApkBuilder | **termux-builder** |
|---------|---------------|------------|-------------------|
| Build APK | ✅ | ✅ | ✅ |
| Java | ✅ | ✅ | ✅ |
| Kotlin | ✅ | ✅ | ✅ |
| ViewBinding | ✅ | ✅ | ✅ |
| BuildConfig | ✅ | ❌ | ✅ |
| R8/ProGuard | ✅ | ❌ | ✅ |
| Dependencias Maven | ✅ | ❌ | ✅ |
| Suporte .aar | ✅ | ❌ | ✅ |
| Manifest merge | ✅ | ❌ | ✅ |
| Debug keystore auto | ✅ | ❌ | ✅ |
| Auto-installer | ❌ | ❌ | ✅ |
| Doctor/diagnostico | ❌ | ❌ | ✅ |
| Scaffolding (init) | ✅ | ❌ | ✅ |
| Install via adb | ✅ | ❌ | ✅ |
| Testes JUnit | ✅ | ❌ | ✅ |
| Lint | ✅ | ❌ | ✅ |
| Decompile/Recompile | ❌ | ❌ | ✅ |
| Compose | ✅ | ❌ | ✅ (experimental) |
| JNI/native libs | ✅ | ✅ | ✅ |
| Roda no celular | ❌ | ✅ | ✅ |
| Sem root | ❌ | ✅ | ✅ |
| Self-contained | ❌ | ❌ | ✅ |

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
