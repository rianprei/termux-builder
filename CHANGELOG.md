## Unreleased

- Gera relatórios JaCoCo em staging e exige XML parseável com raiz report e index HTML antes de publicação. Regressões recusam saída ausente, malformada, raiz incorreta e HTML ausente sem alterar o relatório anterior; staging é limpo. Publicação por cópia preserva arquivos não substituídos e não é atômica.

- Protege destinos de relatório JaCoCo: recusa symlinks no caminho ou na árvore de saída, traversal ambíguo, arquivos especiais e hard links antes de obter a ferramenta ou executar Java. Regressões preservam o arquivo externo; geração real de relatórios e falha com bytecode truncado continuam verificadas no host.

- Verifica testes JVM mistos Java/Kotlin no Termux ARM64/Android 16, com JDK nativo 21.0.12 e JARs portáveis Kotlin 1.9.24. Confirma referências nos dois sentidos, dois testes JUnit, bytecode Java 8 e invalidação da dependência removida sob UID/contexto do aplicativo, sem capacidades Linux. Não comprova build Kotlin de APK/AAB ou KAPT/KSP nativos.

- Corrige testes mistos Java/Kotlin: Kotlin resolve símbolos nas fontes Java antes de javac compilar contra as classes Kotlin. Fixture CLI com compiladores reais reproduziu a falha anterior e verifica referências nos dois sentidos, dois testes JUnit e invalidação após remover a dependência Kotlin.

- Preserva nomes de pacotes contendo class na descoberta JUnit: remove somente a extensão terminal .class. Regressão reproduziu example.classic convertido incorretamente em exampleic; fixture CLI com JUnit real cobre o pacote válido no host JDK 21 e no Termux ARM64/Android 16.

- Corrige o alvo JVM dos testes Kotlin para 1.8 quando java-version é 8, preservando outros níveis. Regressão unitária falhou antes da correção; fixture CLI com Kotlin 1.9.24/JDK 21 reais verifica execução JUnit, bytecode major 52 e remoção do teste. Cenário conectado à CI; execução nativa Kotlin permanece não verificada.

- Valida a fixture JUnit/JaCoCo real no Termux ARM64, Android 16/API 36 e JDK 21.0.12, sob UID/contexto SELinux do aplicativo e sem capacidades Linux. Confirma assertion negativa, remoção de testes, invalidação do bytecode, cobertura independente e erro de relatório; usa JARs oficiais em cache com hashes verificados. Não comprova instrumentação Android nem download no dispositivo.

- Verifica JARs JaCoCo por SHA-256 fixado antes de download/publicação/reuso offline. Bootstrap exige resposta HTTPS 200 direta, limita conteúdo a 8 MiB e usa staging exclusivo; recusa caches corrompidos, symlinks e arquivos especiais, sanitiza erros de rede e limpa downloads interrompidos sem publicar cache parcial. Downloads oficiais e fixture JUnit/JaCoCo reais passaram no host.

- Evita cobertura JaCoCo acumulada entre execuções com append=false e propaga falhas do gerador de relatórios para código 1. Recusa jacoco.exec com symlink, hard link, diretório ou FIFO. Fixture real JUnit/JaCoCo verifica cobertura independente por ramo e falha de relatório com bytecode truncado; conectada à CI.

- Protege build-path e clean contra exclusão do projeto/ancestrais e sobreposição com entradas configuradas, bibliotecas, cache e chaves. Revalida caminhos reais antes da limpeza; rejeita symlinks de saída com barras finais e traversal ambíguo, preservando diretórios externos dedicados. Regressões usam somente projetos temporários; fixture Termux cobre caminhos inseguros e rebuild com --clean.

- Inclui test no lock exclusivo da CLI; regressão reproduz a execução indevida durante outra operação, e a fixture Termux verifica recusa com código 1 sem alterar o APK.

- Invalida test-classes antes de cada execução JUnit, incluindo remoção de todas as fontes, e recusa symlinks nesse destino. Fixture com JDK/JUnit reais reproduziu a execução de teste removido antes da correção; agora verifica falha de assertion, rebuild com um teste e remoção total. Integra a fixture à CI.

