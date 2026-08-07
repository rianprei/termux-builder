## [3.4.0] - 2026-08-07

### Fixed
- `compiler.py`: ecj invocation used duplicate `-cp` flag — corrected ecj args to use `-classpath`
- `setup.py`: version was stale at "1.0.0" — corrected to "3.4.0"
- `install.sh`: used `pip install -e .` (editable) — changed to `pip install .` for stable installs
- `README.md`: credit URL pointed to wrong repo (`nicbarker/android-jar`) — corrected to `Reginer/aosp-android-jar`
- `README.md`: command table was missing `test`, `lint`, `decompile`, `recompile`

## [3.3.0] - 2026-08-07

### Added
- `decompile.py`: APK decompile/recompile via native `apktool` 3.0.3
- `cli.py`: `decompile` and `recompile` subcommands

### Fixed
- `lint.py`: `_check_layout_depth` return value was ignored — fixed to accumulate issues
- `packager.py`: dex numbering collisions with multi-dex — added dedup set

## [2.0.0] - 2026-08-07

### Fixed (tested on real device)
- `binding.py`: ViewBinding `inflate()` used `root` before assignment — fixed
- `manifest.py`: merge was permissions-only — now merges activities, services, receivers, providers, meta-data
- `dexer.py`: auto-detect `dx` vs `d8`, adapt args for each
- `compiler.py`: auto-downgrade Java compile target to 8 when using dx
- `config.py`: fallback to `dx` when `d8` not in PATH
- `cli.py`: fixed android.jar download URL (`nicbarker/android-jar` → `Reginer/aosp-android-jar`)
- `install.sh`: fixed android.jar download URL
- `cli.py`: added `test`, `lint`, `decompile`, `recompile` subcommands; top-level error handler

### Added
- `testing.py`: JUnit 4 test runner
- `lint.py`: Android Lint checks (manifest, Java sources, layout depth)
- `aidl.py`: AIDL compiler support

### Verified
- Full build pipeline tested: `aapt2 compile → aapt2 link → javac → d8 → zip → apksigner`
- `termux-builder init myapp && termux-builder build .` → valid APK (v1+v2+v3 signatures)
- Build time: ~12-17s on aarch64 Termux

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
- Scaffold de projeto (`termux-builder init`)
