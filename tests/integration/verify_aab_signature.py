"""Verify synthetic AAB payload coverage with real JDK signing tools."""
from pathlib import Path
import shutil
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from test_aab_cli import AabSignatureCoverageTests

if not all(shutil.which(tool) for tool in ('java', 'keytool', 'jarsigner', 'javac')):
    raise RuntimeError('Real Java, keytool, jarsigner and javac are required')
result = unittest.TextTestRunner(verbosity=2).run(
    unittest.defaultTestLoader.loadTestsFromTestCase(AabSignatureCoverageTests)
)
if not result.wasSuccessful():
    sys.exit(1)
print('REAL AAB SIGNATURE: self-signed bundle accepted; unsigned payload and signed-entry mutations rejected')