- Serializa operações da CLI no mesmo projeto com flock no diretório: build APK/AAB, clean e deps recusam concorrência antes de alterar saídas, com código 1. Testes cobrem aliases symlink, processos independentes, SIGKILL, exceções e independência entre projetos; nenhum arquivo de lock persistente é criado.

- Corrige assinatura AAB com chaves EC: remove SHA256withRSA fixo e usa a escolha do jarsigner adequada à chave, mantendo digest SHA-256. Regressão com keytool/jarsigner reais cobre RSA e EC; APK/AAB nativos e rebuild passaram com ambos.

- A fixture nativa aceita --key-algorithm e verifica estabilidade do conteúdo AAB entre builds sem alteração, registrando diferenças de conteúdo e metadados por entrada. RSA/EC mantiveram o payload; assinaturas variaram, sem alegar reprodutibilidade do arquivo assinado completo.

- Verifica AAB Java nativo no Termux ARM64 pela CLI e no rebuild, com bundletool pinado, assinatura JAR, identidade do pacote e metadados do modulo base; fixture opcional --aab/--bundletool-jar permite cache offline e rejeita substituicao do JAR por um binario no PATH.

- Valida redirecionamentos do bundletool antes de conectar, limita o download a 64 MiB e remove URLs assinadas dos erros de rede; testes verificam origens, credenciais, portas, limite de redirects, preservacao do cache e fechamento das respostas.

- Adiciona fixture executavel no Termux ARM64 para builds Java reais pela CLI, assinatura, verificacao do APK e rebuild. Validada em Android 16 com UID/contexto do Termux e JAR oficial API 36; documenta a falha do JAR de sistema sem recursos de framework.

- Verifica anotacao em fonte Java processada pelo KAPT no projeto misto: classe e recurso condicionais entram no APK/AAB e desaparecem no rebuild sem clean, junto com a classe Java removida.

- Corrige processamento duplicado javac/KAPT: em projetos mistos, KAPT recebe os fontes Java, Kotlin resolve Java e javac compila apos a geracao sem executar novamente os processadores. A fixture real pela CLI verifica APK/AAB assinados e rebuilds sem clean.

- Verifica estabilidade dos bytes do APK unsigned e do ZIP do modulo base AAB com recursos KAPT/KSP quando apenas os mtimes das entradas mudam.

- Ordena deterministicamente os resultados da descoberta compartilhada de arquivos, eliminando dependencia da ordem de enumeracao do filesystem.

- Faz a descoberta compartilhada de arquivos falhar explicitamente em erros de leitura de diretorios, preservando o retorno vazio para diretorios opcionais ausentes.

- Valida cada classe KAPT antes de invocar a toolchain DEX, recusando symlinks e arquivos especiais e ordenando entradas deterministicamente.

- Valida java-version como inteiro positivo e torna explicito nos logs o fallback existente para alvo Java 8 em modo de compatibilidade DEX/dx.

- Valida niveis de SDK e version-code efetivo como inteiros positivos, incluindo overrides de flavor, antes da preparacao do build.

- Verifica rebuild AAB pela CLI sem clean apos desabilitar KSP, incluindo remocao de classes/recursos e nova validacao do bundle e da assinatura.

- Exercita AAB KSP real pela CLI na fixture da CI, verificando bundletool, assinatura JAR, classes geradas no DEX e recurso no modulo base.

- Valida bins como mapa de strings de executaveis nao vazias e sem NUL antes da resolucao de ferramentas, evitando falhas indiretas nos subprocessos.

- Valida mapas na raiz de project.yml e na secao android; erros de sintaxe YAML informam localizacao sem reproduzir linhas que possam conter credenciais.

- Exige booleanos YAML nas flags de AAB, desugar, R8, ViewBinding, Compose e splits, evitando selecao involuntaria de pipeline com strings como "false".

- Valida a secao android.signing e os booleanos v1-v4 antes do build, evitando interpretacoes divergentes de strings/numeros e diagnosticos tardios do apksigner.

- Valida flags KAPT/KSP como booleanos YAML e annotation-processors como lista de caminhos nao vazios, recusando entradas ambiguas antes da preparacao do build.

- Verifica rebuild pela CLI sem clean apos desabilitar KSP em project.yml, conferindo remocao das classes/recursos gerados e assinatura do APK final.

