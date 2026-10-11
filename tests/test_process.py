import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from builder.utils import project_lock, run


class ProcessCancellationTests(unittest.TestCase):
    def test_restoration_interrupt_stops_descendants_of_finished_launcher(self):
        for phase in ('success', 'returning', 'detached', 'once', 'repeated', 'after-repeated'):
            with self.subTest(phase=phase), tempfile.TemporaryDirectory(prefix='restore group ') as temporary:
                root = Path(temporary)
                ready, marker, next_phase = root / 'ready', root / 'orphan-output', root / 'next-phase'
                grandchild, launcher = root / 'grandchild.py', root / 'launcher.py'
                grandchild.write_text('import signal,sys,time;from pathlib import Path;'
                    'signal.signal(signal.SIGTERM,signal.SIG_IGN);time.sleep(2);'
                    'Path(sys.argv[1]).write_text("orphan output")')
                launcher.write_text('import os,subprocess,sys;from pathlib import Path;'
                    'child=subprocess.Popen([sys.executable,sys.argv[1],sys.argv[3]],'
                    'stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=sys.argv[4]=="detached");'
                    'Path(sys.argv[2]).write_text(str(os.getpid())+" "+str(child.pid)+" "+str(os.getpgid(child.pid)))')
                code = """import os, signal, sys
from pathlib import Path
from builder.utils import run, project_lock
if sys.argv[2] == 'returning':
    def returning_handler(signum, frame):
        Path(sys.argv[3] + '.handled').write_text('handled')
    signal.signal(signal.SIGINT, returning_handler)
previous = signal.getsignal(signal.SIGINT)
original = signal.signal
restoring = False
reinstalled = False
def restore(signum, handler):
    global restoring, reinstalled
    if signum == signal.SIGINT and handler is previous and not restoring:
        restoring = True
        if sys.argv[2] in ('after-repeated', 'returning'):
            value = original(signum, handler)
            os.kill(os.getpid(), signal.SIGINT)
            return value
        if sys.argv[2] not in ('success', 'detached'):
            os.kill(os.getpid(), signal.SIGINT)
    elif signum == signal.SIGINT and handler is not previous and restoring and not reinstalled and sys.argv[2] == 'after-repeated':
        reinstalled = True
        os.kill(os.getpid(), signal.SIGINT)
    return original(signum, handler)
signal.signal = restore
if sys.argv[2] == 'repeated':
    killpg = os.killpg
    repeated = False
    def interrupt_cleanup(group, signum):
        global repeated
        if not repeated:
            repeated = True
            os.kill(os.getpid(), signal.SIGINT)
        return killpg(group, signum)
    os.killpg = interrupt_cleanup
try:
    with project_lock(sys.argv[1]):
        run(sys.argv[4:])
        assert signal.getsignal(signal.SIGINT) is previous
        Path(sys.argv[3]).write_text('next phase')
except KeyboardInterrupt: sys.exit(130)
"""
                environment = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1]))
                controller = subprocess.Popen([sys.executable, '-c', code, temporary,
                    phase, str(next_phase), sys.executable,
                    str(launcher), str(grandchild), str(ready), str(marker), phase],
                    env=environment, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                pids = []
                try:
                    controller.communicate(timeout=5)
                    success = phase in ('success', 'returning', 'detached')
                    self.assertEqual(controller.returncode, 0 if success else 130)
                    self.assertEqual(next_phase.exists(), success)
                    if phase == 'returning':
                        self.assertTrue(Path(str(next_phase) + '.handled').exists())
                    values = [int(value) for value in ready.read_text().split()]
                    pids = values[:2]
                    self.assertEqual(values[2], values[1] if phase == 'detached' else values[0])
                    with project_lock(temporary):
                        time.sleep(2.5)
                        if phase == 'detached':
                            self.assertTrue(marker.exists(), 'separate session did not survive successful run')
                        else:
                            self.assertFalse(marker.exists(), 'finished launcher descendant wrote after lock release')
                finally:
                    if controller.poll() is None:
                        controller.kill()
                        controller.wait()
                    for pid in pids:
                        try:
                            if str(root).encode() in (Path('/proc') / str(pid) / 'cmdline').read_bytes():
                                os.kill(pid, signal.SIGKILL)
                        except (FileNotFoundError, ProcessLookupError):
                            pass

    def test_interrupt_during_handler_restoration_stops_the_next_phase(self):
        code = """import os, signal, subprocess, sys
from pathlib import Path
from builder.utils import run, project_lock
previous = signal.getsignal(signal.SIGINT)
original = signal.signal
interrupted = False
def restore(signum, handler):
    global interrupted
    if signum == signal.SIGINT and handler is previous and not interrupted:
        interrupted = True
        os.kill(os.getpid(), signal.SIGINT)
    return original(signum, handler)
signal.signal = restore
try:
    with project_lock(sys.argv[1]):
        run([sys.executable, '-c', 'import sys;sys.exit(' + sys.argv[2] + ')'])
        Path(sys.argv[3]).write_text('next phase')
except KeyboardInterrupt: sys.exit(130)
except subprocess.CalledProcessError as error: sys.exit(error.returncode)
"""
        for exit_code in (0, 7):
            with self.subTest(exit_code=exit_code), tempfile.TemporaryDirectory() as temporary:
                marker = Path(temporary) / 'next-phase'
                environment = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1]))
                result = subprocess.run([sys.executable, '-c', code, temporary, str(exit_code), str(marker)],
                    env=environment, capture_output=True, timeout=5)
                self.assertEqual(result.returncode, 130)
                self.assertFalse(marker.exists(), 'run continued after an interrupt during restoration')

    def test_interruption_stops_tool_descendants_before_releasing_lock(self):
        for executor, phase in (('direct', 'running'), ('gradle', 'running'),
                                ('direct', 'startup'), ('gradle', 'startup'),
                                ('direct', 'repeated'), ('gradle', 'repeated'),
                                ('direct', 'restoring'), ('gradle', 'restoring')):
            startup = phase == 'startup'
            with self.subTest(executor=executor, phase=phase), tempfile.TemporaryDirectory(prefix='tool cancel ') as temporary:
                root = Path(temporary)
                ready, marker = root / 'ready', root / 'unexpected-output'
                grandchild, child = root / 'grandchild.py', root / 'child.py'
                grandchild.write_text("import signal,sys,time; from pathlib import Path; "
                    "signal.signal(signal.SIGTERM,signal.SIG_IGN); time.sleep(2); "
                    "Path(sys.argv[1]).write_text('orphan output')")
                child.write_text("import os,subprocess,sys,time; from pathlib import Path; "
                    "process=subprocess.Popen([sys.executable,sys.argv[1],sys.argv[3]]); "
                    "ready=Path(sys.argv[2]); staging=ready.with_suffix('.tmp'); "
                    "staging.write_text(str(os.getpid())+' '+str(process.pid)); staging.rename(ready); time.sleep(20)")
                code = """import os, signal, subprocess, sys, time
from pathlib import Path
from builder.utils import run, project_lock
from builder.gradle import _execute
if sys.argv[3] == 'restoring':
    previous = signal.getsignal(signal.SIGINT)
    original = signal.signal
    interrupted = False
    def restore(signum, handler):
        global interrupted
        if signum == signal.SIGINT and handler is previous and not interrupted:
            interrupted = True
            os.kill(os.getpid(), signal.SIGINT)
        return original(signum, handler)
    signal.signal = restore
if sys.argv[3] == 'repeated':
    killpg = os.killpg
    repeated = False
    def interrupt_cleanup(group, signum):
        global repeated
        if not repeated:
            repeated = True
            os.kill(os.getpid(), signal.SIGINT)
        return killpg(group, signum)
    os.killpg = interrupt_cleanup
if sys.argv[3] == 'startup':
    opener = subprocess.Popen
    def spawn(*args, **kwargs):
        process = opener(*args, **kwargs)
        deadline = time.monotonic() + 10
        while not Path(sys.argv[-2]).exists() and time.monotonic() < deadline: time.sleep(.01)
        os.kill(os.getpid(), signal.SIGINT)
        return process
    subprocess.Popen = spawn
try:
    with project_lock(sys.argv[1]):
        if sys.argv[2] == 'gradle': _execute(sys.argv[4:], None, capture=False)
        else: run(sys.argv[4:])
except KeyboardInterrupt: sys.exit(130)
"""
                environment = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1]))
                controller = subprocess.Popen([sys.executable, '-c', code, str(root), executor,
                    phase,
                    sys.executable, str(child), str(grandchild), str(ready), str(marker)],
                    env=environment, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                pids = []
                try:
                    deadline = time.monotonic() + 10
                    while not ready.exists() and time.monotonic() < deadline:
                        if controller.poll() is not None:
                            self.fail('controller exited before tool started')
                        time.sleep(.01)
                    self.assertTrue(ready.exists(), 'tool did not start')
                    pids = [int(pid) for pid in ready.read_text().split()]
                    if not startup:
                        controller.send_signal(signal.SIGINT)
                    controller.communicate(timeout=5)
                    self.assertEqual(controller.returncode, 130)
                    with project_lock(str(root)):
                        time.sleep(2.5)
                        self.assertFalse(marker.exists(), 'cancelled tool descendant wrote after lock release')
                finally:
                    if controller.poll() is None:
                        controller.kill()
                        controller.wait()
                    for pid in pids:
                        try:
                            if str(root).encode() in (Path('/proc') / str(pid) / 'cmdline').read_bytes():
                                os.kill(pid, signal.SIGKILL)
                        except (FileNotFoundError, ProcessLookupError):
                            pass

    def test_run_preserves_completed_process_capture_cwd_and_environment(self):
        with tempfile.TemporaryDirectory(prefix='run API ') as temporary:
            command = [Path(sys.executable), '-c',
                'import os,sys;sys.stdout.write(os.getcwd()+"\\n"+os.environ["TB_PROCESS_VALUE"]);'
                'sys.stderr.write("captured error")']
            previous = signal.getsignal(signal.SIGINT)
            result = run(command, capture=True, cwd=temporary,
                env=dict(os.environ, TB_PROCESS_VALUE='fixture value'))
            self.assertIsInstance(result, subprocess.CompletedProcess)
            self.assertEqual(result.args, [str(value) for value in command])
            self.assertEqual(result.returncode, 0)
            self.assertEqual(result.stdout, temporary + '\nfixture value')
            self.assertEqual(result.stderr, 'captured error')
            self.assertIs(signal.getsignal(signal.SIGINT), previous)

    def test_run_preserves_checked_and_unchecked_failure_outputs(self):
        command = [sys.executable, '-c',
            'import sys;sys.stdout.write("failure output");sys.stderr.write("failure error");sys.exit(7)']
        result = run(command, capture=True, check=False)
        self.assertEqual(result.returncode, 7)
        self.assertEqual(result.stdout, 'failure output')
        self.assertEqual(result.stderr, 'failure error')
        previous = signal.getsignal(signal.SIGINT)
        with self.assertRaises(subprocess.CalledProcessError) as error:
            run(command, capture=True)
        self.assertEqual(error.exception.returncode, 7)
        self.assertEqual(error.exception.cmd, command)
        self.assertEqual(error.exception.stdout, 'failure output')
        self.assertEqual(error.exception.stderr, 'failure error')
        self.assertIs(signal.getsignal(signal.SIGINT), previous)

    def test_run_preserves_redirected_stream_ownership(self):
        with tempfile.TemporaryFile(mode='w+') as output:
            result = run([sys.executable, '-c',
                'import sys;sys.stdout.write("redirected");sys.stderr.write("captured")'],
                capture=True, stdout=output)
            self.assertFalse(output.closed)
            self.assertIsNone(result.stdout)
            self.assertEqual(result.stderr, 'captured')
            output.seek(0)
            self.assertEqual(output.read(), 'redirected')
        result = run([sys.executable, '-c', 'print("uncaptured")'],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.assertIsNone(result.stdout)
        self.assertIsNone(result.stderr)

    def test_returning_sigint_handlers_are_preserved_at_startup_and_runtime(self):
        for startup in (True, False):
            with self.subTest(startup=startup), tempfile.TemporaryDirectory() as temporary:
                ready, acknowledged = Path(temporary) / 'ready', Path(temporary) / 'acknowledged'
                calls = []
                def returning_handler(signum, frame):
                    calls.append(signum)
                    acknowledged.write_text('handled')
                previous = signal.signal(signal.SIGINT, returning_handler)
                sender = None
                opener = subprocess.Popen
                def spawn(*args, **kwargs):
                    process = opener(*args, **kwargs)
                    os.kill(os.getpid(), signal.SIGINT)
                    return process
                def interrupt_when_ready():
                    deadline = time.monotonic() + 5
                    while not ready.exists() and time.monotonic() < deadline:
                        time.sleep(.01)
                    if ready.exists():
                        os.kill(os.getpid(), signal.SIGINT)
                command = [sys.executable, '-c',
                    'import sys,time;from pathlib import Path;Path(sys.argv[1]).write_text("ready");'
                    'deadline=time.monotonic()+5\n'
                    'while not Path(sys.argv[2]).exists() and time.monotonic()<deadline:time.sleep(.01)\n'
                    'print("complete")', str(ready), str(acknowledged)]
                try:
                    if startup:
                        with patch('builder.utils.subprocess.Popen', side_effect=spawn):
                            result = run(command, capture=True)
                    else:
                        sender = threading.Thread(target=interrupt_when_ready)
                        sender.start()
                        result = run(command, capture=True)
                    self.assertEqual(result.stdout, 'complete\n')
                    self.assertEqual(calls, [signal.SIGINT])
                    self.assertIs(signal.getsignal(signal.SIGINT), returning_handler)
                finally:
                    if sender is not None:
                        sender.join(timeout=6)
                    signal.signal(signal.SIGINT, previous)

    def test_run_in_worker_thread_does_not_install_signal_handlers(self):
        results = []
        with patch('builder.utils.signal.signal', wraps=signal.signal) as install:
            worker = threading.Thread(target=lambda: results.append(
                run([sys.executable, '-c', 'print("worker")'], capture=True)))
            worker.start()
            worker.join(timeout=5)
            self.assertFalse(worker.is_alive())
            install.assert_not_called()
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].stdout, 'worker\n')

    def test_child_sigint_is_not_blocked(self):
        result = run([sys.executable, '-c',
            'import os,signal;os.kill(os.getpid(),signal.SIGINT);print("blocked signal")'],
            capture=True, check=False)
        self.assertIn(result.returncode, (-signal.SIGINT, 128 + signal.SIGINT))
        self.assertNotIn('blocked signal', result.stdout)
