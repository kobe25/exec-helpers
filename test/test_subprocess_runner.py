# coding=utf-8

#    Copyright 2018 Alexey Stepanov aka penguinolog.

#    Copyright 2016 Mirantis, Inc.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

from __future__ import absolute_import
from __future__ import division
from __future__ import unicode_literals

import logging
import subprocess
import unittest

import mock

import exec_helpers
from exec_helpers import subprocess_runner

command = 'ls ~\nline 2\nline 3\nline с кирилицей'
command_log = u"Executing command:\n{!s}\n".format(command.rstrip())
stdout_list = [b' \n', b'2\n', b'3\n', b' \n']
stderr_list = [b' \n', b'0\n', b'1\n', b' \n']
print_stdin = 'read line; echo "$line"'


class FakeFileStream(object):
    def __init__(self, *args):
        self.__src = list(args)

    def __iter__(self):
        for _ in range(len(self.__src)):
            yield self.__src.pop(0)

    def fileno(self):
        return hash(tuple(self.__src))


# TODO(AStepanov): Cover negative scenarios (timeout)


@mock.patch('exec_helpers.subprocess_runner.logger', autospec=True)
@mock.patch('select.select', autospec=True)
@mock.patch(
    'exec_helpers.subprocess_runner.set_nonblocking_pipe', autospec=True
)
@mock.patch('subprocess.Popen', autospec=True, name='subprocess.Popen')
class TestSubprocessRunner(unittest.TestCase):
    @staticmethod
    def prepare_close(
        popen,
        cmd=command,
        stderr_val=None,
        ec=0,
        open_stdout=True,
        open_stderr=True,
        cmd_in_result=None,
    ):
        if open_stdout:
            stdout_lines = stdout_list
            stdout = FakeFileStream(*stdout_lines)
        else:
            stdout = stdout_lines = None
        if open_stderr:
            stderr_lines = stderr_list if stderr_val is None else []
            stderr = FakeFileStream(*stderr_lines)
        else:
            stderr = stderr_lines = None

        popen_obj = mock.Mock()
        if stdout:
            popen_obj.attach_mock(stdout, 'stdout')
        else:
            popen_obj.configure_mock(stdout=None)
        if stderr:
            popen_obj.attach_mock(stderr, 'stderr')
        else:
            popen_obj.configure_mock(stderr=None)
        popen_obj.configure_mock(returncode=ec)

        popen.return_value = popen_obj

        # noinspection PyTypeChecker
        exp_result = exec_helpers.ExecResult(
            cmd=cmd_in_result if cmd_in_result is not None else cmd,
            stderr=stderr_lines,
            stdout=stdout_lines,
            exit_code=ec
        )

        return popen_obj, exp_result

    @staticmethod
    def gen_cmd_result_log_message(result):
        return ("Command exit code '{code!s}':\n{cmd!s}\n"
                .format(cmd=result.cmd.rstrip(), code=result.exit_code))

    def test_call(self, popen, _, select, logger):
        popen_obj, exp_result = self.prepare_close(popen)
        select.return_value = [popen_obj.stdout, popen_obj.stderr], [], []

        runner = exec_helpers.Subprocess()

        # noinspection PyTypeChecker
        result = runner.execute(command)
        self.assertEqual(
            result, exp_result

        )
        popen.assert_has_calls((
            mock.call(
                args=[command],
                cwd=None,
                env=None,
                shell=True,
                stderr=subprocess.PIPE,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                universal_newlines=False,
            ),
        ))
        logger.assert_has_calls(
            [
                mock.call.log(level=logging.DEBUG, msg=command_log),
            ] + [
                mock.call.log(
                    level=logging.DEBUG,
                    msg=str(x.rstrip().decode('utf-8'))
                )
                for x in stdout_list
            ] + [
                mock.call.log(
                    level=logging.DEBUG,
                    msg=str(x.rstrip().decode('utf-8')))
                for x in stderr_list
            ] + [
                mock.call.log(
                    level=logging.DEBUG,
                    msg=self.gen_cmd_result_log_message(result)),
            ])
        self.assertIn(
            mock.call.poll(), popen_obj.mock_calls
        )

    def test_call_verbose(self, popen, _, select, logger):
        popen_obj, _ = self.prepare_close(popen)
        select.return_value = [popen_obj.stdout, popen_obj.stderr], [], []

        runner = exec_helpers.Subprocess()

        # noinspection PyTypeChecker
        result = runner.execute(command, verbose=True)

        logger.assert_has_calls(
            [
                mock.call.log(level=logging.INFO, msg=command_log),
            ] + [
                mock.call.log(
                    level=logging.INFO,
                    msg=str(x.rstrip().decode('utf-8')))
                for x in stdout_list
            ] + [
                mock.call.log(
                    level=logging.INFO,
                    msg=str(x.rstrip().decode('utf-8')))
                for x in stderr_list
            ] + [
                mock.call.log(
                    level=logging.INFO,
                    msg=self.gen_cmd_result_log_message(result)),
            ])

    def test_context_manager(self, popen, _, select, logger):
        popen_obj, exp_result = self.prepare_close(popen)
        select.return_value = [popen_obj.stdout, popen_obj.stderr], [], []

        subprocess_runner.SingletonMeta._instances.clear()

        with mock.patch('threading.RLock', autospec=True):
            with exec_helpers.Subprocess() as runner:
                self.assertEqual(
                    mock.call.acquire(), runner.lock.mock_calls[0]
                )
                result = runner.execute(command)
                self.assertEqual(
                    result, exp_result

                )

            self.assertEqual(mock.call.release(), runner.lock.mock_calls[-1])

        subprocess_runner.SingletonMeta._instances.clear()

    @mock.patch('time.sleep', autospec=True)
    def test_execute_timeout_fail(
        self,
        sleep,
        popen, _, select, logger
    ):
        popen_obj, exp_result = self.prepare_close(popen)
        popen_obj.configure_mock(returncode=None)
        select.return_value = [popen_obj.stdout, popen_obj.stderr], [], []

        runner = exec_helpers.Subprocess()

        # noinspection PyTypeChecker

        with self.assertRaises(exec_helpers.ExecHelperTimeoutError):
            # noinspection PyTypeChecker
            runner.execute(command, timeout=1)

        popen.assert_has_calls((
            mock.call(
                args=[command],
                cwd=None,
                env=None,
                shell=True,
                stderr=subprocess.PIPE,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                universal_newlines=False,
            ),
        ))

    def test_execute_no_stdout(self, popen, _, select, logger):
        popen_obj, exp_result = self.prepare_close(popen, open_stdout=False)
        select.return_value = [popen_obj.stdout, popen_obj.stderr], [], []

        runner = exec_helpers.Subprocess()

        # noinspection PyTypeChecker
        result = runner.execute(command, open_stdout=False)
        self.assertEqual(result, exp_result)
        popen.assert_has_calls((
            mock.call(
                args=[command],
                cwd=None,
                env=None,
                shell=True,
                stderr=subprocess.PIPE,
                stdin=subprocess.PIPE,
                stdout=subprocess_runner.devnull,
                universal_newlines=False,
            ),
        ))
        logger.assert_has_calls(
            [
                mock.call.log(level=logging.DEBUG, msg=command_log),
            ] + [
                mock.call.log(
                    level=logging.DEBUG,
                    msg=str(x.rstrip().decode('utf-8')))
                for x in stderr_list
            ] + [
                mock.call.log(
                    level=logging.DEBUG,
                    msg=self.gen_cmd_result_log_message(result)),
            ])
        self.assertIn(
            mock.call.poll(), popen_obj.mock_calls
        )

    def test_execute_no_stderr(self, popen, _, select, logger):
        popen_obj, exp_result = self.prepare_close(popen, open_stderr=False)
        select.return_value = [popen_obj.stdout, popen_obj.stderr], [], []

        runner = exec_helpers.Subprocess()

        # noinspection PyTypeChecker
        result = runner.execute(command, open_stderr=False)
        self.assertEqual(result, exp_result)
        popen.assert_has_calls((
            mock.call(
                args=[command],
                cwd=None,
                env=None,
                shell=True,
                stderr=subprocess_runner.devnull,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                universal_newlines=False,
            ),
        ))
        logger.assert_has_calls(
            [
                mock.call.log(level=logging.DEBUG, msg=command_log),
            ] + [
                mock.call.log(
                    level=logging.DEBUG,
                    msg=str(x.rstrip().decode('utf-8'))
                )
                for x in stdout_list
            ] + [
                mock.call.log(
                    level=logging.DEBUG,
                    msg=self.gen_cmd_result_log_message(result)),
            ])
        self.assertIn(
            mock.call.poll(), popen_obj.mock_calls
        )

    def test_execute_no_stdout_stderr(self, popen, _, select, logger):
        popen_obj, exp_result = self.prepare_close(
            popen,
            open_stdout=False,
            open_stderr=False
        )
        select.return_value = [popen_obj.stdout, popen_obj.stderr], [], []

        runner = exec_helpers.Subprocess()

        # noinspection PyTypeChecker
        result = runner.execute(command, open_stdout=False, open_stderr=False)
        self.assertEqual(result, exp_result)
        popen.assert_has_calls((
            mock.call(
                args=[command],
                cwd=None,
                env=None,
                shell=True,
                stderr=subprocess_runner.devnull,
                stdin=subprocess.PIPE,
                stdout=subprocess_runner.devnull,
                universal_newlines=False,
            ),
        ))
        logger.assert_has_calls(
            [
                mock.call.log(level=logging.DEBUG, msg=command_log),
            ] + [
                mock.call.log(
                    level=logging.DEBUG,
                    msg=self.gen_cmd_result_log_message(result)),
            ])
        self.assertIn(
            mock.call.poll(), popen_obj.mock_calls
        )

    def test_execute_mask_global(self, popen, _, select, logger):
        cmd = "USE='secret=secret_pass' do task"
        log_mask_re = r"secret\s*=\s*([A-Z-a-z0-9_\-]+)"
        masked_cmd = "USE='secret=<*masked*>' do task"
        cmd_log = u"Executing command:\n{!s}\n".format(masked_cmd)

        popen_obj, exp_result = self.prepare_close(
            popen,
            cmd=cmd,
            cmd_in_result=masked_cmd
        )
        select.return_value = [popen_obj.stdout, popen_obj.stderr], [], []

        runner = exec_helpers.Subprocess(
            log_mask_re=log_mask_re
        )

        # noinspection PyTypeChecker
        result = runner.execute(cmd)
        self.assertEqual(
            result, exp_result

        )
        popen.assert_has_calls((
            mock.call(
                args=[cmd],
                cwd=None,
                env=None,
                shell=True,
                stderr=subprocess.PIPE,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                universal_newlines=False,
            ),
        ))
        logger.assert_has_calls(
            [
                mock.call.log(level=logging.DEBUG, msg=cmd_log),
            ] + [
                mock.call.log(
                    level=logging.DEBUG,
                    msg=str(x.rstrip().decode('utf-8'))
                )
                for x in stdout_list
            ] + [
                mock.call.log(
                    level=logging.DEBUG,
                    msg=str(x.rstrip().decode('utf-8')))
                for x in stderr_list
            ] + [
                mock.call.log(
                    level=logging.DEBUG,
                    msg=self.gen_cmd_result_log_message(result)),
            ])
        self.assertIn(
            mock.call.poll(), popen_obj.mock_calls
        )

    def test_execute_mask_local(self, popen, _, select, logger):
        cmd = "USE='secret=secret_pass' do task"
        log_mask_re = r"secret\s*=\s*([A-Z-a-z0-9_\-]+)"
        masked_cmd = "USE='secret=<*masked*>' do task"
        cmd_log = u"Executing command:\n{!s}\n".format(masked_cmd)

        popen_obj, exp_result = self.prepare_close(
            popen,
            cmd=cmd,
            cmd_in_result=masked_cmd
        )
        select.return_value = [popen_obj.stdout, popen_obj.stderr], [], []

        runner = exec_helpers.Subprocess()

        # noinspection PyTypeChecker
        result = runner.execute(cmd, log_mask_re=log_mask_re)
        self.assertEqual(
            result, exp_result

        )
        popen.assert_has_calls((
            mock.call(
                args=[cmd],
                cwd=None,
                env=None,
                shell=True,
                stderr=subprocess.PIPE,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                universal_newlines=False,
            ),
        ))
        logger.assert_has_calls(
            [
                mock.call.log(level=logging.DEBUG, msg=cmd_log),
            ] + [
                mock.call.log(
                    level=logging.DEBUG,
                    msg=str(x.rstrip().decode('utf-8'))
                )
                for x in stdout_list
            ] + [
                mock.call.log(
                    level=logging.DEBUG,
                    msg=str(x.rstrip().decode('utf-8')))
                for x in stderr_list
            ] + [
                mock.call.log(
                    level=logging.DEBUG,
                    msg=self.gen_cmd_result_log_message(result)),
            ])
        self.assertIn(
            mock.call.poll(), popen_obj.mock_calls
        )


