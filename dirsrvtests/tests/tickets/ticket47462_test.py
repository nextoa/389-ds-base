# --- BEGIN COPYRIGHT BLOCK ---
# Copyright (C) 2016 Red Hat, Inc.
# All rights reserved.
#
# License: GPL (version 3 or any later version).
# See LICENSE for details.
# --- END COPYRIGHT BLOCK ---
#
import logging
import time

import ldap
import pytest
from lib389 import Entry
from lib389._constants import *
from lib389.properties import *
from lib389.topologies import topology_m2

logging.getLogger(__name__).setLevel(logging.DEBUG)
log = logging.getLogger(__name__)

DES_PLUGIN = 'cn=DES,cn=Password Storage Schemes,cn=plugins,cn=config'
AES_PLUGIN = 'cn=AES,cn=Password Storage Schemes,cn=plugins,cn=config'
MMR_PLUGIN = 'cn=Multimaster Replication Plugin,cn=plugins,cn=config'
AGMT_DN = ''
USER_DN = 'cn=test_user,' + DEFAULT_SUFFIX
USER1_DN = 'cn=test_user1,' + DEFAULT_SUFFIX
TEST_REPL_DN = 'cn=test repl,' + DEFAULT_SUFFIX
DES2AES_TASK_DN = 'cn=convert,cn=des2aes,cn=tasks,cn=config'


