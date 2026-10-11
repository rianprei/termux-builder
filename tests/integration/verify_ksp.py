import argparse
import os
import re
import secrets
import sys
import yaml
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path
from types import SimpleNamespace

from builder import compiler, ksp, dexer, packager, signer

parser = argparse.ArgumentParser(description='Verify real KSP; optionally build and sign a real APK with SDK tools')
parser.add_argument('--android-jar')
for tool in ('d8', 'dexdump', 'aapt2', 'apksigner'):
    parser.add_argument('--' + tool, default=tool)
options = parser.parse_args()

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
    if options.android_jar:
        config.android_jar = str(Path(options.android_jar).resolve(strict=True))
        config.bin_d8 = options.d8
        config.dex_dir = str(root / 'build/dex')
        config.cache_dir = str(root / 'dex-cache')
        config.build_type = 'debug'
        config.min_sdk = 21
        config.r8_enabled = False
        config.find_lib_jars = lambda: []
        dexer.dex(config)
        inspected = subprocess.run([options.dexdump, '-f', str(root / 'build/dex/classes.dex')], check=True, capture_output=True, text=True)
        descriptors = set(re.findall(r"Class descriptor\s*:\s*'([^']+)'", inspected.stdout))
        if not {'LGenerated;', 'LGeneratedJava;', 'LMain;'}.issubset(descriptors):
            raise RuntimeError('Generated KSP classes missing from DEX definitions')
        config.bin_dir = str(root / 'build/bin')
        Path(config.bin_dir).mkdir()
        config.find_native_libs = lambda: []
        manifest = root / 'AndroidManifest.xml'
        manifest.write_text('<manifest xmlns:android="http://schemas.android.com/apk/res/android" package="com.example.ksp"><uses-sdk android:minSdkVersion="21"/><application/></manifest>')
        subprocess.run([options.aapt2, 'link', '-I', config.android_jar, '--manifest', str(manifest), '-o', str(Path(config.bin_dir) / 'gen.apk.res')], check=True)
        unsigned = packager.package(config)
        config.keystore_path = str(root / 'fixture.p12')
        config.keystore_store_pass = config.keystore_key_pass = secrets.token_hex(16)
        config.keystore_alias = 'fixture'
        environment = os.environ.copy()
        environment['TB_FIXTURE_PASSWORD'] = config.keystore_store_pass
        subprocess.run(['keytool', '-genkeypair', '-keystore', config.keystore_path,
            '-storepass:env', 'TB_FIXTURE_PASSWORD', '-keypass:env', 'TB_FIXTURE_PASSWORD',
            '-alias', config.keystore_alias, '-dname', 'CN=Integration Fixture', '-keyalg', 'RSA', '-validity', '1'], env=environment, check=True)
        config.bin_apksigner = options.apksigner
        config.sign_v1 = config.sign_v2 = config.sign_v3 = True
        config.sign_v4 = False
        signed = signer.sign_apk(config, unsigned, str(root / 'build/ksp-signed.apk'))
        with zipfile.ZipFile(signed) as archive:
            if archive.testzip() or archive.read('generated-data.txt') != b'real-ksp-resource':
                raise RuntimeError('KSP resource missing or corrupt after APK signing')
            if any(name.endswith(('.java', '.kt', '.class')) for name in archive.namelist()):
                raise RuntimeError('Generated sources or JVM bytecode were packed into APK')
        print('REAL KSP APK: D8 class definitions verified; resource preserved in apksigner-verified signed APK')
        source.write_text('class Main { fun value(): Int = 0 }')
        config.ksp_enabled = False
        config.find_lib_jars = lambda: [stdlib]
        config.find_java_files = lambda *args: []
        config.gen_dir = str(root / 'build/gen')
        config.view_binding = False
        compiler.compile_java(config)
        compiler.compile_kotlin(config)
        config.find_lib_jars = lambda: []
        dexer.dex(config)
        inspected = subprocess.run([options.dexdump, '-f', str(root / 'build/dex/classes.dex')], check=True, capture_output=True, text=True)
        descriptors = set(re.findall(r"Class descriptor\s*:\s*'([^']+)'", inspected.stdout))
        if {'LGenerated;', 'LGeneratedJava;', 'LMain;'}.intersection(descriptors) != {'LMain;'}:
            raise RuntimeError('Stale generated KSP classes survived DEX rebuild')
        unsigned = packager.package(config)
        signed = signer.sign_apk(config, unsigned, signed)
        with zipfile.ZipFile(signed) as archive:
            if archive.testzip() or 'generated-data.txt' in archive.namelist():
                raise RuntimeError('Stale KSP resource survived signed APK rebuild')
        print('REAL KSP APK REBUILD: generated classes and resource removed; rebuilt APK signature verified')
        project = root / 'cli-project'
        (project / 'src/java').mkdir(parents=True)
        (project / 'src/res').mkdir()
        (project / 'libraries').mkdir()
        shutil.copyfile(stdlib, project / 'libraries/kotlin-stdlib.jar')
        shutil.copyfile(manifest, project / 'AndroidManifest.xml')
        (project / 'src/java/Main.kt').write_text('class Main { fun value(): Int = GeneratedJava.value() }')
        android_jar = Path(config.android_jar)
        raw = {
            'name': 'ksp-cli', 'cache-path': str(root / 'cache'), 'libs-path': 'libraries',
            'annotation-processors': [str(root / 'processor.jar')],
            'android': {'ksp': True, 'target-sdk': int(android_jar.parent.name.removeprefix('android-')),
                'sdk-path': str(android_jar.parents[2]), 'java-version': 8,
                'keystore-path': config.keystore_path, 'keystore-alias': config.keystore_alias,
                'keystore-store-pass': 'env:TB_FIXTURE_PASSWORD', 'keystore-key-pass': 'env:TB_FIXTURE_PASSWORD'},
            'bins': {'kotlinc': str(wrapper), 'aapt2': options.aapt2, 'd8': options.d8, 'apksigner': options.apksigner},
        }
        (project / 'project.yml').write_text(yaml.safe_dump(raw))
        subprocess.run([sys.executable, '-m', 'builder', 'build', str(project)], env=environment, check=True)
        artifact = project / '.build/ksp-cli-debug.apk'
        subprocess.run([options.apksigner, 'verify', str(artifact)], check=True)
        with zipfile.ZipFile(artifact) as archive:
            if archive.testzip() or archive.read('generated-data.txt') != b'real-ksp-resource':
                raise RuntimeError('KSP resource missing from CLI-built APK')
            cli_dex = root / 'cli-classes.dex'
            cli_dex.write_bytes(archive.read('classes.dex'))
        inspected = subprocess.run([options.dexdump, '-f', str(cli_dex)], check=True, capture_output=True, text=True)
        descriptors = set(re.findall(r"Class descriptor\s*:\s*'([^']+)'", inspected.stdout))
        if not {'LGenerated;', 'LGeneratedJava;', 'LMain;'}.issubset(descriptors):
            raise RuntimeError('Generated KSP class definitions missing from CLI APK')
        print('REAL KSP CLI: project.yml build produced signature-verified APK containing processor resource')
        subprocess.run([sys.executable, '-m', 'builder', 'build', str(project), '--aab'], env=environment, check=True)
        bundle = project / '.build/ksp-cli-debug.aab'
        subprocess.run(['jarsigner', '-verify', str(bundle)], check=True)
        with zipfile.ZipFile(bundle) as archive:
            if archive.testzip() or archive.read('base/root/generated-data.txt') != b'real-ksp-resource':
                raise RuntimeError('KSP resource missing or corrupt in CLI AAB')
            cli_dex.write_bytes(archive.read('base/dex/classes.dex'))
        inspected = subprocess.run([options.dexdump, '-f', str(cli_dex)], check=True, capture_output=True, text=True)
        descriptors = set(re.findall(r"Class descriptor\s*:\s*'([^']+)'", inspected.stdout))
        if not {'LGenerated;', 'LGeneratedJava;', 'LMain;'}.issubset(descriptors):
            raise RuntimeError('Generated KSP classes missing from CLI AAB')
        print('REAL KSP CLI AAB: bundletool validation and signature passed; generated classes/resource preserved')
        raw['android']['ksp'] = False
        raw['annotation-processors'] = []
        (project / 'project.yml').write_text(yaml.safe_dump(raw))
        (project / 'src/java/Main.kt').write_text('class Main { fun value(): Int = 0 }')
        subprocess.run([sys.executable, '-m', 'builder', 'build', str(project)], env=environment, check=True)
        subprocess.run([options.apksigner, 'verify', str(artifact)], check=True)
        with zipfile.ZipFile(artifact) as archive:
            if archive.testzip() or 'generated-data.txt' in archive.namelist():
                raise RuntimeError('Stale KSP resource survived CLI rebuild')
            cli_dex.write_bytes(archive.read('classes.dex'))
        inspected = subprocess.run([options.dexdump, '-f', str(cli_dex)], check=True, capture_output=True, text=True)
        descriptors = set(re.findall(r"Class descriptor\s*:\s*'([^']+)'", inspected.stdout))
        if {'LGenerated;', 'LGeneratedJava;', 'LMain;'}.intersection(descriptors) != {'LMain;'}:
            raise RuntimeError('Stale KSP class definitions survived CLI rebuild')
        print('REAL KSP CLI REBUILD: changed project.yml honored without clean; generated classes/resource removed; signature verified')
