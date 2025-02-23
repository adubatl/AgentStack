import os
import sys
from typing import Callable
from pathlib import Path
import re
import subprocess
import site
from packaging.requirements import Requirement
from agentstack import conf, log


DEFAULT_PYTHON_VERSION = "3.12"
VENV_DIR_NAME: Path = Path(".venv")

# filter uv output by these words to only show useful progress messages
RE_UV_PROGRESS = re.compile(r'^(Resolved|Prepared|Installed|Uninstalled|Audited)')


# When calling `uv` we explicitly specify the --python executable to use so that
# the packages are installed into the correct virtual environment.
# In testing, when this was not set, packages could end up in the pyenv's
# site-packages directory; it's possible an environment variable can control this.
def _get_executeable_paths():
    """Get environment paths based on platform."""
    python_path = '.venv/Scripts/python.exe' if sys.platform == 'win32' else '.venv/bin/python'
    venv_path = conf.PATH / VENV_DIR_NAME.absolute()
    venv_bin_dir = venv_path / ('Scripts' if sys.platform == 'win32' else 'bin')
    return venv_path, venv_bin_dir, python_path


PYTHON_EXECUTABLE, VENV_PATH, VENV_BIN_DIR = _get_executeable_paths()


def install(package: str):
    """Install a package with `uv` and add it to pyproject.toml."""
    global PYTHON_EXECUTABLE
    from agentstack.cli.spinner import Spinner

    def on_progress(line: str):
        if RE_UV_PROGRESS.match(line):
            spinner.clear_and_log(line.strip(), 'info')

    def on_error(line: str):
        log.error(f"uv: [error]\n {line.strip()}")

    with Spinner(f"Installing {package}") as spinner:
        _wrap_command_with_callbacks(
            [get_uv_bin(), 'add', '--python', PYTHON_EXECUTABLE, package],
            on_progress=on_progress,
            on_error=on_error,
        )


def install_project():
    """Install all dependencies for the user's project."""
    global PYTHON_EXECUTABLE
    from agentstack.cli.spinner import Spinner

    def on_progress(line: str):
        if RE_UV_PROGRESS.match(line):
            spinner.clear_and_log(line.strip(), 'info')
        # Add more detailed logging for dependency installation
        elif 'Installing' in line or 'Collecting' in line:
            spinner.clear_and_log(f"📦 {line.strip()}", 'info')
        elif 'Successfully' in line:
            spinner.clear_and_log(f"✅ {line.strip()}", 'success')
        elif 'ERROR' in line.upper() or 'WARNING' in line.upper():
            spinner.clear_and_log(f"⚠️  {line.strip()}", 'warning')

    def on_error(line: str):
        log.error(f"UV installation error:\n{line.strip()}")
        spinner.clear_and_log(f"❌ Installation error: {line.strip()}", 'error')

    try:
        with Spinner("Installing project dependencies...") as spinner:
            spinner.clear_and_log("🔍 Resolving dependencies...", 'info')
            result = _wrap_command_with_callbacks(
                [get_uv_bin(), 'pip', 'install', '--python', PYTHON_EXECUTABLE, '.'],
                on_progress=on_progress,
                on_error=on_error,
            )
            if result is False:
                spinner.clear_and_log(
                    "⚠️  Initial installation failed, retrying with --no-cache flag...", 'warning'
                )
                result = _wrap_command_with_callbacks(
                    [get_uv_bin(), 'pip', 'install', '--no-cache', '--python', PYTHON_EXECUTABLE, '.'],
                    on_progress=on_progress,
                    on_error=on_error,
                )
                if result is False:
                    raise Exception("Installation failed even with --no-cache")
            else:
                spinner.clear_and_log("✨ All dependencies installed successfully!", 'success')
    except Exception as e:
        log.error(f"❌ Installation failed: {str(e)}")
        raise


def remove(package: str):
    """Uninstall a package with `uv`."""
    # If `package` has been provided with a version, it will be stripped.
    requirement = Requirement(package)

    # TODO it may be worth considering removing unused sub-dependencies as well
    def on_progress(line: str):
        if RE_UV_PROGRESS.match(line):
            log.info(line.strip())

    def on_error(line: str):
        log.error(f"uv: [error]\n {line.strip()}")

    log.info(f"Uninstalling {requirement.name}")
    _wrap_command_with_callbacks(
        [get_uv_bin(), 'remove', '--python', PYTHON_EXECUTABLE, requirement.name],
        on_progress=on_progress,
        on_error=on_error,
    )


