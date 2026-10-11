import os,shutil,subprocess,tempfile,zipfile
from pathlib import Path
from types import SimpleNamespace
from builder import kapt,compiler
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
    writer.write("class Generated { fun value(): Int = 7 }"); generated=true;
    try (java.io.Writer javaWriter=processingEnv.getFiler().createSourceFile("GeneratedJava").openWriter()) {
     javaWriter.write("public class GeneratedJava { public static int value() { return 7; } }");
    }
   } catch(java.io.IOException error) { throw new RuntimeException(error); }
  }
  return false;
 }
}
''')
 processor_classes=root/'processor-classes'
 subprocess.run(['javac','-proc:none','-d',str(processor_classes),str(processor_source)],check=True)
 service=processor_classes/'META-INF/services/javax.annotation.processing.Processor'
 service.parent.mkdir(parents=True);service.write_text('Generator\n')
 subprocess.run(['jar','cf',str(root/'processor.jar'),'-C',str(processor_classes),'.'],check=True)
 source=root/'Main.kt';source.write_text('class Main { fun value(): Int = GeneratedJava.value() }')
 config.find_kotlin_files=lambda:[str(source)]
 config.find_lib_jars=lambda:[jar for jar in jars if Path(jar).name=='kotlin-stdlib.jar']
 Path(config.java_classes_dir).mkdir(parents=True)
 compiler.compile_kotlin(config)
 expected = [root/'build/kapt/sources/Generated.kt', root/'build/kotlin/Generated.class',
             root/'build/java/GeneratedJava.class', root/'build/kotlin/Main.class']
 for output in expected:
  if not output.is_file():
   raise RuntimeError('Missing generated output: ' + str(output))
 runner=root/'Runner.java'
 runner.write_text('public class Runner { public static void main(String[] args) { if (new Main().value()!=7 || new Generated().value()!=7) throw new AssertionError(); } }')
 runtime_classpath=os.pathsep.join([config.java_classes_dir,config.kotlin_classes_dir,*config.find_lib_jars(),str(root)])
 subprocess.run(['javac','-proc:none','-classpath',runtime_classpath,'-d',str(root),str(runner)],check=True)
 subprocess.run(['java','-classpath',runtime_classpath,'Runner'],check=True)
 print('REAL KAPT: configured processor generated Kotlin/Java; both compiled and executed; Kotlin references generated Java')
