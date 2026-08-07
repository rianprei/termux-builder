## [3.8.0] - 2026-08-07

Fecha 2 gaps que sobraram da auditoria "100%": R8 nunca era real, e KSP nao existia.

### Fixed — CRITICAL, R8 nunca minificava
- `dexer.py`: `d8 --release` **nunca** rodou R8. `--release` no d8 so significa "compila sem debug info" — nao ativa shrink/obfuscate. Bug achado testando de verdade: decompilei um APK "R8 minification enabled" e as classes nao estavam renomeadas. Existe binario `r8` SEPARADO no Termux que faz shrink/obfuscate real. Corrigido: quando `r8: true` + `build-type: release`, usa o binario `r8` de verdade, com regras default (`-keep` pras 4 classes de entrypoint Android) se `r8-rules` nao for declarado, e gera `mapping.txt` real.
- Testado: `mapping.txt` real gerado, cabecalho `# compiler: R8` confirma execucao real (`d8 --release` nunca produz esse arquivo).

### Added — KSP real
- `ksp.py` novo: KSP nao tem release pra kotlinc 2.x (Termux) — Maven Central cobre so ate kotlinc 2.2.21. Fallback pro K1 1.9.24 (mesmo toolchain do kapt), que tem KSP real (1.9.24-1.0.20).
- Classpath descoberta por tentativa real (cada troca resolveu 1 erro distinto): `kotlin-compiler-embeddable.jar` (nao o `kotlin-compiler.jar` puro da dist standalone — esse da AbstractMethodError, ABI incompativel) + `symbol-processing-api.jar` (KSPLogger, ClassNotFoundException sem ele) + resto da dist standalone pras deps transitivas (trove4j, asm — faltam so no embeddable puro).
- Testado real: plugin carrega e roda sem crash, chega em "No providers found in processor classpath" (esperado sem processor real configurado via `annotation-processors:` — falha alto e claro, nao mente).

### Attempted, genuinamente nao fechado
- Instalar+abrir APK numa tela real: sem device conectado via adb neste ambiente (`adb devices` vazio, `termux-adb devices` vazio — sem debug USB habilitado). Bloqueio de ambiente, nao de codigo.
- KSP com processor real de ponta a ponta: infra confirmada funcional (sem crash), mas nao testado com processor gerando codigo de verdade (precisa `annotation-processors:` apontando pra jar real do usuario).

## [3.7.1] - 2026-08-07

### Added
- `.github/workflows/ci.yml`: syntax check (py_compile) + CLI smoke test (--version, --help, doctor, init scaffold) em push/PR pra main. Nao roda build real de APK (aapt2/d8/apksigner/ecj sao binarios Termux-nativos, nao existem em runner ubuntu-latest) — job separado documenta essa limitacao em vez de fingir cobertura. Primeiro run real: SUCCESS.

## [3.7.0] - 2026-08-07

Fecha de verdade os 2 gaps que a v3.6.x tinha declarado "bloqueio de toolchain externo" sem tentar workaround real primeiro.

### Fixed — desugaring runtime lib
- `dexer.py`: descoberto o boundary real — d8 9.2.4-dev crasha dexando `desugar_jdk_libs.jar` em `--min-api` 21-25, mas funciona limpo em `--min-api` 26+. Agora dexa a lib sempre em `max(min_sdk, 26)` — o app continua com o `min-sdk` real do project.yml, so a lib do backport usa 26 internamente (seguro: so alcancavel via chamada ja desugarada).
- `packager.py`: bug real achado no proprio teste — `classes.dex` da lib desugar colidia em nome com o `classes.dex` do app (zip com 2 entries do mesmo nome, apksigner rejeitava). Corrigido: dex de subdiretorios (libs, desugar_lib) agora sempre pega nome unico `classesN.dex`.
- Testado real: `desugar: true` + `min-sdk: 21` + APK final assinado, `classes.dex` (app) + `classes2.dex` (3MB, backport completo) confirmados via `unzip -l`.