@mock.patch('exec_helpers.subprocess_runner.logger', autospec=True)
class TestSubprocessRunnerHelpers(unittest.TestCase):
    @mock.patch('exec_helpers.subprocess_runner.Subprocess.execute')
    def test_check_call(self, execute, logger):
        exit_code = 0
        return_value = exec_helpers.ExecResult(
            cmd=command,
            stdout=stdout_list,
            stderr=stdout_list,
            exit_code=exit_code,
        )
        execute.return_value = return_value

        verbose = False

        runner = exec_helpers.Subprocess()

        # noinspection PyTypeChecker
        result = runner.check_call(
            command=command, verbose=verbose, timeout=None)
        execute.assert_called_once_with(command, verbose, None)
        self.assertEqual(result, return_value)

        exit_code = 1
        return_value = exec_helpers.ExecResult(
            cmd=command,
            stdout=stdout_list,
            stderr=stdout_list,
            exit_code=exit_code,
        )
        execute.reset_mock()
        execute.return_value = return_value
        with self.assertRaises(exec_helpers.CalledProcessError):
            # noinspection PyTypeChecker
            runner.check_call(command=command, verbose=verbose, timeout=None)
        execute.assert_called_once_with(command, verbose, None)

    @mock.patch('exec_helpers.subprocess_runner.Subprocess.execute')
    def test_check_call_expected(self, execute, logger):
        exit_code = 0
        return_value = exec_helpers.ExecResult(
            cmd=command,
            stdout=stdout_list,
            stderr=stdout_list,
            exit_code=exit_code,
        )
        execute.return_value = return_value

        verbose = False

        runner = exec_helpers.Subprocess()

        # noinspection PyTypeChecker
        result = runner.check_call(
            command=command, verbose=verbose, timeout=None, expected=[0, 75])
        execute.assert_called_once_with(command, verbose, None)
        self.assertEqual(result, return_value)

        exit_code = 1
        return_value = exec_helpers.ExecResult(
            cmd=command,
            stdout=stdout_list,
            stderr=stdout_list,
            exit_code=exit_code,
        )
        execute.reset_mock()
        execute.return_value = return_value
        with self.assertRaises(exec_helpers.CalledProcessError):
            # noinspection PyTypeChecker
            runner.check_call(
                command=command, verbose=verbose, timeout=None,
                expected=[0, 75]
            )
        execute.assert_called_once_with(command, verbose, None)

    @mock.patch('exec_helpers.subprocess_runner.Subprocess.check_call')
    def test_check_stderr(self, check_call, logger):
        return_value = exec_helpers.ExecResult(
            cmd=command,
            stdout=stdout_list,
            exit_code=0,
        )
        check_call.return_value = return_value

        verbose = False
        raise_on_err = True

        runner = exec_helpers.Subprocess()

        # noinspection PyTypeChecker
        result = runner.check_stderr(
            command=command, verbose=verbose, timeout=None,
            raise_on_err=raise_on_err)
        check_call.assert_called_once_with(
            command, verbose, timeout=None,
            error_info=None, raise_on_err=raise_on_err)
        self.assertEqual(result, return_value)

        return_value = exec_helpers.ExecResult(
            cmd=command,
            stdout=stdout_list,
            stderr=stdout_list,
            exit_code=0,
        )

        check_call.reset_mock()
        check_call.return_value = return_value
        with self.assertRaises(exec_helpers.CalledProcessError):
            # noinspection PyTypeChecker
            runner.check_stderr(
                command=command, verbose=verbose, timeout=None,
                raise_on_err=raise_on_err)
        check_call.assert_called_once_with(
            command, verbose, timeout=None,
            error_info=None, raise_on_err=raise_on_err)

    @mock.patch('exec_helpers.subprocess_runner.Subprocess.check_call')
    def test_check_stdin_str(self, check_call, logger):
        stdin = u'this is a line'

        expected_result = exec_helpers.ExecResult(
            cmd=print_stdin,
            stdin=stdin,
            stdout=[stdin],
            stderr=[b''],
            exit_code=0,
        )
        check_call.return_value = expected_result

        verbose = False

        runner = exec_helpers.Subprocess()

        # noinspection PyTypeChecker
        result = runner.check_call(
            command=print_stdin,
            verbose=verbose,
            timeout=None,
            stdin=stdin)
        check_call.assert_called_once_with(
            command=print_stdin,
            verbose=verbose,
            timeout=None,
            stdin=stdin)
        self.assertEqual(result, expected_result)
        assert result == expected_result

    @mock.patch('exec_helpers.subprocess_runner.Subprocess.check_call')
    def test_check_stdin_bytes(self, check_call, logger):
        stdin = b'this is a line'

        expected_result = exec_helpers.ExecResult(
            cmd=print_stdin,
            stdin=stdin,
            stdout=[stdin],
            stderr=[b''],
            exit_code=0,
        )
        check_call.return_value = expected_result

        verbose = False

        runner = exec_helpers.Subprocess()

        # noinspection PyTypeChecker
        result = runner.check_call(
            command=print_stdin,
            verbose=verbose,
            timeout=None,
            stdin=stdin)
        check_call.assert_called_once_with(
            command=print_stdin,
            verbose=verbose,
            timeout=None,
            stdin=stdin)
        self.assertEqual(result, expected_result)
        assert result == expected_result

    @mock.patch('exec_helpers.subprocess_runner.Subprocess.check_call')
    def test_check_stdin_bytearray(self, check_call, logger):
        stdin = bytearray(b'this is a line')

        expected_result = exec_helpers.ExecResult(
            cmd=print_stdin,
            stdin=stdin,
            stdout=[stdin],
            stderr=[b''],
            exit_code=0,
        )
        check_call.return_value = expected_result

        verbose = False

        runner = exec_helpers.Subprocess()

        # noinspection PyTypeChecker
        result = runner.check_call(
            command=print_stdin,
            verbose=verbose,
            timeout=None,
            stdin=stdin)
        check_call.assert_called_once_with(
            command=print_stdin,
            verbose=verbose,
            timeout=None,
            stdin=stdin)
        self.assertEqual(result, expected_result)
        assert result == expected_result