def test_ticket47462(topology_m2):
    """
        Test that AES properly replaces DES during an update/restart, and that
        replication also works correctly.
    """

    #
    # First set config as if it's an older version.  Set DES to use
    # libdes-plugin, MMR to depend on DES, delete the existing AES plugin,
    # and set a DES password for the replication agreement.
    #
    # Add an extra attribute to the DES plugin args
    #
    try:
        topology_m2.ms["master1"].modify_s(DES_PLUGIN,
                                           [(ldap.MOD_REPLACE, 'nsslapd-pluginEnabled', 'on')])
    except ldap.LDAPError as e:
        log.fatal('Failed to enable DES plugin, error: ' +
                  e.message['desc'])
        assert False

    try:
        topology_m2.ms["master1"].modify_s(DES_PLUGIN,
                                           [(ldap.MOD_ADD, 'nsslapd-pluginarg2', 'description')])
    except ldap.LDAPError as e:
        log.fatal('Failed to reset DES plugin, error: ' +
                  e.message['desc'])
        assert False

    try:
        topology_m2.ms["master1"].modify_s(MMR_PLUGIN,
                                           [(ldap.MOD_DELETE,
                                             'nsslapd-plugin-depends-on-named',
                                             'AES')])

    except ldap.NO_SUCH_ATTRIBUTE:
        pass
    except ldap.LDAPError as e:
        log.fatal('Failed to reset MMR plugin, error: ' +
                  e.message['desc'])
        assert False

    #
    # Delete the AES plugin
    #
    try:
        topology_m2.ms["master1"].delete_s(AES_PLUGIN)
    except ldap.NO_SUCH_OBJECT:
        pass
    except ldap.LDAPError as e:
        log.fatal('Failed to delete AES plugin, error: ' +
                  e.message['desc'])
        assert False

    # restart the server so we must use DES plugin
    topology_m2.ms["master1"].restart(timeout=10)

    #
    # Get the agmt dn, and set the password
    #
    try:
        entry = topology_m2.ms["master1"].search_s('cn=config', ldap.SCOPE_SUBTREE,
                                                   'objectclass=nsDS5ReplicationAgreement')
        if entry:
            agmt_dn = entry[0].dn
            log.info('Found agmt dn (%s)' % agmt_dn)
        else:
            log.fatal('No replication agreements!')
            assert False
    except ldap.LDAPError as e:
        log.fatal('Failed to search for replica credentials: ' +
                  e.message['desc'])
        assert False

    try:
        properties = {RA_BINDPW: "password"}
        topology_m2.ms["master1"].agreement.setProperties(None, agmt_dn, None,
                                                          properties)
        log.info('Successfully modified replication agreement')
    except ValueError:
        log.error('Failed to update replica agreement: ' + AGMT_DN)
        assert False

    #
    # Check replication works with the new DES password
    #
    try:
        topology_m2.ms["master1"].add_s(Entry((USER1_DN,
                                               {'objectclass': "top person".split(),
                                                'sn': 'sn',
                                                'description': 'DES value to convert',
                                                'cn': 'test_user'})))
        loop = 0
        ent = None
        while loop <= 10:
            try:
                ent = topology_m2.ms["master2"].getEntry(USER1_DN, ldap.SCOPE_BASE,
                                                         "(objectclass=*)")
                break
            except ldap.NO_SUCH_OBJECT:
                time.sleep(1)
                loop += 1
        if not ent:
            log.fatal('Replication test failed fo user1!')
            assert False
        else:
            log.info('Replication test passed')
    except ldap.LDAPError as e:
        log.fatal('Failed to add test user: ' + e.message['desc'])
        assert False

    #
    # Add a backend (that has no entries)
    #
    try:
        topology_m2.ms["master1"].backend.create("o=empty", {BACKEND_NAME: "empty"})
    except ldap.LDAPError as e:
        log.fatal('Failed to create extra/empty backend: ' + e.message['desc'])
        assert False

    #
    # Run the upgrade...
    #
    topology_m2.ms["master1"].upgrade('online')
    topology_m2.ms["master1"].restart()
    topology_m2.ms["master2"].restart()

    #
    # Check that the restart converted existing DES credentials
    #
    try:
        entry = topology_m2.ms["master1"].search_s('cn=config', ldap.SCOPE_SUBTREE,
                                                   'nsDS5ReplicaCredentials=*')
        if entry:
            val = entry[0].getValue('nsDS5ReplicaCredentials')
            if val.startswith('{AES-'):
                log.info('The DES credentials have been converted to AES')
            else:
                log.fatal('Failed to convert credentials from DES to AES!')
                assert False
        else:
            log.fatal('Failed to find entries with nsDS5ReplicaCredentials')
            assert False
    except ldap.LDAPError as e:
        log.fatal('Failed to search for replica credentials: ' +
                  e.message['desc'])
        assert False

    #
    # Check that the AES plugin exists, and has all the attributes listed in
    # DES plugin.  The attributes might not be in the expected order so check
    # all the attributes.
    #
    try:
        entry = topology_m2.ms["master1"].search_s(AES_PLUGIN, ldap.SCOPE_BASE,
                                                   'objectclass=*')
        if not entry[0].hasValue('nsslapd-pluginarg0', 'description') and \
                not entry[0].hasValue('nsslapd-pluginarg1', 'description') and \
                not entry[0].hasValue('nsslapd-pluginarg2', 'description'):
            log.fatal('The AES plugin did not have the DES attribute copied ' +
                      'over correctly')
            assert False
        else:
            log.info('The AES plugin was correctly setup')
    except ldap.LDAPError as e:
        log.fatal('Failed to find AES plugin: ' + e.message['desc'])
        assert False

    #
    # Check that the MMR plugin was updated
    #
    try:
        entry = topology_m2.ms["master1"].search_s(MMR_PLUGIN, ldap.SCOPE_BASE,
                                                   'objectclass=*')
        if not entry[0].hasValue('nsslapd-plugin-depends-on-named', 'AES'):
            log.fatal('The MMR Plugin was not correctly updated')
            assert False
        else:
            log.info('The MMR plugin was correctly updated')
    except ldap.LDAPError as e:
        log.fatal('Failed to find AES plugin: ' + e.message['desc'])
        assert False

    #
    # Check that the DES plugin was correctly updated
    #
    try:
        entry = topology_m2.ms["master1"].search_s(DES_PLUGIN, ldap.SCOPE_BASE,
                                                   'objectclass=*')
        if not entry[0].hasValue('nsslapd-pluginPath', 'libpbe-plugin'):
            log.fatal('The DES Plugin was not correctly updated')
            assert False
        else:
            log.info('The DES plugin was correctly updated')
    except ldap.LDAPError as e:
        log.fatal('Failed to find AES plugin: ' + e.message['desc'])
        assert False

    #
    # Check replication one last time
    #
    try:
        topology_m2.ms["master1"].add_s(Entry((USER_DN,
                                               {'objectclass': "top person".split(),
                                                'sn': 'sn',
                                                'cn': 'test_user'})))
        loop = 0
        ent = None
        while loop <= 10:
            try:
                ent = topology_m2.ms["master2"].getEntry(USER_DN, ldap.SCOPE_BASE,
                                                         "(objectclass=*)")
                break
            except ldap.NO_SUCH_OBJECT:
                time.sleep(1)
                loop += 1
        if not ent:
            log.fatal('Replication test failed!')
            assert False
        else:
            log.info('Replication test passed')
    except ldap.LDAPError as e:
        log.fatal('Failed to add test user: ' + e.message['desc'])
        assert False

    # Check the entry
    log.info('Entry before running task...')
    try:
        entry = topology_m2.ms["master1"].search_s(USER1_DN,
                                                   ldap.SCOPE_BASE,
                                                   'objectclass=*')
        if entry:
            print(str(entry))
        else:
            log.fatal('Failed to find entries')
            assert False
    except ldap.LDAPError as e:
        log.fatal('Failed to search for entries: ' +
                  e.message['desc'])
        assert False

    #
    # Test the DES2AES Task on USER1_DN
    #
    try:
        topology_m2.ms["master1"].add_s(Entry((DES2AES_TASK_DN,
                                               {'objectclass': ['top',
                                                                'extensibleObject'],
                                                'suffix': DEFAULT_SUFFIX,
                                                'cn': 'convert'})))
    except ldap.LDAPError as e:
        log.fatal('Failed to add task entry: ' + e.message['desc'])
        assert False

    # Wait for task
    task_entry = Entry(DES2AES_TASK_DN)
    (done, exitCode) = topology_m2.ms["master1"].tasks.checkTask(task_entry, True)
    if exitCode:
        log.fatal("Error: des2aes task exited with %d" % (exitCode))
        assert False

    # Check the entry
    try:
        entry = topology_m2.ms["master1"].search_s(USER1_DN,
                                                   ldap.SCOPE_BASE,
                                                   'objectclass=*')
        if entry:
            val = entry[0].getValue('description')
            print(str(entry[0]))
            if val.startswith('{AES-'):
                log.info('Task: DES credentials have been converted to AES')
            else:
                log.fatal('Task: Failed to convert credentials from DES to ' +
                          'AES! (%s)' % (val))
                assert False
        else:
            log.fatal('Failed to find entries')
            assert False
    except ldap.LDAPError as e:
        log.fatal('Failed to search for entries: ' +
                  e.message['desc'])
        assert False


if __name__ == '__main__':
    # Run isolated
    # -s for DEBUG mode
    CURRENT_FILE = os.path.realpath(__file__)
    pytest.main("-s %s" % CURRENT_FILE)