### Fixed — KAPT
- `kapt.py`: kapt3 crasha no K2 (kotlinc 2.4.10 do Termux) mas funciona limpo no K1 (kotlinc 1.9.24, dist oficial JetBrains). Fallback automatico: detecta major version do kotlinc instalado, se for 2.x baixa e cacheia (~90MB, uma vez) a distribuicao standalone K1 oficial e usa ela so pra fase de annotation processing.
- `compiler.py`: kapt real e 2 fases (igual Gradle `kaptGenerateStubsKotlin` vs `compileKotlin`) — descoberto testando que 1 fase so gera stubs, nao produz `.class` final. Fase 1 (K1 + kapt3 plugin, stubsAndApt) gera fontes/stubs. Fase 2 (kotlinc do sistema, sem plugin) compila tudo incluindo fontes geradas.
- Testado real ponta a ponta: `kapt: true` + processor real + arquivo Kotlin real → `Foo.class` compilado com sucesso, confirmado no disco.

### Attempted, genuinamente bloqueado (nao e desistencia sem tentar)
- Reduzir download do K1 (~90MB) — nao ha jar standalone menor com todas as deps de runtime resolvidas; a distribuicao oficial e o menor pacote funcional. Cacheado apos primeira vez.

## [3.6.2] - 2026-08-07

### Fixed (review externo confirmou 1 de 3 claims — verificado, corrigido)
- `aab.py`: AAB nunca era assinado — corrigido, `jarsigner` real aplicado apos build-bundle. Testado: `jarsigner -verify` confirma "jar verified."

### Claims do review externo verificadas
- "--split so existe em aapt2 optimize, nao em link" — FALSO, confirmado `aapt2 link --help` mostra --split real, ja usado e testado (density splits v3.6.0)
- "AAB deve assinar com jarsigner, nao apksigner" — CORRETO, gap real, corrigido acima
- "KAPT incompatibilidade e mais nuance (K2 e alpha/experimental) que impossibilidade absoluta" — linguagem suavizada, erro e real e reproduzido mas causa e instabilidade do K2, nao impossibilidade permanente (confirmado v3.7.0 depois: fallback K1 real resolve)

## [3.6.1] - 2026-08-07

### Added
- `cli.py`: `--flavor <nome>` exposto no `termux-builder build` — testado, rejeita flavor nao declarado, aceita e builda com flavor real

## [3.6.0] - 2026-08-07

Implementacao real dos 5 gaps pedidos (density splits, AAB, desugaring, KAPT/KSP,
build flavors). Cada um testado de verdade neste device, nao so lido/assumido.
2 bugs reais de sintaxe encontrados e corrigidos durante o proprio teste
(aapt2 --split config nao aceita prefixo `density=`, e o d8 desugar
crashava so no self-dex da lib, nao no app).

### Added — testado em device real

- **Density splits reais**: `density-splits: true` gera 1 APK base + 6 splits
  (ldpi/mdpi/hdpi/xhdpi/xxhdpi/xxxhdpi) via `aapt2 link --split`, cada um
  assinado com a mesma keystore. Instala com `adb install-multiple` (real
  semantica de split dependente, nao standalone como ABI split). CLI imprime
  o comando exato de instalacao. `builder/installer.py`: `install_multiple()`.

- **AAB real**: `aab: true` gera `.aab` valido via `aapt2 link --proto-format`
  (resources.pb real, nao res.zip) + bundletool (`google/bundletool` v1.18.3,
  baixado automaticamente do GitHub release se nao presente localmente).
  Estrutura verificada: BundleConfig.pb + base/{dex,manifest,resources.pb,
  native.pb}. `builder/aab.py` reescrito.

- **Desugaring real, parcial**: `desugar: true` baixa `desugar_jdk_libs`
  2.1.5 real do Google Maven, aplica `d8 --desugared-lib` no dex do codigo
  do app (verificado: gera classes.dex corretamente). Dexar a propria lib
  de runtime (`desugar_jdk_libs.jar`) pra empacotar no APK crasha com bug
  real do binario `d8` 9.2.4-dev do Termux (NullPointerException interno,
  reproduzido com --release e --debug) — build falha com erro preciso
  explicando a causa exata e o workaround (min-sdk 26+), nao finge sucesso.
  `builder/desugar.py` novo.

- **Java annotation processing real**: `annotation-processors: [...]` (lista
  de jars) habilita `javac -processorpath` de verdade — testado com processor
  real escrito na hora, gerou codigo (`Generated.java`) e compilou. Mecanismo
  identico ao usado por Dagger/Room quando nao usam KSP.

