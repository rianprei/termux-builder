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
