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

from lib389._constants import (DEFAULT_SUFFIX, DN_DM, PASSWORD, HOST_STANDALONE, SERVERID_STANDALONE,
                              PORT_STANDALONE)

import subprocess

OU_PEOPLE = 'ou=people,{}'.format(DEFAULT_SUFFIX)
TEST_USER_NAME = 'simplepaged_test'
TEST_USER_DN = 'uid={},{}'.format(TEST_USER_NAME, OU_PEOPLE)
TEST_USER_PWD = 'simplepaged_test'
PW_POLICY_CONT_USER = 'cn="cn=nsPwPolicyEntry,uid=simplepaged_test,' \
                      'ou=people,dc=example,dc=com",' \
                      'cn=nsPwPolicyContainer,ou=people,dc=example,dc=com'
PW_POLICY_CONT_PEOPLE = 'cn="cn=nsPwPolicyEntry,' \
                        'ou=people,dc=example,dc=com",' \
                        'cn=nsPwPolicyContainer,ou=people,dc=example,dc=com'

logging.getLogger(__name__).setLevel(logging.INFO)
log = logging.getLogger(__name__)


@pytest.fixture(scope="module")
def test_user(topology_st, request):
    """User for binding operation"""

    log.info('Adding user {}'.format(TEST_USER_DN))
    try:
        topology_st.standalone.add_s(Entry((TEST_USER_DN, {
            'objectclass': 'top person'.split(),
            'objectclass': 'organizationalPerson',
            'objectclass': 'inetorgperson',
            'cn': TEST_USER_NAME,
            'sn': TEST_USER_NAME,
            'userpassword': TEST_USER_PWD,
            'mail': '%s@redhat.com' % TEST_USER_NAME,
            'uid': TEST_USER_NAME
        })))
    except ldap.LDAPError as e:
        log.error('Failed to add user (%s): error (%s)' % (TEST_USER_DN,
                                                           e.message['desc']))
        raise e

    def fin():
        log.info('Deleting user {}'.format(TEST_USER_DN))
        topology_st.standalone.delete_s(TEST_USER_DN)

    request.addfinalizer(fin)


@pytest.fixture(scope="module")
def password_policy(topology_st, test_user):
    """Set up password policy for subtree and user"""

    log.info('Enable fine-grained policy')
    try:
        topology_st.standalone.modify_s(DN_CONFIG, [(ldap.MOD_REPLACE,
                                                     'nsslapd-pwpolicy-local',
                                                     b'on')])
    except ldap.LDAPError as e:
        log.error('Failed to set fine-grained policy: error {}'.format(
            e.message['desc']))
        raise e

    log.info('Create password policy for subtree {}'.format(OU_PEOPLE))
    try:
        subprocess.call(['%s/ns-newpwpolicy.pl' % topology_st.standalone.get_sbin_dir(),
                         '-D', DN_DM, '-w', PASSWORD,
                         '-p', str(PORT_STANDALONE), '-h', HOST_STANDALONE,
                         '-S', OU_PEOPLE, '-Z', SERVERID_STANDALONE])
    except subprocess.CalledProcessError as e:
        log.error('Failed to create pw policy policy for {}: error {}'.format(
            OU_PEOPLE, e.message['desc']))
        raise e

    log.info('Add pwdpolicysubentry attribute to {}'.format(OU_PEOPLE))
    try:
        topology_st.standalone.modify_s(OU_PEOPLE, [(ldap.MOD_REPLACE,
                                                     'pwdpolicysubentry',
                                                     ensure_bytes(PW_POLICY_CONT_PEOPLE))])
    except ldap.LDAPError as e:
        log.error('Failed to pwdpolicysubentry pw policy ' \
                  'policy for {}: error {}'.format(OU_PEOPLE,
                                                   e.message['desc']))
        raise e

    log.info('Create password policy for subtree {}'.format(TEST_USER_DN))
    try:
        subprocess.call(['%s/ns-newpwpolicy.pl' % topology_st.standalone.get_sbin_dir(),
                         '-D', DN_DM, '-w', PASSWORD,
                         '-p', str(PORT_STANDALONE), '-h', HOST_STANDALONE,
                         '-U', TEST_USER_DN, '-Z', SERVERID_STANDALONE])
    except subprocess.CalledProcessError as e:
        log.error('Failed to create pw policy policy for {}: error {}'.format(
            TEST_USER_DN, e.message['desc']))
        raise e

    log.info('Add pwdpolicysubentry attribute to {}'.format(TEST_USER_DN))
    try:
        topology_st.standalone.modify_s(TEST_USER_DN, [(ldap.MOD_REPLACE,
                                                        'pwdpolicysubentry',
                                                        ensure_bytes(PW_POLICY_CONT_USER))])
    except ldap.LDAPError as e:
        log.error('Failed to pwdpolicysubentry pw policy ' \
                  'policy for {}: error {}'.format(TEST_USER_DN,
                                                   e.message['desc']))
        raise e