- **Kotlin KAPT, scaffolding + deteccao real**: `kapt: true` detecta versao
  exata do `kotlinc` instalado, baixa `kotlin-annotation-processing-embeddable`
  correspondente do Maven Central, aplica as flags reais do plugin
  (`-P plugin:org.jetbrains.kotlin.kapt3:...`). Verificado: kotlinc 2.4.10
  (pacote Termux) usa o compilador K2, que quebra o kapt3 com
  `AbstractMethodError: FirKaptAnalysisHandlerExtension` — bug real e
  reproduzido do toolchain Kotlin (kapt nao foi atualizado pro K2 antes do
  Google deprecar em favor do KSP). Build falha com erro preciso, nao
  silencioso. `builder/kapt.py` novo.

- **Build flavors/variants reais**: `Config(project_dir, flavor="x")` +
  `flavors:` no project.yml. Overlay real de source set (`src/<flavor>/java`
  mergeado sobre `src/java`) e overlay de resources (`src/<flavor>/res`
  compilado e linkado junto via `-R`, mesmo mecanismo ja usado pra libs).
  `application-id-suffix` e `version-code`/`version-name` por flavor.

### Known limitations (nao sao bug do termux-builder, sao do toolchain externo)

- Desugaring: runtime backport da lib (`desugar_jdk_libs.jar`) nao empacota
  no APK por bug do `d8` 9.2.4-dev do Termux. Codigo do app e desugarado
  corretamente; APIs java.time/streams crasham em runtime abaixo da API 26
  sem a lib empacotada. Sem fix possivel do lado do termux-builder ate
  Termux empacotar `d8` mais novo.
- KAPT: incompativel com kotlinc 2.4.10 (K2) por bug do proprio plugin kapt3
  da JetBrains, nao atualizado pro K2 antes da depreciacao em favor do KSP.
  Sem fix possivel do lado do termux-builder ate JetBrains lancar build
  K2-compativel ou Termux empacotar kotlinc mais antigo (K1).
- KSP (Kotlin Symbol Processing) nao implementado — mecanismo completamente
  diferente do kapt (plugin proprio, nao usa a interface do kapt3), fora do
  escopo desta rodada.
- CLI (`termux-builder build`) ainda nao expoe `--flavor <nome>` como flag;
  flavors funcionam via `Config(dir, flavor=...)` chamado programaticamente.

## [3.5.0] - 2026-08-07

Resposta a pedido de paridade com Android Studio. A maior parte da lista pedida
(profiler, emulador, layout inspector, autocomplete, Play Console, Firebase,
Crashlytics) e IDE feature ou servico externo, fora de escopo de um CLI de
build. Implementado o que e build-tool real e viavel sem Gradle/AGP.

### Added
- `lint.py`: unused resources (strings/drawables/layouts/mipmaps/styles nunca referenciados) e deprecated API detection (AsyncTask, org.apache.http, android.app.Fragment, Camera legado, WebViewFragment)
- `config.py` + `packager.py` + `signer.py` + `cli.py`: ABI splits reais — `abi-splits: true` no project.yml gera 1 APK assinado por ABI presente em `src/jniLibs/`, cada um so com seu proprio `.so` (app menor por device). Sem `abi-splits` ou sem `.so`, comportamento antigo (APK universal) inalterado.

### Confirmed (ja funcionava, so nao documentado)
- MultiDex automatico: `d8` recebe todas as classes numa invocacao so, gera `classes2.dex`/`classes3.dex` sem flag extra quando >64k methods; `packager.py` ja empacota todos os dex files.

### Declined (fora de escopo deliberadamente)
- IDE features (autocomplete, refactor, profiler, emulador, layout/network/database inspector, live edit, hot swap) — exigem IDE grafica, nao cabe em CLI
- Servicos externos (Play Console, Firebase, Crashlytics, Play Integrity, Play App Signing) — nao sao build tool, sao contas/API de terceiros
- Build flavors/variants completos, KSP/KAPT orchestration, Room codegen, desugaring com jar externo, AAB real — escopo grande demais pra uma rodada, risco de regressao alto sem testes extensos; candidatos a proxima rodada isolada

## [3.4.6] - 2026-08-07

### Fixed (hardening, auditoria qwen — 7a rodada, sem CRITICAL/HIGH pendente)
- `builder/deps.py`: `_extract_aar()` nao bloqueava entradas symlink em AAR — vetor teorico (mitigado por Python 3.12+ no Termux), aplicado hardening: checa `stat.S_ISLNK` via `member.external_attr` antes de extrair.