- Exercita o build KSP pela CLI com project.yml real, biblioteca Kotlin local e senhas por ambiente; verifica assinatura, recurso e definicoes de classe no DEX do APK final.

- Verifica rebuild real de APK assinado apos desabilitar KSP: remove classes e recurso gerados, inspeciona o novo DEX e valida novamente a assinatura.

- Verifica KSP com D8, dexdump, aapt2 e apksigner reais na fixture da CI: gera APK assinado, confere classes no DEX e preservacao do recurso apos assinatura, com chave temporaria e senhas via ambiente.

- Verifica falha de leitura para recursos KAPT/KSP e recuperacao de conflitos entre processadores em APK/modulo base AAB, incluindo preservacao do APK anterior e limpeza do staging.

- Separa recursos KSP de fontes geradas e integra sua coleta segura ao APK/modulo base AAB; fixture real verifica resourceOutputDir e testes negativos cobrem ambos os processadores.

- Falha explicitamente quando a coleta de recursos KAPT nao consegue ler diretorios; recusa saidas que nao sejam diretorios/arquivos regulares e preserva o APK anterior.

- Inclui recursos CLASS_OUTPUT do KAPT no APK e no modulo base AAB, com ordenacao deterministica, rejeicao de symlinks/caminhos reservados/conflitos e preservacao do APK anterior em falhas; amplia a fixture real com aapt2.

- Amplia a integracao KAPT da CI com D8 e dexdump reais, verificando definicoes de classe e remocao de saidas antigas em rebuild sem KAPT.

- Integra classes emitidas diretamente pelo KAPT ao classpath Kotlin/Java final e a coleta do DEX, com validacao de destino e fixture real de geracao e execucao de bytecode.

- Limita a sondagem Kotlin a 30 segundos e diagnostica falhas ao iniciar o executavel sem propagar saida ou dados da excecao do subprocesso.

- Recusa sondagem Kotlin com codigo de saida nao zero, consulta stdout e stderr para a versao e evita incluir a saida bruta do processo nos erros KAPT.

- Verifica Java antes dos downloads do fallback KAPT e informa como corrigir o PATH; regressao comprova que compilador e plugin nao sao baixados quando o runtime esta ausente.

- Resolve caminhos relativos de processadores KSP contra o projeto e usa o separador de classpath exigido pelo plugin; adiciona integracao real na CI com um provider que gera, compila e executa Java/Kotlin.

- Conecta os JARs de annotation-processors a fase KAPT, inclui Java gerado na resolucao Kotlin e compila essas fontes com javac/ECJ; adiciona integracao real na CI com geracao e execucao de classes Java/Kotlin.

- Controla cada redirecionamento da distribuicao Kotlin: somente HTTPS GitHub/CDN autorizado, sem credenciais na URL, com limite de saltos e fechamento das respostas intermediarias; erros de rede nao propagam URLs assinadas.

- Valida compilador embeddable, API e plugin KSP no download e na reutilizacao, compartilha o validador de JARs com KAPT, usa staging exclusivo e falha antes de baixar quando Java esta ausente.

- Valida versoes e JARs do plugin KAPT no download e no cache; usa staging exclusivo, limita tamanho, recusa symlinks e publica somente plugins estruturalmente verificados.

- Publica a distribuicao Kotlin K1 somente apos validar entradas ZIP, limites de tamanho e JARs essenciais em staging exclusivo; recusa caches incompletos/corrompidos e symlinks, limpa downloads interrompidos e preserva reutilizacao offline do cache valido.

- Limpa saidas APT/KAPT/KSP antes da compilacao, incluindo projetos sem fontes restantes; recusa destinos por symlink e cobre remocao de fontes geradas com um processador javac real.

- Invalida fontes ViewBinding antes da geracao para remover bindings de layouts apagados; valida o destino, ordena os layouts e falha explicitamente em XML malformado.

- Remove apenas as fontes AIDL geradas antes de recompilar, inclusive apos apagar a ultima interface; valida o destino antes da limpeza e falha explicitamente quando ha fontes AIDL mas o compilador nao esta no PATH.

- Limpa as classes Java/Kotlin antes da recompilacao, inclusive quando nao restam fontes, para impedir classes removidas no DEX; regressao com javac real e rebuild de APK/AAB na CI.

