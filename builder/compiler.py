import os
import shutil
from builder.utils import run, ensure_dir, ensure_output_path, log

# ecj.jar paths (Termux native — no JDK needed)
_ECJ_JAR = "/data/data/com.termux/files/usr/share/dex/ecj.jar"
_SYSTEM_ANDROID_JAR = "/data/data/com.termux/files/usr/share/java/android.jar"


def _dexer_is_dx(config):
    return os.path.basename(config.bin_d8) != "d8" or shutil.which(config.bin_d8) is None


def _effective_java_version(config):
    # dx only supports up to class version 52 (Java 8)
    if _dexer_is_dx(config) and config.java_version > 8:
        log.warning("DEX compatibility fallback: requested Java %s -> Java 8; select an available d8 to keep the requested target", config.java_version)
        return 8
    return config.java_version


def _can_use_ecj():
    """ecj + dalvikvm: 100% native Termux, no JDK required."""
    return (
        shutil.which("dalvikvm") is not None
        and os.path.isfile(_ECJ_JAR)
    )


def _resolve_android_jar(config):
    """Use project SDK jar, fallback to system android.jar."""
    if os.path.isfile(config.android_jar):
        return config.android_jar
    if os.path.isfile(_SYSTEM_ANDROID_JAR):
        log.info("Using system android.jar: %s", _SYSTEM_ANDROID_JAR)
        return _SYSTEM_ANDROID_JAR
    raise FileNotFoundError(
        "android.jar not found. Run: termux-builder setup"
    )


def _clear_processor_outputs(config, *names):
    paths = [os.path.join(config.build_dir, name) for name in names]
    for path in paths:
        ensure_output_path(config.build_dir, path, "Annotation processor output")
    for path in paths:
        if os.path.lexists(path):
            shutil.rmtree(path)


def compile_java(config):
    _clear_processor_outputs(config, "gen-apt")
    ensure_output_path(config.build_dir, config.java_classes_dir, "Java classes")
    if os.path.lexists(config.java_classes_dir):
        shutil.rmtree(config.java_classes_dir)
    java_files = config.find_java_files()
    gen_java = config.find_java_files(config.gen_dir)
    binding_java = config.find_java_files(config.binding_dir) if config.view_binding else []

    all_java = java_files + gen_java + binding_java
    if not all_java:
        log.warning("No Java files to compile")
        return

    kotlin_files = config.find_kotlin_files() if hasattr(config, "find_kotlin_files") else []
    if kotlin_files and (
        getattr(config, "kapt_enabled", False) or not getattr(config, "annotation_processors", None)
    ):
        log.info("Java compilation deferred until Kotlin classes and generated sources are available")
        return

    log.info("Compiling %d Java files", len(all_java))
    ensure_dir(config.java_classes_dir)

    android_jar = _resolve_android_jar(config)
    lib_jars = config.find_lib_jars()
    classpath = os.pathsep.join([android_jar] + lib_jars)
    java_ver = _effective_java_version(config)
    javac = shutil.which(config.bin_javac)

    processors = getattr(config, "annotation_processors", None)
    if processors and javac is None:
        raise RuntimeError("annotation processors require javac (ecj does not support -processorpath) — install: pkg install openjdk-17")

    if _can_use_ecj() and javac is None:
        _compile_java_ecj(all_java, classpath, java_ver, config.java_classes_dir)
    else:
        _compile_java_javac(config, all_java, classpath, java_ver, processors)


def _compile_java_ecj(java_files, classpath, java_ver, out_dir):
    """Compile via ecj (Eclipse JDT) + dalvikvm — 100% native, no JDK."""
    log.info("Using ecj compiler (native Termux, no JDK)")
    run([
        "dalvikvm", "-Xmx512m",
        "-cp", _ECJ_JAR,
        "org.eclipse.jdt.internal.compiler.batch.Main",
        "-proc:none",
        "-source", str(java_ver),
        "-target", str(java_ver),
        "-classpath", classpath,
        "-d", out_dir,
        *java_files,
    ])


def _compile_java_javac(config, java_files, classpath, java_ver, processors=None):
    args = [
        config.bin_javac,
        "-source", str(java_ver),
        "-target", str(java_ver),
        "-classpath", classpath,
        "-nowarn",
    ]
    if processors:
        resolved = _resolve_processor_jars(config, processors)
        args += ["-processorpath", os.pathsep.join(resolved)]
        gen_dir = ensure_dir(os.path.join(config.build_dir, "gen-apt"))
        args += ["-s", gen_dir]
    else:
        args += ["-proc:none"]
    args += ["-d", config.java_classes_dir, *java_files]
    run(args)