### Status
7 rodadas de auditoria (propria, opencode, hermes, 2x adversarial, generica, qwen). Sem achado CRITICAL/HIGH pendente.

## [3.4.5] - 2026-08-07

### Fixed (auditoria adversarial rodada 2, contra commit anterior a v3.4.4)
- `builder/cli.py`: `termux-builder init --package "../../evil"` permitia criar diretorios fora do projeto — sem validacao de package name. Adicionado `re.fullmatch` estilo Java (`com.example.app`) antes de qualquer `os.makedirs`.
- `builder/resources.py`: segundo branch de `_resolve_android_jar()` era dead code (config.py ja resolve pro system jar antes, primeiro `if` sempre pega) — removido, warning duplicado eliminado.

### Achados da auditoria ja corrigidos em v3.4.4, confirmados stale
- Path traversal via `artifact`/`version` em `deps.py` (lib_out) — auditoria leu commit anterior ao fix; regex de charset em GAV ja bloqueia
- Senha de keystore em argv — auditoria leu commit anterior ao fix; `env:VAR` ja em uso desde v3.4.4

### Verified (device real)
- `dalvikvm -cp ecj.jar org.eclipse.jdt.internal.compiler.batch.Main -version` executa e imprime versao do compiler — fallback ecj+dalvikvm CONFIRMADO funcional, nao so binario presente
- `termux-builder init x --package "../../evil"` rejeitado com exit 1
- Analise: `CalledProcessError.stderr` fica None com `capture_output=False` (streaming ao vivo, decisao anterior) — fix de "capturar stderr no handler" nao teria efeito real, descartado

## [3.4.4] - 2026-08-07

### Fixed (auditoria adversarial — achados A-D, validados em device real com build ponta-a-ponta)
- `builder/signer.py` + `builder/utils.py`: senha de keystore vazava via argv (`--ks-pass pass:<senha>`) e log DEBUG (`ps aux`/`/proc/pid/cmdline` legiveis) — corrigido pra usar `--ks-pass env:VAR`/`--key-pass env:VAR`, senha passada via variavel de ambiente do subprocess, nao mais no argv. `utils.run()` ganhou parametro `env=`.
- `builder/deps.py`: coordenada GAV (group:artifact:version) sem validacao de charset — artifact malicioso via POM transitivo podia injetar `../` e escrever fora de `.libs/` — adicionada validacao `re.fullmatch`. Group/artifact estrito; version permite sintaxe de range Maven (`[1.0,2.0)`) sem falso-positivo.
- `builder/deps.py`: extracao de AAR nao-atomica — processo morto no meio deixava `classes.jar` presente sem renomear, cache tratava como valido (estado parcial consumido silenciosamente) — agora extrai em dir temporario e renomeia ao final.
- `builder/cli.py`: `_setup()` baixava `android.jar` direto no path final (nao-atomico, igual ao bug ja corrigido em deps.py) — corrigido pra usar `.tmp` + `os.rename`.
- `builder/cache.py`: removido — codigo morto desde v3.4.2, CHANGELOG afirmava removido mas arquivo seguia no pacote.

### Verified (device real, nao so leitura de codigo)
- Build limpo (`init` + `build`) sem deps: sucesso, 27s
- Build com `BuildConfig.DEBUG` usado em codigo real: sucesso (valida fix CRITICAL da v3.4.3)
- Log verbose confirma `env:_TB_KS_PASS` no lugar de `pass:<senha>` real no apksigner invocation
- Resolucao de dependencia Maven real (androidx.core) + extracao AAR: sucesso, 24 deps resolvidas
- Regressao propria achada e corrigida no processo: regex de validacao GAV rejeitava range de versao Maven valido (`[2.1.0]`) como falso-positivo — corrigido antes do release

## [3.4.3] - 2026-08-07