- Endurece a resolucao Maven: coordenadas invalidas, POMs malformados, repositorios inacessiveis, redirects e artefatos ausentes agora encerram a operacao com erro; downloads sao limitados as origens HTTPS configuradas, usam temporarios exclusivos e nao promovem arquivos incompletos ao cache.
- Valida o formato do `.sha1` retornado pelo repositorio e documenta quando a verificacao do checksum foi omitida; adiciona regressao para symlink em temporario, falha de rede e dependencias ausentes.
- Separa cache e artefatos extraidos por `groupId`, confere SHA-256 ao reutilizar binarios e arquivos expandidos, e registra coordenada, origem e hashes para auditoria local.
- Limita a leitura do POM as dependencias diretas, expande propriedades locais, normaliza ranges exatos `[versao]` e aplica mediacao por menor profundidade com desempate pela ordem declarada.
- Implementa heranca de POM remoto, propriedades herdadas, BOM imports recursivos e gestao local de versao/escopo/exclusao; exclusoes Maven sao aplicadas por caminho e preservadas no cache.
- Preserva e aplica tipos Maven `jar`/`aar` nas arestas de dependencias e no cache; mantem explicita a limitacao de `parent.relativePath` local, profiles Maven, scopes fora do subconjunto e tipos fora do subconjunto.
- Mantem somente as versoes Maven selecionadas no classpath sem apagar bibliotecas antigas; registra coordenadas resolvidas para identificar os artefatos gerados.
- Rejeita entradas AAR com traversal, symlinks ou caminhos duplicados; staging e exclusivo e removido mesmo quando o ZIP e invalido.
- Continua recusando ranges abertos, escopos nao suportados, classifiers, packaging que nao seja `jar`/`aar` e tipos desconhecidos; impede copiar POMs ou formatos desconhecidos com extensao `.jar`.
- Gera saidas AAPT2 distintas e estaveis para AARs com o mesmo nome, limita o link aos recursos ativos em ordem previsivel e deixa de apagar ZIPs arbitrarios do diretorio de build.
- Evolui o merge nativo de manifests com prioridade deterministica, combinacao de atributos, diagnostico de conflitos, placeholders por projeto/flavor, diretivas `tools:*` selecionadas e validacao de `minSdkVersion`.
- Falha explicitamente em placeholders ausentes, diretivas `tools:*` desconhecidas, XML invalido e manifests de biblioteca por symlink; documenta os limites restantes frente ao AGP.
- Publica APKs e AABs por staging atomico somente depois da verificacao; rejeita destinos por symlink ou fora da arvore de build e impede colisao de saidas entre flavors.
- Valida com `apksigner` o APK e o `.idsig` de V4 antes de publicar o par assinado; se qualquer rename falhar, restaura o par anterior e preserva backups para recuperacao quando o rollback tambem falha.
- Valida os diretorios AAPT2 e AAB antes de cria-los, qualifica nomes de classes relativos nos manifests pelo pacote de origem, e une arestas Maven com type implícito/explicito quando resolvem para o mesmo JAR ou AAR.
- Ignora manifests e JARs de staging Maven incompleto, recupera diretorios de DEX temporarios de processos mortos e escreve entradas adicionadas ao APK com metadados ZIP estaveis.
- Serializa a resolução Maven com a leitura e geração do cache DEX por um lock `flock` comum; fingerprint é calculado sob o lock e a validação pós-geração descarta resultados se as entradas mudarem. O lock rejeita symlinks e a regressão cobre concorrência, falhas, interrupção e retomada.
- Identifica o PID no staging AAR e remove diretorios abandonados por processos mortos sem tocar extrações ainda ativas.
- Inclui DEX de dependencias AAR tanto em APK quanto em AAB; o build real AndroidX gerou 15 entradas DEX em cada formato e passou nas verificacoes de assinatura/estrutura.
- Expande regressao para caminhos inseguros, falhas de assinatura sem sobrescrever artefatos anteriores, caches incompletos, ZIPs reprodutiveis e integracao AndroidX na CI.

