import os
import unittest
from parameterized import parameterized
from pathlib import Path
import shutil
from cli_test_utils import run_cli
from agentstack import conf
from agentstack import frameworks
from agentstack.templates import get_all_templates

BASE_PATH = Path(__file__).parent


class CLIInitTest(unittest.TestCase):
    def setUp(self):
        self.framework = os.getenv('TEST_FRAMEWORK')
        self.project_dir = BASE_PATH / 'tmp' / self.framework / 'test_repo'
        os.chdir(str(BASE_PATH))  # Change directory before cleanup to avoid Windows file locks

        # Clean up any existing test directory
        if self.project_dir.exists():
            shutil.rmtree(self.project_dir, ignore_errors=True)

        os.makedirs(self.project_dir, exist_ok=True)
        os.chdir(self.project_dir)  # gitpython needs a cwd

        # Force UTF-8 encoding for the test environment
        os.environ['PYTHONIOENCODING'] = 'utf-8'

    def tearDown(self):
        shutil.rmtree(self.project_dir, ignore_errors=True)

    @parameterized.expand([(template.name,) for template in get_all_templates()])
    def test_init_command(self, template_name: str):
        """Test the 'init' command to create a project directory."""
        result = run_cli('init', 'test_project', '--template', template_name)
        self.assertEqual(result.returncode, 0)
        self.assertTrue((self.project_dir / 'test_project').exists())

    @parameterized.expand([(k, v) for k, v in frameworks.ALIASED_FRAMEWORKS.items()])
    def test_init_command_aliased_framework_empty_project(self, alias: str, framework: str):
        """Test the 'init' command with an aliased framework."""
        if framework != self.framework:
            self.skipTest(f"{alias} is not related to this framework")

        result = run_cli('init', 'test_project', '--template', 'empty', '--framework', alias)
        self.assertEqual(result.returncode, 0)

        # Verify the framework was set correctly
        conf.set_path(self.project_dir / 'test_project')
        config = conf.ConfigFile()
        self.assertEqual(config.framework, framework)
