import os
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path
from types import SimpleNamespace

from builder import compiler, ksp

with tempfile.TemporaryDirectory(prefix='real-ksp-') as temp:
    root = Path(temp)
    config = SimpleNamespace(
        cache_dir=str(root / 'cache'), build_dir=str(root / 'build'), project_dir=temp,
        kotlin_classes_dir=str(root / 'build/kotlin'), java_classes_dir=str(root / 'build/java'),
        kapt_enabled=False, ksp_enabled=True, annotation_processors=['processor.jar'], compose=False,
        bin_javac=shutil.which('javac'), bin_d8='d8', java_version=8, android_jar=str(root / 'android.jar'),
    )
    with zipfile.ZipFile(config.android_jar, 'w'):
        pass
    prefix, plugin = ksp.setup_ksp_toolchain(config)
    wrapper = root / 'kotlinc'
    wrapper.write_text('#!/usr/bin/env python3\nimport os,sys\nprefix=' + repr(prefix) + '\nos.execv(prefix[0],prefix+sys.argv[1:])\n')
    wrapper.chmod(0o755)
    config.bin_kotlinc = str(wrapper)
    jars = prefix[prefix.index('-cp') + 1].split(os.pathsep)
    api = root / 'cache/ksp' / ('symbol-processing-api-' + ksp._KSP_VERSION + '.jar')
    stdlib = next(jar for jar in jars if Path(jar).name == 'kotlin-stdlib.jar')
    processor_source = root / 'Provider.kt'
    processor_source.write_text('''
import com.google.devtools.ksp.processing.*
import com.google.devtools.ksp.symbol.KSAnnotated
class Provider : SymbolProcessorProvider {
    override fun create(environment: SymbolProcessorEnvironment): SymbolProcessor = Processor(environment.codeGenerator)
}
class Processor(private val generator: CodeGenerator) : SymbolProcessor {
    private var generated = false
    override fun process(resolver: Resolver): List<KSAnnotated> {
        if (!generated) {
            generator.createNewFile(Dependencies.ALL_FILES, "", "Generated", "kt").use {
                it.write("class Generated { fun value(): Int = 7 }".toByteArray())
            }
            generator.createNewFile(Dependencies.ALL_FILES, "", "GeneratedJava", "java").use {
                it.write("public class GeneratedJava { public static int value() { return 7; } }".toByteArray())
            }
            generator.createNewFile(Dependencies.ALL_FILES, "", "generated-data", "txt").use {
                it.write("real-ksp-resource".toByteArray())
            }
            generated = true
        }
        return emptyList()
    }
}
''')
    processor_classes = root / 'processor-classes'
    subprocess.run(prefix + [str(processor_source), '-no-stdlib', '-no-reflect', '-classpath', os.pathsep.join([str(api), stdlib]), '-d', str(processor_classes)], check=True)
    service = processor_classes / 'META-INF/services/com.google.devtools.ksp.processing.SymbolProcessorProvider'
    service.parent.mkdir(parents=True)
    service.write_text('Provider\n')
    subprocess.run(['jar', 'cf', str(root / 'processor.jar'), '-C', str(processor_classes), '.'], check=True)
    source = root / 'Main.kt'
    source.write_text('class Main { fun value(): Int = GeneratedJava.value() }')
    config.find_kotlin_files = lambda: [str(source)]
    config.find_lib_jars = lambda: [stdlib]
    Path(config.java_classes_dir).mkdir(parents=True)
    compiler.compile_kotlin(config)
    for output in (root / 'build/kotlin/Generated.class', root / 'build/java/GeneratedJava.class', root / 'build/kotlin/Main.class'):
        if not output.is_file():
            raise RuntimeError('Missing generated output: ' + str(output))
    runner = root / 'Runner.java'
    runner.write_text('public class Runner { public static void main(String[] args) { if (new Main().value()!=7 || new Generated().value()!=7) throw new AssertionError(); } }')
    runtime_classpath = os.pathsep.join([config.java_classes_dir, config.kotlin_classes_dir, stdlib, str(root)])
    subprocess.run(['javac', '-proc:none', '-classpath', runtime_classpath, '-d', str(root), str(runner)], check=True)
    subprocess.run(['java', '-classpath', runtime_classpath, 'Runner'], check=True)
    print('REAL KSP: configured provider generated Kotlin/Java; both compiled and executed; Kotlin references generated Java')
    resource = root / 'build/ksp/resources/generated-data.txt'
    if resource.read_bytes() != b'real-ksp-resource':
        raise RuntimeError('KSP resource was not separated from generated sources')
    print('REAL KSP RESOURCE: provider output preserved in dedicated resource directory')
