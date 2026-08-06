import os
from builder.utils import run, ensure_dir, log


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

    lib_jars = config.find_lib_jars()
    classpath = os.pathsep.join([config.android_jar] + lib_jars)

    run([
        config.bin_javac,
        "-source", str(config.java_version),
        "-target", str(config.java_version),
        "-classpath", classpath,
        "-nowarn",
        "-proc:none",
        "-d", config.java_classes_dir,
        *all_java,
    ])


def compile_kotlin(config):
    kt_files = config.find_kotlin_files()
    if not kt_files:
        return

    log.info("Compiling %d Kotlin files", len(kt_files))
    ensure_dir(config.kotlin_classes_dir)

    lib_jars = config.find_lib_jars()
    classpath = os.pathsep.join([
        config.android_jar,
        config.java_classes_dir,
        *lib_jars,
    ])

    args = [
        config.bin_kotlinc,
        *kt_files,
        "-classpath", classpath,
        "-d", config.kotlin_classes_dir,
        "-jvm-target", str(config.java_version),
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
    candidates = [
        os.path.join(config.libs_dir, "compose-compiler.jar"),
        os.path.join(config.cache_dir, "compose-compiler.jar"),
    ]
    for c in candidates:
        if os.path.isfile(c):
            return c
    log.warning("Compose compiler plugin not found — Kotlin compiled without Compose support")
    return None
