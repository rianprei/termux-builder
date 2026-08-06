# termux-builder

Android Studio no Termux — build APK **sem root, sem PC**. Java, Kotlin, ViewBinding, dependencias Maven, R8, BuildConfig, debug keystore, install via adb. Tudo em um comando.

## Instalacao

Instale [Termux](https://f-droid.org/packages/com.termux/) pelo F-Droid, depois:

```
curl -s https://raw.githubusercontent.com/rianprei/termux-builder/main/install.sh | bash
```

O installer:
- Instala todas as dependencias automaticamente (openjdk-17, aapt2, d8, apksigner, kotlin, python)
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
| `termux-builder build <dir> --install` | Compila e instala via adb |
| `termux-builder build <dir> --clean` | Build limpo (remove artifacts) |
| `termux-builder clean <dir>` | Remove .build/ |
| `termux-builder deps <dir>` | Baixa dependencias Maven |
| `termux-builder doctor` | Diagnostico do ambiente |
| `termux-builder setup --api 34` | Instala android.jar |

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
  view-binding: true      # gera classes de binding
  compose: false          # Jetpack Compose (experimental)
  r8: true                # minificacao R8 (release only)
  r8-rules: proguard-rules.pro

  keystore-path: my.keystore
  keystore-alias: mykey
  keystore-store-pass: password
  keystore-key-pass: password
```

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
│   │   ├── layout/          # XMLs de layout
│   │   ├── values/          # strings, styles, colors
│   │   └── drawable/        # Imagens e drawables
│   ├── assets/              # Assets raw
│   └── jniLibs/             # Native libs (.so)
├── .libs/                   # Bibliotecas (jar, aar extraido)
├── .cache/                  # Cache de deps e builds
└── .build/                  # Output (APK final aqui)
```

## Features

### Build Pipeline Completo

| Etapa | Ferramenta | Status |
|-------|-----------|--------|
| Compilar resources | aapt2 | ✅ |
| Gerar R.java | aapt2 link | ✅ |
| Gerar BuildConfig.java | termux-builder | ✅ |
| ViewBinding | termux-builder | ✅ |
| Merge manifests | termux-builder | ✅ |
| Compilar Java | javac | ✅ |
| Compilar Kotlin | kotlinc | ✅ |
| DEX (bytecode Android) | d8 | ✅ |
| Minificacao R8 | d8 --release | ✅ |
| Package APK | zip | ✅ |
| Assinar APK | apksigner | ✅ |
| Instalar via adb | adb/termux-adb | ✅ |

### Dependencias Maven

Declare no `project.yml` e o builder baixa automaticamente:

```yaml
dependencies:
  - "androidx.core:core:1.12.0"
  - "com.google.code.gson:gson:2.10.1"
```

- Resolve do Maven Central + Google Maven
- Resolve dependencias transitivas
- Suporta .jar e .aar
- Cache local em `.cache/deps/`

### Suporte a .aar

Bibliotecas .aar sao extraidas automaticamente:
- `classes.jar` → compilacao
- `res/` → aapt2
- `AndroidManifest.xml` → merge
- `jni/` → native libs

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
| Compose | ✅ | ❌ | ✅ (experimental) |
| JNI/native libs | ✅ | ✅ | ✅ |
| Roda no celular | ❌ | ✅ | ✅ |
| Sem root | ❌ | ✅ | ✅ |
| Auto-updater | ❌ | ❌ | ✅ |
| Self-contained | ❌ | ❌ | ✅ |

## Diagnostico

```bash
termux-builder doctor
```

Verifica: javac, kotlinc, aapt2, d8, apksigner, android.jar, Python deps, adb. Output verde/vermelho por item.

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
- **[nicbarker/android-jar](https://github.com/nicbarker/android-jar)** — android.jar pre-compilado

## Licenca

[MIT](LICENSE)
