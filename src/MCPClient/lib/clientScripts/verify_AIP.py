#!/usr/bin/env python2
from __future__ import print_function
import os
from pprint import pformat
import shutil
import sys

import django
django.setup()
from django.conf import settings as mcpclient_settings

# archivematicaCommon
from archivematicaFunctions import get_setting
from custom_handlers import get_script_logger
import databaseFunctions
from executeOrRunSubProcess import executeOrRun

from main.models import File


class VerifyChecksumsError(Exception):
    """Checksum verification has failed."""


def extract_aip(aip_path, extract_path):
    os.makedirs(extract_path)
    command = "atool --extract-to={} -V0 {}".format(extract_path, aip_path)
    print('Running extraction command:', command)
    exit_code, _, _ = executeOrRun("command", command, printing=True)
    if exit_code != 0:
        raise Exception("Error extracting AIP")

    aip_identifier, ext = os.path.splitext(os.path.basename(aip_path))
    if ext in ('.bz2', '.gz'):
        aip_identifier, _ = os.path.splitext(aip_identifier)
    return os.path.join(extract_path, aip_identifier)


def write_premis_event(sip_uuid, checksum_type, event_outcome,
                       event_outcome_detail_note):
    """Write the AIP-level "fixity check" PREMIS event."""
    try:
        databaseFunctions.insertIntoEvents(
            fileUUID=sip_uuid,
            eventType='fixity check',
            eventDetail='program="python, bag"; module="hashlib.{}()"'.format(
                checksum_type),
            eventOutcome=event_outcome,
            eventOutcomeDetailNote=event_outcome_detail_note
        )
    except Exception as err:
        print('Failed to write PREMIS event to database. Error: {error}'.format(
            error=err))
    else:
        return event_outcome_detail_note


def get_manifest_path(bag, sip_uuid, checksum_type):
    """Raise exception if if the Bag manifest file is not a file."""
    manifest_path = os.path.join(
        bag, 'manifest-{algo}.txt'.format(algo=checksum_type))
    if not os.path.isfile(manifest_path):
        event_outcome_detail_note = (
            'Unable to perform AIP-level fixity check on AIP {aip_uuid} because'
            ' unable to find a Bag manifest file at expected path'
            ' {manifest_path}.'.format(aip_uuid=sip_uuid,
                                       manifest_path=manifest_path))
        raise VerifyChecksumsError(
            write_premis_event(sip_uuid, checksum_type, 'Fail',
                               event_outcome_detail_note))
    return manifest_path


def parse_manifest(manifest_path, sip_uuid, checksum_type):
    """Raise exception if the Bag manifest file cannot be parsed."""
    with open(manifest_path) as filei:
        try:
            return {
                k.replace('data/', '', 1): v for k, v in
                dict(reversed(line.split()) for line in filei).items()}
        except Exception as err:
            event_outcome_detail_note = (
                'Unable to perform AIP-level fixity check on AIP {aip_uuid}'
                ' because unable to parse manifest file at path'
                ' {manifest_path}. Error:\n{error}'.format(
                    aip_uuid=sip_uuid,
                    manifest_path=manifest_path,
                    error=err))
            raise VerifyChecksumsError(
                write_premis_event(sip_uuid, checksum_type, 'Fail',
                                   event_outcome_detail_note))


def assert_checksum_types_match(file_, sip_uuid, settings_checksum_type):
    """Raise exception if checksum types (i.e., algorithms, e.g., 'sha256') of
    the file and the settings do not match.
    """
    if file_.checksumtype != settings_checksum_type:
        event_outcome_detail_note = (
            'The checksum type of file {file_uuid} is'
            ' {file_checksum_type}; given the current application settings, we'
            ' expect it to {settings_checksum_type}'.format(
                file_uuid=file_.uuid,
                file_checksum_type=file_.checksumtype,
                settings_checksum_type=settings_checksum_type))
        raise VerifyChecksumsError(
            write_premis_event(sip_uuid, settings_checksum_type, 'Fail',
                               event_outcome_detail_note))


def get_expected_checksum(file_, sip_uuid, checksum_type, path2checksum,
                          file_path, manifest_path):
    """Raise an exception if an expected checksum cannot be found in the
    Bag manifest.
    """
    try:
        return path2checksum[file_path]
    except KeyError:
        event_outcome_detail_note = (
            'Unable to find expected path {expected_path} for file'
            ' {file_uuid} in the following mapping from file paths to'
            ' checksums that was extracted from Bag manifest file'
            ' {manifest_file}: {mapping}'.format(
                expected_path=file_path,
                file_uuid=file_.uuid,
                manifest_file=manifest_path,
                mapping=pformat(path2checksum)))
        raise VerifyChecksumsError(
            write_premis_event(sip_uuid, checksum_type, 'Fail',
                               event_outcome_detail_note))


