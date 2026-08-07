import os
import shutil
from builder.utils import run, ensure_dir, log

# ecj.jar paths (Termux native — no JDK needed)
_ECJ_JAR = "/data/data/com.termux/files/usr/share/dex/ecj.jar"
_SYSTEM_ANDROID_JAR = "/data/data/com.termux/files/usr/share/java/android.jar"


def _dexer_is_dx(config):
    return os.path.basename(config.bin_d8) != "d8" or shutil.which("d8") is None


def _effective_java_version(config):
    # dx only supports up to class version 52 (Java 8)
    if _dexer_is_dx(config) and config.java_version > 8:
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


def compile_java(config):
    java_files = config.find_java_files()
    gen_java = config.find_java_files(config.gen_dir)
    binding_java = config.find_java_files(config.binding_dir) if config.view_binding else []

    all_java = java_files + gen_java + binding_java
    if not all_java:
        log.warning("No Java files to compile")
        return

    log.info("Compiling %d Java files", len(all_java))
    ensure_dir(config.java_classes_dir)

    android_jar = _resolve_android_jar(config)
    lib_jars = config.find_lib_jars()
    classpath = os.pathsep.join([android_jar] + lib_jars)
    java_ver = _effective_java_version(config)

    if _can_use_ecj() and shutil.which("javac") is None:
        _compile_java_ecj(all_java, classpath, java_ver, config.java_classes_dir)
    else:
        _compile_java_javac(config, all_java, classpath, java_ver)


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
        "-cp", classpath,
        "-d", out_dir,
        *java_files,
    ])


def _compile_java_javac(config, java_files, classpath, java_ver):
    run([
        config.bin_javac,
        "-source", str(java_ver),
        "-target", str(java_ver),
        "-classpath", classpath,
        "-nowarn",
        "-proc:none",
        "-d", config.java_classes_dir,
        *java_files,
    ])


def compile_kotlin(config):
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

    args = [
        config.bin_kotlinc,
        *kt_files,
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


def _find_compose_compiler(config):
    for c in (
        os.path.join(config.libs_dir, "compose-compiler.jar"),
        os.path.join(config.cache_dir, "compose-compiler.jar"),
    ):
        if os.path.isfile(c):
            return c
    log.warning("Compose compiler plugin not found — compiled without Compose support")
    return None
