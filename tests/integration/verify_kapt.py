import argparse,base64,os,re,secrets,shutil,subprocess,sys,tempfile,zipfile
import yaml
from pathlib import Path
from types import SimpleNamespace
from builder import kapt,compiler,dexer,packager,aab
parser=argparse.ArgumentParser(description='Verify real KAPT generation and execution; optionally verify real DEX output')
parser.add_argument('--android-jar')
parser.add_argument('--d8', default='d8')
parser.add_argument('--dexdump', default='dexdump')
parser.add_argument('--aapt2', default='aapt2')
parser.add_argument('--apksigner', default='apksigner')
options=parser.parse_args()
with tempfile.TemporaryDirectory(prefix='real-kapt-') as temp:
 root=Path(temp)
 config=SimpleNamespace(cache_dir=str(root/'cache'),build_dir=str(root/'build'),project_dir=temp,
  kotlin_classes_dir=str(root/'build/kotlin'),java_classes_dir=str(root/'build/java'),
  kapt_enabled=True,ksp_enabled=False,annotation_processors=['processor.jar'],compose=False,
  bin_javac=shutil.which('javac'),bin_d8='d8',java_version=8,android_jar=str(root/'android.jar'))
 with zipfile.ZipFile(config.android_jar,'w'):
  pass
 jars=kapt.setup_k1_compiler(config)
 prefix=[shutil.which('java'),'-cp',os.pathsep.join(jars),'org.jetbrains.kotlin.cli.jvm.K2JVMCompiler']
 wrapper=root/'kotlinc'
 wrapper.write_text('#!/usr/bin/env python3\nimport os,sys\nprefix='+repr(prefix)+'\nos.execv(prefix[0],prefix+sys.argv[1:])\n')
 wrapper.chmod(0o755)
 config.bin_kotlinc=str(wrapper)
 direct_source=root/'Direct.java'
 direct_source.write_text('public class Direct { public static int value() { return 11; } }')
 subprocess.run(['javac','-proc:none','--release','8','-d',str(root),str(direct_source)],check=True)
 direct_bytes=base64.b64encode((root/'Direct.class').read_bytes()).decode('ascii')
 (root/'Direct.class').unlink()
 processor_source=root/'Generator.java'
 processor_source.write_text('''
import java.util.Set;
import javax.annotation.processing.*;
import javax.lang.model.SourceVersion;
import javax.lang.model.element.*;
import javax.tools.StandardLocation;
@SupportedAnnotationTypes("*")
public class Generator extends AbstractProcessor {
 boolean generated;
 public SourceVersion getSupportedSourceVersion() { return SourceVersion.latestSupported(); }
 public boolean process(Set<? extends TypeElement> annotations, RoundEnvironment round) {
  if (!generated && !round.processingOver()) {
   try (java.io.Writer writer=processingEnv.getFiler().createResource(StandardLocation.SOURCE_OUTPUT,"","Generated.kt").openWriter()) {
    try (java.io.OutputStream binary=processingEnv.getFiler().createClassFile("Direct").openOutputStream()) {
     binary.write(java.util.Base64.getDecoder().decode("DIRECT_BYTES"));
    }
    try (java.io.Writer resource=processingEnv.getFiler().createResource(StandardLocation.CLASS_OUTPUT,"","generated-data.txt").openWriter()) {
     resource.write("real-kapt-resource");
    }
    writer.write("class Generated { fun value(): Int = 7 }"); generated=true;
    try (java.io.Writer javaWriter=processingEnv.getFiler().createSourceFile("GeneratedJava").openWriter()) {
     javaWriter.write("public class GeneratedJava { public static int value() { return 7; } }");
    }
   } catch(java.io.IOException error) { throw new RuntimeException(error); }
  }
  return false;
 }
}
'''.replace('DIRECT_BYTES',direct_bytes))
 processor_classes=root/'processor-classes'
 subprocess.run(['javac','-proc:none','-d',str(processor_classes),str(processor_source)],check=True)
 service=processor_classes/'META-INF/services/javax.annotation.processing.Processor'
 service.parent.mkdir(parents=True);service.write_text('Generator\n')
 subprocess.run(['jar','cf',str(root/'processor.jar'),'-C',str(processor_classes),'.'],check=True)
 source=root/'Main.kt';source.write_text('class Main { fun value(): Int = GeneratedJava.value() + Direct.value() }')
 config.find_kotlin_files=lambda:[str(source)]
 config.find_lib_jars=lambda:[jar for jar in jars if Path(jar).name=='kotlin-stdlib.jar']
 Path(config.java_classes_dir).mkdir(parents=True)
 compiler.compile_kotlin(config)
 expected = [root/'build/kapt/sources/Generated.kt', root/'build/kotlin/Generated.class',
             root/'build/java/GeneratedJava.class', root/'build/kotlin/Main.class', root/'build/kapt/classes/Direct.class']
 for output in expected:
  if not output.is_file():
   raise RuntimeError('Missing generated output: ' + str(output))
 runner=root/'Runner.java'
 runner.write_text('public class Runner { public static void main(String[] args) { if (new Main().value()!=18 || new Generated().value()!=7) throw new AssertionError(); } }')
 runtime_classpath=os.pathsep.join([config.java_classes_dir,config.kotlin_classes_dir,str(root/'build/kapt/classes'),*config.find_lib_jars(),str(root)])
 subprocess.run(['javac','-proc:none','-classpath',runtime_classpath,'-d',str(root),str(runner)],check=True)
 subprocess.run(['java','-classpath',runtime_classpath,'Runner'],check=True)
 print('REAL KAPT: configured processor generated Kotlin/Java; both compiled and executed; Kotlin references generated Java and directly emitted bytecode')

 if options.android_jar:
  config.android_jar=str(Path(options.android_jar).resolve(strict=True))
  config.bin_d8=options.d8
  config.dex_dir=str(root/'build/dex')
  config.cache_dir=str(root/'dex-cache')
  config.build_type='debug'
  config.min_sdk=21
  config.r8_enabled=False
  libraries=config.find_lib_jars
  config.find_lib_jars=lambda:[]
  dexer.dex(config)
  output=root/'build/dex/classes.dex'
  inspected=subprocess.run([options.dexdump,'-f',str(output)],check=True,capture_output=True,text=True)
  descriptors=set(re.findall(r"Class descriptor\s*:\s*'([^']+)'",inspected.stdout))
  expected={'LDirect;','LGenerated;','LGeneratedJava;','LMain;'}
  if not expected.issubset(descriptors):
   raise RuntimeError('Missing DEX class definitions: '+repr(expected-descriptors))
  print('REAL DEX: dexdump verified class definitions for direct KAPT bytecode and generated Java/Kotlin')
  config.bin_dir=str(root/'build/bin')
  Path(config.bin_dir).mkdir()
  config.find_native_libs=lambda:[]
  manifest=root/'AndroidManifest.xml'
  manifest.write_text('<manifest xmlns:android="http://schemas.android.com/apk/res/android" package="com.example.kapt"><uses-sdk android:minSdkVersion="21"/><application/></manifest>')
  link=[options.aapt2,'link','-I',config.android_jar,'--manifest',str(manifest)]
  subprocess.run(link+['-o',str(Path(config.bin_dir)/'gen.apk.res')],check=True)
  apk=packager.package(config)
  with zipfile.ZipFile(apk) as archive:
   if archive.testzip() or archive.read('generated-data.txt')!=b'real-kapt-resource':
    raise RuntimeError('Generated resource missing or corrupt in APK')
  proto=root/'proto.apk'
  subprocess.run(link+['--proto-format','-o',str(proto)],check=True)
  base=root/'build/bundle/base'
  aab._prepare_base_module(config,str(base),str(proto))
  if (base/'root/generated-data.txt').read_bytes()!=b'real-kapt-resource':
   raise RuntimeError('Generated resource missing from AAB base module')
  print('REAL PACKAGING: KAPT resource preserved in unsigned APK and proto AAB base module')
  source.write_text('class Main { fun value(): Int = 0 }')
  config.kapt_enabled=False
  config.find_lib_jars=libraries
  config.find_java_files=lambda *args:[]
  config.gen_dir=str(root/'build/gen')
  config.view_binding=False
  compiler.compile_java(config)
  compiler.compile_kotlin(config)
  config.find_lib_jars=lambda:[]
  dexer.dex(config)
  rebuilt=subprocess.run([options.dexdump,'-f',str(output)],check=True,capture_output=True,text=True)
  descriptors=set(re.findall(r"Class descriptor\s*:\s*'([^']+)'",rebuilt.stdout))
  if expected.intersection(descriptors) != {'LMain;'}:
   raise RuntimeError('Stale processor classes survived DEX rebuild: '+repr(descriptors))
  print('REAL DEX REBUILD: disabling KAPT removed direct bytecode and generated Java/Kotlin classes')
  project=root/'cli-project'
  (project/'src/java').mkdir(parents=True)
  (project/'src/res').mkdir()
  (project/'libraries').mkdir()
  shutil.copyfile(libraries()[0],project/'libraries/kotlin-stdlib.jar')
  shutil.copyfile(manifest,project/'AndroidManifest.xml')
  (project/'src/java/JavaConsumer.java').write_text('public class JavaConsumer { public static int value() { return GeneratedJava.value() + Direct.value() + new Generated().value(); } }')
  environment=os.environ.copy()
  environment['TB_FIXTURE_PASSWORD']=secrets.token_hex(16)
  keystore=root/'fixture.p12'
  subprocess.run(['keytool','-genkeypair','-keystore',str(keystore),
   '-storepass:env','TB_FIXTURE_PASSWORD','-keypass:env','TB_FIXTURE_PASSWORD',
   '-alias','fixture','-dname','CN=Integration Fixture','-keyalg','RSA','-validity','1'],env=environment,check=True)
  android_jar=Path(config.android_jar)
  raw={'name':'kapt-cli','cache-path':str(root/'cache'),'libs-path':'libraries',
   'annotation-processors':[str(root/'processor.jar')],
   'android':{'kapt':True,'target-sdk':int(android_jar.parent.name.removeprefix('android-')),
    'sdk-path':str(android_jar.parents[2]),'java-version':8,
    'keystore-path':str(keystore),'keystore-alias':'fixture',
    'keystore-store-pass':'env:TB_FIXTURE_PASSWORD','keystore-key-pass':'env:TB_FIXTURE_PASSWORD'},
   'bins':{'kotlinc':str(wrapper),'aapt2':options.aapt2,'d8':options.d8,'apksigner':options.apksigner}}
  for enabled in (True,False):
   raw['android']['kapt']=enabled
   raw['annotation-processors']=[str(root/'processor.jar')] if enabled else []
   (project/'project.yml').write_text(yaml.safe_dump(raw))
   (project/'src/java/Main.kt').write_text('class Main { fun value(): Int = '+
    ('JavaConsumer.value()' if enabled else '0')+' }')
   if not enabled:
    (project/'src/java/JavaConsumer.java').unlink()
   for bundle in (False,True):
    subprocess.run([sys.executable,'-m','builder','build',str(project)]+(['--aab'] if bundle else []),env=environment,check=True)
    if not bundle:
     cli_classpath=os.pathsep.join([str(project/'.build/bin/classes/java'),
      str(project/'.build/bin/classes/kotlin'),str(project/'.build/kapt/classes'),
      str(project/'libraries/kotlin-stdlib.jar'),str(root)])
     cli_runner=root/'CliRunner.java'
     cli_runner.write_text('public class CliRunner { public static void main(String[] args) { if (new Main().value()!='+
      ('25' if enabled else '0')+') throw new AssertionError(); } }')
     subprocess.run(['javac','-proc:none','-classpath',cli_classpath,'-d',str(root),str(cli_runner)],check=True)
     subprocess.run(['java','-classpath',cli_classpath,'CliRunner'],check=True)
    artifact=project/('.build/kapt-cli-debug.'+('aab' if bundle else 'apk'))
    subprocess.run(['jarsigner','-verify',str(artifact)] if bundle else
     [options.apksigner,'verify',str(artifact)],check=True)
    with zipfile.ZipFile(artifact) as archive:
     if archive.testzip():
      raise RuntimeError('Corrupt CLI KAPT artifact: '+str(artifact))
     resource_name=('base/root/' if bundle else '')+'generated-data.txt'
     if enabled:
      if archive.read(resource_name)!=b'real-kapt-resource':
       raise RuntimeError('KAPT resource differs in CLI artifact')
     elif resource_name in archive.namelist():
      raise RuntimeError('Stale KAPT resource survived CLI rebuild')
     cli_dex=root/'cli-classes.dex'
     cli_dex.write_bytes(archive.read('base/dex/classes.dex' if bundle else 'classes.dex'))
    inspected=subprocess.run([options.dexdump,'-f',str(cli_dex)],check=True,capture_output=True,text=True)
    descriptors=set(re.findall(r"Class descriptor\s*:\s*'([^']+)'",inspected.stdout))
    if (enabled and not expected.issubset(descriptors)) or (not enabled and expected.intersection(descriptors)!={'LMain;'}):
     raise RuntimeError('Incorrect KAPT class definitions in CLI artifact: '+repr(descriptors))
    print('REAL KAPT CLI '+('AAB' if bundle else 'APK')+(' BUILD' if enabled else ' REBUILD')+
     ': signature and ZIP verified; generated classes/resource '+('preserved' if enabled else 'removed without clean'))