def upgrade(package: str, use_venv: bool = True):
    """Upgrade a package with `uv`."""

    # TODO should we try to update the project's pyproject.toml as well?
    def on_progress(line: str):
        if RE_UV_PROGRESS.match(line):
            log.info(line.strip())

    def on_error(line: str):
        log.error(f"uv: [error]\n {line.strip()}")

    extra_args = []
    if not use_venv:
        # uv won't let us install without a venv if we don't specify a target
        extra_args = ['--target', site.getusersitepackages()]

    log.info(f"Upgrading {package}")
    _wrap_command_with_callbacks(
        [get_uv_bin(), 'pip', 'install', '-U', '--python', PYTHON_EXECUTABLE, *extra_args, package],
        on_progress=on_progress,
        on_error=on_error,
        use_venv=use_venv,
    )


def create_venv(python_version: str = DEFAULT_PYTHON_VERSION):
    """Initialize a virtual environment in the project directory of one does not exist."""
    if os.path.exists(conf.PATH / VENV_DIR_NAME):
        return  # venv already exists

    RE_VENV_PROGRESS = re.compile(r'^(Using|Creating)')

    def on_progress(line: str):
        if RE_VENV_PROGRESS.match(line):
            log.info(line.strip())

    def on_error(line: str):
        log.error(f"uv: [error]\n {line.strip()}")

    _wrap_command_with_callbacks(
        [get_uv_bin(), 'venv', '--python', python_version],
        on_progress=on_progress,
        on_error=on_error,
    )


def get_uv_bin() -> str:
    """Find the path to the uv binary."""
    try:
        import uv

        return uv.find_uv_bin()
    except ImportError as e:
        raise e


def _setup_env() -> dict[str, str]:
    """Copy the current environment and add the virtual environment path for use by a subprocess."""
    env = os.environ.copy()

    env["VIRTUAL_ENV"] = str(VENV_PATH)
    env["UV_INTERNAL__PARENT_INTERPRETER"] = sys.executable

    return env


def _wrap_command_with_callbacks(
    command: list[str],
    on_progress: Callable[[str], None] = lambda x: None,
    on_complete: Callable[[str], None] = lambda x: None,
    on_error: Callable[[str], None] = lambda x: None,
    use_venv: bool = True,
) -> bool:
    """Run a command with progress callbacks. Returns bool for cmd success."""
    process = None
    try:
        all_lines = ''
        log.debug(f"Running command: {' '.join(command)}")

        process = subprocess.Popen(
            command,
            cwd=conf.PATH.absolute(),
            env=_setup_env(),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        assert process.stdout and process.stderr  # appease type checker

        # Read output with timeout
        try:
            while process.poll() is None:
                try:
                    stdout, stderr = process.communicate(timeout=1.0)
                    if stdout:
                        on_progress(stdout)
                        all_lines += stdout
                    if stderr:
                        on_progress(stderr)
                        all_lines += stderr
                except subprocess.TimeoutExpired:
                    continue
                except Exception as e:
                    log.error(f"Error reading output: {e}")
                    break

            # Get any remaining output
            stdout, stderr = process.communicate()
            if stdout:
                on_progress(stdout)
                all_lines += stdout
            if stderr:
                on_progress(stderr)
                all_lines += stderr

        except Exception as e:
            log.error(f"Error during output reading: {e}")
            process.kill()
            raise

        return_code = process.wait()
        log.debug(f"Process completed with return code: {return_code}")

        if return_code == 0:
            on_complete(all_lines)
            return True
        else:
            error_msg = f"Process failed with return code {return_code}"
            log.error(error_msg)
            on_error(all_lines)
            return False
    except Exception as e:
        error_msg = f"Exception running command: {str(e)}"
        log.error(error_msg)
        on_error(error_msg)
        return False
    finally:
        if process:
            try:
                process.terminate()
            except Exception as e:
                log.error(f"Error terminating process: {e}")