### Fixed (dupla auditoria cruzada — opencode + hermes, confirmada contra codigo real)
- `builder/cli.py`: `buildconfig.generate()` era chamado ANTES de `resources.link_resources()`; `_link_aapt2()` faz `rmtree(gen_dir)` e apaga o `BuildConfig.java` recem-gerado, nunca recompilado — CRITICAL, feature documentada no README quebrava silenciosamente no primeiro uso real de `BuildConfig.*`
- `builder/cli.py`: `termux-builder test` nao propagava falha de teste — `testing.run_tests()` retorna False mas exit code sempre 0 (false-green em CI)
- `builder/cli.py`: except tuple do handler top-level nao capturava `subprocess.CalledProcessError`, `yaml.YAMLError`, `ET.ParseError`, `requests.RequestException` — traceback cru pro usuario final em vez de "BUILD FAILED: ..."
- `builder/resources.py`: warning de system android.jar nunca disparava — `config.android_jar` ja resolve pro system jar em `config.py`, entao `resources._resolve_android_jar()` retornava no primeiro `if` antes de checar o path — corrigido pra comparar contra a constante
- `builder/deps.py`: download nao-atomico deixava .jar corrompido permanente no cache se rede caisse no meio — agora escreve em `.tmp` e usa `os.rename`
- `builder/deps.py`: zip-slip em `_extract_aar()` — AAR malicioso podia escrever fora de `.libs/` via `../` no path — agora valida cada member antes de extrair
- `builder/deps.py`: GET de POM sem try/except — erro de rede propagava traceback cru — agora `log.warning` + continue

### Rejeitado (claim incorreta de auditoria externa)
- Claim "dalvikvm nao existe no Termux, fallback ecj+dalvikvm esta quebrado" — FALSO, verificado `which dalvikvm` no device real: `/data/data/com.termux/files/usr/bin/dalvikvm` existe. Fallback ecj+dalvikvm ja foi testado e validado end-to-end em sessao anterior (S60, 2026-08-06).
- Claim "utils.py run() nao captura stderr, debugging impossivel" — FALSO, `capture_output=False` faz stderr herdar terminal e imprimir ao vivo durante a execucao, nao e silenciado.

### Verified
- 3 modulos alterados passam `ast.parse` sem erro

## [3.4.2] - 2026-08-07

### Fixed (auditoria externa — ChatGPT cross-check, confirmada)
- `install.sh`: `pkg install ... || true` mascarava falha de instalacao de pacotes core (openjdk-17, aapt2, apksigner, dx) — agora `fail` hard se instalacao core falhar
- `builder/aab.py`: `build_bundle()` gerava AAB invalido (res.zip != resources.pb) sem bloquear — agora `raise NotImplementedError` explicito na entrada da funcao ate proto-format link ser implementado
- `builder/cli.py`: branch de `BuildCache` em `_build()` era efetivamente morto (gen_dir sempre reescrito por buildconfig/resources antes do check, cache nunca pulava) — revertido pra sempre compilar, remove I/O de cache sem beneficio
- `builder/deps.py`: `_find_artifact()` usava apenas HEAD para probe de artefato — mirrors que bloqueiam HEAD quebravam resolucao de dependencia — adicionado fallback GET
- `builder/manifest.py`: escopo de merge (whitelist de tags) nao estava documentado — comentario adicionado explicando limitacao intencional
- `README.md`: installer descrito como instalando "d8" mas `install.sh` instala `dx` — corrigido pra refletir comportamento real

### Verified
- 22 modulos `builder/*.py` + `install.sh` passam validacao de sintaxe (`ast.parse` / `bash -n`)

## [3.4.1] - 2026-08-07

### Fixed
- `doctor.py`: version string hardcoded "v3.0.0" — now uses `builder.__version__` dynamically
- `resources.py`: silent fallback to system android.jar gave no warning before aapt2 link failure (missing theme resources) — now warns clearly and points to `termux-builder setup`
- `testing.py`: `_find_test_classes()` matched any class containing "Test"/"test" substring (false positives like `AbstractTestHelper`) — now requires class name to start or end with "Test"
- `aab.py`: `build_bundle()` used `res.zip` (aapt2 compile output) where bundletool needs `resources.pb` (aapt2 link --proto-format) — added explicit warning; AAB output may still be invalid until proto-format link is implemented
- `cli.py`: wired `BuildCache` into `_build()` for incremental Java/Kotlin compilation skip — tracks both `sources_dir` and `gen_dir` (R.java/BuildConfig regenerate every build, so cache is conservative and never skips on stale-generated-sources risk)
- `README.md`: removed false "Auto-updater ✅" comparison claim (install.sh does `git pull`, not a real updater)

### Verified
- All 22 `builder/*.py` modules pass `ast.parse` syntax validation
- `_build()` cache logic confirmed safe: gen_dir always regenerated by aapt2 link, so compile never skips when resources change

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
