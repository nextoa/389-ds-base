# --- BEGIN COPYRIGHT BLOCK ---
# Copyright (C) 2016 Red Hat, Inc.
# All rights reserved.
#
# License: GPL (version 3 or any later version).
# See LICENSE for details.
# --- END COPYRIGHT BLOCK ---
#
import pytest
from lib389.tasks import *
from lib389.utils import *
from lib389.topologies import topology_st

logging.getLogger(__name__).setLevel(logging.DEBUG)
log = logging.getLogger(__name__)


def test_ticket47921(topology_st):
    '''
    Test that indirect cos reflects the current value of the indirect entry
    '''

    INDIRECT_COS_DN = 'cn=cos definition,' + DEFAULT_SUFFIX
    MANAGER_DN = 'uid=my manager,ou=people,' + DEFAULT_SUFFIX
    USER_DN = 'uid=user,ou=people,' + DEFAULT_SUFFIX

    # Add COS definition
    try:
        topology_st.standalone.add_s(Entry((INDIRECT_COS_DN,
                                            {
                                                'objectclass': 'top cosSuperDefinition cosIndirectDefinition ldapSubEntry'.split(),
                                                'cosIndirectSpecifier': 'manager',
                                                'cosAttribute': 'roomnumber'
                                                })))
    except ldap.LDAPError as e:
        log.fatal('Failed to add cos defintion, error: ' + e.message['desc'])
        assert False

    # Add manager entry
    try:
        topology_st.standalone.add_s(Entry((MANAGER_DN,
                                            {'objectclass': 'top extensibleObject'.split(),
                                             'uid': 'my manager',
                                             'roomnumber': '1'
                                             })))
    except ldap.LDAPError as e:
        log.fatal('Failed to add manager entry, error: ' + e.message['desc'])
        assert False

    # Add user entry
    try:
        topology_st.standalone.add_s(Entry((USER_DN,
                                            {'objectclass': 'top person organizationalPerson inetorgperson'.split(),
                                             'sn': 'last',
                                             'cn': 'full',
                                             'givenname': 'mark',
                                             'uid': 'user',
                                             'manager': MANAGER_DN
                                             })))
    except ldap.LDAPError as e:
        log.fatal('Failed to add manager entry, error: ' + e.message['desc'])
        assert False

    # Test COS is working
    try:
        entry = topology_st.standalone.search_s(DEFAULT_SUFFIX, ldap.SCOPE_SUBTREE,
                                                "uid=user",
                                                ['roomnumber'])
        if entry:
            if entry[0].getValue('roomnumber') != '1':
                log.fatal('COS is not working.')
                assert False
        else:
            log.fatal('Failed to find user entry')
            assert False
    except ldap.LDAPError as e:
        log.error('Failed to search for user entry: ' + e.message['desc'])
        assert False

    # Modify manager entry
    try:
        topology_st.standalone.modify_s(MANAGER_DN, [(ldap.MOD_REPLACE, 'roomnumber', '2')])
    except ldap.LDAPError as e:
        log.error('Failed to modify manager entry: ' + e.message['desc'])
        assert False

    # Confirm COS is returning the new value
    try:
        entry = topology_st.standalone.search_s(DEFAULT_SUFFIX, ldap.SCOPE_SUBTREE,
                                                "uid=user",
                                                ['roomnumber'])
        if entry:
            if entry[0].getValue('roomnumber') != '2':
                log.fatal('COS is not working after manager update.')
                assert False
        else:
            log.fatal('Failed to find user entry')
            assert False
    except ldap.LDAPError as e:
        log.error('Failed to search for user entry: ' + e.message['desc'])
        assert False

    log.info('Test complete')


if __name__ == '__main__':
    # Run isolated
    # -s for DEBUG mode
    CURRENT_FILE = os.path.realpath(__file__)
    pytest.main("-s %s" % CURRENT_FILE)