@pytest.mark.parametrize('subtree_pwchange,user_pwchange,exception',
                         [('on', 'off', ldap.UNWILLING_TO_PERFORM),
                          ('off', 'off', ldap.UNWILLING_TO_PERFORM),
                          ('off', 'on', None), ('on', 'on', None)])
def test_change_pwd(topology_st, test_user, password_policy,
                    subtree_pwchange, user_pwchange, exception):
    """Verify that 'passwordChange' attr works as expected
    User should have a priority over a subtree.

    :id: 2c884432-2ba1-4662-8e5d-2cd49f77e5fa
    :setup: Standalone instance, a test user,
            password policy entries for a user and a subtree
    :steps:
        1. Set passwordChange on the user and the subtree
           to various combinations
        2. Bind as test user
        3. Try to change password
        4. Clean up - change the password to default while bound as DM
    :expectedresults:
        1. passwordChange should be successfully set
        2. Bind should be successful
        3. Subtree/User passwordChange - result, accordingly:
           off/on, on/on - success;
           on/off, off/off - UNWILLING_TO_PERFORM
        4. Operation should be successful
    """

    log.info('Set passwordChange to "{}" - {}'.format(subtree_pwchange,
                                                      PW_POLICY_CONT_PEOPLE))
    try:
        topology_st.standalone.modify_s(PW_POLICY_CONT_PEOPLE, [(ldap.MOD_REPLACE,
                                                                 'passwordChange',
                                                                 ensure_bytes(subtree_pwchange))])
    except ldap.LDAPError as e:
        log.error('Failed to set passwordChange ' \
                  'policy for {}: error {}'.format(PW_POLICY_CONT_PEOPLE,
                                                   e.message['desc']))
        raise e

    log.info('Set passwordChange to "{}" - {}'.format(user_pwchange,
                                                      PW_POLICY_CONT_USER))
    try:
        topology_st.standalone.modify_s(PW_POLICY_CONT_USER, [(ldap.MOD_REPLACE,
                                                               'passwordChange',
                                                               ensure_bytes(user_pwchange))])
    except ldap.LDAPError as e:
        log.error('Failed to set passwordChange ' \
                  'policy for {}: error {}'.format(PW_POLICY_CONT_USER,
                                                   e.message['desc']))
        raise e
    time.sleep(1)

    try:
        log.info('Bind as user and modify userPassword')
        topology_st.standalone.simple_bind_s(TEST_USER_DN, TEST_USER_PWD)
        if exception:
            with pytest.raises(exception):
                topology_st.standalone.modify_s(TEST_USER_DN, [(ldap.MOD_REPLACE,
                                                                'userPassword',
                                                                b'new_pass')])
        else:
            topology_st.standalone.modify_s(TEST_USER_DN, [(ldap.MOD_REPLACE,
                                                            'userPassword',
                                                            b'new_pass')])
    except ldap.LDAPError as e:
        log.error('Failed to change userpassword for {}: error {}'.format(
            TEST_USER_DN, e.message['info']))
        raise e
    finally:
        log.info('Bind as DM')
        topology_st.standalone.simple_bind_s(DN_DM, PASSWORD)
        topology_st.standalone.modify_s(TEST_USER_DN, [(ldap.MOD_REPLACE,
                                                        'userPassword',
                                                        ensure_bytes(TEST_USER_PWD))])