### Fixed
- `build --aab` and `android.aab: true` now reach the AAB pipeline after compilation; the APK build remains the default, and AAB output cannot be passed to `--install`.
- APK output is returned only after `apksigner verify` succeeds; AAB output is checked for required bundle entries and a valid JAR signature.
- AAB signing now passes both keystore passwords through the subprocess environment.
- Keystore password settings accept `env:VARIABLE` references and fail clearly when the variable is unset; literal values remain supported for compatibility.
- Proto-APK extraction rejects traversal paths and symlink entries before writing bundle files.

### Tests
- Added CLI/config regression tests, unsafe archive tests, signature checks, and a real `keytool`/`jarsigner` integration test.

## [3.11.0] - 2026-08-09

### Added
- `recon <apk>`: engenharia reversa estatica de APK, absorvido do repo separado `termux-reverse-apk` (agora descontinuado em favor de integrar no builder que ja tem apktool/analyze). Decompila com `decompile()` existente, parseia manifest (permissoes, componentes exportados, min/target-sdk lendo de `apktool.yml` quando o apktool move pra la), escaneia smali/resources com 11 categorias de padrao (secrets, firebase URL, AWS key, URL/HTTP em texto claro, WebView JS, exec de shell, SQL, crypto fraca, base64, shared prefs) com severity+confidence por achado, lista libs nativas por ABI. `--html` gera relatorio visual alem do JSON. Testado real: `recon HackersKeyboard.apk --html` — package `org.pocketworkstation.pckeyboard`, min-sdk 14, target-sdk 26, 567 findings (0 high/261 medium/306 low), 7 native libs.

## [3.10.0] - 2026-08-09

5 features de build avancado, sem credencial externa nem rewrite arquitetural.

### Added
- Signing V1+V2+V3+V4 simultaneo: `project.yml` aceita `android.signing.{v1,v2,v3,v4}` (default v1-v3 on, v4 on se `min-sdk >= 30`). Testado real: `apksigner verify --verbose` confirma v1/v2/v3 true no APK gerado.
- Lint reports XML/HTML: `lint --report <path>` escreve `.xml` (formato `<issues>`) ou `.html` (tabela) com as mesmas mensagens do check. Testado real: 1 issue capturada e escrita nos dois formatos.
- Lint baseline: `lint --write-baseline <path>` snapshota issues atuais; `lint --baseline <path>` suprime issues ja conhecidas em runs futuros. Testado real: issue suprimida corretamente na segunda run.
- Dependency checksum verification: cada artefato baixado do Maven agora valida contra o `.sha1` publicado ao lado (Maven Central nao publica sha256 — sha1 e o real). Mismatch remove o arquivo e aborta o build. Testado real contra download de 5 artefatos (androidx.annotation + transitivos).
- Test coverage (JaCoCo): `test --coverage [--coverage-report <dir>]` baixa `org.jacoco.agent`/`org.jacoco.cli` 0.8.12 do Maven Central, roda os testes com `-javaagent`, gera relatorio HTML+XML. Testado real: 1 teste JUnit rodado com agent, relatorio de 5 classes gerado.

### Fixed
- `test --coverage`: jacoco cli falhava com `FileNotFoundError` quando o projeto nao tem fonte Kotlin (`kotlin_classes_dir` inexistente) — agora so passa `--classfiles` pra diretorios que existem.

## [3.9.0] - 2026-08-09

Adiciona 6 comandos CLI que cobrem o que da pra cobrir sem virar IDE/GUI (Android Studio tem editor visual, debugger interativo, profiler grafico, emulador com janela — isso nao vira CLI; o resto, sim).

