## [2.0.0] - 2026-08-07

### Fixed (tested on real device)
- `binding.py`: ViewBinding `inflate()` used `root` before assignment — fixed to use `R.layout.*`
- `manifest.py`: Manifest merge was permissions-only — now merges activities, services, receivers, providers, meta-data
- `dexer.py`: Auto-detect `dx` vs `d8`, adapt args for each (dx needs JAR input, different flags)
- `compiler.py`: Auto-downgrade Java compile target to 8 when using `dx` (dx 1.16 max is class version 52)
- `config.py`: Fallback to `dx` when `d8` not in PATH
- `doctor.py`: Show `dx` as valid dexer alternative
- `cli.py`: Wired incremental build cache, added `--aab` flag, `test`/`lint` commands
- `cli.py`: Fixed android.jar download URL (was `nicbarker/android-jar`, correct is `Reginer/aosp-android-jar`)
- `install.sh`: Fixed android.jar download URL

### Added
- `testing.py`: JUnit test runner
- `lint.py`: Android Lint checks (manifest, Java sources, layout depth)
- `aidl.py`: AIDL compiler support
- `aab.py`: App Bundle (AAB) output via bundletool

### Verified
- Full build pipeline tested: `aapt2 compile → aapt2 link → javac → dx → zip → apksigner`
- `termux-builder init myapp && termux-builder build .` → valid APK (v1+v2+v3 signatures)
- Build time: ~12-17s on aarch64 Termux

# Changelog

## [1.0.0] - 2026-08-06

### Adicionado
- Build pipeline completo: aapt2 → javac/kotlinc → d8 → APK → apksigner
- CLI: `build`, `init`, `clean`, `deps`, `doctor`, `setup`
- Resolver de dependencias Maven (Maven Central + Google Maven)
- Suporte a .aar (extracao automatica)
- Geracao de BuildConfig.java
- ViewBinding
- Manifest merging (permissoes de libs)
- R8/ProGuard minificacao
- Jetpack Compose (experimental, via -Xplugin)
- Debug keystore gerado automaticamente
- JNI/native libs (.so por ABI)
- Install via adb/termux-adb
- Auto-installer (install.sh) com download de android.jar
- Doctor (diagnostico do ambiente)
- Cache de dependencias e builds incrementais
- Scaffold de projeto (`termux-builder init`)
