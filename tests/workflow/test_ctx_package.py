"""Failure-oriented archive adapter tests. Synthetic tools are not CI scan evidence."""
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts'))
import ctx_package as package
from test_ctx_source_security import ENV

IMAGE_ID = 'sha256:' + 'b' * 64
LOADED_ID = 'sha256:' + 'd' * 64
TAG = 'habitat-ci:' + ENV['CTX_SOURCE_SHA'] + '-' + ENV['CI_PIPELINE_ID'] + '-' + ENV['CI_JOB_ID']


class PackageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        (self.root / 'backend/aicl').mkdir(parents=True)
        (self.root / 'backend/aicl/app.py').write_text('app = object()\n')
        (self.root / 'backend/requirements.lock').write_text('demo==1 --hash=sha256:' + 'a' * 64)
        (self.root / 'Dockerfile').write_text('FROM example@sha256:' + 'a' * 64)
        config = json.dumps({'architecture': 'amd64', 'os': 'linux',
                             'config': {'Labels': {'org.opencontainers.image.revision': ENV['CTX_SOURCE_SHA']}}}).encode()
        self.config_id = 'sha256:' + hashlib.sha256(config).hexdigest()
        stream = io.BytesIO()
        with tarfile.open(fileobj=stream, mode='w') as archive:
            for name, data in [('manifest.json', json.dumps([{'Config': 'config.json', 'RepoTags': [TAG]}]).encode()), ('config.json', config)]:
                member = tarfile.TarInfo(name)
                member.size = len(data)
                archive.addfile(member, io.BytesIO(data))
        self.archive_bytes = stream.getvalue()
        self.calls = []
        self.loaded_secret_file = None
        self.report = {'SchemaVersion': 2, 'ArtifactType': 'container_image',
                       'Metadata': {'ImageID': self.config_id, 'OS': {'Family': 'debian', 'Name': '13'}},
                       'Results': [{'Class': 'os-pkgs', 'Type': 'debian', 'Vulnerabilities': []},
                                   {'Class': 'lang-pkgs', 'Type': 'python-pkg', 'Vulnerabilities': []}]}
        self.patcher = patch.object(package, 'run', side_effect=self.tool)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        self.version = patch.object(package, 'check_version')
        self.version.start()
        self.addCleanup(self.version.stop)

    def tool(self, argv, root, env, **kwargs):
        self.calls.append(argv)
        if argv[:3] == ['docker', 'image', 'inspect']:
            return subprocess.CompletedProcess(argv, 0, stdout=LOADED_ID + '\n', stderr='')
        if argv[:2] == ['docker', 'build']:
            Path(argv[argv.index('--iidfile') + 1]).write_text(IMAGE_ID)
        elif argv[:2] == ['docker', 'save']:
            Path(argv[argv.index('--output') + 1]).write_bytes(self.archive_bytes)
        elif argv[0] == 'trivy':
            output = Path(argv[argv.index('--output') + 1])
            report = ({'bomFormat': 'CycloneDX', 'components': [{'type': 'library', 'name': 'demo'}]}
                      if argv[argv.index('--format') + 1] == 'cyclonedx' else self.report)
            output.write_text(json.dumps(report))
        elif argv[:2] == ['docker', 'run']:
            self.loaded_secret_file = Path(argv[argv.index('--env-file') + 1])
            contents = self.loaded_secret_file.read_text()
            self.assertIn('AICL_SESSION_SECRET=', contents)
            self.assertEqual(self.loaded_secret_file.stat().st_mode & 0o777, 0o600)
            self.assertEqual(argv[argv.index('--network') + 1], 'none')
            self.assertIn('--read-only', argv)
            self.assertIn(LOADED_ID, argv)
            self.assertIn('--pull=never', argv)
            self.assertNotIn('AICL_SESSION_SECRET=', ' '.join(argv))
        return subprocess.CompletedProcess(argv, 0, stdout='', stderr='')

    def packaged(self):
        evidence = package.package(self.root, ENV)
        package.write_json(self.root, '.ctx/reports/package.json', {
            'step': 'package', 'status': 'passed', 'source_sha': ENV['CTX_SOURCE_SHA'],
            'project_id': ENV['CI_PROJECT_ID'], 'pipeline_id': ENV['CI_PIPELINE_ID'], 'evidence': evidence})
        return evidence

    def test_build_scan_and_configuration_share_immutable_archive_and_ephemeral_secrets(self):
        evidence = self.packaged()
        self.assertEqual(evidence['image_id'], IMAGE_ID)
        self.assertEqual(evidence['image_config_id'], self.config_id)
        self.assertEqual(evidence['artifact_digest'], package.file_digest(self.root / package.ARCHIVE))
        scan = package.artifact_security(self.root, ENV)
        self.assertTrue(scan['passed'])
        self.assertEqual(scan['artifact_digest'], evidence['artifact_digest'])
        result = package.configure(self.root, ENV)
        self.assertTrue(result['passed'])
        self.assertTrue(result['validation_only'])
        self.assertFalse(result['applied'])
        self.assertFalse(self.loaded_secret_file.exists())
        config = package.read_json(self.root / result['configuration_path'])
        self.assertEqual(config['image_id'], IMAGE_ID)
        self.assertEqual(config['validated_image_id'], LOADED_ID)
        self.assertEqual(set(config['secret_references']), set(package.SECRET_NAMES))
        self.assertFalse(set(config['env']) & set(package.SECRET_NAMES))
        self.assertIn('cloud provisioning', config['not_verified'])

    def test_cross_pipeline_tampered_archive_and_sbom_are_rejected_before_execution(self):
        evidence = self.packaged()
        for key in ('CTX_SOURCE_SHA', 'CI_PROJECT_ID', 'CI_PIPELINE_ID'):
            with self.assertRaisesRegex(package.Blocked, 'another candidate or pipeline'):
                package.prior_package(self.root, {**ENV, key: '9'})
        archive = self.root / package.ARCHIVE
        archive.write_bytes(b'altered')
        with self.assertRaisesRegex(package.Blocked, 'archive digest'):
            package.prior_package(self.root, ENV)
        archive.write_bytes(self.archive_bytes)
        (self.root / package.SBOM).write_text('{}')
        with self.assertRaisesRegex(package.Blocked, 'SBOM digest'):
            package.prior_package(self.root, ENV)
        self.assertNotEqual(evidence['sbom_sha256'], package.file_digest(self.root / package.SBOM))

    def test_missing_package_coverage_wrong_image_and_any_vulnerability_block(self):
        self.packaged()
        self.report['Metadata']['ImageID'] = 'sha256:' + 'c' * 64
        with self.assertRaisesRegex(package.Blocked, 'another image'):
            package.artifact_security(self.root, ENV)
        self.report['Metadata']['ImageID'] = self.config_id
        python = self.report['Results'].pop()
        with self.assertRaisesRegex(package.Blocked, 'Python packages'):
            package.artifact_security(self.root, ENV)
        self.report['Results'].append(python)
        self.report['Results'][0]['Vulnerabilities'] = [{'VulnerabilityID': 'CVE-fixture', 'PkgName': 'demo',
                                                        'InstalledVersion': '1', 'Severity': 'LOW'}]
        with self.assertRaisesRegex(package.Blocked, 'blocking container vulnerabilities'):
            package.artifact_security(self.root, ENV)
        report = package.read_json(self.root / '.ctx/security/gl-container-scanning-report.json')
        self.assertEqual(report['vulnerabilities'][0]['severity'], 'Low')
        self.assertEqual(report['vulnerabilities'][0]['location']['image'], self.config_id)

    def test_archive_requires_the_exact_source_label_and_a_single_image(self):
        self.packaged()
        with self.assertRaisesRegex(package.Blocked, 'another source candidate'):
            package.archive_config_id(self.root / package.ARCHIVE, 'c' * 40)
        with tarfile.open(self.root / package.ARCHIVE, 'a') as archive:
            payload = b'[]'
            member = tarfile.TarInfo('manifest.json')
            member.size = len(payload)
            archive.addfile(member, io.BytesIO(payload))
        with self.assertRaisesRegex(package.Blocked, 'duplicate archive metadata'):
            package.archive_config_id(self.root / package.ARCHIVE, ENV['CTX_SOURCE_SHA'])


    def test_failed_build_cannot_reuse_prior_archive_and_runtime_failure_never_passes(self):
        self.packaged()
        with patch.object(package, 'run', side_effect=package.Blocked('tool failed')):
            with self.assertRaisesRegex(package.Blocked, 'tool failed'):
                package.package(self.root, ENV)
        self.assertFalse((self.root / package.ARCHIVE).exists())
        self.packaged()
        def fail_runtime(argv, *args, **kwargs):
            if argv[:2] == ['docker', 'run']:
                raise package.Blocked('runtime failed')
            return self.tool(argv, *args, **kwargs)
        with patch.object(package, 'run', side_effect=fail_runtime):
            with self.assertRaisesRegex(package.Blocked, 'runtime failed'):
                package.configure(self.root, ENV)


if __name__ == '__main__':
    unittest.main()