def test_pwd_min_age(topology_st, test_user, password_policy):
    """If we set passwordMinAge to some value, for example to 10, then it
    should not allow the user to change the password within 10 seconds after
    his previous change.

    :id: 85b98516-8c82-45bd-b9ec-90bd1245e09c
    :setup: Standalone instance, a test user,
            password policy entries for a user and a subtree
    :steps:
        1. Set passwordMinAge to 10 on the user pwpolicy entry
        2. Set passwordMinAge to 10 on the subtree pwpolicy entry
        3. Set passwordMinAge to 10 on the cn=config entry
        4. Bind as test user
        5. Try to change the password two times in a row
        6. Wait 12 seconds
        7. Try to change the password
        8. Clean up - change the password to default while bound as DM
    :expectedresults:
        1. passwordMinAge should be successfully set on the user pwpolicy entry
        2. passwordMinAge should be successfully set on the subtree pwpolicy entry
        3. passwordMinAge should be successfully set on the cn=config entry
        4. Bind should be successful
        5. The password should be successfully changed
        6. 12 seconds have passed
        7. Constraint Violation error should be raised
        8. Operation should be successful
    """

    num_seconds = '10'

    log.info('Set passwordminage to "{}" - {}'.format(num_seconds, PW_POLICY_CONT_PEOPLE))
    try:
        topology_st.standalone.modify_s(PW_POLICY_CONT_PEOPLE, [(ldap.MOD_REPLACE,
                                                                 'passwordminage',
                                                                 ensure_bytes(num_seconds))])
    except ldap.LDAPError as e:
        log.error('Failed to set passwordminage ' \
                  'policy for {}: error {}'.format(PW_POLICY_CONT_PEOPLE,
                                                   e.message['desc']))
        raise e

    log.info('Set passwordminage to "{}" - {}'.format(num_seconds, PW_POLICY_CONT_USER))
    try:
        topology_st.standalone.modify_s(PW_POLICY_CONT_USER, [(ldap.MOD_REPLACE,
                                                               'passwordminage',
                                                               ensure_bytes(num_seconds))])
    except ldap.LDAPError as e:
        log.error('Failed to set passwordminage ' \
                  'policy for {}: error {}'.format(PW_POLICY_CONT_USER,
                                                   e.message['desc']))
        raise e

    log.info('Set passwordminage to "{}" - {}'.format(num_seconds, DN_CONFIG))
    try:
        topology_st.standalone.modify_s(DN_CONFIG, [(ldap.MOD_REPLACE,
                                                     'passwordminage',
                                                     ensure_bytes(num_seconds))])
    except ldap.LDAPError as e:
        log.error('Failed to set passwordminage ' \
                  'policy for {}: error {}'.format(DN_CONFIG,
                                                   e.message['desc']))
        raise e
    time.sleep(1)

    try:
        log.info('Bind as user and modify userPassword')
        topology_st.standalone.simple_bind_s(TEST_USER_DN, TEST_USER_PWD)
        topology_st.standalone.modify_s(TEST_USER_DN, [(ldap.MOD_REPLACE,
                                                        'userPassword',
                                                        b'new_pass')])
    except ldap.LDAPError as e:
        log.error('Failed to change userpassword for {}: error {}'.format(
            TEST_USER_DN, e.message['info']))
        raise e
    time.sleep(1)

    log.info('Bind as user and modify userPassword straight away after previous change')
    topology_st.standalone.simple_bind_s(TEST_USER_DN, 'new_pass')
    with pytest.raises(ldap.CONSTRAINT_VIOLATION):
        topology_st.standalone.modify_s(TEST_USER_DN, [(ldap.MOD_REPLACE,
                                                        'userPassword',
                                                        b'new_new_pass')])

    log.info('Wait {} second'.format(int(num_seconds) + 2))
    time.sleep(int(num_seconds) + 2)

    try:
        log.info('Bind as user and modify userPassword')
        topology_st.standalone.simple_bind_s(TEST_USER_DN, 'new_pass')
        topology_st.standalone.modify_s(TEST_USER_DN, [(ldap.MOD_REPLACE,
                                                        'userPassword',
                                                        ensure_bytes(TEST_USER_PWD))])
    except ldap.LDAPError as e:
        log.error('Failed to change userpassword for {}: error {}'.format(
            TEST_USER_DN, e.message['info']))
        raise e
    finally:
        log.info('Bind as DM')
        topology_st.standalone.simple_bind_s(DN_DM, PASSWORD)
        topology_st.standalone.modify_s(TEST_USER_DN, [(ldap.MOD_REPLACE,
                                                        'userPassword',
                                                        ensure_bytes(TEST_USER_PWD))])


if __name__ == '__main__':
    # Run isolated
    # -s for DEBUG mode
    CURRENT_FILE = os.path.realpath(__file__)
    pytest.main("-s %s" % CURRENT_FILE)
