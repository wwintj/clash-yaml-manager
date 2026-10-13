#!/usr/bin/env python3
"""D2 bounded, independent READ-ONLY assessment of explicit offline fixtures.

No Apply, migration, cleanup, service operations or provider override arguments.
Run only from a trusted tool checkout, never from the Package being inspected.
"""
import sys

if __name__ == '__main__':
    sys.dont_write_bytecode = True

import argparse
import hashlib
import os
import stat

from scripts import recovery_inspect as inspect, recovery_io as io, recovery_manifest as schema
from scripts import recovery_package as package
from scripts import recovery_assess_data as data, recovery_assess_evidence as evidence
from scripts.backup_audit import AuditFault

MAX_ANALYSIS_BYTES = 32 * 1024 * 1024
MAX_ANALYSIS_FILE = 8 * 1024 * 1024
MAX_REPORT_BYTES = 64 * 1024
POLICY = dict(name='same-identity-offline-assessment', version=1,
              restrictions=['SAME_HOST', 'SAME_INSTALL_PREFIX', 'EXACT_TRUSTED_APPLICATION_IDENTITY',
                            'PRESERVE_LIVE_STATE', 'PRESERVE_LIVE_ENV_AND_AUTH', 'PRESERVE_LIVE_RUNTIME',
                            'PRESERVE_LIVE_UNITS', 'PRESERVE_EXTERNAL_COMPONENTS'],
              scope='OFFLINE_SYNTHETIC_TARGET_ONLY', execution_authorized=False,
              phase_c_material_policy='UNCHANGED_SEPARATE_POLICY')


def report():
    return inspect.report() | dict(schema_version=1, ASSESSMENT_SUPPORTED=False,
        RESTORE_APPLY_IMPLEMENTED=False, code='NOT_EVALUATED', policy=POLICY,
        policy_sha256=evidence.digest(POLICY), tool=None, binding=None, evidence=[], checks=[], phases=[],
        trusted_host_facts='UNKNOWN', runtime_compatibility='UNKNOWN', state_compatibility='UNKNOWN',
        blockers=['EXTENDED_METADATA_NOT_CAPTURED', 'EXACT_FILESYSTEM_RESTORE_UNSUPPORTED',
                  'RUNTIME_CLOSURE_UNKNOWN', 'RESTORE_APPLY_NOT_IMPLEMENTED'])


def check(result, name, status, origin, reason):
    schema.require(origin in evidence.ORIGINS, 'INVALID_EVIDENCE')
    schema.require(len(result['checks']) < 128, 'ANALYSIS_ENTRY_LIMIT')
    result['checks'].append(dict(check=name, status=status, origin=origin, reason=reason))


def target_data(path, budget):
    # Reuse Phase C's full admission/content checks. Never resolve install_path from JSON.
    environment, _ = inspect.read_target(path, budget)
    files, hashes = {}, {}
    with io.absolute_directory(path) as root:
        before = inspect.inventory(root, budget, target=True)
        for name, fingerprint in before.items():
            if not name or not stat.S_ISREG(fingerprint[2]):
                continue
            with io.at(root, name.split('/')[:-1]) as parent:
                raw, _, digest = io.stream(parent, name.split('/')[-1], budget, stored=True,
                                          limit=inspect.MAX_TARGET_BYTES)
            hashes[name] = digest
            if name.startswith(('state/', 'outputs/')):
                files[name] = raw
        schema.require(before == inspect.inventory(root, budget, target=True), 'OBJECT_CHANGED')
    # The environment may have changed between the Phase C read and our descriptor observation.
    schema.require(hashes.get('environment.json') == evidence.digest(environment), 'OBJECT_CHANGED')
    return environment, files, dict(inventory=before, content=hashes)