def _resolve_processor_jars(config, processors):
    """processors: list of paths (relative to project) to annotation
    processor jars, e.g. downloaded via `termux-builder deps` into .libs/
    or placed manually. Real javac -processorpath wiring — this is the
    actual APT mechanism Dagger/Room's javac processors use (KSP/Kotlin
    processors are a separate, Kotlin-compiler-plugin based mechanism,
    see compile_kotlin's kapt handling)."""
    resolved = []
    for p in processors:
        full = os.path.join(config.project_dir, p) if not os.path.isabs(p) else p
        if not os.path.isfile(full):
            raise RuntimeError(f"annotation-processors: jar not found: {full}")
        resolved.append(full)
    return resolved


def compile_kotlin(config):
    _clear_processor_outputs(config, "kapt", "ksp")
    ensure_output_path(config.build_dir, config.kotlin_classes_dir, "Kotlin classes")
    if os.path.lexists(config.kotlin_classes_dir):
        shutil.rmtree(config.kotlin_classes_dir)
    kt_files = config.find_kotlin_files()
    if not kt_files:
        return

    log.info("Compiling %d Kotlin files", len(kt_files))
    ensure_dir(config.kotlin_classes_dir)

    android_jar = _resolve_android_jar(config)
    lib_jars = config.find_lib_jars()
    classpath = os.pathsep.join([android_jar, config.java_classes_dir] + lib_jars)
    java_ver = _effective_java_version(config)
    jvm_target = "1.8" if java_ver == 8 else str(java_ver)

    all_kt_files = list(kt_files)
    generated_java = []
    java_sources = []
    if hasattr(config, "find_java_files") and (
        getattr(config, "kapt_enabled", False) or not getattr(config, "annotation_processors", None)
    ):
        java_sources += config.find_java_files()
        if getattr(config, "gen_dir", None):
            java_sources += config.find_java_files(config.gen_dir)
        if getattr(config, "view_binding", False):
            java_sources += config.find_java_files(config.binding_dir)

    if getattr(config, "ksp_enabled", False):
        processor_jars = _resolve_processor_jars(config, config.annotation_processors)
        from builder.ksp import setup_ksp_toolchain
        prefix, ksp_plugin_jar = setup_ksp_toolchain(config)
        if not prefix:
            raise RuntimeError("ksp: failed to resolve KSP toolchain — check network")

        ksp_gen = ensure_dir(os.path.join(config.build_dir, "ksp", "gen"))
        ksp_classes = ensure_dir(os.path.join(config.build_dir, "ksp", "classes"))
        ksp_resources = ensure_dir(os.path.join(config.build_dir, "ksp", "resources"))
        ksp_caches = ensure_dir(os.path.join(config.build_dir, "ksp", "caches"))
        ksp_base = ensure_dir(os.path.join(config.build_dir, "ksp"))

        log.info("ksp: running symbol processor (phase 1/2)")
        run(prefix + [
            *kt_files,
            "-classpath", classpath,
            "-d", os.path.join(config.build_dir, "ksp", "stub_out"),
            "-jvm-target", jvm_target,
            "-no-reflect",
            "-no-stdlib",
            f"-Xplugin={ksp_plugin_jar}",
            "-P", f"plugin:com.google.devtools.ksp.symbol-processing:projectBaseDir={ksp_base}",
            "-P", f"plugin:com.google.devtools.ksp.symbol-processing:kspOutputDir={ksp_gen}",
            "-P", f"plugin:com.google.devtools.ksp.symbol-processing:classOutputDir={ksp_classes}",
            "-P", f"plugin:com.google.devtools.ksp.symbol-processing:javaOutputDir={ksp_gen}",
            "-P", f"plugin:com.google.devtools.ksp.symbol-processing:kotlinOutputDir={ksp_gen}",
            "-P", f"plugin:com.google.devtools.ksp.symbol-processing:resourceOutputDir={ksp_resources}",
            "-P", f"plugin:com.google.devtools.ksp.symbol-processing:cachesDir={ksp_caches}",
            "-P", "plugin:com.google.devtools.ksp.symbol-processing:incremental=false",
            "-P", "plugin:com.google.devtools.ksp.symbol-processing:allWarningsAsErrors=false",
            "-P", f"plugin:com.google.devtools.ksp.symbol-processing:apclasspath={os.pathsep.join(processor_jars)}",
        ])

        from builder.utils import find_files as _ff2
        generated_kt = _ff2(ksp_gen, ".kt")
        generated_java += _ff2(ksp_gen, ".java")
        all_kt_files = kt_files + generated_kt
        log.info("ksp: compiling %d file(s) including %d generated (phase 2/2)", len(all_kt_files), len(generated_kt))

    if getattr(config, "kapt_enabled", False):
        processor_args = []
        for processor in _resolve_processor_jars(config, config.annotation_processors):
            processor_args += ["-P", f"plugin:org.jetbrains.kotlin.kapt3:apclasspath={processor}"]
        from builder.kapt import resolve_kapt_toolchain
        prefix, plugin_jar = resolve_kapt_toolchain(config)
        if not prefix:
            raise RuntimeError("kapt: failed to resolve a working kotlinc+kapt3 toolchain — check network")

        # Real kapt is 2 phases (same as Gradle's kaptGenerateStubsKotlin vs
        # compileKotlin tasks): phase 1 runs the annotation processor via
        # the kapt3 compiler plugin in stubsAndApt mode, which generates
        # stub/source files but does NOT compile the application's .class output
        # (processors may emit bytecode directly into classes_dir).
        # (verified: exit 0, kotlin_classes_dir stays empty after phase 1
        # alone). Phase 2 is a normal kotlinc compile that also includes
        # whatever .kt/.java sources kapt generated.
        sources_dir = ensure_dir(os.path.join(config.build_dir, "kapt", "sources"))
        classes_dir = ensure_dir(os.path.join(config.build_dir, "kapt", "classes"))
        stubs_dir = ensure_dir(os.path.join(config.build_dir, "kapt", "stubs"))

        log.info("kapt: running annotation processor (phase 1/2)")
        run(prefix + [
            *kt_files,
            *java_sources,
            "-classpath", classpath,
            "-d", stubs_dir,
            "-jvm-target", jvm_target,
            "-no-reflect",
            "-no-stdlib",
            f"-Xplugin={plugin_jar}",
            "-P", f"plugin:org.jetbrains.kotlin.kapt3:sources={sources_dir}",
            "-P", f"plugin:org.jetbrains.kotlin.kapt3:classes={classes_dir}",
            "-P", f"plugin:org.jetbrains.kotlin.kapt3:stubs={stubs_dir}",
            "-P", "plugin:org.jetbrains.kotlin.kapt3:aptMode=stubsAndApt",
            "-P", "plugin:org.jetbrains.kotlin.kapt3:correctErrorTypes=true",
        ] + processor_args)

        classpath = os.pathsep.join([classpath, classes_dir])

        from builder.utils import find_files as _ff
        generated_kt = _ff(sources_dir, ".kt")
        generated_java += _ff(sources_dir, ".java")
        all_kt_files += generated_kt
        log.info("kapt: compiling %d file(s) including %d generated (phase 2/2)", len(all_kt_files), len(generated_kt))

    args = [
        config.bin_kotlinc,
        *all_kt_files,
        *java_sources,
        *generated_java,
        "-classpath", classpath,
        "-d", config.kotlin_classes_dir,
        "-jvm-target", jvm_target,
        "-no-reflect",
        "-no-stdlib",
    ]

    if config.compose:
        compose_jar = _find_compose_compiler(config)
        if compose_jar:
            args += [f"-Xplugin={compose_jar}"]
            log.info("Compose compiler plugin: %s", compose_jar)

    run(args)

    if generated_java or java_sources:
        ensure_output_path(config.build_dir, config.java_classes_dir, "Generated Java classes")
        ensure_dir(config.java_classes_dir)
        generated_classpath = os.pathsep.join([classpath, config.kotlin_classes_dir])
        if _can_use_ecj() and shutil.which(config.bin_javac) is None:
            _compile_java_ecj(java_sources + generated_java, generated_classpath, java_ver, config.java_classes_dir)
        else:
            _compile_java_javac(config, java_sources + generated_java, generated_classpath, java_ver)


def _find_compose_compiler(config):
    for c in (
        os.path.join(config.libs_dir, "compose-compiler.jar"),
        os.path.join(config.cache_dir, "compose-compiler.jar"),
    ):
        if os.path.isfile(c):
            return c
    log.warning("Compose compiler plugin not found — compiled without Compose support")
    return None
