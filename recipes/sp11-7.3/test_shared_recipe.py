import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('sp11_73', Path(__file__).with_name('sp11_73.py'))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class SharedRelease(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.audio = self.root/'audio'
        recipe = self.audio/'recipes/sp11-7.3'
        recipe.mkdir(parents=True)
        (recipe/'release-lock.json').write_text(json.dumps({'recipe_id': 'fixture'}))
        (recipe/'recipe.py').write_text('fixture tool')
        self.lock = self.root/'shared-release.json'
        self.lock.write_text(json.dumps({
            'recipe_id': 'fixture', 'audio_commit': 'fixture-commit',
            'audio_files': {str(p.relative_to(self.audio)): hashlib.sha256(p.read_bytes()).hexdigest()
                            for p in recipe.iterdir()}}))

    def test_exact_shared_recipe_accepted(self):
        self.assertEqual(module.shared_recipe(self.audio, self.lock), self.audio/'recipes/sp11-7.3/recipe.py')

    def test_mixed_release_refused(self):
        (self.audio/'recipes/sp11-7.3/recipe.py').write_text('other release')
        with self.assertRaisesRegex(ValueError, 'shared recipe differs'):
            module.shared_recipe(self.audio, self.lock)

    def test_missing_checkout_refused(self):
        with self.assertRaisesRegex(ValueError, 'missing shared recipe'):
            module.shared_recipe(self.root/'missing', self.lock)

    def test_symlink_outside_checkout_refused(self):
        path = self.audio/'recipes/sp11-7.3/recipe.py'
        data = path.read_bytes()
        path.unlink()
        outside = self.root/'outside'
        outside.write_bytes(data)
        path.symlink_to(outside)
        with self.assertRaisesRegex(ValueError, 'missing shared recipe'):
            module.shared_recipe(self.audio, self.lock)


if __name__ == '__main__':
    unittest.main()