def material(package_fd, manifest, budget):
    files, total = {}, 0
    with io.child_directory(package_fd, 'blobs', stored=True) as blobs:
        for entry in manifest['entries']:
            budget.tick()
            if entry['kind'] != 'file':
                continue
            path = entry['path']
            selected = (path.startswith('state/') or path == 'venv/pyvenv.cfg'
                        or path.startswith('venv/bin/') or path.endswith(('/WHEEL', '/METADATA', '.pth', '.so'))
                        or path.endswith(('/sitecustomize.py', '/usercustomize.py')))
            if not selected:
                continue
            total += entry['size']
            schema.require(total <= MAX_ANALYSIS_BYTES, 'ANALYSIS_BYTE_LIMIT')
            raw, _, digest = io.stream(blobs, entry['blob'], budget, stored=True, limit=MAX_ANALYSIS_FILE)
            schema.require(digest == entry['sha256'], 'CONTENT_DIGEST_MISMATCH')
            files[path] = raw
    return files


def runtime_checks(files, manifest, environment, result):
    declared, target = manifest['runtime_requirements'], environment['runtime']
    for key in ('os', 'architecture', 'python_version', 'python_abi'):
        value = target[key]
        if value is None:
            check(result, 'target_' + key, 'UNKNOWN', 'SYNTHETIC_DECLARED', 'TARGET_RUNTIME_NOT_OBSERVED')
        else:
            code = 'PYTHON_ABI_MISMATCH' if key == 'python_abi' else 'RUNTIME_IDENTITY_MISMATCH'
            schema.require(value == declared[key], code)
            check(result, 'target_' + key, 'DECLARATIONS_AGREE', 'SYNTHETIC_DECLARED',
                  'NOT_TRUSTED_HOST_OR_RUNTIME_CLOSURE')
    data.venv_config(files['venv/pyvenv.cfg'], declared)
    check(result, 'pyvenv_cfg', 'PARTIAL', 'STATIC_DERIVED_FACT', 'CFG_NOT_BASE_INTERPRETER_PROVENANCE')
    external = schema.resolve_links(manifest['entries'])
    schema.require({link['target'] for link in external} <= set(environment['external_python']), 'BROKEN_EXTERNAL_LINK')
    check(result, 'python_links', 'PARTIAL', 'VERIFIED_PACKAGE_FACT', 'EXTERNAL_TARGETS_ONLY_DECLARED')
    for path, raw in files.items():
        if not path.startswith('venv/'):
            continue
        if path.endswith('/WHEEL'):
            tags = data.wheel(raw)
            # Coarse tag agreement is data-only and cannot certify a loader or CPU closure.
            version = 'cp' + ''.join(declared['python_version'].split('.')[:2])
            for tag in tags:
                interpreter, abi, platform = tag.split('-')
                schema.require(interpreter in ('py3', version) and abi in ('none', 'abi3', version),
                               'WHEEL_ABI_MISMATCH')
                if platform != 'any':
                    schema.require(declared['architecture'] in platform, 'WHEEL_PLATFORM_MISMATCH')
                    schema.require(declared['os'] == 'Linux' and platform.startswith(
                        ('linux_', 'manylinux', 'musllinux')), 'WHEEL_PLATFORM_MISMATCH')
            check(result, 'wheel_tags', 'PARTIAL', 'STATIC_DERIVED_FACT', 'TAGS_NOT_RUNTIME_CLOSURE')
        elif path.endswith('/METADATA'):
            value = data.text(raw)
            headers = value.split('\n\n', 1)[0].splitlines()
            for key in ('Metadata-Version', 'Name', 'Version'):
                schema.require(sum(line.startswith(key + ': ') for line in headers) == 1, 'INVALID_WHEEL_METADATA')
            check(result, 'distribution_metadata', 'PARTIAL', 'STATIC_DERIVED_FACT', 'SELF_REPORTED_NOT_RELEASE_PROVENANCE')
        elif path.endswith('.so') or path in ('venv/bin/python', 'venv/bin/python3'):
            schema.require(declared['os'] == 'Linux', 'UNSUPPORTED_NATIVE_FORMAT')
            data.elf(raw, declared['architecture'])
            check(result, 'native_header', 'PARTIAL', 'STATIC_DERIVED_FACT', 'DYNAMIC_DEPENDENCIES_UNKNOWN')
        elif path.endswith(('/sitecustomize.py', '/usercustomize.py')):
            schema.require(False, 'EXECUTABLE_STARTUP_UNSUPPORTED')
        elif path.endswith('.pth') or path.startswith('venv/bin/'):
            data.startup_data(raw, '.pth' if path.endswith('.pth') else 'script', environment['install_path'])
            check(result, 'startup_configuration', 'UNKNOWN', 'STATIC_DERIVED_FACT', 'DATA_NOT_EXECUTED')
    check(result, 'system_libraries_cpu_loader', 'UNKNOWN', 'UNKNOWN', 'FULL_DYNAMIC_RUNTIME_CLOSURE_NOT_IMPLEMENTED')