def assert_checksums_match(file_, sip_uuid, checksum_type, expected_checksum):
    """Raise an exception if checksums do not match."""
    if file_.checksum != expected_checksum:
        event_outcome_detail_note = (
            'The checksum {db_checksum} for file {file_uuid} from the'
            ' database did not match the corresponding checksum from the'
            ' Bag manifest file {manifest_checksum}'.format(
                file_uuid=file_.uuid,
                db_checksum=file_.checksum,
                manifest_checksum=expected_checksum))
        raise VerifyChecksumsError(
            write_premis_event(sip_uuid, checksum_type, 'Fail',
                               event_outcome_detail_note))


def verify_checksums(bag, sip_uuid):
    """Verify that the checksums generated at the beginning of transfer match
    those generated near the end of ingest by bag, i.e., "Prepare AIP"
    (bagit_v0.0).
    """
    checksum_type = get_setting(
        'checksum_type', mcpclient_settings.DEFAULT_CHECKSUM_ALGORITHM)
    try:
        manifest_path = get_manifest_path(bag, sip_uuid, checksum_type)
        path2checksum = parse_manifest(manifest_path, sip_uuid, checksum_type)
        verification_count = 0
        for file_ in File.objects.filter(sip_id=sip_uuid):
            if not file_.currentlocation.startswith('%SIPDirectory%objects/'):
                continue
            file_path = file_.currentlocation.replace('%SIPDirectory%', '', 1)
            assert_checksum_types_match(file_, sip_uuid, checksum_type)
            expected_checksum = get_expected_checksum(
                file_, sip_uuid, checksum_type, path2checksum, file_path,
                manifest_path)
            assert_checksums_match(file_, sip_uuid, checksum_type,
                                   expected_checksum)
            verification_count += 1
    except VerifyChecksumsError as err:
        print(err)
        return 1
    event_outcome_detail_note = (
        'All {verification_count} checksums generated at start of transfer'
        ' match those generated by BagIt (bag).'.format(
            verification_count=verification_count))
    write_premis_event(sip_uuid, checksum_type, 'Pass',
                       event_outcome_detail_note)
    print(event_outcome_detail_note)
    return 0


def verify_aip():
    """Verify the AIP was bagged correctly by extracting it and running
    verification on its contents. This is also where we verify the checksums
    now that the verifyPREMISChecksums_v0.0 ("Verify checksums generated on
    ingest") micro-service has been removed. It was removed because verifying
    checksums by calculating them in that MS and then having bagit calculate
    them here was redundant.

    sys.argv[1] = UUID
      UUID of the SIP, which will become the UUID of the AIP
    sys.argv[2] = current location
      Full absolute path to the AIP's current location on the local filesystem
    """

    sip_uuid = sys.argv[1]  # %sip_uuid%
    aip_path = sys.argv[2]  # SIPDirectory%%sip_name%-%sip_uuid%.7z

    temp_dir = mcpclient_settings.TEMP_DIRECTORY

    is_uncompressed_aip = os.path.isdir(aip_path)

    if is_uncompressed_aip:
        bag = aip_path
    else:
        try:
            extract_dir = os.path.join(temp_dir, sip_uuid)
            bag = extract_aip(aip_path, extract_dir)
        except Exception:
            print('Error extracting AIP at "{}"'.format(aip_path), file=sys.stderr)
            return 1

    verification_commands = [
        '/usr/share/bagit/bin/bag verifyvalid "{}"'.format(bag),
        '/usr/share/bagit/bin/bag checkpayloadoxum "{}"'.format(bag),
        '/usr/share/bagit/bin/bag verifycomplete "{}"'.format(bag),
        '/usr/share/bagit/bin/bag verifypayloadmanifests "{}"'.format(bag),
        '/usr/share/bagit/bin/bag verifytagmanifests "{}"'.format(bag),
    ]
    return_code = 0
    for command in verification_commands:
        print("Running test: ", command)
        exit_code, _, _ = executeOrRun("command", command, printing=True)
        if exit_code != 0:
            print("Failed test: ", command, file=sys.stderr)
            return_code = 1

    if return_code == 0:
        return_code = verify_checksums(bag, sip_uuid)
    else:
        print('Not verifying checksums because other tests have already'
              ' failed.')

    # cleanup
    if not is_uncompressed_aip:
        shutil.rmtree(extract_dir)
    return return_code


if __name__ == '__main__':
    logger = get_script_logger("archivematica.mcp.client.verifyAIP")

    sys.exit(verify_aip())