### Added
- `analyze <apk>`: breakdown de tamanho por dex/resources/assets/native_libs/manifest + `aapt2 dump badging` (package/label/sdk). Testado real: zip sintetico com buckets conhecidos confere exato; rodado tambem contra APK real gerado por `termux-builder build` (breakdown correto, aapt2 badging funcionando).
- `db pull <pkg> <db>`: `adb exec-out run-as <pkg> cat databases/<db>` + `sqlite3 .schema`/`.tables`. Bug achado antes de publicar: `utils.run()` forca `text=True`, corrompe bytes binarios do SQLite no round-trip decode/encode — corrigido usando `subprocess.run` raw (bytes) direto no modulo, nao via `utils.run`.
- `logcat [pkg]`: sem pkg = `adb logcat` cru; com pkg = resolve PID via `pidof -s` e filtra `--pid`. Testado real: sem device conectado, comportamento correto do proprio adb ("waiting for device"), nao crasha.
- `deps-tree <dir>`: le os arquivos `.transitive` que `deps.py` ja salva em cache por lib, monta arvore recursiva com guarda de ciclo. Reusa cache existente, nao duplica logica de resolucao.
- `applinks <dominio> <pkg> [--fingerprint]`: busca `/.well-known/assetlinks.json`, valida `relation` + `package_name` + fingerprint opcional. Testado real contra `google.com`/`com.google.android.calendar` (statement real bate).
- `emulator list` / `emulator start <avd> [--window]`: wrap `avdmanager list avd` / `emulator -avd <nome> -no-window -no-audio -gpu swiftshader_indirect` (headless por padrao). Nao testado ponta-a-ponta — sem `avdmanager` instalado no ambiente de teste (SDK emulator nao vem por padrao); erro sai claro e nao mascarado.

### Verified
- `termux-builder init` + `termux-builder build .` reais: APK assinado gerado em 12.7s, 0 erro.
- `analyze`/`lint`/`deps-tree` rodados contra o projeto/APK real acima: todos corretos.
- `db pull`/`logcat`/`emulator list` sem device/AVD: falham limpo com mensagem clara, sem stack trace vazado, sem crash.
- Instalacao fresh via `curl | bash` no device real: 0 erro, `termux-builder --help` lista os 6 comandos novos.

## [3.8.0] - 2026-08-07

Fecha 2 gaps que sobraram da auditoria "100%": R8 nunca era real, e KSP nao existia.

### Fixed — CRITICAL, R8 nunca minificava
- `dexer.py`: `d8 --release` **nunca** rodou R8. `--release` no d8 so significa "compila sem debug info" — nao ativa shrink/obfuscate. Bug achado testando de verdade: decompilei um APK "R8 minification enabled" e as classes nao estavam renomeadas. Existe binario `r8` SEPARADO no Termux que faz shrink/obfuscate real. Corrigido: quando `r8: true` + `build-type: release`, usa o binario `r8` de verdade, com regras default (`-keep` pras 4 classes de entrypoint Android) se `r8-rules` nao for declarado, e gera `mapping.txt` real.
- Testado: `mapping.txt` real gerado, cabecalho `# compiler: R8` confirma execucao real (`d8 --release` nunca produz esse arquivo).

### Added — KSP real
- `ksp.py` novo: KSP nao tem release pra kotlinc 2.x (Termux) — Maven Central cobre so ate kotlinc 2.2.21. Fallback pro K1 1.9.24 (mesmo toolchain do kapt), que tem KSP real (1.9.24-1.0.20).
- Classpath descoberta por tentativa real (cada troca resolveu 1 erro distinto): `kotlin-compiler-embeddable.jar` (nao o `kotlin-compiler.jar` puro da dist standalone — esse da AbstractMethodError, ABI incompativel) + `symbol-processing-api.jar` (KSPLogger, ClassNotFoundException sem ele) + resto da dist standalone pras deps transitivas (trove4j, asm — faltam so no embeddable puro).
- Testado real: plugin carrega e roda sem crash, chega em "No providers found in processor classpath" (esperado sem processor real configurado via `annotation-processors:` — falha alto e claro, nao mente).

### Verified apos publicacao (KSP com processor real)
- Escrito `SymbolProcessor` real (KSP API), compilado, empacotado com `META-INF/services` correto. Rodado via `annotation-processors:` apontando pro jar. Resultado: `KspGenerated.class` compilado de verdade, codigo gerado (`class KspGenerated { fun msg() = "ksp works" }`) confere exatamente com o que o processor escreveu. KSP fechado ponta a ponta, nao so infra.

### Genuinamente bloqueado (permissao de OS, nao de codigo)
- Instalar+abrir APK numa tela real: `adb devices`/`termux-adb devices` vazios (sem debug USB/wireless habilitado). Tentei ativar via `settings put global adb_wifi_enabled` — `SecurityException: requires android.permission.INTERACT_ACROSS_USERS`. Termux (app sandboxed) nao tem permissao de alterar essa configuracao do sistema; requer o usuario abrir Configuracoes > Opcoes do desenvolvedor manualmente.

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