def assess(selected, target):
    result = report()
    try:
        budget = io.Budget()
        result['tool'] = evidence.tool_binding(budget)
        result['phases'].append('PACKAGE_VERIFICATION_STARTED')
        with package.managed() as (packages, records):
            operation = inspect.select(packages, records, selected, budget)
            manifest, _ = inspect.inspect_fd(packages, records, operation, budget)
            result['phases'].append('PACKAGE_VERIFIED')
            record_info = os.stat(operation + '.json', dir_fd=records, follow_symlinks=False)
            record_raw, _, record_digest = io.stream(records, operation + '.json', budget,
                                                     expected=record_info, stored=True, limit=32 * 1024)
            record = package.validate_record(schema.parse(record_raw))
            environment, current, target_before = target_data(target, budget)
            result['phases'].append('TARGET_VALIDATED')
            schema.require(environment['current_identity'] == manifest['source_identity'], 'CROSS_VERSION_NOT_PROVEN')
            schema.require(environment['install_path'] == manifest['installation_binding']['install_path'],
                           'INSTALL_PREFIX_MISMATCH')
            observed = evidence.ProcessHostFactsProvider().observe()
            result['evidence'].append(evidence.summarize(observed))
            check(result, 'process_host_runtime', 'PARTIAL', observed['origin'],
                  'THIS_PROCESS_NOT_SYNTHETIC_TARGET_SERVICE_RUNTIME')
            result['trusted_host_facts'] = 'PARTIAL'
            check(result, 'captured_runtime', 'DECLARED', 'OPERATOR_DECLARED', 'ROOT_OPERATOR_DECLARATION_NOT_OBSERVATION')
            check(result, 'target_environment', 'DECLARED', 'SYNTHETIC_DECLARED', 'EXPLICIT_OFFLINE_FIXTURE_NOT_PRODUCTION')
            with io.child_directory(packages, operation, stored=True) as package_fd:
                files = material(package_fd, manifest, budget)
                result['phases'].append('RUNTIME_ANALYSIS_STARTED')
                runtime_checks(files, manifest, environment, result)
                result['phases'].append('RUNTIME_DATA_ANALYZED')
                result['phases'].append('STATE_ANALYSIS_STARTED')
                data.state_checks(current, files)
                result['phases'].append('STATE_DATA_ANALYZED')
            check(result, 'state_closure', 'PARTIAL', 'STATIC_DERIVED_FACT', 'OPAQUE_YAML_AND_COMPLETE_BUSINESS_SEMANTICS_UNKNOWN')
            check(result, 'auth_env', 'UNKNOWN', 'UNKNOWN', 'LIVE_ENV_PRESERVED_NOT_PARSED_OR_AUTHENTICATED')
            release = evidence.PinnedLocalReleaseProvider().observe(manifest['source_identity'], budget)
            result['evidence'].append(evidence.summarize(release))
            if release['origin'] == 'VERIFIED_TRUSTED_RELEASE_FACT':
                application = {entry['path']: entry['sha256'] for entry in manifest['entries']
                               if entry['kind'] == 'file' and entry['role'] == 'APPLICATION'
                               and entry['path'] != 'application/INSTALLATION.json'}
                schema.require(application == release['application'], 'TRUSTED_APPLICATION_MISMATCH')
                check(result, 'application_provenance', 'VERIFIED', release['origin'], 'INDEPENDENT_ACCEPTED_RELEASE_PIN_AND_LOCAL_GIT_OBJECTS')
            else:
                check(result, 'application_provenance', 'UNKNOWN', 'UNKNOWN', 'INDEPENDENT_TRUSTED_RELEASE_UNAVAILABLE')
                result['blockers'].append('EXACT_TRUSTED_APPLICATION_IDENTITY_NOT_PROVEN')
            check(result, 'same_host', 'UNKNOWN', 'OPERATOR_DECLARED', 'CAPTURE_HOST_BINDING_NOT_INDEPENDENTLY_OBSERVED')
            result['blockers'].append('SAME_HOST_BINDING_NOT_PROVEN')
            check(result, 'extended_metadata', 'UNSUPPORTED', 'UNSUPPORTED', 'EXTENDED_METADATA_NOT_CAPTURED')
            result['phases'].append('FINAL_REVALIDATION_REACHED')
            final_env, _, target_after = target_data(target, budget)
            schema.require(environment == final_env and target_before == target_after, 'OBJECT_CHANGED')
            final, _ = inspect.inspect_fd(packages, records, operation, budget)
            schema.require(final == manifest, 'OBJECT_CHANGED')
            again, _, _ = io.stream(records, operation + '.json', budget, expected=record_info,
                                    stored=True, limit=32 * 1024)
            schema.require(again == record_raw, 'OBJECT_CHANGED')
            binding = dict(operation_id=operation, package=dict(device=record['package_device'], inode=record['package_inode']),
                           record=dict(device=record_info.st_dev, inode=record_info.st_ino, sha256=record_digest),
                           manifest_sha256=record['manifest_sha256'], target_identity=environment['current_identity'],
                           target_evidence_sha256=evidence.digest(target_before), acquired_at=evidence.now())
        # Only publish integrity flags AFTER every inherited FD exit revalidation.
        result['phases'].append('EXIT_REVALIDATION_COMPLETED')
        result.update({flag: True for flag in inspect.FLAGS[:4]})
        result.update(code='ASSESSMENT_BLOCKED', operation_id=operation, binding=binding,
                      runtime_compatibility='PARTIAL', state_compatibility='PARTIAL')
        # Offline fixture statements do not prove SAME_HOST. Completion is not sufficient admission.
        schema.require(result['tool'] == evidence.tool_binding(budget), 'TOOL_CHANGED')
        render(result)
    except (AuditFault, OSError) as error:
        result.update({flag: False for flag in inspect.FLAGS})
        result.update(ASSESSMENT_SUPPORTED=False, code=package.error_code(error), binding=None,
                      runtime_compatibility='BLOCKED', state_compatibility='BLOCKED')
        if result['code'] == 'REPORT_BYTE_LIMIT':
            result['checks'] = []
            result['evidence'] = []
        if result['phases'] and result['phases'][-1] == 'FINAL_REVALIDATION_REACHED':
            result['phases'].append('FINAL_REVALIDATION_REJECTED')
    return result


def render(result):
    raw = schema.canonical(result)
    schema.require(len(raw) <= MAX_REPORT_BYTES, 'REPORT_BYTE_LIMIT')
    return raw


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    choice = parser.add_mutually_exclusive_group(required=True)
    choice.add_argument('--id'); choice.add_argument('--latest', action='store_true')
    parser.add_argument('--target-fixture', required=True)
    args = parser.parse_args(argv)
    result = assess('latest' if args.latest else args.id, args.target_fixture)
    print(render(result).decode('ascii'))
    return 0 if result['ASSESSMENT_SUPPORTED'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
