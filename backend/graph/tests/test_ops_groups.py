import importlib.util
import pathlib
import subprocess
import tempfile
import unittest


def _load(name):
    path = pathlib.Path(__file__).resolve().parents[1] / (name + '.py')
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


og = _load('ops_groups')
core = og.core


def git(root, *args):
    return subprocess.run(['git', '-C', str(root), *args], capture_output=True, text=True).stdout.strip()


def write(root, name, text):
    path = pathlib.Path(root, name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode('utf-8'))


class GroupTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self._tmp.name) / 'proj'
        self.root.mkdir()
        git(self.root, 'init', '-q', '-b', 'feat/x')
        git(self.root, 'config', 'user.email', 't@t.t')
        git(self.root, 'config', 'user.name', 'T')
        git(self.root, 'config', 'core.autocrlf', 'false')
        write(self.root, 'README.txt', 'base\n')
        git(self.root, 'add', '-A')
        git(self.root, 'commit', '-qm', 'base')

    def tearDown(self):
        self._tmp.cleanup()

    def _edit(self):
        write(self.root, 'backend/graph/ops_core.py', 'a = 1\n')
        write(self.root, 'backend/graph/tests/test_ops_core.py', 't = 1\n')
        write(self.root, 'backend/api/services.py', 's = 1\n')
        write(self.root, 'docs/09.md', '# doc\n')
        write(self.root, '.env', 'T=1\n')

    def test_groups_by_folder_tests_with_code_docs_last(self):
        self._edit()
        groups, skipped = og.group_changes(core.git_changes(self.root))
        by_label = {g['label']: g['paths'] for g in groups}
        self.assertEqual(skipped, ['.env'])
        self.assertEqual(sorted(by_label['backend/graph']), ['backend/graph/ops_core.py', 'backend/graph/tests/test_ops_core.py'])
        self.assertEqual(by_label['backend/api'], ['backend/api/services.py'])
        self.assertEqual(groups[-1]['label'], 'docs')
        text = og.format_groups(groups, skipped, 'feat/x')
        self.assertIn('Grupo 1:', text)
        self.assertIn('.env', text)

    def test_big_folder_splits_by_prefix_and_respects_limit(self):
        for n in range(6):
            write(self.root, f'pkg/alpha_{n}.py', 'x = 1\n')
            write(self.root, f'pkg/beta_{n}.py', 'x = 1\n')
        write(self.root, 'pkg/solo.py', 'x = 1\n')
        groups, _ = og.group_changes(core.git_changes(self.root))
        labels = [g['label'] for g in groups]
        self.assertTrue(any('[alpha]' in l for l in labels))
        self.assertTrue(any('[beta]' in l for l in labels))
        self.assertTrue(all(len(g['paths']) <= og.MAX_GROUP for g in groups))
        self.assertEqual(sum(len(g['paths']) for g in groups), 13)

    def test_commit_groups_makes_one_commit_per_group(self):
        self._edit()
        result = og.commit_groups(self.root, [
            {'paths': ['backend/graph/ops_core.py', 'test_ops_core.py'], 'message': 'feat: ops core'},
            {'paths': ['services.py'], 'message': 'fix: services'},
            {'paths': ['docs/09.md'], 'message': 'docs: chat ops'},
        ])
        self.assertIn('git reset --soft HEAD~3', result)
        self.assertEqual(git(self.root, 'rev-list', '--count', 'HEAD'), '4')
        self.assertEqual(git(self.root, 'log', '--format=%s', '-3').splitlines(), ['docs: chat ops', 'fix: services', 'feat: ops core'])
        self.assertEqual(sorted(git(self.root, 'show', '--name-only', '--format=', 'HEAD~2').split()),
                         ['backend/graph/ops_core.py', 'backend/graph/tests/test_ops_core.py'])
        self.assertIn('.env', git(self.root, 'status', '--porcelain'))
        self.assertIn('Ficaram sem commit', result)

    def test_invalid_group_makes_no_commit(self):
        self._edit()
        bad = [
            [{'paths': ['services.py'], 'message': 'ok'}, {'paths': ['nao_existe.py'], 'message': 'x'}],
            [{'paths': ['services.py'], 'message': 'ok'}, {'paths': ['docs/09.md'], 'message': ' '}],
            [{'paths': ['services.py'], 'message': 'ok'}, {'paths': ['.env'], 'message': 'x'}],
            [{'paths': ['services.py'], 'message': 'ok'}, {'paths': ['services.py'], 'message': 'dup'}],
            [],
        ]
        for groups in bad:
            self.assertTrue(og.commit_groups(self.root, groups).startswith('ERRO'))
        self.assertEqual(git(self.root, 'rev-list', '--count', 'HEAD'), '1')

    def test_protected_branch(self):
        self._edit()
        git(self.root, 'checkout', '-q', '-b', 'main')
        self.assertIn('protegida', og.commit_groups(self.root, [{'paths': ['services.py'], 'message': 'x'}]))


if __name__ == '__main__':
    unittest.main()
